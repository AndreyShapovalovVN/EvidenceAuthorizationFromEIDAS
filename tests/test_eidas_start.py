import base64
import json
from uuid import UUID

from lxml import html

import main
from lib import eidas_sp_service


def test_eidas_start_builds_request_and_saves_callback_state(
    client, fake_redis_client, monkeypatch
):
    message_id = "00000000-0000-0000-0000-000000000001"
    fake_redis_client.get_from_redis.return_value = {"request": "edm"}
    monkeypatch.setattr(main, "get_redis_client", lambda: fake_redis_client)
    monkeypatch.setattr(eidas_sp_service, "EIDAS_SP_CITIZEN_COUNTRY", "UA")
    monkeypatch.setattr(
        eidas_sp_service, "EIDAS_SP_CALLBACK_URL",
        "https://preview.example.org/auth/eidas/callback",
    )

    response = client.get(f"/auth/eidas/start/{message_id}")

    assert response.status_code == 200
    form = html.fromstring(response.text).xpath("//form")[0]
    assert form.get("method") == "POST"
    assert form.get("action") == eidas_sp_service.EIDAS_SPECIFIC_CONNECTOR_URL
    encoded_request = form.xpath(".//input[@name='SMSSPRequest']/@value")[0]
    envelope = json.loads(base64.b64decode(encoded_request, validate=True))
    assert set(envelope) == {"authentication_request"}
    payload = envelope["authentication_request"]
    assert "_name_" not in payload
    assert payload["citizen_country"] == "UA"
    assert payload["serviceUrl"] == "https://preview.example.org/auth/eidas/callback"
    assert payload["force_authentication"] is True
    assert [attribute["name"] for attribute in payload["attribute_list"]] == [
        "FirstName", "FamilyName", "DateOfBirth", "PersonIdentifier",
    ]
    assert all(attribute["required"] for attribute in payload["attribute_list"])
    assert str(UUID(payload["id"])) == payload["id"]
    fake_redis_client.get_from_redis.assert_awaited_once_with(
        main.KEYS.get_request_edm(message_id)
    )
    fake_redis_client.save_to_redis.assert_awaited_once_with(
        main.KEYS.get_eidas_state_key(payload["id"]), {"message_id": message_id}
    )


def test_eidas_start_rejects_missing_edm(client, fake_redis_client, monkeypatch):
    monkeypatch.setattr(main, "get_redis_client", lambda: fake_redis_client)

    response = client.get("/auth/eidas/start/00000000-0000-0000-0000-000000000001")

    assert response.status_code == 400
    fake_redis_client.save_to_redis.assert_not_awaited()
