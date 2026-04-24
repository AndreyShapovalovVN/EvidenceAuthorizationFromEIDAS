"""Resolve the next URL after authentication based on EDM preview flags."""

import logging
import os

from fastapi import HTTPException
from pyRegRep4.RIMParsing import Parsing  # type: ignore
from pyRegRep4.utils import deep_get

from lib.UseRedis import UseRedisAsync
from redis_keys import Keys

_logger = logging.getLogger(__name__)

KEYS = Keys()
PREVIEW_URL = os.getenv("PREVIEW_URL")


def _get_content(edm_payload: dict) -> dict:
    if not isinstance(edm_payload, dict):
        raise HTTPException(
            status_code=422,
            detail="EDM content not found in Redis for key",
        )
    content = edm_payload.get("content2") if edm_payload.get("content2") else edm_payload.get("content")
    if content is None:
        raise HTTPException(
            status_code=408,
            detail="EDM content not found in Redis for key",
        )
    return Parsing(content).serialize()


async def resolve_url(
        client: UseRedisAsync,
        message_id: str,
) -> str | None:

    key = KEYS.REQUEST_EDM.format(conversation_id=message_id)
    edm_payload = await client.get_from_redis(key)
    if not isinstance(edm_payload, list) or not edm_payload:
        return None
    edm = _get_content(edm_payload[0])

    version_protokol = deep_get(edm, 'doc', 'SpecificationIdentifier', default='')
    if 'oots-edm:v2' in version_protokol:
        return deep_get(edm, 'doc', 'ReturnLocation', default='')
    return None

async def if_preview(client: UseRedisAsync, message_id: str) -> bool:
    key = KEYS.REQUEST_EDM.format(conversation_id=message_id)
    edm_payload = await client.get_from_redis(key)
    if not isinstance(edm_payload, list) or not edm_payload:
        return False
    edm = _get_content(edm_payload[0])
    preview = deep_get(edm, 'doc', 'PossibilityForPreview', default=False)
    return preview
