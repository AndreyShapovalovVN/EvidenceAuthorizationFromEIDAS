"""Resolve the next URL after authentication based on EDM preview flags."""

import logging
import os

from fastapi import HTTPException
from pyRegRep4.RIMParsing import Parsing  # type: ignore

from lib.UseRedis import UseRedisAsync

_logger = logging.getLogger(__name__)

EDM_DATASET_KEY = "oots:message:request:edm:{conversation_id}"
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


async def resolve_continue_url(
        client: UseRedisAsync,
        message_id: str,
        returnurl: str | None,
        returnmethod: str | None = None,
) -> str | None:
    """
    Функція, яка визначає URL для редіректу після аутентифікації на основі EDM-прапора PossibilityForPreview.
    Якщо встановлений прапор вимагає перегляд та підтвердження доказу, то повертає URL з PreviewLocation,
    інакше повертає returnurl.
    """

    _logger.debug(f"Отримали параметри returnurl: {returnurl}, returnmethod: {returnmethod} для message_id: {message_id}")

    key = EDM_DATASET_KEY.format(conversation_id=message_id)

    _logger.info(f"Отримуємо EDM дані з Redis для message_id: {message_id} за ключем: {key}")

    edm_payload = await client.get_from_redis(key)

    _logger.debug(f"Отримано EDM дані з Redis для message_id {message_id}: {edm_payload}")
    edm = _get_content(edm_payload[0])  # type: ignore

    if edm.get("doc", {}).get("PossibilityForPreview"):
        _logger.debug(f"{PREVIEW_URL}/{message_id}?returnurl={returnurl}&returnmethod={returnmethod}")
        return f"{PREVIEW_URL}/{message_id}?returnurl={returnurl}&returnmethod={returnmethod}"
    else:
        _logger.debug(f"Повертаємо на портал запросу: {returnurl}")
        return returnurl
