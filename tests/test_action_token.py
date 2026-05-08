import base64
import hashlib
import hmac
import json
import time

from lib import action_token


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def test_action_token_valid_for_same_message_and_action():
    token = action_token.issue_action_token("msg-1", "preview-continue", ttl_seconds=60)

    assert action_token.verify_action_token(token, "msg-1", "preview-continue") is True


def test_action_token_rejects_other_message_id():
    token = action_token.issue_action_token("msg-1", "preview-continue", ttl_seconds=60)

    assert action_token.verify_action_token(token, "msg-2", "preview-continue") is False


def test_action_token_rejects_other_action():
    token = action_token.issue_action_token("msg-1", "preview-continue", ttl_seconds=60)

    assert action_token.verify_action_token(token, "msg-1", "preview-timeout") is False


def test_action_token_rejects_legacy_signature():
    payload = {
        "mid": "msg-legacy",
        "act": "auth-continue",
        "exp": int(time.time()) + 60,
    }
    payload_raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    payload_b64 = _b64encode(payload_raw)

    legacy_sig = hmac.new(
        action_token._TOKEN_SECRET.encode("utf-8"),
        payload_raw,
        hashlib.sha256,
    ).digest()
    token = f"{payload_b64}.{_b64encode(legacy_sig)}"

    assert action_token.verify_action_token(token, "msg-legacy", "auth-continue") is False

