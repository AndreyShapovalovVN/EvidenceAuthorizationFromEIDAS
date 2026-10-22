import os
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

TEST_ENV_DEFAULTS = {
    "COUNTRY": "UA",
    "QUEUE_OUTCOMING": "test-queue",
}

for key, value in TEST_ENV_DEFAULTS.items():
    os.environ.setdefault(key, value)

import main


class FakeRedisClient:
    def __init__(self):
        self.health_check = AsyncMock(return_value=True)
        self.save_to_redis = AsyncMock(return_value=None)
        self.get_from_redis = AsyncMock(return_value=None)
        self.get_flag = AsyncMock(return_value=False)
        self.set_flag = AsyncMock(return_value=None)
        self.push_to_queue = AsyncMock(return_value=None)
        self.delete_from_redis = AsyncMock(return_value=1)


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(main, "initialize_redis", AsyncMock())
    monkeypatch.setattr(main, "close_redis", AsyncMock())
    with TestClient(main.app) as test_client:
        yield test_client


@pytest.fixture
def fake_redis_client():
    return FakeRedisClient()
