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
        returnurl: str | None, ) -> str | None:

    key = KEYS.REQUEST_EDM.format(conversation_id=message_id)
    edm_payload = await client.get_from_redis(key)
    if not isinstance(edm_payload, list) or not edm_payload:
        return returnurl
    edm = _get_content(edm_payload[0])

    version_protokol = deep_get(edm, 'doc', 'SpecificationIdentifier', default='')
    if 'oots-edm:v2' in version_protokol:
        return deep_get(edm, 'doc', 'ReturnLocation', default=returnurl)
    return returnurl


async def resolve_continue_url(
        client: UseRedisAsync,
        message_id: str,
        returnurl: str | None,
) -> str | None:
    """
    Функція, яка визначає URL для редіректу після аутентифікації на основі EDM-прапора PossibilityForPreview.
    Якщо встановлений прапор вимагає перегляд та підтвердження доказу, то повертає URL з PreviewLocation,
    інакше повертає returnurl.
    """

    _logger.debug(f"Отримали параметри returnurl: {returnurl} для message_id: {message_id}")

    key = KEYS.REQUEST_EDM.format(conversation_id=message_id)

    _logger.info(f"Отримуємо EDM дані з Redis для message_id: {message_id} за ключем: {key}")

    edm_payload = await client.get_from_redis(key)

    _logger.debug(f"Отримано EDM дані з Redis для message_id {message_id}: {edm_payload}")
    edm = _get_content(edm_payload[0])  # type: ignore

    returnurl = await resolve_url(client, message_id, returnurl)

    preview = deep_get(edm, 'doc', 'PossibilityForPreview', default=False)

    if preview:
        preview_url = f"{PREVIEW_URL}/{message_id}?returnurl={returnurl}"
        _logger.debug(preview_url)
        return preview_url
    else:
        _logger.debug(f"Повертаємо на портал запросу: {returnurl}")
        return returnurl
