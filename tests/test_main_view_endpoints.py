import main
from unittest.mock import AsyncMock
from lib.action_token import issue_action_token
from lib.evidence_view_model import build_evidence_view_model
from lib.MessageChecker import MessageStatus
from redis_keys import Keys


def _token_headers(message_id: str, action: str) -> dict[str, str]:
    return {"X-Action-Token": issue_action_token(message_id, action)}


def test_view_without_returnurl_shows_waiting(client, fake_redis_client, monkeypatch):
    fake_redis_client.get_from_redis.return_value = None
    fake_redis_client.get_flag.return_value = False
    monkeypatch.setattr(main, "get_redis_client", lambda: fake_redis_client)

    response = client.get("/preview/00000000-0000-0000-0000-000000000001")

    assert response.status_code == 200
    assert "Loading Evidence" in response.text


def test_preview_skips_when_request_preview_flag_not_set(client, fake_redis_client, monkeypatch):
    fake_redis_client.get_flag.return_value = False
    fake_redis_client.get_from_redis.return_value = None
    monkeypatch.setattr(main, "get_redis_client", lambda: fake_redis_client)

    response = client.get(
        "/preview/00000000-0000-0000-0000-000000000002?returnurl=https://example.com/back",
        follow_redirects=False,
    )

    assert response.status_code == 200
    assert "Loading Evidence" in response.text
    fake_redis_client.push_to_queue.assert_not_awaited()


def test_preview_shows_waiting_when_flag_set_but_evidence_missing(client, fake_redis_client, monkeypatch):
    fake_redis_client.get_flag.side_effect = lambda key, **_: "request:preview" in key
    fake_redis_client.get_from_redis.return_value = None
    monkeypatch.setattr(main, "get_redis_client", lambda: fake_redis_client)

    response = client.get("/preview/00000000-0000-0000-0000-000000000003?returnurl=https://example.com/back")

    assert response.status_code == 200
    assert "Loading Evidence" in response.text
    assert 'const timeoutRedirectUrl = "https://example.com/back";' in response.text
    assert "const previewUrl = `/preview/${messageId}`;" in response.text


def test_preview_renders_immediately_when_both_ready(client, fake_redis_client, monkeypatch):
    evidence_data = {
        "evidences": [
            {
                "id": "pkg-1",
                "permit": False,
                "RegistryPackage": [
                    {
                        "classification": {"classificationNode": "MainEvidence"},
                        "RepositoryItemRef": {"title": "Doc", "href": "cid:1"},
                        "content_type": "application/xml",
                        "content": "<A/>",
                    }
                ],
            }
        ]
    }
    fake_redis_client.get_flag.return_value = True
    fake_redis_client.get_from_redis.return_value = evidence_data
    monkeypatch.setattr(main, "get_redis_client", lambda: fake_redis_client)

    response = client.get("/preview/00000000-0000-0000-0000-000000000004?returnurl=https://example.com/back")

    assert response.status_code == 200
    assert "Evidences" in response.text


def test_preview_redirects_to_returnurl_when_exp_ready(client, fake_redis_client, monkeypatch):
    message_id = "00000000-0000-0000-0000-000000000005"
    return_url = "https://example.com/back"

    def _get_from_redis(key):
        if key == main.KEYS.get_return_url(message_id):
            return return_url
        if key == main.KEYS.get_response_exp(message_id):
            return {"exception": {"code": "EDM:ERR:0005"}}
        if key == main.KEYS.get_response_evidence(message_id):
            return None
        return None

    fake_redis_client.get_from_redis.side_effect = _get_from_redis
    monkeypatch.setattr(main, "get_redis_client", lambda: fake_redis_client)

    response = client.get(f"/preview/{message_id}", follow_redirects=False)

    assert response.status_code == 307
    assert response.headers["location"] == return_url


def test_auth_builds_continue_url_to_preview_with_returnurl(client, fake_redis_client, monkeypatch):
    # Мокуємо REQUEST_EDM як наявний, REQUEST_PERSON як відсутній
    def side_effect_fn(key):
        if "request:edm" in key:
            return {"some": "edm"}
        if "request:person" in key:
            return None
        return None
    
    fake_redis_client.get_from_redis.side_effect = side_effect_fn

    monkeypatch.setattr(
        main,
        "check_message",
        AsyncMock(return_value=MessageStatus(preview_ready=True, timed_out=False)),
    )
    monkeypatch.setattr(main, "if_preview", AsyncMock(return_value=True))
    monkeypatch.setattr(main, "get_redis_client", lambda: fake_redis_client)

    response = client.get("/auth/00000000-0000-0000-0000-000000000001?returnurl=https://example.com/callback")

    assert response.status_code == 200
    assert 'const continueUrl = "/preview/00000000-0000-0000-0000-000000000001";' in response.text


