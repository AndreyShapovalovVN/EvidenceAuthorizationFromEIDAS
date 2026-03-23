import asyncio
from typing import Any, cast
from unittest.mock import AsyncMock

from lib.MessageChecker import EDM_ERR_CODE, check_message


class FakeRedisForChecker:
    def __init__(self, evidence_data=None, preview_values=None):
        self.get_from_redis = AsyncMock(return_value=evidence_data)
        values = preview_values if preview_values is not None else [None]
        self.get_raw_from_redis = AsyncMock(side_effect=values)


def test_check_message_returns_success_when_edm_err_0002_found():
    client = FakeRedisForChecker(
        evidence_data={
            "exception": {
                "code": "EDM:ERR:0002",
                "message": "Evidence error",
                "detail": "details",
                "preview_link": None,
            }
        }
    )

    status = asyncio.run(
        check_message(cast(Any, client), "msg-1", timeout=0.1, interval=0.05)
    )

    assert not status.has_error
    assert status.evidence_error.code == EDM_ERR_CODE
    assert status.preview_ready
    assert not status.timed_out


def test_check_message_returns_preview_ready_when_flag_appears():
    client = FakeRedisForChecker(evidence_data=None, preview_values=[None, b"1"])

    status = asyncio.run(
        check_message(cast(Any, client), "msg-2", timeout=0.2, interval=0.05)
    )

    assert not status.has_error
    assert status.preview_ready
    assert not status.timed_out


def test_check_message_times_out_when_preview_flag_missing():
    client = FakeRedisForChecker(evidence_data=None, preview_values=[None, None, None])

    status = asyncio.run(
        check_message(cast(Any, client), "msg-3", timeout=0.12, interval=0.05)
    )

    assert not status.has_error
    assert not status.preview_ready
    assert status.timed_out


