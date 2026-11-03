"""Resolve and filter the caller return URL from EDM metadata."""

import logging
import re

from fastapi import HTTPException
from oots_lib.import_env import import_env
from oots_lib.lib.UseRedis import UseRedisAsync
from oots_lib.models.Person import Person
from pyRegRep4.RIMParsing import Parsing  # type: ignore
from pyRegRep4.utils import deep_get

from lib.preview_keys import PreviewKeys as Keys

_logger = logging.getLogger(__name__)

KEYS = Keys()


def filter_returnurl(returnurl: str | None) -> str | None:
    """Validate returnurl using regex from environment, fallback to permissive default.

    Env:
      RETURNURL_REGEX - regex pattern, default ".*"
    """
    if not returnurl:
        return None

    pattern = import_env("RETURNURL_REGEX", ".*")
    try:
        matcher = re.compile(pattern)
    except re.error:
        _logger.warning("Invalid RETURNURL_REGEX=%r, fallback to default '.*'", pattern)
        matcher = re.compile(r".*")

    if matcher.fullmatch(returnurl):
        return returnurl

    _logger.warning("returnurl rejected by RETURNURL_REGEX pattern")
    return None


def _get_content(edm_payload: dict) -> dict:
    if not isinstance(edm_payload, dict):
        raise HTTPException(
            status_code=422,
            detail="EDM content not found in Redis for key",
        )
    content = (
        edm_payload.get("content2")
        if edm_payload.get("content2")
        else edm_payload.get("content")
    )
    if content is None:
        raise HTTPException(
            status_code=408,
            detail="EDM content not found in Redis for key",
        )
    return Parsing(content).serialize()


def request_person_identifier(edm_payload) -> str | None:
    """Read the evidence subject's identifier from the incoming EDM."""
    if isinstance(edm_payload, list):
        edm_payload = edm_payload[0] if edm_payload else None
    if not isinstance(edm_payload, dict) or not (
        edm_payload.get("content2") or edm_payload.get("content")
    ):
        return None
    try:
        edm = _get_content(edm_payload)
        person_xml = deep_get(edm, "query", "NaturalPerson", default=None)
        if person_xml is None:
            return None
        person = Person()
        person.xml = person_xml
        return person.identifier.value if person.identifier else None
    except Exception:
        _logger.warning("Cannot read NaturalPerson identifier from request EDM")
        return None


async def resolve_url(
    client: UseRedisAsync,
    message_id: str,
) -> str | None:

    key = KEYS.REQUEST_EDM.format(conversation_id=message_id)
    edm_payload = await client.get_from_redis(key)
    if not isinstance(edm_payload, list) or not edm_payload:
        return None
    edm = _get_content(edm_payload[0])

    version_protokol = deep_get(edm, "doc", "SpecificationIdentifier", default="")
    if "oots-edm:v2" in version_protokol:
        return deep_get(edm, "doc", "ReturnLocation", default="")
    return None


async def resolve_possibility_for_preview(
    client: UseRedisAsync, message_id: str, keys: Keys
) -> bool | None:
    """Read the request flag; missing or malformed metadata still needs preview."""
    payload = await client.get_from_redis(keys.get_request_edm(message_id))
    if isinstance(payload, list):
        payload = payload[0] if payload else None
    if not isinstance(payload, dict) or not (
        payload.get("content2") or payload.get("content")
    ):
        return None
    try:
        edm = _get_content(payload)
    except Exception:
        _logger.warning("Cannot read PossibilityForPreview for message_id=%s", message_id)
        return None
    value = deep_get(edm, "doc", "PossibilityForPreview", default=None)
    return value if isinstance(value, bool) else None
