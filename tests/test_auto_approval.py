from copy import deepcopy

import pytest

import main
from lib.action_token import issue_action_token

MESSAGE_ID = "00000000-0000-0000-0000-000000000042"
RETURN_URL = "https://example.com/back"


def _request_xml(value):
    slot = (
        ""
        if value is None
        else f"""
    <rim:Slot name="PossibilityForPreview">
        <rim:SlotValue xsi:type="rim:BooleanValueType">
            <rim:Value>{str(value).lower()}</rim:Value>
        </rim:SlotValue>
    </rim:Slot>"""
    )
    return f"""<query:QueryRequest
        xmlns:query="urn:oasis:names:tc:ebxml-regrep:xsd:query:4.0"
        xmlns:rim="urn:oasis:names:tc:ebxml-regrep:xsd:rim:4.0"
        xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
        {slot}
    </query:QueryRequest>"""


@pytest.fixture
def state(fake_redis_client, monkeypatch):
    data = {
        main.KEYS.get_return_url(MESSAGE_ID): RETURN_URL,
        main.KEYS.get_request_edm(MESSAGE_ID): [{"content": _request_xml(False)}],
        main.KEYS.get_response_evidence(MESSAGE_ID): {
            "preview": False,
            "evidences": [
                {"cid": "doc-1", "permit": False, "content": "<A/>"},
                {"cid": "doc-2", "permit": False, "content": "<B/>"},
            ],
        },
    }
    fake_redis_client.get_from_redis.side_effect = lambda key: deepcopy(data.get(key))
    fake_redis_client.save_to_redis.side_effect = lambda key, value: data.update(
        {key: deepcopy(value)}
    )
    fake_redis_client.get_flag.side_effect = lambda key, default=False: data.get(
        key, default
    )
    fake_redis_client.set_flag.side_effect = lambda key, value: data.update(
        {key: value}
    )
    monkeypatch.setattr(main, "get_redis_client", lambda: fake_redis_client)
    return data


