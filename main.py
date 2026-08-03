"""HTTP entrypoint for the authorization UI service."""

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import UUID

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from lxml import etree
from pydantic import BaseModel
from redis.exceptions import ConnectionError as RedisConnectionError

from lib.action_token import issue_action_token, verify_action_token
from lib.eidas_autofill_service import EidasAutofillService
from lib.eidas_sp_service import (
    SEND_METHOD_FIELD,
    SEND_METHOD_VALUE,
    SIMPLE_RESPONSE_FIELD,
    EidasSpService,
)
from lib.ICEI import ICEIError, IdICEI
from lib.MessageChecker import check_message
from lib.PersonRequestService import (
    ContinuePayload,
    save_identified_person_request,
    save_person_request,
)
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
from lib.RedirectService import filter_returnurl, if_preview, resolve_url
from lib.UseRedis import close_redis, get_redis_client, initialize_redis
from Models.eIDAS_SP_Response import SimpleResponseError

WAIT_EVENT_TIME = int(os.getenv("EVIDENCE_TIMEOUT", "600"))
WAIT_EVENT_SLEEP = int(os.getenv("REDIS_TIMEOUT", "6")) / 2

QUEUE_OUTGOING = os.getenv("QUEUE_OUTGOING", "oots:queue:outgoing")

# id.gov.ua (ICEI) налаштування
ICEI_REDIRECT_URI = os.getenv(
    "ICEI_REDIRECT_URI", "http://localhost:8000/auth/icei/callback"
)

# eIDAS Simple Protocol (guide §12) налаштування
EIDAS_SP_PUBLIC_BASE_URL = os.getenv("EIDAS_SP_PUBLIC_BASE_URL")
EIDAS_SP_CALLBACK_PATH = "/auth/eidas/callback"

KEYS = PreviewKeys()
EIDAS_SP_SERVICE = EidasSpService()

logging.basicConfig(level=logging.DEBUG)
_logger = logging.getLogger("Authorization UI")
APP_TITLE = "Authorization UI"

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
EIDAS_TEST_DATA_PATH = Path(
    os.getenv(
        "EIDAS_TEST_DATA_PATH",
        str(BASE_DIR / "tests" / "eIDAS-id-data-test.csv"),
    )
)


def _build_eidas_autofill_service() -> EidasAutofillService | None:
    candidates = [EIDAS_TEST_DATA_PATH]
    if not EIDAS_TEST_DATA_PATH.is_absolute():
        candidates.append(BASE_DIR / EIDAS_TEST_DATA_PATH)
    bundled_default = BASE_DIR / "tests" / "eIDAS-id-data-test.csv"
    if bundled_default not in candidates:
        candidates.append(bundled_default)

    last_error: ValueError | None = None
    for candidate in candidates:
        try:
            return EidasAutofillService(candidate)
        except ValueError as exc:
            last_error = exc
            continue

    if last_error is not None:
        _logger.warning("eIDAS autofill is disabled: %s", last_error)
    return None


try:
    EIDAS_AUTOFILL_SERVICE: EidasAutofillService | None = _build_eidas_autofill_service()
except Exception as exc:
    _logger.warning("eIDAS autofill is disabled: %s", exc)
    EIDAS_AUTOFILL_SERVICE = None

COMMON_ERROR_RESPONSES = {
    400: {"description": "Bad request"},
    403: {"description": "Forbidden"},
    404: {"description": "Not found"},
    408: {"description": "Request timeout"},
    422: {"description": "Unprocessable entity"},
    502: {"description": "Bad gateway"},
    503: {"description": "Service unavailable"},
}

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

def _fromstring_filter(xml_payload: str):
    """Parse XML for legacy Jinja template accordion rendering."""
    try:
        return etree.fromstring(xml_payload.encode("utf-8"))
    except Exception:
        return None


