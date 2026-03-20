import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from redis.exceptions import ConnectionError as RedisConnectionError

from lib.MessageChecker import check_message
from lib.PersonRequestService import ContinuePayload, save_person_request
from lib.RedirectService import resolve_continue_url
from lib.UseRedis import close_redis, get_redis_client, initialize_redis

logging.basicConfig(level=logging.DEBUG)
_logger = logging.getLogger("Authorization UI")

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


@asynccontextmanager
async def lifespan(_: FastAPI):
    try:
        await initialize_redis()
    except Exception as exc:
        _logger.warning("Redis недоступний на старті: %s", exc)
    yield
    await close_redis()


app = FastAPI(title="Authorization UI", lifespan=lifespan)


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
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
                "code": "",
            },
        )

    if status.timed_out:
        raise HTTPException(
            status_code=408,
            detail=f"Таймаут очікування preview для message_id={message_id}",
        )
    continue_url = await resolve_continue_url(
        client=client,
        message_id=message_id,
        returnurl=request.query_params.get("returnurl"),
        returnmethod=request.query_params.get("returnmethod"),
    )

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
