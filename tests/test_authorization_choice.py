from copy import deepcopy
from unittest.mock import AsyncMock

import pytest
from lxml import html

import main
from lib.action_token import issue_action_token

MESSAGE_ID = "00000000-0000-0000-0000-000000000043"
STORED_ID = "UA/UA/1234567890"
INCOMING_ID = "DE/DE/9876543210"


def request_xml(identifier):
    return f"""<query:QueryRequest
        xmlns:query="urn:oasis:names:tc:ebxml-regrep:xsd:query:4.0"
        xmlns:rim="urn:oasis:names:tc:ebxml-regrep:xsd:rim:4.0"
        xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
        xmlns:sdg="http://data.europa.eu/p4s">
        <query:Query queryDefinition="test">
            <rim:Slot name="NaturalPerson">
                <rim:SlotValue xsi:type="rim:AnyValueType">
                    <sdg:Person>
                        <sdg:Identifier schemeID="eidas">{identifier}</sdg:Identifier>
                    </sdg:Person>
                </rim:SlotValue>
            </rim:Slot>
        </query:Query>
    </query:QueryRequest>"""


@pytest.fixture
def state(fake_redis_client, monkeypatch):
    data = {
        main.KEYS.get_request_edm(MESSAGE_ID): [{"content": request_xml(INCOMING_ID)}],
        main.KEYS.get_request_person(MESSAGE_ID): {"eidas_identifier": STORED_ID},
    }
    fake_redis_client.get_from_redis.side_effect = lambda key: deepcopy(data.get(key))
    fake_redis_client.save_to_redis.side_effect = lambda key, value: data.update(
        {key: deepcopy(value)}
    )
    fake_redis_client.delete_from_redis.side_effect = lambda key: data.pop(key, None)
    monkeypatch.setattr(main, "get_redis_client", lambda: fake_redis_client)
    return data


@pytest.mark.parametrize("identifier", [STORED_ID, {"value": STORED_ID}])
@pytest.mark.parametrize("field", ["identifier", "eidas_identifier"])
def test_mismatch_offers_choice_without_changing_person(
    client, fake_redis_client, state, identifier, field
):
    person = {field: identifier}
    state[main.KEYS.get_request_person(MESSAGE_ID)] = person
    response = client.get(f"/auth/{MESSAGE_ID}?returnurl=https://example.com/back")

    assert response.status_code == 200
    assert "Ви вже нещодавно проходили авторизацію" in response.text
    page = html.fromstring(response.text)
    assert page.xpath("//a/@href") == [f"/preview/{MESSAGE_ID}"]
    assert "Пройти нову авторизацію" in response.text
    assert "window.location" not in response.text
    assert STORED_ID not in response.text
    assert INCOMING_ID not in response.text
    assert state[main.KEYS.get_request_person(MESSAGE_ID)] == person
    assert state[main.KEYS.get_return_url(MESSAGE_ID)] == "https://example.com/back"
    fake_redis_client.delete_from_redis.assert_not_awaited()
    fake_redis_client.push_to_queue.assert_not_awaited()


@pytest.mark.parametrize("incoming", [STORED_ID, None, "malformed"])
def test_matching_or_unavailable_identifier_keeps_existing_redirect(
    client, state, incoming
):
    state[main.KEYS.get_request_edm(MESSAGE_ID)] = [
        {"content": request_xml(incoming) if incoming else "<QueryRequest/>"}
    ]
    if incoming == "malformed":
        state[main.KEYS.get_request_edm(MESSAGE_ID)] = [{"content": "<broken"}]
    response = client.get(f"/auth/{MESSAGE_ID}")
    assert response.status_code == 200
    assert "window.location.href" in response.text


def test_content2_takes_priority_over_content(client, state):
    state[main.KEYS.get_request_edm(MESSAGE_ID)] = {
        "content": request_xml(STORED_ID),
        "content2": request_xml(INCOMING_ID),
    }
    response = client.get(f"/auth/{MESSAGE_ID}")
    assert "Пройти нову авторизацію" in response.text


def test_restart_button_starts_eidas_and_removes_old_person(
    client, state, fake_redis_client
):
    page = html.fromstring(client.get(f"/auth/{MESSAGE_ID}").text)
    action = page.xpath("//form/@action")[0]
    response = client.post(action)

    assert response.status_code == 200
    assert 'name="SMSSPRequest"' in response.text
    assert main.KEYS.get_request_person(MESSAGE_ID) not in state
    assert any(
        value == {"message_id": MESSAGE_ID}
        for key, value in state.items()
        if "eidas:sp:state:" in key
    )
    fake_redis_client.push_to_queue.assert_not_awaited()


@pytest.mark.parametrize(
    "token", [None, "invalid", issue_action_token(MESSAGE_ID, "auth-cancel")]
)
def test_restart_requires_its_action_token(client, state, fake_redis_client, token):
    response = client.post(
        f"/auth/eidas/restart/{MESSAGE_ID}", params={"token": token} if token else {}
    )
    assert response.status_code == 403
    fake_redis_client.delete_from_redis.assert_not_awaited()


def test_restart_rejects_expired_request(client, state, fake_redis_client):
    del state[main.KEYS.get_request_edm(MESSAGE_ID)]
    response = client.post(
        f"/auth/eidas/restart/{MESSAGE_ID}",
        params={"token": issue_action_token(MESSAGE_ID, "auth-restart")},
    )
    assert response.status_code == 400
    fake_redis_client.delete_from_redis.assert_not_awaited()


def test_failed_preparation_preserves_person(
    client, state, fake_redis_client, monkeypatch
):
    monkeypatch.setattr(
        main,
        "prepare_eidas_redirect",
        AsyncMock(
            side_effect=main.HTTPException(status_code=503, detail="Unavailable")
        ),
    )
    response = client.post(
        f"/auth/eidas/restart/{MESSAGE_ID}",
        params={"token": issue_action_token(MESSAGE_ID, "auth-restart")},
    )
    assert response.status_code == 503
    assert main.KEYS.get_request_person(MESSAGE_ID) in state
    fake_redis_client.delete_from_redis.assert_not_awaited()
