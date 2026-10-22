"""Assurance checks must run before persisting an eIDAS identity."""

import base64
import json

import pytest

import main

MESSAGE_ID = "00000000-0000-0000-0000-000000000021"
REQUEST_ID = "eidas-request-21"


def _response(level):
    response = {
        "inresponse_to": REQUEST_ID,
        "status": {"status_code": "Success"},
        "attribute_list": [
            {"name": "FirstName", "value": ["Test"]},
            {"name": "FamilyName", "value": ["Person"]},
            {"name": "PersonIdentifier", "value": ["UA/UA/1234567890"]},
            {"name": "DateOfBirth", "value": ["1992-04-18"]},
        ],
    }
    if level is not None:
        response["authentication_context_class"] = level
    return {"response": response}


def _configure_state(fake_redis_client, monkeypatch):
    monkeypatch.setenv("EIDAS_SP_ALLOWED_LOA", "High")
    fake_redis_client.get_from_redis.return_value = {"message_id": MESSAGE_ID}
    monkeypatch.setattr(main, "get_redis_client", lambda: fake_redis_client)


@pytest.mark.parametrize("level", ["Low", "Substantial", "", None, "Unknown", "high"])
def test_non_high_assurance_sends_edm_error_without_saving_person(
    client, fake_redis_client, monkeypatch, level
):
    _configure_state(fake_redis_client, monkeypatch)
    payload = _response(level)
    # Assurance rejection must not depend on the presence of identity attributes.
    payload["response"]["attribute_list"] = []

    response = client.post("/auth/eidas/callback", json=payload, follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == f"/preview/{MESSAGE_ID}"
    fake_redis_client.delete_from_redis.assert_awaited_once_with(
        main.KEYS.get_eidas_state_key(REQUEST_ID)
    )
    fake_redis_client.save_to_redis.assert_awaited_once()
    key, saved = fake_redis_client.save_to_redis.await_args.args
    assert key == main.KEYS.get_response_exp(MESSAGE_ID)
    assert saved["exception"]["code"] == "EDM:ERR:0001"
    assert saved["exception"]["message"] == "Failed Authentication"
    assert "Allowed level_of_assurance values: High" in saved["exception"]["detail"]
    fake_redis_client.push_to_queue.assert_awaited_once_with(
        main.QUEUE_OUTGOING, MESSAGE_ID
    )


def test_high_assurance_saves_person_without_edm_error(
    client, fake_redis_client, monkeypatch
):
    _configure_state(fake_redis_client, monkeypatch)

    response = client.post(
        "/auth/eidas/callback", json=_response("High"), follow_redirects=False
    )

    assert response.status_code == 303
    assert response.headers["location"] == f"/preview/{MESSAGE_ID}"
    fake_redis_client.save_to_redis.assert_awaited_once()
    key, saved = fake_redis_client.save_to_redis.await_args.args
    assert key == main.KEYS.get_request_person(MESSAGE_ID)
    assert saved["level_of_assurance"] == "High"
    fake_redis_client.push_to_queue.assert_not_awaited()


@pytest.mark.parametrize(
    ("allowed_levels", "level"),
    [
        ("High,Substantial", "Substantial"),
        (" High, Low, , ", "Low"),
        (None, "Low"),
        (None, "Unknown"),
        (None, None),
        ("", "Substantial"),
        ("", None),
        (" , ", "Unknown"),
    ],
)
def test_configured_or_unrestricted_assurance_saves_person(
    client, fake_redis_client, monkeypatch, allowed_levels, level
):
    _configure_state(fake_redis_client, monkeypatch)
    if allowed_levels is None:
        monkeypatch.delenv("EIDAS_SP_ALLOWED_LOA", raising=False)
    else:
        monkeypatch.setenv("EIDAS_SP_ALLOWED_LOA", allowed_levels)

    response = client.post(
        "/auth/eidas/callback", json=_response(level), follow_redirects=False
    )

    assert response.status_code == 303
    fake_redis_client.save_to_redis.assert_awaited_once()
    key, saved = fake_redis_client.save_to_redis.await_args.args
    assert key == main.KEYS.get_request_person(MESSAGE_ID)
    assert saved["level_of_assurance"] == (level or "")
    fake_redis_client.push_to_queue.assert_not_awaited()


@pytest.mark.parametrize(
    "method,path,expected_status",
    [
        ("post", "/auth/continue", 405),
        ("get", "/auth/icei/start/" + MESSAGE_ID, 404),
        ("get", "/auth/icei/callback", 404),
    ],
)
def test_retired_authentication_routes_are_removed(client, method, path, expected_status):
    assert client.request(method, path).status_code == expected_status


def test_eidas_callback_accepts_base64_form(client, fake_redis_client, monkeypatch):
    _configure_state(fake_redis_client, monkeypatch)
    encoded = base64.b64encode(json.dumps(_response("High")).encode()).decode()

    response = client.post(
        "/auth/eidas/callback", data={"SMSSPResponse": encoded}, follow_redirects=False
    )

    assert response.status_code == 303
    assert response.headers["location"] == f"/preview/{MESSAGE_ID}"
    assert fake_redis_client.save_to_redis.await_args.args[
        0
    ] == main.KEYS.get_request_person(MESSAGE_ID)


@pytest.mark.parametrize(
    "case,expected_status",
    [
        ("missing-attributes", 422),
        ("failed-authentication", 502),
        ("expired-state", 400),
    ],
)
def test_eidas_callback_rejects_invalid_responses(
    client, fake_redis_client, monkeypatch, case, expected_status
):
    _configure_state(fake_redis_client, monkeypatch)
    payload = _response("High")
    if case == "missing-attributes":
        payload["response"]["attribute_list"] = []
    elif case == "failed-authentication":
        payload["response"]["status"] = {"status_code": "Failed"}
    else:
        fake_redis_client.get_from_redis.return_value = None

    response = client.post("/auth/eidas/callback", json=payload, follow_redirects=False)

    assert response.status_code == expected_status
    fake_redis_client.save_to_redis.assert_not_awaited()
    fake_redis_client.push_to_queue.assert_not_awaited()
