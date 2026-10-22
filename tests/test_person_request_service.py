import asyncio
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest

from lib.PersonRequestService import (
    save_identified_person_request,
)


class FakeRedisSaver:
    def __init__(self):
        self.save_to_redis = AsyncMock(return_value=None)
        self.get_from_redis = AsyncMock(
            return_value=[{"process_queue": "oots:queue:process"}]
        )
        self.push_to_queue = AsyncMock(return_value=None)


def test_save_identified_person_request_accepts_missing_birth_and_gender():
    client = FakeRedisSaver()

    redis_key, person_data = asyncio.run(
        save_identified_person_request(
            cast(Any, client),
            message_id="msg-eidas-1",
            first_name="Ірина",
            last_name="Пархоменко",
            identifier="5566778899",
            date_of_birth=None,
            gender=None,
        )
    )

    assert redis_key == "oots:message:request:person:msg-eidas-1"
    assert person_data["date_of_birth"] is None
    assert person_data["gender"] is None
    assert person_data["eidas_identifier"] == "UA/UA/5566778899"
    client.push_to_queue.assert_not_awaited()


def test_save_identified_person_request_stores_birth_and_gender_when_present():
    client = FakeRedisSaver()

    _, person_data = asyncio.run(
        save_identified_person_request(
            cast(Any, client),
            message_id="msg-eidas-2",
            first_name="Олег",
            last_name="Кравець",
            identifier="UA/UA/2233445566",
            date_of_birth="1988-03-11",
            gender="M",
        )
    )

    assert person_data["date_of_birth"] == "1988-03-11"
    assert person_data["gender"] == "M"
    client.push_to_queue.assert_not_awaited()


def test_save_identified_person_rejects_empty_message_id():
    client = FakeRedisSaver()
    with pytest.raises(ValueError, match="message_id"):
        asyncio.run(
            save_identified_person_request(
                cast(Any, client),
                message_id=" ",
                first_name="Test",
                last_name="Person",
                identifier="UA/UA/123",
                date_of_birth=None,
            )
        )
    client.save_to_redis.assert_not_awaited()
