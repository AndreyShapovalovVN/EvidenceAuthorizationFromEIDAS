import asyncio
from typing import Any, cast
from unittest.mock import AsyncMock

from lib import RedirectService


class FakeRedisForRedirect:
    def __init__(self, edm_payload):
        self.get_from_redis = AsyncMock(return_value=edm_payload)


class _ParsedContent:
    def __init__(self, result):
        self._result = result

    def serialize(self):
        return self._result


def _patch_parsing(monkeypatch, result):
    def _fake_parsing(*_args, **_kwargs):
        return _ParsedContent(result)

    monkeypatch.setattr(RedirectService, "Parsing", _fake_parsing)


def test_if_preview_returns_true_when_preview_possible(monkeypatch):
    _patch_parsing(monkeypatch, {"doc": {"PossibilityForPreview": True}})

    client = FakeRedisForRedirect([
        {"content": "<Root><PossibilityForPreview>true</PossibilityForPreview></Root>"}
    ])

    preview = asyncio.run(
        RedirectService.if_preview(
            cast(Any, client),
            message_id="msg-1",
        )
    )

    assert preview is True


def test_if_preview_returns_false_when_preview_not_possible(monkeypatch):
    _patch_parsing(monkeypatch, {"doc": {"PossibilityForPreview": False}})

    client = FakeRedisForRedirect([
        {"content": "<Root><PossibilityForPreview>false</PossibilityForPreview></Root>"}
    ])

    preview = asyncio.run(
        RedirectService.if_preview(
            cast(Any, client),
            message_id="msg-5",
        )
    )

    assert preview is False


def test_resolve_url_uses_return_location_from_edm_v2(monkeypatch):
    _patch_parsing(
        monkeypatch,
        {
            "doc": {
                "SpecificationIdentifier": "oots-edm:v2.0",
                "ReturnLocation": "https://portal.local/return/from-body",
                "PossibilityForPreview": False,
            }
        },
    )

    client = FakeRedisForRedirect([
        {"content": "<Root><SpecificationIdentifier>oots-edm:v2.0</SpecificationIdentifier></Root>"}
    ])

    url = asyncio.run(RedirectService.resolve_url(cast(Any, client), message_id="msg-v2"))

    assert url == "https://portal.local/return/from-body"


def test_resolve_url_returns_none_for_legacy_protocol(monkeypatch):
    _patch_parsing(monkeypatch, {"doc": {"SpecificationIdentifier": "oots-edm:v1.0"}})

    client = FakeRedisForRedirect([
        {"content": "<Root><SpecificationIdentifier>oots-edm:v1.0</SpecificationIdentifier></Root>"}
    ])

    url = asyncio.run(RedirectService.resolve_url(cast(Any, client), message_id="msg-v1"))
    assert url is None


def test_resolve_url_returns_none_when_edm_missing():
    client = FakeRedisForRedirect(None)

    url = asyncio.run(RedirectService.resolve_url(cast(Any, client), message_id="msg-6"))
    assert url is None


def test_if_preview_returns_false_when_edm_missing():
    client = FakeRedisForRedirect(None)

    preview = asyncio.run(RedirectService.if_preview(cast(Any, client), message_id="msg-8"))
    assert preview is False


def test_resolve_url_raises_when_redis_fails():
    client = FakeRedisForRedirect({})
    client.get_from_redis = AsyncMock(side_effect=RuntimeError("redis is down"))

    try:
        asyncio.run(RedirectService.resolve_url(cast(Any, client), message_id="msg-7"))
        assert False, "Expected RuntimeError"
    except RuntimeError as exc:
        assert str(exc) == "redis is down"


def test_filter_returnurl_default_pattern_allows_any_url(monkeypatch):
    monkeypatch.delenv("RETURNURL_REGEX", raising=False)

    url = "https://portal.local/return?token=abc"
    assert RedirectService.filter_returnurl(url) == url


def test_filter_returnurl_rejects_when_pattern_does_not_match(monkeypatch):
    monkeypatch.setenv("RETURNURL_REGEX", r"^https://allowed\\.example/.*$")

    assert RedirectService.filter_returnurl("https://evil.example/phish") is None


def test_filter_returnurl_falls_back_when_pattern_invalid(monkeypatch):
    monkeypatch.setenv("RETURNURL_REGEX", r"[")

    url = "https://portal.local/return"
    assert RedirectService.filter_returnurl(url) == url