@pytest.mark.parametrize("new_structure", [False, True])
def test_both_false_approve_every_evidence_and_dispatch_once(
    client, fake_redis_client, state, new_structure
):
    evidence_key = main.KEYS.get_response_evidence(MESSAGE_ID)
    if new_structure:
        state[evidence_key]["evidences"] = [
            {"id": "pkg-1", "permit": False, "RegistryPackage": [{"content": "<A/>"}]},
            {"permit": False, "RegistryPackage": [{"content": "<B/>"}]},
        ]
    original = deepcopy(state[evidence_key]["evidences"])

    for _ in range(2):
        response = client.get(f"/preview/{MESSAGE_ID}", follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"] == RETURN_URL

    expected = [dict(evidence, permit=True) for evidence in original]
    assert state[evidence_key] == {"preview": False, "evidences": expected}
    assert main.KEYS.get_response_exp(MESSAGE_ID) not in state
    fake_redis_client.push_to_queue.assert_awaited_once_with(
        main.QUEUE_OUTGOING, MESSAGE_ID
    )


@pytest.mark.parametrize("request_preview", [False, True, None])
@pytest.mark.parametrize("provider_preview", [False, True, None, "false", 0])
def test_preview_is_required_unless_both_flags_are_false(
    client, fake_redis_client, state, request_preview, provider_preview
):
    if request_preview is False and provider_preview is False:
        return
    state[main.KEYS.get_request_edm(MESSAGE_ID)][0]["content"] = _request_xml(
        request_preview
    )
    state[main.KEYS.get_response_evidence(MESSAGE_ID)]["preview"] = provider_preview

    response = client.get(f"/preview/{MESSAGE_ID}")

    assert response.status_code == 200
    assert "Evidences" in response.text
    fake_redis_client.push_to_queue.assert_not_awaited()
    fake_redis_client.save_to_redis.assert_not_awaited()


def test_auto_approval_after_waiting_for_evidence(client, fake_redis_client, state):
    evidence_key = main.KEYS.get_response_evidence(MESSAGE_ID)
    evidence = state.pop(evidence_key)
    assert "Loading Evidence" in client.get(f"/preview/{MESSAGE_ID}").text

    state[evidence_key] = evidence
    progress = client.get(
        f"/preview/progress/{MESSAGE_ID}",
        headers={"X-Action-Token": issue_action_token(MESSAGE_ID, "preview-progress")},
    )
    assert progress.json()["stage"] == 2
    response = client.get(f"/preview/{MESSAGE_ID}", follow_redirects=False)
    assert response.status_code == 303
    fake_redis_client.push_to_queue.assert_awaited_once_with(
        main.QUEUE_OUTGOING, MESSAGE_ID
    )


def test_auto_approval_without_return_url_has_no_confirmation_or_timeout(
    client, fake_redis_client, state
):
    del state[main.KEYS.get_return_url(MESSAGE_ID)]
    response = client.get(f"/preview/{MESSAGE_ID}")
    assert response.status_code == 200
    assert "Evidence sent" in response.text
    assert "preview_lifecycle.js" not in response.text
    assert 'id="submitBtn"' not in response.text
    fake_redis_client.push_to_queue.assert_awaited_once()


@pytest.mark.parametrize("request_payload", [None, [], [{}], [{"content": "<invalid"}]])
def test_missing_or_malformed_request_keeps_confirmation(
    client, fake_redis_client, state, request_payload
):
    state[main.KEYS.get_request_edm(MESSAGE_ID)] = request_payload
    response = client.get(f"/preview/{MESSAGE_ID}")
    assert "Evidences" in response.text
    fake_redis_client.push_to_queue.assert_not_awaited()


def test_content2_takes_priority(client, fake_redis_client, state):
    state[main.KEYS.get_request_edm(MESSAGE_ID)][0].update(
        content=_request_xml(True), content2=_request_xml(False)
    )
    assert (
        client.get(f"/preview/{MESSAGE_ID}", follow_redirects=False).status_code == 303
    )
    fake_redis_client.push_to_queue.assert_awaited_once()


def test_existing_exception_does_not_auto_approve(client, fake_redis_client, state):
    state[main.KEYS.get_response_exp(MESSAGE_ID)] = {
        "exception": {"code": "EDM:ERR:0005"}
    }
    response = client.get(f"/preview/{MESSAGE_ID}", follow_redirects=False)
    assert response.headers["location"] == RETURN_URL
    fake_redis_client.push_to_queue.assert_not_awaited()


def test_empty_evidence_does_not_dispatch(client, fake_redis_client, state):
    state[main.KEYS.get_response_evidence(MESSAGE_ID)]["evidences"] = []
    assert client.get(f"/preview/{MESSAGE_ID}").status_code == 400
    fake_redis_client.push_to_queue.assert_not_awaited()


def test_failed_dispatch_can_be_retried(client, fake_redis_client, state):
    fake_redis_client.push_to_queue.side_effect = RuntimeError("queue unavailable")
    with pytest.raises(RuntimeError, match="queue unavailable"):
        client.get(f"/preview/{MESSAGE_ID}")
    assert main.KEYS.get_approvals_dispatched_key(MESSAGE_ID) not in state
    fake_redis_client.push_to_queue.side_effect = None
    assert (
        client.get(f"/preview/{MESSAGE_ID}", follow_redirects=False).status_code == 303
    )
    assert fake_redis_client.push_to_queue.await_count == 2


def test_manual_decisions_survive_reopening(client, fake_redis_client, state):
    state[main.KEYS.get_response_evidence(MESSAGE_ID)]["preview"] = True
    response = client.post(
        "/preview/continue",
        headers={"X-Action-Token": issue_action_token(MESSAGE_ID, "preview-continue")},
        json={"message_uuid": MESSAGE_ID, "approvals": {"doc-1": True, "doc-2": False}},
    )
    assert response.status_code == 200
    assert (
        client.get(f"/preview/{MESSAGE_ID}", follow_redirects=False).status_code == 303
    )
    assert (
        state[main.KEYS.get_response_evidence(MESSAGE_ID)]["evidences"][1]["permit"]
        is False
    )
    fake_redis_client.push_to_queue.assert_awaited_once()
