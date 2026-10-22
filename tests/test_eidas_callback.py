"""Assurance checks must run before persisting an eIDAS identity."""

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
    assert "Expected level_of_assurance=High" in saved["exception"]["detail"]
    fake_redis_client.push_to_queue.assert_awaited_once_with(main.QUEUE_OUTGOING, MESSAGE_ID)


def test_high_assurance_saves_person_without_edm_error(client, fake_redis_client, monkeypatch):
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