templates.env.filters["fromstring"] = _fromstring_filter


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

    existing_person = await client.get_from_redis(KEYS.get_request_person(message_id_str))
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

    stored_returnurl = await client.get_from_redis(KEYS.get_return_url(message_id_str))
    preview = await if_preview(client, message_id_str)
    continue_url = f"/preview/{message_id_str}" if preview else stored_returnurl

    return templates.TemplateResponse(
        request,
        "login.html",
        {
            "message_id": message_id_str,
            "continue_url": continue_url,
            "auth_continue_token": issue_action_token(message_id_str, "auth-continue"),
        },
    )

@app.post(
    "/auth/continue",
    responses={
        403: {"description": "Invalid action token"},
        422: {"description": "Invalid person data"},
        503: {"description": "Redis save failed"},
    },
)
async def continue_auth(request: Request, payload: ContinuePayload):
    """Validate and persist person data received from the login form."""
    _require_action_token(request, payload.message_id, "auth-continue")
    try:
        redis_key, person_data = await save_person_request(get_redis_client(), payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Не вдалося зберегти дані в Redis: {exc}",
        ) from exc

    return {
        "status": "ok",
        "message": "Дані збережено",
        "redis_key": redis_key,
        "person": person_data,
    }


def _get_eidas_autofill_payload():
    if EIDAS_AUTOFILL_SERVICE is None:
        raise HTTPException(status_code=503, detail="eIDAS test data is not configured")
    return EIDAS_AUTOFILL_SERVICE.get_next_payload()


# NOTE: these two endpoints return canned data from a local CSV for manual
# QA of the "Manual Entry" form; they are no longer linked from login.html
# now that "Log in via eIDAS" performs the real Simple Protocol flow below
# (/auth/eidas/start -> Specific Connector -> /auth/eidas/callback).
@app.get(
    "/auth/eidas/login",
    responses={503: {"description": "eIDAS test data is not configured"}},
)
async def auth_eidas_login():
    """Return next eIDAS test record for form autofill (dev/QA only)."""
    return _get_eidas_autofill_payload()


@app.get(
    "/auth/eidas/next",
    responses={503: {"description": "eIDAS test data is not configured"}},
)
async def auth_eidas_next():
    """Legacy alias for the eIDAS autofill endpoint (dev/QA only)."""
    return _get_eidas_autofill_payload()


# ---------------------------------------------------------------------------
# id.gov.ua (ICEI) identification routes
# ---------------------------------------------------------------------------


@app.get(
    "/auth/icei/start/{message_id}",
    tags=["ICEI"],
    responses={400: {"description": "Invalid message_id"}},
)
async def icei_start(message_id: UUID):
    message_id_str = str(message_id)
    """Крок 3: перенаправити користувача на сторінку ідентифікації id.gov.ua.

    Зберігає `state → message_id` у Redis і виконує 307-редирект.
    """
    client = get_redis_client()

    edm = await client.get_from_redis(KEYS.get_request_edm(message_id_str))
    if edm is None:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid message_id: EDM not found for {message_id_str}",
        )

    icei = IdICEI(redirect_uri=ICEI_REDIRECT_URI)

    # Зберігаємо state → message_id (видалимо одразу після callback)
    state_key = KEYS.get_request_icei_state(icei.state)
    await client.save_to_redis(state_key, {"message_id": message_id_str})

    _logger.info(
        "ICEI start: message_id=%s state=%s → %s",
        message_id_str,
        icei.state,
        icei.auth_url,
    )
    return RedirectResponse(url=icei.auth_url, status_code=307)


