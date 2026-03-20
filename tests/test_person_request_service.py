import asyncio
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest

from lib.PersonRequestService import ContinuePayload, save_person_request


class FakeRedisSaver:
    def __init__(self):
        self.save_to_redis = AsyncMock(return_value=None)
        self.get_from_redis = AsyncMock(return_value=[{"process_queue": "oots:queue:process"}])
        self.push_to_queue = AsyncMock(return_value=None)


def test_save_person_request_stores_by_message_id_key():
    payload = ContinuePayload(
        first_name="Пилип",
        last_name="Ляхович",
        date_of_birth="1994-01-21",
        identifier="UA/UA/1059233691",
        message_id="msg-500",
        level_of_assurance="High",
    )
    client = FakeRedisSaver()

    redis_key, person_data = asyncio.run(save_person_request(cast(Any, client), payload))

    assert redis_key == "oots:request:person:msg-500"
    assert isinstance(person_data, dict)
    client.save_to_redis.assert_awaited_once()
    client.get_from_redis.assert_awaited_once_with("oots:message:request:edm:msg-500")
    client.push_to_queue.assert_awaited_once_with("oots:queue:process", "msg-500")


def test_save_person_request_raises_on_empty_message_id():
    payload = ContinuePayload(
        first_name="Andrii",
        last_name="Kovalenko",
        date_of_birth="1992-04-18",
        identifier="UA/UA/3124509876",
        message_id=" ",
        level_of_assurance="High",
    )
    client = FakeRedisSaver()

    with pytest.raises(ValueError, match="message_id"):
        asyncio.run(save_person_request(cast(Any, client), payload))
