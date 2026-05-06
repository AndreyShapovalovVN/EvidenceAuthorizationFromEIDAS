"""Helpers for validating and storing Person requests in Redis."""

import logging
from datetime import date, datetime

from pydantic import BaseModel

from Models.Person import Identifier, Person
from lib.UseRedis import UseRedisAsync
from redis_keys import Keys

KEYS = Keys()
_logger = logging.getLogger(__name__)


class ContinuePayload(BaseModel):
    """Payload received from the login form continuation step."""

    first_name: str
    last_name: str
    date_of_birth: str
    identifier: str
    message_id: str
    level_of_assurance: str = "High"


def _parse_birth_date(value: str) -> date:
    """Parse a birth date in ISO or Ukrainian dotted format."""
    value = value.strip()
    for fmt in ("%Y-%m-%d", "%d.%m.%Y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    raise ValueError("date_of_birth має бути у форматі YYYY-MM-DD або DD.MM.YYYY")


def _build_eidas_identifier(raw_identifier: str) -> str:
    """Normalize an identifier to the `country/country/identifier` eIDAS format."""
    raw_identifier = raw_identifier.strip()
    if not raw_identifier:
        raise ValueError("identifier не може бути порожнім")

    if raw_identifier.count("/") == 2:
        return raw_identifier

    return f"UA/UA/{raw_identifier}"


async def save_person_request(
        client: UseRedisAsync,
        payload: ContinuePayload,
) -> tuple[str, dict]:
    """Create a `Person`, store it in Redis, and enqueue the message for processing."""
    message_id = payload.message_id.strip()
    if not message_id:
        raise ValueError("message_id не може бути порожнім")

    person = Person(
        LevelOfAssurance=payload.level_of_assurance,
        identifier=Identifier(_build_eidas_identifier(payload.identifier)),
        FamilyNameNonLatin=payload.last_name.strip(),
        GivenNameNonLatin=payload.first_name.strip(),
        DateOfBirth=_parse_birth_date(payload.date_of_birth),
    )

    person_data = person.dict
    request_person_key = KEYS.request_person(message_id)
    await client.save_to_redis(request_person_key, person_data)
    await person_push_to_queue(client, message_id)

    return request_person_key, person_data

async def person_push_to_queue(client: UseRedisAsync, message_id: str) -> bool:
    """Push message to process queue when request EDM contains a valid queue name.

    Returns:
        True if message was pushed to queue, otherwise False.
    """
    edm = await client.get_from_redis(KEYS.request_edm(message_id))

    if isinstance(edm, list):
        first_item = edm[0] if edm else None
    else:
        first_item = edm

    if not isinstance(first_item, dict):
        _logger.warning("Skip queue push: request EDM missing or invalid for message_id=%s", message_id)
        return False

    queue = first_item.get("process_queue")
    if not isinstance(queue, str) or not queue.strip():
        _logger.warning("Skip queue push: process_queue is missing for message_id=%s", message_id)
        return False

    await client.push_to_queue(queue, message_id)
    return True