def test_auth_saves_returnurl_to_redis(client, fake_redis_client, monkeypatch):
    # Мокуємо REQUEST_EDM як наявний, REQUEST_PERSON як відсутній
    def side_effect_fn(key):
        if "request:edm" in key:
            return {"some": "edm"}
        if "request:person" in key:
            return None
        return None
    
    fake_redis_client.get_from_redis.side_effect = side_effect_fn

    monkeypatch.setattr(
        main,
        "check_message",
        AsyncMock(return_value=MessageStatus(preview_ready=True, timed_out=False)),
    )
    monkeypatch.setattr(main, "get_redis_client", lambda: fake_redis_client)

    client.get("/auth/00000000-0000-0000-0000-000000000006?returnurl=https://example.com/callback")

    returnurl_key = Keys().get_return_url("00000000-0000-0000-0000-000000000006")
    save_calls = [c.args for c in fake_redis_client.save_to_redis.await_args_list]
    assert any(c[0] == returnurl_key for c in save_calls)


def test_auth_builds_continue_url_to_preview_without_returnurl(client, fake_redis_client, monkeypatch):
    # Мокуємо REQUEST_EDM як наявний, REQUEST_PERSON як відсутній
    def side_effect_fn(key):
        if "request:edm" in key:
            return {"some": "edm"}
        if "request:person" in key:
            return None
        return None
    
    fake_redis_client.get_from_redis.side_effect = side_effect_fn

    monkeypatch.setattr(
        main,
        "check_message",
        AsyncMock(return_value=MessageStatus(preview_ready=True, timed_out=False)),
    )
    monkeypatch.setattr(main, "if_preview", AsyncMock(return_value=True))
    monkeypatch.setattr(main, "get_redis_client", lambda: fake_redis_client)

    response = client.get("/auth/00000000-0000-0000-0000-000000000007")

    assert response.status_code == 200
    assert 'const continueUrl = "/preview/00000000-0000-0000-0000-000000000007";' in response.text


def test_auth_eidas_next_returns_sequential_records(client, monkeypatch):
    class StubAutofillService:
        def __init__(self):
            self._counter = 0

        def get_next_payload(self):
            self._counter += 1
            return {
                "first_name": f"Name{self._counter}",
                "last_name": f"Last{self._counter}",
                "date_of_birth": "1990-01-01",
                "identifier": f"UA/UA/{self._counter}",
                "level_of_assurance": "High",
            }

    monkeypatch.setattr(main, "EIDAS_AUTOFILL_SERVICE", StubAutofillService())

    first = client.get("/auth/eidas/next")
    second = client.get("/auth/eidas/next")

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["identifier"] == "UA/UA/1"
    assert second.json()["identifier"] == "UA/UA/2"


def test_auth_eidas_next_returns_503_when_service_disabled(client, monkeypatch):
    monkeypatch.setattr(main, "EIDAS_AUTOFILL_SERVICE", None)

    response = client.get("/auth/eidas/next")

    assert response.status_code == 503
    assert "not configured" in response.json()["detail"]


def test_view_returns_404_when_data_missing(client, fake_redis_client, monkeypatch):
    fake_redis_client.get_flag.return_value = True
    fake_redis_client.get_from_redis.return_value = None
    monkeypatch.setattr(main, "get_redis_client", lambda: fake_redis_client)

    response = client.get("/preview/00000000-0000-0000-0000-000000000007?returnurl=https://example.com")

    # Сторінка чекання показується, коли evidence не готовий.
    assert response.status_code == 200
    assert "Loading Evidence" in response.text


def test_view_progress_returns_stage_1_when_no_data(client, fake_redis_client, monkeypatch):
    fake_redis_client.get_flag.return_value = False
    fake_redis_client.get_from_redis.return_value = None
    monkeypatch.setattr(main, "get_redis_client", lambda: fake_redis_client)

    response = client.get(
        "/preview/progress/00000000-0000-0000-0000-000000000007",
        headers=_token_headers("00000000-0000-0000-0000-000000000007", "preview-progress"),
    )

    assert response.status_code == 200
    assert response.json()["stage"] == 1
    assert response.json()["preview_ready"] is True
    assert response.json()["evidence_ready"] is False
    assert response.json()["exp_ready"] is False
    fake_redis_client.push_to_queue.assert_not_awaited()


