"""HTTP entrypoint for the authorization UI service."""

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from lxml import etree
from pydantic import BaseModel
from redis.exceptions import ConnectionError as RedisConnectionError

from lib.MessageChecker import check_message
from lib.PersonRequestService import ContinuePayload, save_person_request
from lib.RedirectService import resolve_url
from lib.UseRedis import close_redis, get_redis_client, initialize_redis
from lib.eidas_autofill_service import EidasAutofillService
from lib.preview_service import (
    EmptyEvidenceListError,
    EvidenceDataNotFoundError,
    build_evidence_page_context,
    build_preview_progress,
    check_evidence_ready,
    persist_approvals,
    record_view_timeout,
)
from redis_keys import Keys

WAIT_EVENT_TIME = int(os.environ.get("EVIDENCE_TIMEOUT", "600"))
WAIT_EVENT_SLEEP = int(os.environ.get("WAIT_EVENT_SLEEP", "5"))

QUEUE_OUTGOING = os.getenv("QUEUE_OUTGOING", "oots:queue:outgoing")

KEYS = Keys()

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

try:
    EIDAS_AUTOFILL_SERVICE: EidasAutofillService | None = EidasAutofillService(EIDAS_TEST_DATA_PATH)
except ValueError as exc:
    _logger.warning("eIDAS autofill is disabled: %s", exc)
    EIDAS_AUTOFILL_SERVICE = None


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


@app.get("/health", tags=["System"])
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


@app.get("/auth/{message_id}", response_class=HTMLResponse)
async def root(request: Request, message_id: str):
    client = get_redis_client()

    # Зберігаємо returnurl в Redis при першому заході
    query_returnurl = request.query_params.get("returnurl")
    if not query_returnurl:
        try:
            query_returnurl = await resolve_url(client, message_id)
        except Exception:
            query_returnurl = None

    if query_returnurl:
        await client.save_to_redis(KEYS.return_url(message_id), query_returnurl)

    status = await check_message(client, message_id)

    if status.has_error:
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

    if status.timed_out:
        raise HTTPException(
            status_code=408,
            detail=f"Таймаут очікування preview для message_id={message_id}",
        )

    return templates.TemplateResponse(
        request,
        "login.html",
        {
            "message_id": message_id,
            "continue_url": f"/preview/{message_id}",
        },
    )


@app.post("/auth/continue")
async def continue_auth(payload: ContinuePayload):
    """Validate and persist person data received from the login form."""
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


@app.get("/auth/eidas/next")
async def auth_eidas_next():
    """Return next eIDAS test record for form autofill."""
    if EIDAS_AUTOFILL_SERVICE is None:
        raise HTTPException(status_code=503, detail="eIDAS test data is not configured")
    return EIDAS_AUTOFILL_SERVICE.get_next_payload()


async def _render_evidence_page(
        request: Request, message_id: str
) -> HTMLResponse:
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

    return templates.TemplateResponse(request, "evidences.html", context)


@app.get("/preview/{message_id}")
async def view_evidence(request: Request, message_id: str):
    """Показує сторінку з таскбаром очікування, потім рендер evidence."""
    client = get_redis_client()

    # Читаємо returnurl з Redis (збережено при авторизації)
    stored = await client.get_from_redis(KEYS.return_url(message_id))
    if not stored:
        query_returnurl = request.query_params.get("returnurl")
        if not query_returnurl:
            try:
                query_returnurl = await resolve_url(client, message_id)
            except Exception:
                query_returnurl = None
        if query_returnurl:
            await client.save_to_redis(KEYS.return_url(message_id), query_returnurl)

    evidence_ready = await check_evidence_ready(client, message_id, KEYS)

    if evidence_ready:
        # Евіденс готовий, рендеримо evidence сторінку одразу
        return await _render_evidence_page(request, message_id)

    # Якщо ні, показуємо сторінку чекання
    return templates.TemplateResponse(
        request,
        "view_waiting.html",
        {
            "message_id": message_id,
            "wait_time": WAIT_EVENT_TIME,
            "poll_interval": WAIT_EVENT_SLEEP,
        },
    )


@app.get("/preview/progress/{message_id}")
async def view_progress(message_id: str):
    """API endpoint для отримання прогресу завантаження evidence."""
    client = get_redis_client()
    return await build_preview_progress(client, message_id, KEYS)


@app.post("/preview/continue")
async def continue_view(request: Request, payload: ViewContinuePayload):
    """Persist checkbox approvals for preview evidences."""
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
        raise HTTPException(status_code=404, detail=f"Data not found in Redis by id: {message_id}") from exc

    # Читаємо returnurl з Redis (збережено при авторизації)
    returnurl = await client.get_from_redis(KEYS.return_url(message_id))

    return {
        "status": "success",
        "message": "Approvals received",
        "approvals": approvals,
        "returnurl": returnurl,
    }


@app.post("/preview/timeout/{message_id}")
async def view_timeout(message_id: str):
    """Записує статус таймауту в Redis при спливанні часу на клієнті."""
    client = get_redis_client()
    await record_view_timeout(client, message_id, KEYS, QUEUE_OUTGOING)

    _logger.warning("View timeout recorded for message_id=%s", message_id)

    return {
        "status": "timeout_recorded",
        "message_id": message_id,
    }
