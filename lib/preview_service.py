"""Preview flow services: readiness, page context, approvals, timeout."""

import asyncio
from typing import Any

from lib.evidence_view_model import (
    build_evidence_view_model,
    is_new_evidences_structure,
    normalize_preview_descriptions,
)
from lib.UseRedis import UseRedisAsync
from redis_keys import Keys


class EvidenceDataNotFoundError(Exception):
    """Raised when evidence payload is missing in Redis."""


class EmptyEvidenceListError(Exception):
    """Raised when evidence payload contains no renderable evidences."""


async def check_preview_ready(client: UseRedisAsync, message_id: str, keys: Keys) -> bool:
    preview_key = keys.request_preview(message_id)
    return await client.get_flag(preview_key, default=False)


async def check_evidence_ready(client: UseRedisAsync, message_id: str, keys: Keys) -> bool:
    evidence_key = keys.response_evidence(message_id)
    return await client.get_from_redis(evidence_key) is not None


async def build_evidence_page_context(
    client: UseRedisAsync,
    message_id: str,
    returnurl: str,
    keys: Keys,
) -> dict[str, Any]:
    redis_key = keys.response_evidence(message_id)
    data = await client.get_from_redis(redis_key)
    if not isinstance(data, dict):
        raise EvidenceDataNotFoundError(message_id)

    evidences = build_evidence_view_model(data)
    if not evidences:
        raise EmptyEvidenceListError(message_id)

    return {
        "returnurl": returnurl,
        "message_id": message_id,
        "message_uuid": message_id,
        "title": str(data.get("title") or "Evidence Preview"),
        "preview_descriptions": normalize_preview_descriptions(data),
        "evidences": evidences,
    }


async def build_preview_progress(client: UseRedisAsync, message_id: str, keys: Keys) -> dict[str, Any]:
    preview_ready = await check_preview_ready(client, message_id, keys)
    evidence_ready = await check_evidence_ready(client, message_id, keys)

    stage = 0
    if preview_ready:
        stage = 1
    if evidence_ready:
        stage = 2

    return {
        "message_id": message_id,
        "stage": stage,
        "preview_ready": preview_ready,
        "evidence_ready": evidence_ready,
    }


async def persist_approvals(
    client: UseRedisAsync,
    message_id: str,
    approvals: dict[str, bool],
    keys: Keys,
    queue_outgoing: str,
) -> dict[str, bool]:
    evidence_key = keys.response_evidence(message_id)
    permit_key = keys.response_permit(message_id)

    json_data = await client.get_from_redis(evidence_key)
    if not isinstance(json_data, dict):
        raise EvidenceDataNotFoundError(message_id)

    evidences = json_data.get("evidences") or []
    if is_new_evidences_structure(json_data):
        for package in evidences:
            if not isinstance(package, dict):
                continue
            approval_key = str(package.get("id") or "")
            if approval_key and approval_key in approvals:
                package["permit"] = bool(approvals[approval_key])
    else:
        for index, evidence in enumerate(evidences):
            if not isinstance(evidence, dict):
                continue
            approval_key = str(evidence.get("cid") or f"legacy-{index}")
            if approval_key in approvals:
                evidence["permit"] = bool(approvals[approval_key])

    json_data["preview"] = False

    await asyncio.gather(
        client.save_to_redis(evidence_key, json_data),
        client.set_flag(permit_key, True),
        client.push_to_queue(queue_outgoing, message_id),
    )

    return approvals


async def record_view_timeout(client: UseRedisAsync, message_id: str, keys: Keys, queue_outgoing: str) -> None:
    timeout_key = keys.response_exp(message_id)
    await client.save_to_redis(
        timeout_key,
        {
            "exception": {
                "code": "EDM:ERR:0005",
                "message": f"View timeout for message_id={message_id}",
                "detail": f"View timeout for message_id={message_id}",
            }
        },
    )
    await client.push_to_queue(queue_outgoing, message_id)

