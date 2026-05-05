"""Stateless HMAC-signed action tokens for lightweight endpoint authorization."""

import base64
import hashlib
import hmac
import json
import os
import time
from typing import Any

_TOKEN_SECRET = os.getenv("ACTION_TOKEN_SECRET", "dev-action-secret")
_TOKEN_TTL_SECONDS = int(os.getenv("ACTION_TOKEN_TTL", "900"))


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64decode(raw: str) -> bytes:
    padded = raw + "=" * ((4 - len(raw) % 4) % 4)
    return base64.urlsafe_b64decode(padded.encode("ascii"))


def _sign(payload_raw: bytes) -> str:
    signature = hmac.new(_TOKEN_SECRET.encode("utf-8"), payload_raw, hashlib.sha256).digest()
    return _b64encode(signature)


def issue_action_token(message_id: str, action: str, ttl_seconds: int | None = None) -> str:
    ttl = _TOKEN_TTL_SECONDS if ttl_seconds is None else ttl_seconds
    payload: dict[str, Any] = {
        "mid": message_id,
        "act": action,
        "exp": int(time.time()) + int(ttl),
    }
    payload_raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return f"{_b64encode(payload_raw)}.{_sign(payload_raw)}"


def verify_action_token(token: str | None, message_id: str, action: str) -> bool:
    if not token:
        return False

    parts = token.split(".", 1)
    if len(parts) != 2:
        return False

    payload_b64, signature = parts
    try:
        payload_raw = _b64decode(payload_b64)
        payload = json.loads(payload_raw)
    except Exception:
        return False

    expected_signature = _sign(payload_raw)
    if not hmac.compare_digest(signature, expected_signature):
        return False

    if payload.get("mid") != message_id:
        return False
    if payload.get("act") != action:
        return False

    exp = payload.get("exp")
    if not isinstance(exp, int):
        return False

    return time.time() <= exp