@app.get(
    "/auth/icei/callback",
    tags=["ICEI"],
    responses={
        400: {"description": "Invalid or expired state parameter"},
        422: {"description": "Invalid identified person data"},
        502: {"description": "ICEI identification failed"},
        503: {"description": "Redis save failed"},
    },
)
async def icei_callback(code: str, state: str):
    """Крок 10–11: обробка callback від id.gov.ua.

    Обмінює code на access_token, отримує дані особи, зберігає в Redis
    та перенаправляє на /preview/{message_id}.
    """
    client = get_redis_client()

    # Зчитуємо message_id та одразу видаляємо state (одноразовий)
    state_key = KEYS.get_request_icei_state(state)
    state_data = await client.get_from_redis(state_key)
    await client.delete_from_redis(state_key)

    if not isinstance(state_data, dict) or not state_data.get("message_id"):
        _logger.warning("ICEI callback: invalid or expired state")
        raise HTTPException(
            status_code=400, detail="Invalid or expired state parameter"
        )

    message_id: str = state_data["message_id"]
    _logger.info("ICEI callback: message_id=%s code=***", message_id)

    # Кроки 11.1–11.6: code → UserProfile
    try:
        icei = IdICEI(redirect_uri=ICEI_REDIRECT_URI)
        profile = await icei.fetch_person(code)
    except ICEIError as exc:
        _logger.exception(
            "ICEI identification failed for message_id=%s: %s", message_id, exc
        )
        raise HTTPException(
            status_code=502,
            detail=f"ICEI identification failed: {exc}",
        ) from exc

    # Зберігаємо Person у Redis та ставимо в чергу (кроки 11.5–11.6)
    # Сесію/токени не зберігаємо: беремо тільки персональні атрибути.
    try:
        await save_identified_person_request(
            client,
            message_id=message_id,
            first_name=profile.givenname,
            last_name=profile.lastname,
            identifier=profile.identifier,
            date_of_birth=profile.date_of_birth,
            gender=profile.gender,
            level_of_assurance="High",
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Не вдалося зберегти дані в Redis: {exc}",
        ) from exc

    _logger.info(
        "ICEI: person saved for message_id=%s (%s %s)",
        message_id,
        profile.lastname,
        profile.givenname,
    )
    return RedirectResponse(url=f"/preview/{message_id}", status_code=307)


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
    """Крок 1: побудувати SimpleRequest і повернути авто-сабміт форму,
    що передає запит на Specific Connector (guide §12.2)."""
    message_id_str = str(message_id)

    client = get_redis_client()
    request_edm = await client.get_from_redis(KEYS.get_request_edm(message_id_str))
    if request_edm is None:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid message_id: EDM not found for {message_id_str}",
        )

    base_url = EIDAS_SP_PUBLIC_BASE_URL or str(request.base_url).rstrip("/")
    callback_url = f"{base_url}{EIDAS_SP_CALLBACK_PATH}"

    auth_request = EIDAS_SP_SERVICE.build_auth_request(service_url=callback_url)

    # Зберігаємо request.id -> message_id, щоб зіставити SimpleResponse
    # (поле inresponse_to) з message_id при отриманні callback-у.
    state_key = KEYS.get_eidas_state_key(auth_request.id)
    await client.save_to_redis(state_key, {"message_id": message_id_str})

    _logger.info(
        "eIDAS SP start: message_id=%s request_id=%s -> %s",
        message_id_str,
        auth_request.id,
        EIDAS_SP_SERVICE.specific_connector_url,
    )

    return templates.TemplateResponse(
        request,
        "eidas_redirect.html",
        {
            "specific_connector_url": EIDAS_SP_SERVICE.specific_connector_url,
            "simple_request_b64": EidasSpService.encode_request(auth_request),
            "send_method_field": SEND_METHOD_FIELD,
            "send_method_value": SEND_METHOD_VALUE,
        },
    )


async def _read_simple_response_body(request: Request) -> str | None:
    """Extract the raw SimpleResponse payload from a JSON body or an
    urlencoded/multipart form field, whichever the Specific Connector used."""
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        body_bytes = await request.body()
        return body_bytes.decode("utf-8") if body_bytes else None

    form = await request.form()
    form_value = form.get(SIMPLE_RESPONSE_FIELD)
    if form_value is not None and not isinstance(form_value, str):
        raise HTTPException(
            status_code=400,
            detail="SimpleResponse must be a form text field, not a file upload",
        )
    return form_value


def _parse_simple_response(raw_body: str | None):
    if not raw_body:
        raise HTTPException(status_code=400, detail="Missing SimpleResponse payload")
    try:
        return EIDAS_SP_SERVICE.parse_response(raw_body)
    except SimpleResponseError as exc:
        raise HTTPException(status_code=400, detail=f"Malformed SimpleResponse: {exc}") from exc