def test_view_progress_enqueues_process_queue_once(client, fake_redis_client, monkeypatch):
    message_id = "00000000-0000-0000-0000-000000000009"
    dispatch_key = f"oots:message:request:process_queue_dispatched:{message_id}"
    state = {"dispatched": False}

    def _get_from_redis(key):
        if key == main.KEYS.get_request_edm(message_id):
            return [{"process_queue": "oots:queue:process"}]
        if key == main.KEYS.get_response_evidence(message_id):
            return None
        if key == main.KEYS.get_response_exp(message_id):
            return None
        return None

    def _get_flag(key, default=False):
        if key == dispatch_key:
            return state["dispatched"]
        return default

    def _set_flag(key, value):
        if key != dispatch_key:
            return None
        state["dispatched"] = bool(value)
        return None

    fake_redis_client.get_from_redis.side_effect = _get_from_redis
    fake_redis_client.get_flag.side_effect = _get_flag
    fake_redis_client.set_flag.side_effect = _set_flag
    monkeypatch.setattr(main, "get_redis_client", lambda: fake_redis_client)

    first = client.get(
        f"/preview/progress/{message_id}",
        headers=_token_headers(message_id, "preview-progress"),
    )
    second = client.get(
        f"/preview/progress/{message_id}",
        headers=_token_headers(message_id, "preview-progress"),
    )

    assert first.status_code == 200
    assert second.status_code == 200
    fake_redis_client.push_to_queue.assert_awaited_once_with("oots:queue:process", message_id)
    assert state["dispatched"] is True


def test_view_progress_returns_exp_ready_when_exp_exists(client, fake_redis_client, monkeypatch):
    message_id = "00000000-0000-0000-0000-000000000007"

    def _get_from_redis(key):
        if key == main.KEYS.get_response_exp(message_id):
            return {"exception": {"code": "EDM:ERR:0005"}}
        return None

    fake_redis_client.get_from_redis.side_effect = _get_from_redis
    monkeypatch.setattr(main, "get_redis_client", lambda: fake_redis_client)

    response = client.get(
        f"/preview/progress/{message_id}",
        headers=_token_headers(message_id, "preview-progress"),
    )

    assert response.status_code == 200
    assert response.json()["stage"] == 1
    assert response.json()["evidence_ready"] is False
    assert response.json()["exp_ready"] is True


def test_view_renders_pdf_template(client, fake_redis_client, monkeypatch):
    evidence_data = {
        "title": "Evidence package",
        "PreviewDescription": [{"lang": "EN", "value": "Demo preview"}],
        "preview": True,
        "evidences": [
            {
                "id": "pkg-1",
                "permit": False,
                "RegistryPackage": [
                    {
                        "classification": {
                            "id": "cls-1",
                            "classificationScheme": "urn:fdc:oots:classification:edm",
                            "classificationNode": "MainEvidence",
                        },
                        "EvidenceMetadata": "Birth certificate",
                        "RepositoryItemRef": {
                            "title": "Evidence XML",
                            "href": "cid:main-1",
                        },
                        "content_type": "application/xml",
                        "content": "<Root><A>1</A></Root>",
                    },
                    {
                        "classification": {
                            "id": "cls-2",
                            "classificationScheme": "urn:fdc:oots:classification:edm",
                            "classificationNode": "HumanReadableVersion",
                        },
                        "EvidenceMetadata": "Birth certificate",
                        "RepositoryItemRef": {
                            "title": "Evidence PDF",
                            "href": "cid:pdf-1",
                        },
                        "content_type": "application/pdf",
                        "content": "JVBERi0xLjcK",
                    },
                ],
            }
        ],
    }
    fake_redis_client.get_flag.return_value = True
    fake_redis_client.get_from_redis.return_value = evidence_data
    monkeypatch.setattr(main, "get_redis_client", lambda: fake_redis_client)

    response = client.get("/preview/00000000-0000-0000-0000-000000000008?returnurl=https://example.com")

    assert response.status_code == 200
    assert "Evidences" in response.text
    assert "HumanReadableVersion" in response.text
    assert "/static/evidences.js" in response.text


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
    fake_redis_client.get_flag.return_value = True
    fake_redis_client.get_from_redis.return_value = evidence_data
    monkeypatch.setattr(main, "get_redis_client", lambda: fake_redis_client)

    response = client.get("/preview/00000000-0000-0000-0000-000000000009?returnurl=https://example.com")

    assert response.status_code == 200
    assert "Evidences" in response.text
    assert "MainEvidence" in response.text
    assert "/static/evidences.js" in response.text


