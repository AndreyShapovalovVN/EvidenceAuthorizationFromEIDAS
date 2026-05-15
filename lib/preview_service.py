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


async def check_evidence_ready(client: UseRedisAsync, message_id: str, keys: Keys) -> bool:
    evidence_key = keys.response_evidence(message_id)
    return await client.get_from_redis(evidence_key) is not None


async def check_exp_ready(client: UseRedisAsync, message_id: str, keys: Keys) -> bool:
    exp_key = keys.response_exp(message_id)
    return await client.get_from_redis(exp_key) is not None


async def build_evidence_page_context(
    client: UseRedisAsync,
    message_id: str,
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
        "message_id": message_id,
        "message_uuid": message_id,
        "title": str(data.get("title") or "Evidence Preview"),
        "preview_descriptions": normalize_preview_descriptions(data),
        "evidences": evidences,
    }


async def build_preview_progress(client: UseRedisAsync, message_id: str, keys: Keys) -> dict[str, Any]:
    # Preview flag is no longer a blocking phase for UI progress.
    preview_ready = True
    evidence_ready, exp_ready = await asyncio.gather(
        check_evidence_ready(client, message_id, keys),
        check_exp_ready(client, message_id, keys),
    )

    stage = 2 if evidence_ready else 1

    return {
        "message_id": message_id,
        "stage": stage,
        "preview_ready": preview_ready,
        "evidence_ready": evidence_ready,
        "exp_ready": exp_ready,
    }


async def persist_approvals(
    client: UseRedisAsync,
    message_id: str,
    approvals: dict[str, bool],
    keys: Keys,
    queue_outgoing: str,
) -> dict[str, bool]:
    evidence_key = keys.response_evidence(message_id)
    # permit_key = keys.response_permit(message_id)

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
        # client.set_flag(permit_key, True),
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
                "message": "Preview timeout",
                "detail": f"Timeout reached for message_id={message_id}",
                "preview_link": None,
            }
        },
    )
    await client.push_to_queue(queue_outgoing, message_id)