async def _pop_eidas_message_id(client, request_id: str) -> str:
    """Look up and consume the one-time request_id -> message_id mapping
    saved by eidas_start; raises 400 if it's missing or already used."""
    state_key = KEYS.get_eidas_state_key(request_id)
    state_data = await client.get_from_redis(state_key)
    await client.delete_from_redis(state_key)

    if not isinstance(state_data, dict) or not state_data.get("message_id"):
        _logger.warning("eIDAS callback: invalid or expired request id")
        raise HTTPException(status_code=400, detail="Invalid or expired eIDAS request id")

    return state_data["message_id"]


def _raise_if_eidas_failed(simple_response, message_id: str) -> None:
    if simple_response.is_success:
        return

    _logger.warning(
        "eIDAS authentication failed for message_id=%s: %s / %s",
        message_id,
        simple_response.status.status_code,
        simple_response.status.status_message,
    )
    raise HTTPException(
        status_code=502,
        detail={
            "code": simple_response.status.sub_status_code
            or simple_response.status.status_code,
            "message": simple_response.status.status_message
            or "eIDAS authentication failed",
        },
    )


async def _save_eidas_person(client, message_id: str, person_payload: dict) -> None:
    try:
        await save_identified_person_request(
            client,
            message_id=message_id,
            first_name=person_payload["first_name"],
            last_name=person_payload["last_name"],
            identifier=person_payload["identifier"],
            date_of_birth=person_payload["date_of_birth"],
            gender=person_payload["gender"],
            level_of_assurance=person_payload["level_of_assurance"],
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Не вдалося зберегти дані в Redis: {exc}",
        ) from exc


@app.post(
    "/auth/eidas/callback",
    tags=["eIDAS"],
    responses={
        400: {"description": "Invalid or expired request id / malformed SimpleResponse"},
        422: {"description": "Invalid identified person data"},
        502: {"description": "eIDAS authentication failed"},
        503: {"description": "Redis save failed"},
    },
)
async def eidas_callback(request: Request):
    """Крок 2: прийняти SimpleResponse від Specific Connector (guide §12.4),
    зберегти Person у Redis та повернути користувача на /preview/{message_id}."""
    raw_body = await _read_simple_response_body(request)
    simple_response = _parse_simple_response(raw_body)

    client = get_redis_client()
    message_id = await _pop_eidas_message_id(client, simple_response.inresponse_to)
    _raise_if_eidas_failed(simple_response, message_id)

    person_payload = simple_response.to_person_payload()
    await _save_eidas_person(client, message_id, person_payload)

    _logger.info(
        "eIDAS: person saved for message_id=%s (%s %s)",
        message_id,
        person_payload["last_name"],
        person_payload["first_name"],
    )
    return RedirectResponse(url=f"/preview/{message_id}", status_code=307)


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
    message_id_str = str(message_id)
    """Показує сторінку з таскбаром очікування, потім рендер evidence."""
    client = get_redis_client()

    # Читаємо returnurl з Redis (збережено при авторизації)
    stored = await client.get_from_redis(KEYS.get_return_url(message_id_str))
    returnurl = filter_returnurl(stored if isinstance(stored, str) else None)
    if not returnurl:
        query_returnurl = request.query_params.get("returnurl")
        if not query_returnurl:
            try:
                query_returnurl = await resolve_url(client, message_id_str)
            except Exception:
                query_returnurl = None
        query_returnurl = filter_returnurl(query_returnurl)
        if query_returnurl:
            await client.save_to_redis(
                KEYS.get_return_url(message_id_str), query_returnurl
            )
            returnurl = query_returnurl

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
    message_id_str = str(message_id)
    """API endpoint для отримання прогресу завантаження evidence."""
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
    message_id_str = str(message_id)
    """Записує статус таймауту в Redis при спливанні часу на клієнті."""
    _require_action_token(request, message_id_str, "preview-timeout")
    client = get_redis_client()
    await record_view_timeout(client, message_id_str, KEYS, QUEUE_OUTGOING)

    _logger.warning("View timeout recorded for message_id=%s", message_id_str)

    return {
        "status": "timeout_recorded",
        "message_id": message_id_str,
    }