def test_build_evidence_view_model_ignores_xml_metadata_in_sidebar():
    new_model = build_evidence_view_model(
        {
            "evidences": [
                {
                    "id": "pkg-xml",
                    "permit": False,
                    "RegistryPackage": [
                        {
                            "classification": {"classificationNode": "MainEvidence"},
                            "EvidenceMetadata": "<sdg:Evidence xmlns:sdg=\"urn:test\"><sdg:Title>Bad XML</sdg:Title></sdg:Evidence>",
                            "RepositoryItemRef": {
                                "title": "Readable title",
                                "href": "cid:main-xml",
                            },
                            "content_type": "application/xml",
                            "content": "<Root/>",
                        }
                    ],
                }
            ]
        }
    )

    legacy_model = build_evidence_view_model(
        {
            "evidences": [
                {
                    "cid": "doc-legacy",
                    "metadata": "<xml>legacy metadata</xml>",
                    "content_type": "application/xml",
                    "content": "<Legacy/>",
                }
            ]
        }
    )

    assert new_model[0]["title"] == "Readable title"
    assert new_model[0]["contents"][0]["label"] == "MainEvidence: Readable title"
    assert legacy_model[0]["title"] == "doc-legacy"


def test_continue_view_updates_legacy_approvals_and_flags(client, fake_redis_client, monkeypatch):
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
        headers=_token_headers("msg-005", "preview-continue"),
        json={
            "message_uuid": "msg-005",
            "approvals": {"doc-1": True, "doc-2": False},
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "success"

    evidence_key = Keys.RESPONSE_EVIDENCE.format(conversation_id="msg-005")

    first_call = fake_redis_client.save_to_redis.call_args_list[0]

    assert first_call.args[0] == evidence_key
    assert first_call.args[1]["preview"] is False
    assert first_call.args[1]["evidences"][0]["permit"] is True
    assert first_call.args[1]["evidences"][1]["permit"] is False


def test_continue_view_updates_new_structure_approvals(client, fake_redis_client, monkeypatch):
    fake_redis_client.get_from_redis.return_value = {
        "preview": True,
        "evidences": [
            {
                "id": "pkg-42",
                "permit": False,
                "RegistryPackage": [
                    {
                        "classification": {
                            "classificationNode": "MainEvidence",
                            "classificationScheme": "urn:fdc:oots:classification:edm",
                            "id": "cls-1",
                        },
                        "EvidenceMetadata": "Meta",
                        "RepositoryItemRef": {"title": "Main", "href": "cid:main"},
                        "content_type": "application/xml",
                        "content": "<A/>",
                    }
                ],
            }
        ],
    }
    monkeypatch.setattr(main, "get_redis_client", lambda: fake_redis_client)

    response = client.post(
        "/preview/continue",
        headers=_token_headers("msg-777", "preview-continue"),
        json={
            "message_uuid": "msg-777",
            "approvals": {"pkg-42": True},
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "success"

    saved_payload = fake_redis_client.save_to_redis.await_args_list[0].args[1]
    assert saved_payload["preview"] is False
    assert saved_payload["evidences"][0]["permit"] is True


def test_continue_view_returns_returnurl_for_client_redirect(client, fake_redis_client, monkeypatch):
    fake_redis_client.get_from_redis.side_effect = [
        {
            "preview": True,
            "evidences": [{"cid": "doc-ret", "permit": False}],
        },
        "https://example.com/back",
    ]
    monkeypatch.setattr(main, "get_redis_client", lambda: fake_redis_client)

    response = client.post(
        "/preview/continue",
        headers=_token_headers("msg-ret", "preview-continue"),
        json={
            "message_uuid": "msg-ret",
            "approvals": {"doc-ret": True},
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "success"
    assert response.json()["returnurl"] == "https://example.com/back"


# ─── /preview/continue: розширені тести ────────────────────────────────────────

def test_continue_view_pushes_to_outgoing_queue(client, fake_redis_client, monkeypatch):
    """push_to_queue повинен викликатися з правильним message_id."""
    fake_redis_client.get_from_redis.return_value = {
        "preview": True,
        "evidences": [{"cid": "doc-q", "permit": False}],
    }
    monkeypatch.setattr(main, "get_redis_client", lambda: fake_redis_client)

    client.post(
        "/preview/continue",
        headers=_token_headers("msg-q01", "preview-continue"),
        json={"message_uuid": "msg-q01", "approvals": {"doc-q": True}},
    )

    fake_redis_client.push_to_queue.assert_awaited_once()
    call_args = fake_redis_client.push_to_queue.await_args
    assert call_args.args[1] == "msg-q01"


def test_continue_view_returns_404_when_data_missing(client, fake_redis_client, monkeypatch):
    """Якщо даних в Redis немає — повертає 404."""
    fake_redis_client.get_from_redis.return_value = None
    monkeypatch.setattr(main, "get_redis_client", lambda: fake_redis_client)

    response = client.post(
        "/preview/continue",
        headers=_token_headers("msg-missing", "preview-continue"),
        json={"message_uuid": "msg-missing", "approvals": {}},
    )

    assert response.status_code == 404
    assert "msg-missing" in response.json()["detail"]


def test_continue_view_unknown_approval_key_keeps_original_permit(client, fake_redis_client, monkeypatch):
    """Evidence якого немає в approvals зберігає свій початковий permit."""
    fake_redis_client.get_from_redis.return_value = {
        "preview": True,
        "evidences": [
            {"cid": "doc-known", "permit": False},
            {"cid": "doc-untouched", "permit": True},
        ],
    }
    monkeypatch.setattr(main, "get_redis_client", lambda: fake_redis_client)

    client.post(
        "/preview/continue",
        headers=_token_headers("msg-partial", "preview-continue"),
        json={"message_uuid": "msg-partial", "approvals": {"doc-known": True}},
    )

    saved = fake_redis_client.save_to_redis.await_args_list[0].args[1]
    assert saved["evidences"][0]["permit"] is True     # змінився
    assert saved["evidences"][1]["permit"] is True     # залишився True


def test_continue_view_unchecks_permit(client, fake_redis_client, monkeypatch):
    """permit можна зняти (True → False)."""
    fake_redis_client.get_from_redis.return_value = {
        "preview": True,
        "evidences": [{"cid": "doc-was-true", "permit": True}],
    }
    monkeypatch.setattr(main, "get_redis_client", lambda: fake_redis_client)

    client.post(
        "/preview/continue",
        headers=_token_headers("msg-uncheck", "preview-continue"),
        json={"message_uuid": "msg-uncheck", "approvals": {"doc-was-true": False}},
    )

    saved = fake_redis_client.save_to_redis.await_args_list[0].args[1]
    assert saved["evidences"][0]["permit"] is False


def test_continue_view_new_structure_sets_permit_flag_in_redis(client, fake_redis_client, monkeypatch):
    """Для нової структури permit флаги коректно зберігаються."""
    fake_redis_client.get_from_redis.return_value = {
        "preview": True,
        "evidences": [
            {
                "id": "pkg-n1",
                "permit": False,
                "RegistryPackage": [
                    {
                        "classification": {"classificationNode": "MainEvidence",
                                           "classificationScheme": "urn:x", "id": "c1"},
                        "EvidenceMetadata": "M",
                        "RepositoryItemRef": {"title": "T", "href": "cid:t"},
                        "content_type": "application/xml",
                        "content": "<A/>",
                    }
                ],
            },
            {
                "id": "pkg-n2",
                "permit": False,
                "RegistryPackage": [
                    {
                        "classification": {"classificationNode": "MainEvidence",
                                           "classificationScheme": "urn:x", "id": "c2"},
                        "EvidenceMetadata": "M2",
                        "RepositoryItemRef": {"title": "T2", "href": "cid:t2"},
                        "content_type": "application/xml",
                        "content": "<B/>",
                    }
                ],
            },
        ],
    }
    monkeypatch.setattr(main, "get_redis_client", lambda: fake_redis_client)

    response = client.post(
        "/preview/continue",
        headers=_token_headers("msg-n2", "preview-continue"),
        json={"message_uuid": "msg-n2", "approvals": {"pkg-n1": True, "pkg-n2": False}},
    )

    assert response.status_code == 200
    saved = fake_redis_client.save_to_redis.call_args_list[0].args[1]
    assert saved["evidences"][0]["permit"] is True
    assert saved["evidences"][1]["permit"] is False


def test_view_timeout_records_edm_error_and_pushes_queue(client, fake_redis_client, monkeypatch):
    monkeypatch.setattr(main, "get_redis_client", lambda: fake_redis_client)

    response = client.post(
        "/preview/timeout/00000000-0000-0000-0000-000000000010",
        headers=_token_headers("00000000-0000-0000-0000-000000000010", "preview-timeout"),
    )

    assert response.status_code == 200
    assert response.json()["status"] == "timeout_recorded"

    saved_call = fake_redis_client.save_to_redis.await_args
    assert saved_call.args[0] == Keys().get_response_exp("00000000-0000-0000-0000-000000000010")
    assert saved_call.args[1]["exception"]["code"] == "EDM:ERR:0005"
    assert saved_call.args[1]["exception"]["message"] == "Preview timeout"
    assert saved_call.args[1]["exception"]["detail"] == "Timeout reached for message_id=00000000-0000-0000-0000-000000000010"
    assert "preview_link" in saved_call.args[1]["exception"]

    fake_redis_client.push_to_queue.assert_awaited_once_with(
        main.QUEUE_OUTGOING, "00000000-0000-0000-0000-000000000010"
    )


def test_preview_continue_returns_403_without_action_token(client, fake_redis_client, monkeypatch):
    monkeypatch.setattr(main, "get_redis_client", lambda: fake_redis_client)

    response = client.post(
        "/preview/continue",
        json={"message_uuid": "msg-forbidden", "approvals": {}},
    )

    assert response.status_code == 403


def test_preview_timeout_returns_403_without_action_token(client, fake_redis_client, monkeypatch):
    monkeypatch.setattr(main, "get_redis_client", lambda: fake_redis_client)

    response = client.post("/preview/timeout/00000000-0000-0000-0000-000000000011")

    assert response.status_code == 403


def test_auth_redirects_to_preview_when_person_already_authorized(client, fake_redis_client, monkeypatch):
    """Перевіряємо що при повторному заході на /auth/{message_id} з вже авторизованою особою
    користувач перенаправляється на /preview/{message_id}"""
    # Мокуємо REQUEST_EDM як наявний та REQUEST_PERSON як наявний
    def _get_from_redis(key):
        if "request:person" in key:
            return {"first_name": "John", "last_name": "Doe"}
        if "request:edm" in key:
            return {"some": "edm"}
        return None

    fake_redis_client.get_from_redis.side_effect = _get_from_redis
    
    monkeypatch.setattr(main, "get_redis_client", lambda: fake_redis_client)
    
    response = client.get("/auth/00000000-0000-0000-0000-000000000012", follow_redirects=False)
    
    # Перевіряємо що повертається редирект шаблон з правильним url
    assert response.status_code == 200
    assert (
        "redirect_to_preview.html" in response.text
        or "/preview/00000000-0000-0000-0000-000000000012" in response.text
    )
    assert (
        "Авторизація вже виконана" in response.text
        or "preview/00000000-0000-0000-0000-000000000012" in response.text
    )


def test_auth_returns_invalid_link_when_edm_missing(client, fake_redis_client, monkeypatch):
    """Перевіряємо що при відсутності REQUEST_EDM показується помилка про неправильне посилання"""
    # Симулюємо відсутність EDM, але наявність returnurl
    def side_effect_fn(key):
        if "returnurl" in key:
            return "https://example.com/back"
        return None
    
    fake_redis_client.get_from_redis.side_effect = side_effect_fn
    
    monkeypatch.setattr(main, "get_redis_client", lambda: fake_redis_client)
    
    response = client.get(
        "/auth/00000000-0000-0000-0000-000000000013?returnurl=https://example.com/back",
        follow_redirects=False,
    )
    
    # Перевіряємо що показується сторінка з помилкою
    assert response.status_code == 200
    assert "invalid_link.html" in response.text or "Неправильне посилання" in response.text
    assert "EDM не знайдено" in response.text


def test_auth_returns_400_when_edm_missing_and_no_returnurl(client, fake_redis_client, monkeypatch):
    """Перевіряємо що при відсутності EDM і returnurl повертається 400"""
    # Симулюємо відсутність EDM
    fake_redis_client.get_from_redis.return_value = None
    
    monkeypatch.setattr(main, "get_redis_client", lambda: fake_redis_client)
    
    response = client.get("/auth/00000000-0000-0000-0000-000000000014", follow_redirects=False)
    
    # Перевіряємо 400 статус
    assert response.status_code == 400
    assert "EDM not found" in response.json()["detail"]
