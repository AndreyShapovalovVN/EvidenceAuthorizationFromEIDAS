"""Helpers for validating and storing Person requests in Redis."""

from datetime import date, datetime

from pydantic import BaseModel

from lib.Person import Identifier, Person
from lib.UseRedis import UseRedisAsync


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


def _build_person_key(message_id: str) -> str:
    """Build the Redis key used to store the serialized person payload."""
    clean_message_id = message_id.strip()
    if not clean_message_id:
        raise ValueError("message_id не може бути порожнім")
    return f"oots:request:person:{clean_message_id}"


async def save_person_request(
    client: UseRedisAsync,
    payload: ContinuePayload,
) -> tuple[str, dict]:
    """Create a `Person`, store it in Redis, and enqueue the message for processing."""
    person = Person(
        LevelOfAssurance=payload.level_of_assurance,
        identifier=Identifier(_build_eidas_identifier(payload.identifier)),
        FamilyNameNonLatin=payload.last_name.strip(),
        GivenNameNonLatin=payload.first_name.strip(),
        DateOfBirth=_parse_birth_date(payload.date_of_birth),
    )

    person_data = person.dict
    redis_key = _build_person_key(payload.message_id)
    await client.save_to_redis(redis_key, person_data)
    edm = await client.get_from_redis(f"oots:message:request:edm:{payload.message_id}")
    queue = edm[0].get('process_queue')  # type: ignore
    await client.push_to_queue(queue, payload.message_id)
    return redis_key, person_data

