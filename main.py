"""HTTP entrypoint for the authorization UI service."""

import logging
import os
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from lxml import etree
from pydantic import BaseModel
from redis.exceptions import ConnectionError as RedisConnectionError

from lib.MessageChecker import check_message
from lib.PersonRequestService import ContinuePayload, save_person_request
from lib.UseRedis import close_redis, get_redis_client, initialize_redis
from redis_keys import Keys

WAIT_EVENT_TIME = int(os.environ.get("WAIT_EVENT_TIME", "120"))
WAIT_EVENT_SLEEP = int(os.environ.get("WAIT_EVENT_SLEEP", "5"))

QUEUE_OUTGOING = os.getenv("QUEUE_OUTGOING", "oots:queue:outgoing")

KEYS = Keys()


logging.basicConfig(level=logging.DEBUG)
_logger = logging.getLogger("Authorization UI")
APP_TITLE = "Authorization UI"

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


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
    continue_url = f"/preview/{message_id}"
    query_pairs = list(request.query_params.multi_items())
    if query_pairs:
        continue_url = f"{continue_url}?{urlencode(query_pairs, doseq=True)}"

    return templates.TemplateResponse(
        request,
        "login.html",
        {
            "message_id": message_id,
            "continue_url": continue_url,
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


async def _check_preview_ready(client, message_id: str) -> bool:
    """Перевіряє чи готовий прапор preview в Redis."""
    preview_key = KEYS.request_preview(message_id)
    return await client.get_raw_from_redis(preview_key) is not None


async def _check_evidence_ready(client, message_id: str) -> bool:
    """Перевіряє чи готовий evidence в Redis."""
    evidence_key = KEYS.response_evidence(message_id)
    return await client.get_from_redis(evidence_key) is not None


async def _render_evidence_page(
    request: Request, message_id: str, returnurl: str
) -> HTMLResponse:
    """Рендер PDF або XML сторінки з evidences."""
    client = get_redis_client()
    redis_key = KEYS.response_evidence(message_id)
    data = await client.get_from_redis(redis_key)

    if not isinstance(data, dict):
        raise HTTPException(
            status_code=404,
            detail=f"Data not found in Redis by id: {message_id}",
        )

    evidences: list[dict[str, Any]] = data.get("evidences") or []
    if not evidences:
        raise HTTPException(
            status_code=400,
            detail="No evidences found for preview",
        )

    first_content_type = evidences[0].get("content_type")
    if first_content_type == "application/pdf":
        pdf_list = [
            {"title": evidence.get("cid"), "pdf_preview": evidence.get("content", "")}
            for evidence in evidences
        ]
        return templates.TemplateResponse(
            request,
            "pdf.html",
            {
                "returnurl": returnurl,
                "message_id": message_id,
                "message_uuid": message_id,
                "pdf_list": pdf_list,
            },
        )

    if first_content_type == "application/xml":
        xml_list = [
            {"title": evidence.get("cid"), "xml": evidence.get("content", "")}
            for evidence in evidences
        ]
        return templates.TemplateResponse(
            request,
            "xml.html",
            {
                "xml_list": xml_list,
                "message_id": message_id,
                "message_uuid": message_id,
                "returnurl": returnurl,
            },
        )

    raise HTTPException(
        status_code=400,
        detail=f"Unsupported content type: {first_content_type}",
    )


@app.get("/preview/{message_id}")
async def view_evidence(request: Request, message_id: str):
    """Показує сторінку з таскбаром очікування, потім рендер evidence."""
    returnurl = request.query_params.get("returnurl")

    if not returnurl:
        raise HTTPException(
            status_code=400,
            detail="Відсутній обовʼязковий параметр 'returnurl'. "
                   "URL повинен містити параметр returnurl. Приклад: /preview/123?returnurl=https://example.com",
        )

    client = get_redis_client()

    # Перевіряємо чи обидва етапи вже готові
    _ = await _check_preview_ready(client, message_id)
    evidence_ready = await _check_evidence_ready(client, message_id)

    if evidence_ready:
        # Обидва готові, рендеримо evidence сторінку одразу
        return await _render_evidence_page(request, message_id, returnurl)

    # Якщо ні, показуємо сторінку чекання
    return templates.TemplateResponse(
        request,
        "view_waiting.html",
        {
            "message_id": message_id,
            "returnurl": returnurl,
            "wait_time": WAIT_EVENT_TIME,
            "poll_interval": WAIT_EVENT_SLEEP,
        },
    )


@app.get("/preview/progress/{message_id}")
async def view_progress(message_id: str):
    """API endpoint для отримання прогресу завантаження evidence."""
    client = get_redis_client()

    preview_ready = await _check_preview_ready(client, message_id)
    evidence_ready = await _check_evidence_ready(client, message_id)

    # Визначаємо етап:
    # 0 - нічого не готове
    # 1 - preview готовий
    # 2 - evidence готовий
    stage = 0
    if preview_ready:
        stage = 1
    if evidence_ready:
        stage = 2

    return {
        "message_id": message_id,
        "stage": stage,
        "preview_ready": preview_ready,
        "evidence_ready": evidence_ready,
    }


@app.post("/preview/continue")
async def continue_view(payload: ViewContinuePayload):
    """Persist checkbox approvals for preview evidences."""
    client = get_redis_client()
    message_id = payload.message_uuid

    evidence_key = KEYS.response_evidence(message_id)
    permit_key = KEYS.response_permit(message_id)
    json_data = await client.get_from_redis(evidence_key)
    if not isinstance(json_data, dict):
        raise HTTPException(status_code=404, detail=f"Data not found in Redis by id: {message_id}")

    evidences = json_data.get("evidences") or []
    for evidence in evidences:
        cid = evidence.get("cid")
        if cid in payload.approvals:
            evidence["permit"] = payload.approvals[cid]

    json_data["preview"] = False

    await  asyncio.gather(
        client.save_to_redis(evidence_key, json_data),
        client.save_to_redis(permit_key, "true"),
        client.push_to_queue(QUEUE_OUTGOING, message_id),
    )

    return {
        "status": "success",
        "message": "Approvals received",
        "approvals": payload.approvals,
    }


@app.post("/preview/timeout/{message_id}")
async def view_timeout(message_id: str):
    """Записує статус таймауту в Redis при спливанні часу на клієнті."""
    client = get_redis_client()

    # Записуємо таймаут-статус під спеціальним ключем
    timeout_key = KEYS.response_exp(message_id)
    await client.save_to_redis(
        timeout_key,
        {
            "exception": {
                "code": "EDM:ERR:0005",
                "message": f"View timeout for message_id={message_id}",
                "detail": f"View timeout for message_id={message_id}",
            }
        }
    )
    await client.push_to_queue(QUEUE_OUTGOING, message_id)

    _logger.warning("View timeout recorded for message_id=%s", message_id)

    return {
        "status": "timeout_recorded",
        "message_id": message_id,
    }
