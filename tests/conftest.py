from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

import main


class FakeRedisClient:
    def __init__(self):
        self.health_check = AsyncMock(return_value=True)
        self.save_to_redis = AsyncMock(return_value=None)
        self.get_from_redis = AsyncMock(return_value=None)
        self.get_raw_from_redis = AsyncMock(return_value=None)
        self.push_to_queue = AsyncMock(return_value=None)


@pytest.fixture
def client():
    with TestClient(main.app) as test_client:
        yield test_client


@pytest.fixture
def fake_redis_client():
    return FakeRedisClient()

