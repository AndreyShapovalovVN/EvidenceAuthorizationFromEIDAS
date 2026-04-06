import main
from lib.MessageChecker import MessageStatus
from redis_keys import Keys


def test_view_requires_returnurl(client):
    response = client.get("/preview/msg-001")

    assert response.status_code == 400
    assert "returnurl" in response.json()["detail"]


def test_auth_builds_continue_url_to_preview_with_returnurl(client, monkeypatch):
    async def fake_check_message(_, __):
        return MessageStatus(preview_ready=True, timed_out=False)

    monkeypatch.setattr(main, "check_message", fake_check_message)

    response = client.get("/auth/msg-001?returnurl=https://example.com/callback")

    assert response.status_code == 200
    assert "/preview/msg-001?returnurl=https%3A%2F%2Fexample.com%2Fcallback" in response.text


def test_auth_builds_continue_url_to_preview_without_returnurl(client, monkeypatch):
    async def fake_check_message(_, __):
        return MessageStatus(preview_ready=True, timed_out=False)

    monkeypatch.setattr(main, "check_message", fake_check_message)

    response = client.get("/auth/msg-002")

    assert response.status_code == 200
    assert 'const continueUrl = "/preview/msg-002";' in response.text


def test_view_returns_404_when_data_missing(client, fake_redis_client, monkeypatch):
    fake_redis_client.get_from_redis.return_value = None
    monkeypatch.setattr(main, "get_redis_client", lambda: fake_redis_client)

    response = client.get("/preview/msg-002?returnurl=https://example.com")

    # Сторінка чекання показується, коли evidence не готовий
    assert response.status_code == 200
    assert "Loading Evidence" in response.text


def test_view_progress_returns_stage_0_when_no_data(client, fake_redis_client, monkeypatch):
    fake_redis_client.get_from_redis.return_value = None
    monkeypatch.setattr(main, "get_redis_client", lambda: fake_redis_client)

    response = client.get("/preview/progress/msg-002")

    assert response.status_code == 200
    assert response.json()["stage"] == 0
    assert response.json()["preview_ready"] is False
    assert response.json()["evidence_ready"] is False


def test_view_renders_pdf_template(client, fake_redis_client, monkeypatch):
    evidence_data = {
        "preview": True,
        "evidences": [
            {
                "cid": "doc-1",
                "content_type": "application/pdf",
                "content": "JVBERi0xLjcK",
            }
        ],
    }
    fake_redis_client.get_from_redis.return_value = evidence_data
    # get_raw_from_redis сигналізує, що evidence готовий → рендеримо одразу
    fake_redis_client.get_raw_from_redis.return_value = b"1"
    monkeypatch.setattr(main, "get_redis_client", lambda: fake_redis_client)

    response = client.get("/preview/msg-003?returnurl=https://example.com")

    assert response.status_code == 200
    assert "PDF Evidences" in response.text
    assert "/preview/continue" in response.text


def test_view_renders_xml_template(client, fake_redis_client, monkeypatch):
    evidence_data = {
        "preview": True,
        "evidences": [
            {
                "cid": "doc-xml",
                "content_type": "application/xml",
                "content": "<Root><Name>Test</Name></Root>",
            }
        ],
    }
    fake_redis_client.get_from_redis.return_value = evidence_data
    fake_redis_client.get_raw_from_redis.return_value = b"1"
    monkeypatch.setattr(main, "get_redis_client", lambda: fake_redis_client)

    response = client.get("/preview/msg-004?returnurl=https://example.com")

    assert response.status_code == 200
    assert "XML Documents Viewer" in response.text
    assert "/preview/continue" in response.text


def test_continue_view_updates_approvals_and_flags(client, fake_redis_client, monkeypatch):
    fake_redis_client.get_from_redis.return_value = {
        "preview": True,
        "evidences": [
            {"cid": "doc-1", "permit": False},
            {"cid": "doc-2", "permit": False},
        ],
    }
    monkeypatch.setattr(main, "get_redis_client", lambda: fake_redis_client)

    response = client.post(
        "/preview/continue",
        json={
            "message_uuid": "msg-005",
            "approvals": {"doc-1": True, "doc-2": False},
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "success"

    evidence_key = Keys.RESPONSE_EVIDENCE.format(conversation_id="msg-005")
    permit_key = Keys.RESPONSE_PERMIT.format(conversation_id="msg-005")

    first_call = fake_redis_client.save_to_redis.await_args_list[0]
    second_call = fake_redis_client.save_to_redis.await_args_list[1]

    assert first_call.args[0] == evidence_key
    assert first_call.args[1]["preview"] is False
    assert first_call.args[1]["evidences"][0]["permit"] is True
    assert first_call.args[1]["evidences"][1]["permit"] is False

    assert second_call.args[0] == permit_key
    assert second_call.args[1] == "true"

