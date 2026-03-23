from unittest.mock import AsyncMock

import main
from lib.MessageChecker import ExceptionInfo, MessageStatus
from redis.exceptions import ConnectionError as RedisConnectionError


def test_health_ok(client, fake_redis_client, monkeypatch):
    monkeypatch.setattr(main, "get_redis_client", lambda: fake_redis_client)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "redis": "up"}


def test_health_redis_down_returns_503(client, fake_redis_client, monkeypatch):
    fake_redis_client.health_check = AsyncMock(
        side_effect=RedisConnectionError("Redis unavailable")
    )
    monkeypatch.setattr(main, "get_redis_client", lambda: fake_redis_client)

    response = client.get("/health")

    assert response.status_code == 503
    assert response.json()["detail"] == "Redis недоступний"


def test_root_renders_html_when_edm_err_0002_found(client, monkeypatch):
    async def fake_check_message(_, __):
        return MessageStatus(
            evidence_error=ExceptionInfo(
                code="EDM:ERR:0002",
                message="Evidence not found",
                detail="No evidence",
                preview_link=None,
            ),
            preview_ready=True,
            timed_out=False,
        )

    async def fake_resolve_continue_url(**_):
        return "http://continue.local/path"

    monkeypatch.setattr(main, "check_message", fake_check_message)
    monkeypatch.setattr(main, "resolve_continue_url", fake_resolve_continue_url)

    response = client.get("/auth/msg-001")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "msg-001" in response.text


def test_root_returns_408_on_preview_timeout(client, monkeypatch):
    async def fake_check_message(_, __):
        return MessageStatus(preview_ready=False, timed_out=True)

    monkeypatch.setattr(main, "check_message", fake_check_message)

    response = client.get("/auth/msg-002")

    assert response.status_code == 408
    assert "Таймаут" in response.json()["detail"]


def test_root_renders_html_when_checks_pass(client, monkeypatch):
    async def fake_check_message(_, __):
        return MessageStatus(preview_ready=True, timed_out=False)

    async def fake_resolve_continue_url(**_):
        return "http://continue.local/path"

    monkeypatch.setattr(main, "check_message", fake_check_message)
    monkeypatch.setattr(main, "resolve_continue_url", fake_resolve_continue_url)

    response = client.get("/auth/msg-003")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "Secure Authorization" in response.text
    assert "Log in via eIDAS" in response.text
    assert "msg-003" in response.text


def test_continue_auth_saves_person_and_returns_key(client, monkeypatch, fake_redis_client):
    async def fake_save_person_request(_, payload):
        assert payload.message_id == "msg-101"
        return "oots:request:person:msg-101", {"GivenNameNonLatin": "Andrii"}

    monkeypatch.setattr(main, "get_redis_client", lambda: fake_redis_client)
    monkeypatch.setattr(main, "save_person_request", fake_save_person_request)

    response = client.post(
        "/auth/continue",
        json={
            "first_name": "Andrii",
            "last_name": "Kovalenko",
            "date_of_birth": "1992-04-18",
            "identifier": "UA/UA/3124509876",
            "message_id": "msg-101",
            "level_of_assurance": "High",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["redis_key"] == "oots:request:person:msg-101"
    assert body["status"] == "ok"


def test_continue_auth_returns_422_on_value_error(client, monkeypatch, fake_redis_client):
    async def fake_save_person_request(_, __):
        raise ValueError("invalid payload")

    monkeypatch.setattr(main, "get_redis_client", lambda: fake_redis_client)
    monkeypatch.setattr(main, "save_person_request", fake_save_person_request)

    response = client.post(
        "/auth/continue",
        json={
            "first_name": "Andrii",
            "last_name": "Kovalenko",
            "date_of_birth": "1992-04-18",
            "identifier": "UA/UA/3124509876",
            "message_id": "msg-201",
            "level_of_assurance": "High",
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "invalid payload"


def test_continue_auth_returns_503_on_storage_error(client, monkeypatch, fake_redis_client):
    async def fake_save_person_request(_, __):
        raise RuntimeError("redis timeout")

    monkeypatch.setattr(main, "get_redis_client", lambda: fake_redis_client)
    monkeypatch.setattr(main, "save_person_request", fake_save_person_request)

    response = client.post(
        "/auth/continue",
        json={
            "first_name": "Andrii",
            "last_name": "Kovalenko",
            "date_of_birth": "1992-04-18",
            "identifier": "UA/UA/3124509876",
            "message_id": "msg-301",
            "level_of_assurance": "High",
        },
    )

    assert response.status_code == 503
    assert "Не вдалося зберегти дані в Redis" in response.json()["detail"]

