import main
from lib.evidence_view_model import build_evidence_view_model
from lib.MessageChecker import MessageStatus
from redis_keys import Keys


def test_view_requires_returnurl(client):
    response = client.get("/preview/msg-001")

    assert response.status_code == 400
    assert "returnurl" in response.json()["detail"]


def test_preview_skips_when_request_preview_flag_not_set(client, fake_redis_client, monkeypatch):
    fake_redis_client.get_flag.return_value = False
    monkeypatch.setattr(main, "get_redis_client", lambda: fake_redis_client)

    response = client.get("/preview/msg-skip?returnurl=https://example.com/back", follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["location"] == "https://example.com/back"
    fake_redis_client.push_to_queue.assert_not_awaited()


def test_preview_shows_waiting_when_flag_set_but_evidence_missing(client, fake_redis_client, monkeypatch):
    fake_redis_client.get_flag.side_effect = lambda key, **_: "request:preview" in key
    fake_redis_client.get_from_redis.return_value = None
    monkeypatch.setattr(main, "get_redis_client", lambda: fake_redis_client)

    response = client.get("/preview/msg-wait?returnurl=https://example.com/back")

    assert response.status_code == 200
    assert "Loading Evidence" in response.text


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

    response = client.get("/preview/msg-ready?returnurl=https://example.com/back")

    assert response.status_code == 200
    assert "Evidences" in response.text
    assert 'returnurl: "https://example.com/back"' in response.text


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

    response = client.get("/preview/msg-002?returnurl=https://example.com")

    # Сторінка чекання показується, коли evidence не готовий.
    assert response.status_code == 200
    assert "Loading Evidence" in response.text


def test_view_progress_returns_stage_0_when_no_data(client, fake_redis_client, monkeypatch):
    fake_redis_client.get_flag.return_value = False
    fake_redis_client.get_from_redis.return_value = None
    monkeypatch.setattr(main, "get_redis_client", lambda: fake_redis_client)

    response = client.get("/preview/progress/msg-002")

    assert response.status_code == 200
    assert response.json()["stage"] == 0
    assert response.json()["preview_ready"] is False
    assert response.json()["evidence_ready"] is False


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

    response = client.get("/preview/msg-003?returnurl=https://example.com")

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

    response = client.get("/preview/msg-004?returnurl=https://example.com")

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
    fake_redis_client.get_from_redis.return_value = {
        "preview": True,
        "evidences": [{"cid": "doc-ret", "permit": False}],
    }
    monkeypatch.setattr(main, "get_redis_client", lambda: fake_redis_client)

    response = client.post(
        "/preview/continue?returnurl=https://example.com/back",
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
        json={"message_uuid": "msg-n2", "approvals": {"pkg-n1": True, "pkg-n2": False}},
    )

    assert response.status_code == 200
    saved = fake_redis_client.save_to_redis.call_args_list[0].args[1]
    assert saved["evidences"][0]["permit"] is True
    assert saved["evidences"][1]["permit"] is False


