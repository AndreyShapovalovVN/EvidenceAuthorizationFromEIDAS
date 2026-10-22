"""HTTP entrypoint for the authorization UI service."""

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import UUID

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from oots_lib.import_env import import_env
from oots_lib.lib.UseRedis import close_redis, get_redis_client, initialize_redis
from pydantic import BaseModel
from redis.exceptions import ConnectionError as RedisConnectionError

from lib.action_token import issue_action_token, verify_action_token
from lib.eidas_sp_service import (
    EIDAS_SPECIFIC_CONNECTOR_URL,
    prepare_eidas_redirect,
    process_eidas_callback,
)
from lib.MessageChecker import check_message
from lib.preview_keys import PreviewKeys
from lib.preview_service import (
    EmptyEvidenceListError,
    EvidenceDataNotFoundError,
    build_evidence_page_context,
    build_preview_progress,
    check_evidence_ready,
    check_exp_ready,
    persist_approvals,
    record_view_timeout,
)
from lib.RedirectService import filter_returnurl, resolve_url

WAIT_EVENT_TIME = int(import_env("EVIDENCE_TIMEOUT", "600"))
WAIT_EVENT_SLEEP = int(import_env("REDIS_TIMEOUT", "6")) / 2

QUEUE_OUTGOING = import_env("QUEUE_OUTCOMING")

KEYS = PreviewKeys()

logging.basicConfig(level=logging.DEBUG)
_logger = logging.getLogger("Authorization UI")
APP_TITLE = "Authorization UI"

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


async def _get_safe_returnurl(client, request: Request, message_id: str) -> str | None:
    returnurl = request.query_params.get("returnurl")

    if not returnurl:
        try:
            returnurl = await resolve_url(client, message_id)
        except Exception:
            returnurl = None

    return filter_returnurl(returnurl)


def _render_invalid_link_or_raise(
    request: Request,
    returnurl: str | None,
):
    if returnurl:
        return templates.TemplateResponse(
            request,
            "invalid_link.html",
            {
                "message": "Неправильне посилання: EDM не знайдено",
                "returnurl": returnurl,
            },
        )

    raise HTTPException(
        status_code=400,
        detail="Invalid link: EDM not found and no returnurl provided",
    )


def _raise_if_message_failed(status) -> None:
    if not status.has_error:
        return

    err = status.evidence_error
    raise HTTPException(
        status_code=422,
        detail={
            "code": err.code if err else "EDM:ERR:UNKNOWN",
            "message": err.message if err else "Evidence error",
            "detail": err.detail if err else None,
            "preview_link": err.preview_link if err else None,
        },
    )


def _raise_if_message_timed_out(status, message_id: str) -> None:
    if status.timed_out:
        raise HTTPException(
            status_code=408,
            detail=f"Таймаут очікування preview для message_id={message_id}",
        )


class ViewContinuePayload(BaseModel):
    message_uuid: str
    approvals: dict[str, bool]


