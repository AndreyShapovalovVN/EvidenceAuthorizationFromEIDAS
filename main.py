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
    return await client.get_flag(preview_key, default=False)


async def _check_evidence_ready(client, message_id: str) -> bool:
    """Перевіряє чи готовий evidence в Redis."""
    evidence_key = KEYS.response_evidence(message_id)
    return await client.get_from_redis(evidence_key) is not None

def _is_new_evidences_structure(data: dict[str, Any]) -> bool:
    evidences = data.get("evidences")
    if not isinstance(evidences, list) or not evidences:
        return False
    first = evidences[0]
    return isinstance(first, dict) and isinstance(first.get("RegistryPackage"), list)


def _normalize_preview_descriptions(data: dict[str, Any]) -> list[str]:
    descriptions: list[str] = []
    raw = data.get("PreviewDescription", [])
    if not isinstance(raw, list):
        return descriptions

    for item in raw:
        if isinstance(item, dict):
            if "value" in item:
                descriptions.append(str(item.get("value", "")))
            else:
                # Legacy format: [{"UA": "..."}, {"EN": "..."}]
                descriptions.extend(str(value) for value in item.values())

    return [value for value in descriptions if value]


def _looks_like_xml(value: str) -> bool:
    text = value.strip()
    if not text:
        return False

    lowered = text[:256].lower()
    return (
        text.startswith("<")
        or "<?xml" in lowered
        or "xmlns:" in lowered
        or "</" in lowered
        or lowered.startswith("&lt;")
    )


def _safe_sidebar_text(value: Any) -> str:
    text = str(value or "").strip()
    if not text or _looks_like_xml(text):
        return ""
    return " ".join(text.split())


def _build_evidence_view_model(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Builds unified UI model for both new and legacy evidence formats."""
    results: list[dict[str, Any]] = []

    if _is_new_evidences_structure(data):
        for package_index, package in enumerate(data.get("evidences", [])):
            if not isinstance(package, dict):
                continue

            approval_key = str(package.get("id") or f"evidence-{package_index}")
            permit = bool(package.get("permit", False))
            package_objects = package.get("RegistryPackage", [])

            content_items: list[dict[str, Any]] = []
            title = _safe_sidebar_text(package.get("title"))

            for content_index, obj in enumerate(package_objects):
                if not isinstance(obj, dict):
                    continue

                classification = obj.get("classification", {})
                class_node = "Unknown"
                if isinstance(classification, dict):
                    class_node = str(classification.get("classificationNode") or "Unknown")

                repo_ref = obj.get("RepositoryItemRef", {})
                ref_title = class_node
                ref_href = ""
                if isinstance(repo_ref, dict):
                    ref_title = str(repo_ref.get("title") or class_node)
                    ref_href = str(repo_ref.get("href") or "")

                safe_ref_title = _safe_sidebar_text(ref_title)
                if not title and class_node in {"MainEvidence", "HumanReadableVersion"}:
                    title = safe_ref_title

                content_type = str(obj.get("content_type") or "")
                content = obj.get("content")
                label = class_node
                if safe_ref_title and safe_ref_title != class_node:
                    label = f"{class_node}: {safe_ref_title}"

                content_items.append(
                    {
                        "id": f"{approval_key}:{content_index}",
                        "label": label,
                        "classification_node": class_node,
                        "content_type": content_type,
                        "content": content,
                        "cid": ref_href,
                    }
                )

            if not content_items:
                continue

            if not title:
                title = _safe_sidebar_text(approval_key) or f"Evidence {package_index + 1}"

            default_item = next(
                (
                    item for item in content_items
                    if item["classification_node"] == "HumanReadableVersion"
                    and item["content_type"] == "application/pdf"
                ),
                content_items[0],
            )

            results.append(
                {
                    "id": f"evidence-{package_index}",
                    "approval_key": approval_key,
                    "title": title,
                    "permit": permit,
                    "default_content_id": default_item["id"],
                    "contents": content_items,
                }
            )

        return results

    # Legacy fallback: one flat evidence item == one evidence card
    for index, item in enumerate(data.get("evidences", [])):
        if not isinstance(item, dict):
            continue

        cid = str(item.get("cid") or f"legacy-{index}")
        content_type = str(item.get("content_type") or "")
        content = item.get("content")
        content_id = f"legacy-{index}:0"
        title = _safe_sidebar_text(item.get("title")) or _safe_sidebar_text(cid) or f"Evidence {index + 1}"

        results.append(
            {
                "id": f"legacy-{index}",
                "approval_key": cid,
                "title": title,
                "permit": bool(item.get("permit", False)),
                "default_content_id": content_id,
                "contents": [
                    {
                        "id": content_id,
                        "label": f"MainEvidence: {cid}",
                        "classification_node": "MainEvidence",
                        "content_type": content_type,
                        "content": content,
                        "cid": cid,
                    }
                ],
            }
        )

    return results


async def _render_evidence_page(
    request: Request, message_id: str, returnurl: str
) -> HTMLResponse:
    """Рендерить уніфіковану сторінку перегляду evidences."""
    client = get_redis_client()
    redis_key = KEYS.response_evidence(message_id)
    data = await client.get_from_redis(redis_key)

    if not isinstance(data, dict):
        raise HTTPException(
            status_code=404,
            detail=f"Data not found in Redis by id: {message_id}",
        )

    evidences = _build_evidence_view_model(data)
    if not evidences:
        raise HTTPException(
            status_code=400,
            detail="No evidences found for preview",
        )

    return templates.TemplateResponse(
        request,
        "evidences.html",
        {
            "returnurl": returnurl,
            "message_id": message_id,
            "message_uuid": message_id,
            "title": str(data.get("title") or "Evidence Preview"),
            "preview_descriptions": _normalize_preview_descriptions(data),
            "evidences": evidences,
        },
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
    if _is_new_evidences_structure(json_data):
        for package in evidences:
            if not isinstance(package, dict):
                continue
            approval_key = str(package.get("id") or "")
            if approval_key and approval_key in payload.approvals:
                package["permit"] = bool(payload.approvals[approval_key])
    else:
        for index, evidence in enumerate(evidences):
            if not isinstance(evidence, dict):
                continue
            approval_key = str(evidence.get("cid") or f"legacy-{index}")
            if approval_key in payload.approvals:
                evidence["permit"] = bool(payload.approvals[approval_key])

    json_data["preview"] = False

    await  asyncio.gather(
        client.save_to_redis(evidence_key, json_data),
        client.set_flag(permit_key, True),
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
