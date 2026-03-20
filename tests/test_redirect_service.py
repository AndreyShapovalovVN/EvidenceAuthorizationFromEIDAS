import asyncio
from typing import Any, cast
from unittest.mock import AsyncMock

from lib import RedirectService


class FakeRedisForRedirect:
    def __init__(self, edm_payload):
        self.get_from_redis = AsyncMock(return_value=edm_payload)


def test_resolve_continue_url_uses_preview_location_when_preview_possible(monkeypatch):
    class DummyParsing:
        def __init__(self, _):
            pass

        def serialize(self):
            return {
                "doc": {
                    "PossibilityForPreview": True,
                    "PreviewLocation": "http://evidence.local/preview/msg-1",
                }
            }

    monkeypatch.setattr(RedirectService, "Parsing", DummyParsing)

    client = FakeRedisForRedirect(
        {
            "content": "<Root><PossibilityForPreview>true</PossibilityForPreview></Root>"
        }
    )

    url = asyncio.run(
        RedirectService.resolve_continue_url(
            cast(Any, client),
            message_id="msg-1",
            returnurl="http://oots-portal.oots-dev.k8s/previewed?token=abc",
            returnmethod="GET",
        )
    )

    assert url == (
        "http://evidence.local/preview/msg-1"
        "?http://oots-portal.oots-dev.k8s/previewed?token=abc"
    )


def test_resolve_continue_url_returns_returnurl_when_preview_not_possible(monkeypatch):
    class DummyParsing:
        def __init__(self, _):
            pass

        def serialize(self):
            return {"doc": {"PossibilityForPreview": False}}

    monkeypatch.setattr(RedirectService, "Parsing", DummyParsing)

    client = FakeRedisForRedirect(
        {
            "content": "<Root><PossibilityForPreview>false</PossibilityForPreview></Root>"
        }
    )

    url = asyncio.run(
        RedirectService.resolve_continue_url(
            cast(Any, client),
            message_id="msg-5",
            returnurl="http://oots-portal.oots-dev.k8s/previewed?token=xyz",
            returnmethod="GET",
        )
    )

    assert url == "http://oots-portal.oots-dev.k8s/previewed?token=xyz"


def test_resolve_continue_url_raises_when_edm_missing():
    client = FakeRedisForRedirect(None)

    try:
        asyncio.run(
            RedirectService.resolve_continue_url(
                cast(Any, client),
                message_id="msg-6",
                returnurl="http://oots-portal.oots-dev.k8s/previewed?token=xyz",
            )
        )
        assert False, "Expected ValueError"
    except ValueError as exc:
        assert "EDM content not found" in str(exc)


def test_resolve_continue_url_raises_when_redis_fails():
    client = FakeRedisForRedirect({})
    client.get_from_redis = AsyncMock(side_effect=RuntimeError("redis is down"))

    try:
        asyncio.run(
            RedirectService.resolve_continue_url(
                cast(Any, client),
                message_id="msg-7",
                returnurl="http://oots-portal.oots-dev.k8s/previewed?token=xyz",
            )
        )
        assert False, "Expected RuntimeError"
    except RuntimeError as exc:
        assert str(exc) == "redis is down"


