"""Preview flow services: readiness, page context, approvals, timeout."""

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

from lib.UseRedis import UseRedisAsync
from lib.evidence_view_model import (
    build_evidence_view_model,
    is_new_evidences_structure,
    normalize_preview_descriptions,
)
from redis_keys import Keys

_logger = logging.getLogger(__name__)


@dataclass
class PreviewKeys(Keys):
    PROCESS_QUEUE_DISPATCHED_KEY = "oots:preview:process_queue_dispatched:{conversation_id}"

    def get_process_queue_dispatched_key(self, message_id: str) -> str:
        return self.PROCESS_QUEUE_DISPATCHED_KEY.format(conversation_id=message_id)


class EvidenceDataNotFoundError(Exception):
    """Raised when evidence payload is missing in Redis."""


class EmptyEvidenceListError(Exception):
    """Raised when evidence payload contains no renderable evidences."""


def _get_approval_key(
        evidence: object,
        index: int,
        *,
        new_structure: bool,
) -> str | None:
    if not isinstance(evidence, dict):
        return None

    if new_structure:
        approval_key = str(evidence.get("id") or "")
        return approval_key or None

    return str(evidence.get("cid") or f"legacy-{index}")


def _apply_approvals(
        evidences: list[Any],
        approvals: dict[str, bool],
        *,
        new_structure: bool,
) -> None:
    for index, evidence in enumerate(evidences):
        approval_key = _get_approval_key(
            evidence,
            index,
            new_structure=new_structure,
        )

        if approval_key not in approvals:
            continue

        evidence["permit"] = bool(approvals[approval_key])


async def check_evidence_ready(client: UseRedisAsync, message_id: str, keys: Keys) -> bool:
    evidence_key = keys.get_response_evidence(message_id)
    return await client.get_from_redis(evidence_key) is not None


async def check_exp_ready(client: UseRedisAsync, message_id: str, keys: Keys) -> bool:
    exp_key = keys.get_response_exp(message_id)
    exp_payload = await client.get_from_redis(exp_key)
    if isinstance(exp_payload, dict):
        return isinstance(exp_payload.get("exception"), dict)
    return bool(exp_payload)


async def build_evidence_page_context(
        client: UseRedisAsync,
        message_id: str,
        keys: Keys,
) -> dict[str, Any]:
    redis_key = keys.get_response_evidence(message_id)
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
    await _enqueue_process_queue(client, message_id, keys)

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


def _extract_process_queue(edm: Any) -> str | None:
    if isinstance(edm, list):
        first_item = edm[0] if edm else None
    else:
        first_item = edm

    if not isinstance(first_item, dict):
        return None

    queue = first_item.get("process_queue")
    if not isinstance(queue, str) or not queue.strip():
        return None

    return queue.strip()


async def _enqueue_process_queue(client: UseRedisAsync, message_id: str, keys: PreviewKeys) -> bool:
    dispatch_key = keys.get_process_queue_dispatched_key(message_id)
    if await client.get_flag(dispatch_key, default=False):
        return False

    queue = _extract_process_queue(await client.get_from_redis(keys.get_request_edm(message_id)))
    if queue is None:
        _logger.debug("Skip queue push: process_queue missing for message_id=%s", message_id)
        return False

    await client.set_flag(dispatch_key, True)
    try:
        await client.push_to_queue(queue, message_id)
    except Exception:
        await client.delete_from_redis(dispatch_key)
        raise

    _logger.debug("Queued message_id=%s to process_queue=%s", message_id, queue)
    return True


async def persist_approvals(
        client: UseRedisAsync,
        message_id: str,
        approvals: dict[str, bool],
        keys: Keys,
        queue_outgoing: str,
) -> dict[str, bool]:
    evidence_key = keys.get_response_evidence(message_id)
    json_data = await client.get_from_redis(evidence_key)

    if not isinstance(json_data, dict):
        raise EvidenceDataNotFoundError(message_id)

    evidences = json_data.get("evidences") or []

    _apply_approvals(
        evidences,
        approvals,
        new_structure=is_new_evidences_structure(json_data),
    )

    json_data["preview"] = False

    await asyncio.gather(
        client.save_to_redis(evidence_key, json_data),
        client.push_to_queue(queue_outgoing, message_id),
    )

    return approvals


async def record_view_timeout(client: UseRedisAsync, message_id: str, keys: Keys, queue_outgoing: str) -> None:
    timeout_key = keys.get_response_exp(message_id)
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