def _require_action_token(request: Request, message_id: str, action: str) -> None:
    token = request.headers.get("X-Action-Token")
    if token is None:
        token = request.query_params.get("token")
    if not verify_action_token(token, message_id, action):
        raise HTTPException(status_code=403, detail="Forbidden: invalid action token")


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Initialize shared resources on startup and close them on shutdown."""
    try:
        await initialize_redis()
    except Exception as exc:
        _logger.warning("Redis недоступний на старті: %s", exc)
    yield
    await close_redis()


app = FastAPI(title=APP_TITLE, lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    """Add a minimal set of security headers to every response."""
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response


@app.get(
    "/health",
    tags=["System"],
    responses={503: {"description": "Redis unavailable"}},
)
async def health_check():
    """Перевірка працездатності сервісу та доступності Redis."""
    client = get_redis_client()
    try:
        await client.health_check()
    except RedisConnectionError as exc:
        _logger.warning("Health check Redis failed: %s", exc)
        raise HTTPException(status_code=503, detail="Redis недоступний") from exc

    return {"status": "ok", "redis": "up"}


@app.get("/favicon.ico")
async def favicon():
    """Return 404 for missing favicon requests."""
    return HTMLResponse(status_code=404)


@app.get(
    "/auth/{message_id}",
    response_class=HTMLResponse,
    responses={
        400: {"description": "Invalid link"},
        408: {"description": "Preview timeout"},
        422: {"description": "Evidence error"},
    },
)
async def root(request: Request, message_id: UUID):
    message_id_str = str(message_id)

    client = get_redis_client()
    request_edm = await client.get_from_redis(KEYS.get_request_edm(message_id_str))
    returnurl = await _get_safe_returnurl(client, request, message_id_str)

    if request_edm is None:
        return _render_invalid_link_or_raise(request, returnurl)

    existing_person = await client.get_from_redis(
        KEYS.get_request_person(message_id_str)
    )
    if existing_person is not None:
        return templates.TemplateResponse(
            request,
            "redirect_to_preview.html",
            {
                "message_id": message_id_str,
                "preview_url": f"/preview/{message_id_str}",
            },
        )

    if returnurl:
        await client.save_to_redis(KEYS.get_return_url(message_id_str), returnurl)

    status = await check_message(client, message_id_str)
    _raise_if_message_failed(status)
    _raise_if_message_timed_out(status, message_id_str)

    return templates.TemplateResponse(
        request,
        "login.html",
        {
            "message_id": message_id_str,
        },
    )


# ---------------------------------------------------------------------------
# eIDAS Simple Protocol (guide §12) routes: SP -> Specific Connector -> SP
# ---------------------------------------------------------------------------


@app.get(
    "/auth/eidas/start/{message_id}",
    response_class=HTMLResponse,
    tags=["eIDAS"],
    responses={400: {"description": "Invalid message_id"}},
)
async def eidas_start(request: Request, message_id: UUID):
    """Крок 1: побудувати SimpleRequest і повернути автосабміт форму,
    що передає запит на Specific Connector (guide §12.2)."""
    message_id_str = str(message_id)

    client = get_redis_client()
    request_edm = await client.get_from_redis(KEYS.get_request_edm(message_id_str))
    if request_edm is None:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid message_id: EDM not found for {message_id_str}",
        )

    redirect_context = await prepare_eidas_redirect(
        client,
        message_id_str,
        keys=KEYS,
    )

    _logger.info(
        "eIDAS SP start: message_id=%s request_id=%s -> %s",
        message_id_str,
        redirect_context["request_id"],
        EIDAS_SPECIFIC_CONNECTOR_URL,
    )

    return templates.TemplateResponse(
        request,
        "eidas_redirect.html",
        {
            "specific_connector_url": redirect_context["specific_connector_url"],
            "simple_request_b64": redirect_context["simple_request_b64"],
            "send_method_field": redirect_context["send_method_field"],
            "send_method_value": redirect_context["send_method_value"],
        },
    )


@app.post(
    "/auth/eidas/callback",
    tags=["eIDAS"],
    responses={
        400: {
            "description": "Invalid or expired request id / malformed SimpleResponse"
        },
        422: {"description": "Invalid identified person data"},
        502: {"description": "eIDAS authentication failed"},
        503: {"description": "Redis save failed"},
    },
)
async def eidas_callback(request: Request):
    """Крок 2: прийняти SimpleResponse від Specific Connector (guide §12.4),
    перевірити дозволені рівні LoA, зберегти Person та перейти на preview."""
    message_id = await process_eidas_callback(
        request,
        get_redis_client(),
        queue_outgoing=QUEUE_OUTGOING,
        keys=KEYS,
        logger=_logger,
    )
    # Callback is POST-based; 303 ensures the browser follows with GET /preview/{id}.
    return RedirectResponse(url=f"/preview/{message_id}", status_code=303)


async def _render_evidence_page(request: Request, message_id: str) -> HTMLResponse:
    """Render evidence page using prepared context from service layer."""
    client = get_redis_client()
    try:
        context = await build_evidence_page_context(client, message_id, KEYS)
    except EvidenceDataNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail=f"Data not found in Redis by id: {message_id}",
        ) from exc
    except EmptyEvidenceListError as exc:
        raise HTTPException(
            status_code=400,
            detail="No evidences found for preview",
        ) from exc

    context["continue_token"] = issue_action_token(message_id, "preview-continue")
    return templates.TemplateResponse(request, "evidences.html", context)


@app.get(
    "/preview/{message_id}",
    responses={
        400: {"description": "No evidences found for preview"},
        404: {"description": "Preview data not found"},
    },
)
async def view_evidence(request: Request, message_id: UUID):
    """Показує сторінку з таскбаром очікування, потім рендер evidence."""
    message_id_str = str(message_id)
    client = get_redis_client()

    # Читаємо returnurl з Redis (збережено при авторизації)
    stored = await client.get_from_redis(KEYS.get_return_url(message_id_str))
    returnurl = filter_returnurl(stored if isinstance(stored, str) else None)
    if not returnurl:
        returnurl = await _get_safe_returnurl(client, request, message_id_str)
        if returnurl:
            await client.save_to_redis(KEYS.get_return_url(message_id_str), returnurl)

    exp_ready = await check_exp_ready(client, message_id_str, KEYS)
    if exp_ready and returnurl:
        # If exp is already raised, return user immediately to caller system.
        return RedirectResponse(url=returnurl, status_code=307)

    evidence_ready = await check_evidence_ready(client, message_id_str, KEYS)

    if evidence_ready:
        # Евіденс готовий, рендеримо evidence сторінку одразу
        return await _render_evidence_page(request, message_id_str)

    # Якщо ні, показуємо сторінку чекання
    return templates.TemplateResponse(
        request,
        "view_waiting.html",
        {
            "message_id": message_id_str,
            "returnurl": returnurl,
            "wait_time": WAIT_EVENT_TIME,
            "poll_interval": WAIT_EVENT_SLEEP,
            "progress_token": issue_action_token(message_id_str, "preview-progress"),
            "timeout_token": issue_action_token(message_id_str, "preview-timeout"),
        },
    )


@app.get(
    "/preview/progress/{message_id}",
    responses={403: {"description": "Invalid action token"}},
)
async def view_progress(request: Request, message_id: UUID):
    """API endpoint для отримання прогресу завантаження evidence."""
    message_id_str = str(message_id)
    _require_action_token(request, message_id_str, "preview-progress")
    client = get_redis_client()
    return await build_preview_progress(client, message_id_str, KEYS)


@app.post(
    "/preview/continue",
    responses={
        403: {"description": "Invalid action token"},
        404: {"description": "Preview data not found"},
    },
)
async def continue_view(request: Request, payload: ViewContinuePayload):
    """Persist checkbox approvals for preview evidences."""
    _require_action_token(request, payload.message_uuid, "preview-continue")
    client = get_redis_client()
    message_id = payload.message_uuid
    try:
        approvals = await persist_approvals(
            client,
            message_id,
            payload.approvals,
            KEYS,
            QUEUE_OUTGOING,
        )
    except EvidenceDataNotFoundError as exc:
        raise HTTPException(
            status_code=404, detail=f"Data not found in Redis by id: {message_id}"
        ) from exc

    # Читаємо returnurl з Redis (збережено при авторизації)
    stored = await client.get_from_redis(KEYS.get_return_url(message_id))
    returnurl = filter_returnurl(stored if isinstance(stored, str) else None)

    return {
        "status": "success",
        "message": "Approvals received",
        "approvals": approvals,
        "returnurl": returnurl,
    }


@app.post(
    "/preview/timeout/{message_id}",
    responses={403: {"description": "Invalid action token"}},
)
async def view_timeout(request: Request, message_id: UUID):
    """Записує статус таймауту в Redis при спливанні часу на клієнті."""
    message_id_str = str(message_id)
    _require_action_token(request, message_id_str, "preview-timeout")
    client = get_redis_client()
    await record_view_timeout(client, message_id_str, KEYS, QUEUE_OUTGOING)

    _logger.warning("View timeout recorded for message_id=%s", message_id_str)

    return {
        "status": "timeout_recorded",
        "message_id": message_id_str,
    }
