"""Helpers for validating and storing Person requests in Redis."""

from datetime import date, datetime

from pydantic import BaseModel

from Models.Person import Identifier, Person
from lib.UseRedis import UseRedisAsync
from redis_keys import Keys

KEYS = Keys()


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
    """Create a `Person` and store it in Redis."""
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
    request_person_key = KEYS.get_request_person(message_id)
    await client.save_to_redis(request_person_key, person_data)
    return request_person_key, person_data


async def save_identified_person_request(
    client: UseRedisAsync,
    *,
    message_id: str,
    first_name: str,
    last_name: str,
    identifier: str,
    date_of_birth: str | None,
    gender: str | None = None,
    level_of_assurance: str = "High",
) -> tuple[str, dict]:
    """Зберегти дані особи, отримані від зовнішнього провайдера ідентифікації."""
    clean_id = message_id.strip()
    if not clean_id:
        raise ValueError("message_id не може бути порожнім")

    parsed_date = _parse_birth_date(date_of_birth) if date_of_birth else None

    person = Person(
        LevelOfAssurance=level_of_assurance,
        identifier=Identifier(_build_eidas_identifier(identifier)),
        FamilyNameNonLatin=last_name.strip(),
        GivenNameNonLatin=first_name.strip(),
        DateOfBirth=parsed_date,
        Gender=gender.strip() if isinstance(gender, str) and gender.strip() else None,
    )

    person_data = person.dict
    request_person_key = KEYS.get_request_person(clean_id)
    await client.save_to_redis(request_person_key, person_data)
    return request_person_key, person_data
