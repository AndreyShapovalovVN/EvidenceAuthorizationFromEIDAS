"""Assurance checks must run before persisting an eIDAS identity."""

import base64
import json

import pytest
from lxml import etree

import main
from lib.action_token import issue_action_token

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
def test_non_high_assurance_returns_to_login_without_publishing_error(
    client, fake_redis_client, monkeypatch, level
):
    _configure_state(fake_redis_client, monkeypatch)
    payload = _response(level)
    # Assurance rejection must not depend on the presence of identity attributes.
    payload["response"]["attribute_list"] = []

    response = client.post("/auth/eidas/callback", json=payload, follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == f"/auth/{MESSAGE_ID}?assurance=rejected"
    fake_redis_client.delete_from_redis.assert_awaited_once_with(
        main.KEYS.get_eidas_state_key(REQUEST_ID)
    )
    fake_redis_client.save_to_redis.assert_not_awaited()
    fake_redis_client.push_to_queue.assert_not_awaited()


@pytest.mark.parametrize(
    ("letter", "expected_level"),
    [("A", "low"), ("B", "low"), ("C", "substantial"), ("D", "substantial"), ("E", "high")],
)
def test_letter_assurance_is_mapped_before_validation_and_storage(
    client, fake_redis_client, monkeypatch, letter, expected_level
):
    _configure_state(fake_redis_client, monkeypatch)
    monkeypatch.setenv("EIDAS_SP_ALLOWED_LOA", expected_level)

    response = client.post(
        "/auth/eidas/callback", json=_response(letter), follow_redirects=False
    )

    assert response.status_code == 303
    fake_redis_client.save_to_redis.assert_awaited_once()
    key, saved = fake_redis_client.save_to_redis.await_args.args
    assert key == main.KEYS.get_request_person(MESSAGE_ID)
    assert saved["level_of_assurance"] == expected_level
    fake_redis_client.push_to_queue.assert_not_awaited()


@pytest.mark.parametrize("letter", ["A", "B", "C", "D"])
def test_mapped_assurance_is_rejected_when_not_allowed(
    client, fake_redis_client, monkeypatch, letter
):
    _configure_state(fake_redis_client, monkeypatch)
    monkeypatch.setenv("EIDAS_SP_ALLOWED_LOA", "high")

    response = client.post(
        "/auth/eidas/callback", json=_response(letter), follow_redirects=False
    )

    assert response.status_code == 303
    assert response.headers["location"] == f"/auth/{MESSAGE_ID}?assurance=rejected"
    fake_redis_client.save_to_redis.assert_not_awaited()
    fake_redis_client.push_to_queue.assert_not_awaited()


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
def test_retired_authentication_routes_are_removed(
    client, method, path, expected_status
):
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
    else:
        fake_redis_client.get_from_redis.return_value = None

    response = client.post("/auth/eidas/callback", json=payload, follow_redirects=False)

    assert response.status_code == expected_status
    fake_redis_client.save_to_redis.assert_not_awaited()
    fake_redis_client.push_to_queue.assert_not_awaited()


@pytest.mark.parametrize("as_form", [False, True])
@pytest.mark.parametrize(
    "status,expected_detail",
    [
        (
            {
                "status_code": "Responder",
                "sub_status_code": "AuthnFailed",
                "status_message": "003002 - Authentication Failed.",
            },
            "eIDAS AuthnFailed: 003002 - Authentication Failed.",
        ),
        ({"status_code": "Failed"}, "eIDAS Failed: eIDAS authentication failed"),
    ],
)
def test_failed_authentication_publishes_edm_error(
    client, fake_redis_client, monkeypatch, status, expected_detail, as_form
):
    _configure_state(fake_redis_client, monkeypatch)
    payload = _response("Low")
    payload["response"]["status"] = status
    payload["response"]["attribute_list"] = []
    if as_form:
        encoded = base64.b64encode(json.dumps(payload).encode()).decode()
        request_body = {"data": {"SMSSPResponse": encoded}}
    else:
        request_body = {"json": payload}

    response = client.post(
        "/auth/eidas/callback", **request_body, follow_redirects=False
    )

    assert response.status_code == 303
    assert response.headers["location"] == f"/preview/{MESSAGE_ID}"
    fake_redis_client.delete_from_redis.assert_awaited_once_with(
        main.KEYS.get_eidas_state_key(REQUEST_ID)
    )
    fake_redis_client.save_to_redis.assert_awaited_once_with(
        main.KEYS.get_response_exp(MESSAGE_ID),
        {
            "exception": {
                "code": "EDM:ERR:0001",
                "message": "Failed Authentication",
                "detail": expected_detail,
                "preview_link": None,
            }
        },
    )
    fake_redis_client.push_to_queue.assert_awaited_once_with(
        main.QUEUE_OUTGOING, MESSAGE_ID
    )


@pytest.mark.parametrize("operation", ["save_to_redis", "push_to_queue"])
def test_error_publication_failure_returns_503(
    client, fake_redis_client, monkeypatch, operation
):
    _configure_state(fake_redis_client, monkeypatch)
    payload = _response("Low")
    payload["response"]["status"] = {"status_code": "AuthnFailed"}
    getattr(fake_redis_client, operation).side_effect = RuntimeError(
        "Redis unavailable"
    )

    response = client.post("/auth/eidas/callback", json=payload, follow_redirects=False)

    assert response.status_code == 503
    fake_redis_client.save_to_redis.assert_awaited_once()
    if operation == "save_to_redis":
        fake_redis_client.push_to_queue.assert_not_awaited()
    else:
        fake_redis_client.push_to_queue.assert_awaited_once()


def _configure_login_state(fake_redis_client, monkeypatch, returnurl=None):
    _configure_state(fake_redis_client, monkeypatch)
    monkeypatch.setenv("EIDAS_SP_ALLOWED_LOA", "high")
    stored = {
        main.KEYS.get_request_edm(MESSAGE_ID): {"some": "edm"},
        main.KEYS.get_eidas_state_key(REQUEST_ID): {"message_id": MESSAGE_ID},
    }
    if returnurl:
        stored[main.KEYS.get_return_url(MESSAGE_ID)] = returnurl
    fake_redis_client.get_from_redis.side_effect = stored.get
    fake_redis_client.save_to_redis.side_effect = stored.__setitem__
    fake_redis_client.delete_from_redis.side_effect = lambda key: stored.pop(key, None)
    return stored


def test_rejected_assurance_shows_login_and_allows_successful_retry(
    client, fake_redis_client, monkeypatch
):
    stored = _configure_login_state(fake_redis_client, monkeypatch)

    rejected = client.post("/auth/eidas/callback", json=_response("A"))

    assert rejected.status_code == 200
    assert rejected.url.path == f"/auth/{MESSAGE_ID}"
    page = etree.HTML(rejected.text)
    assert "не підходить для продовження" in page.xpath('string(//*[@role="alert"])')
    assert page.xpath('//*[@id="eidas-login-btn"]/@href') == [
        f"/auth/eidas/start/{MESSAGE_ID}"
    ]
    assert "Відмовитися від авторизації" in page.xpath("string(//form/button)")
    assert main.KEYS.get_eidas_state_key(REQUEST_ID) not in stored
    fake_redis_client.save_to_redis.assert_not_awaited()
    fake_redis_client.push_to_queue.assert_not_awaited()

    retry = client.get(f"/auth/eidas/start/{MESSAGE_ID}")
    retry_page = etree.HTML(retry.text)
    encoded = retry_page.xpath('//input[@name="SMSSPRequest"]/@value')[0]
    request_id = json.loads(base64.b64decode(encoded))["authentication_request"]["id"]
    payload = _response("E")
    payload["response"]["inresponse_to"] = request_id

    accepted = client.post("/auth/eidas/callback", json=payload, follow_redirects=False)

    assert accepted.status_code == 303
    assert accepted.headers["location"] == f"/preview/{MESSAGE_ID}"
    assert stored[main.KEYS.get_request_person(MESSAGE_ID)]["level_of_assurance"] == "high"
    assert main.KEYS.get_response_exp(MESSAGE_ID) not in stored


@pytest.mark.parametrize("rejected", [False, True])
@pytest.mark.parametrize("returnurl", [None, "https://example.com/callback"])
def test_explicit_decline_publishes_error_and_returns_to_caller(
    client, fake_redis_client, monkeypatch, rejected, returnurl
):
    stored = _configure_login_state(fake_redis_client, monkeypatch, returnurl)
    if rejected:
        login = client.post("/auth/eidas/callback", json=_response("A"))
    else:
        login = client.get(f"/auth/{MESSAGE_ID}")
        assert not etree.HTML(login.text).xpath('//*[@role="alert"]')
    page = etree.HTML(login.text)
    cancel_url = page.xpath("//form/@action")[0]
    assert main.KEYS.get_response_exp(MESSAGE_ID) not in stored
    fake_redis_client.push_to_queue.assert_not_awaited()

    response = client.post(cancel_url, follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == (returnurl or f"/preview/{MESSAGE_ID}")
    assert stored[main.KEYS.get_response_exp(MESSAGE_ID)] == {
        "exception": {
            "code": "EDM:ERR:0001",
            "message": "Failed Authentication",
            "detail": "The user declined eIDAS authorization.",
            "preview_link": None,
        }
    }
    assert main.KEYS.get_request_person(MESSAGE_ID) not in stored
    fake_redis_client.push_to_queue.assert_awaited_once_with(main.QUEUE_OUTGOING, MESSAGE_ID)


@pytest.mark.parametrize(
    "token",
    [None, "invalid", issue_action_token(MESSAGE_ID, "preview-continue")],
)
def test_decline_requires_action_token(client, fake_redis_client, monkeypatch, token):
    _configure_login_state(fake_redis_client, monkeypatch)
    response = client.post(
        f"/auth/eidas/cancel/{MESSAGE_ID}",
        params={"token": token} if token else {},
        follow_redirects=False,
    )
    assert response.status_code == 403
    fake_redis_client.save_to_redis.assert_not_awaited()
    fake_redis_client.push_to_queue.assert_not_awaited()


@pytest.mark.parametrize("case,status", [("missing-edm", 400), ("authorized", 409)])
def test_decline_rejects_invalid_or_completed_authorization(
    client, fake_redis_client, monkeypatch, case, status
):
    stored = _configure_login_state(fake_redis_client, monkeypatch)
    if case == "missing-edm":
        stored.pop(main.KEYS.get_request_edm(MESSAGE_ID))
    else:
        stored[main.KEYS.get_request_person(MESSAGE_ID)] = {"identifier": "person"}
    response = client.post(
        f"/auth/eidas/cancel/{MESSAGE_ID}",
        params={"token": issue_action_token(MESSAGE_ID, "auth-cancel")},
        follow_redirects=False,
    )
    assert response.status_code == status
    fake_redis_client.save_to_redis.assert_not_awaited()
    fake_redis_client.push_to_queue.assert_not_awaited()


@pytest.mark.parametrize("operation", ["save_to_redis", "push_to_queue"])
def test_decline_does_not_redirect_when_error_publication_fails(
    client, fake_redis_client, monkeypatch, operation
):
    _configure_login_state(fake_redis_client, monkeypatch)
    getattr(fake_redis_client, operation).side_effect = RuntimeError("Redis unavailable")
    response = client.post(
        f"/auth/eidas/cancel/{MESSAGE_ID}",
        params={"token": issue_action_token(MESSAGE_ID, "auth-cancel")},
        follow_redirects=False,
    )
    assert response.status_code == 503
    assert "location" not in response.headers
