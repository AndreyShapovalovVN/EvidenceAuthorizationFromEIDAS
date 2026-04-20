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

    # Сторінка чекання показується, коли evidence не готовий.
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
    fake_redis_client.get_from_redis.return_value = evidence_data
    fake_redis_client.get_flag.return_value = True
    monkeypatch.setattr(main, "get_redis_client", lambda: fake_redis_client)

    response = client.get("/preview/msg-004?returnurl=https://example.com")

    assert response.status_code == 200
    assert "Evidences" in response.text
    assert "MainEvidence" in response.text
    assert "/static/evidences.js" in response.text


def test_build_evidence_view_model_ignores_xml_metadata_in_sidebar():
    new_model = main._build_evidence_view_model(
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

    legacy_model = main._build_evidence_view_model(
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
    permit_key = Keys.RESPONSE_PERMIT.format(conversation_id="msg-005")

    first_call = fake_redis_client.save_to_redis.await_args_list[0]

    assert first_call.args[0] == evidence_key
    assert first_call.args[1]["preview"] is False
    assert first_call.args[1]["evidences"][0]["permit"] is True
    assert first_call.args[1]["evidences"][1]["permit"] is False

    fake_redis_client.set_flag.assert_awaited_once_with(permit_key, True)


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

