"""Tests for IdICEI OAuth2 client and /auth/icei/* routes.

All tests mock httpx and Redis — no real network or Redis required.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

import main
from lib.ICEI import ICEIError, IdICEI, UserProfile
from tests.conftest import FakeRedisClient


# ---------------------------------------------------------------------------
# UserProfile unit tests
# ---------------------------------------------------------------------------

class TestUserProfile:
    def test_identifier_prefers_edrpoucode(self):
        p = UserProfile(
            givenname="Іван", lastname="Іваненко", middlename=None,
            edrpoucode="1234567890", drfocode="DRFO", unzr="UNZR",
            auth_type="dig_sign", subjectcn=None,
        )
        assert p.identifier == "1234567890"

    def test_identifier_falls_back_to_drfocode(self):
        p = UserProfile(
            givenname="Іван", lastname="Іваненко", middlename=None,
            edrpoucode=None, drfocode="DRFO123", unzr="UNZR456",
            auth_type="dig_sign", subjectcn=None,
        )
        assert p.identifier == "DRFO123"

    def test_identifier_falls_back_to_unzr(self):
        p = UserProfile(
            givenname="Іван", lastname="Іваненко", middlename=None,
            edrpoucode=None, drfocode=None, unzr="20000101-12345",
            auth_type="dig_sign", subjectcn=None,
        )
        assert p.identifier == "20000101-12345"

    def test_identifier_empty_when_no_data(self):
        p = UserProfile(
            givenname="", lastname="", middlename=None,
            edrpoucode=None, drfocode=None, unzr=None,
            auth_type=None, subjectcn=None,
        )
        assert p.identifier == ""

    def test_from_dict_maps_fields(self):
        data = {
            "givenname": "Петро",
            "lastname": "Петренко",
            "middlename": "Петрович",
            "edrpoucode": "9876543210",
            "drfocode": "",
            "unzr": "19900515-00001",
            "auth_type": "dig_sign",
            "subjectcn": "Петренко Петро Петрович",
            "dateOfBirth": "1990-05-15",
            "gender": "M",
            "extra_field": "ignored",
        }
        p = UserProfile.from_dict(data)
        assert p.givenname == "Петро"
        assert p.lastname == "Петренко"
        assert p.middlename == "Петрович"
        assert p.edrpoucode == "9876543210"
        assert p.drfocode is None   # empty string → None
        assert p.unzr == "19900515-00001"
        assert p.auth_type == "dig_sign"
        assert p.subjectcn == "Петренко Петро Петрович"
        assert p.date_of_birth == "1990-05-15"
        assert p.gender == "M"
        assert p.raw == data


# ---------------------------------------------------------------------------
# IdICEI unit tests
# ---------------------------------------------------------------------------

def _make_http_mock(*responses):
    """Return a context-manager mock that returns responses in sequence."""
    call_count = [0]

    def _next_response(*_args, **_kwargs):
        idx = min(call_count[0], len(responses) - 1)
        call_count[0] += 1
        return responses[idx]

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(side_effect=_next_response)
    return mock_client


def _mock_resp(status: int, data: dict) -> MagicMock:
    r = MagicMock()
    r.status_code = status
    r.json.return_value = data
    r.text = str(data)
    return r


class TestIdICEI:
    def test_auth_url_contains_required_params(self):
        icei = IdICEI(redirect_uri="https://example.com/callback")
        url = icei.auth_url
        assert "response_type=code" in url
        assert "auth_type=dig_sign" in url
        assert f"state={icei.state}" in url
        assert "redirect_uri=" in url

    def test_state_is_unique_per_instance(self):
        a = IdICEI()
        b = IdICEI()
        assert a.state != b.state

    def test_default_redirect_uri(self):
        icei = IdICEI()
        assert "localhost" in icei.redirect_uri

    def test_get_access_token_success(self):
        token_response = {
            "access_token": "tok123",
            "token_type": "bearer",
            "expires_in": 3600,
            "refresh_token": "ref456",
            "user_id": 42,
        }
        mock_client = _make_http_mock(_mock_resp(200, token_response))
        icei = IdICEI()
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = asyncio.run(icei.get_access_token("authcode"))
        assert result["access_token"] == "tok123"
        assert result["user_id"] == 42

    def test_get_access_token_raises_on_error_response(self):
        mock_client = _make_http_mock(
            _mock_resp(200, {"error": "invalid_grant", "error_description": "bad code"})
        )
        icei = IdICEI()
        with patch("httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(ICEIError, match="invalid_grant"):
                asyncio.run(icei.get_access_token("badcode"))

    def test_get_user_info_success(self):
        user_data = {
            "givenname": "Марія",
            "lastname": "Шевченко",
            "edrpoucode": "1122334455",
            "auth_type": "dig_sign",
        }
        mock_client = _make_http_mock(_mock_resp(200, user_data))
        icei = IdICEI()
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = asyncio.run(icei.get_user_info("tok123", "42"))
        assert result["givenname"] == "Марія"

    def test_get_user_info_raises_on_encrypted_response(self):
        mock_client = _make_http_mock(
            _mock_resp(200, {"encryptedUserInfo": "base64data=="})
        )
        icei = IdICEI()
        with patch("httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(ICEIError, match="encryptedUserInfo"):
                asyncio.run(icei.get_user_info("tok123", "42"))

    def test_get_user_info_decrypts_encrypted_response(self):
        mock_client = _make_http_mock(
            _mock_resp(200, {"encryptedUserInfo": "base64data=="})
        )
        decryptor = MagicMock(return_value={
            "givenname": "Ірина",
            "lastname": "Пархоменко",
            "edrpoucode": "5566778899",
            "date_of_birth": "1987-10-02",
            "gender": "F",
        })
        icei = IdICEI(decryptor=decryptor)
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = asyncio.run(icei.get_user_info("tok123", "42"))
        decryptor.assert_called_once_with("base64data==")
        assert result["givenname"] == "Ірина"

    def test_logout_success(self):
        logout_response = {"error": "0", "error_description": "Дані користувача із ID = 42 видалено успішно"}
        mock_client = _make_http_mock(_mock_resp(200, logout_response))
        icei = IdICEI()
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = asyncio.run(icei.logout("tok123", "42"))
        assert result is True

    def test_logout_handles_server_error_gracefully(self):
        logout_response = {"error": "1", "error_description": "Invalid access_token"}
        mock_client = _make_http_mock(_mock_resp(200, logout_response))
        icei = IdICEI()
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = asyncio.run(icei.logout("invalid_token", "42"))
        assert result is False

    def test_logout_handles_http_error_gracefully(self):
        mock_client = _make_http_mock(_mock_resp(500, {"error": "server error"}))
        icei = IdICEI()
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = asyncio.run(icei.logout("tok123", "42"))
        assert result is False

    def test_logout_returns_false_on_missing_token(self):
        icei = IdICEI()
        result = asyncio.run(icei.logout("", "42"))
        assert result is False

    def test_fetch_person_full_flow(self):
        """fetch_person() виконує get_access_token → get_user_info → UserProfile."""
        token_resp = _mock_resp(200, {
            "access_token": "AT", "token_type": "bearer",
            "expires_in": 3600, "refresh_token": "RT", "user_id": 99,
        })
        user_resp = _mock_resp(200, {
            "givenname": "Олена", "lastname": "Коваль",
            "edrpoucode": "5544332211", "auth_type": "dig_sign",
        })
        logout_resp = _mock_resp(200, {
            "error": "0",
            "error_description": "Дані користувача із ID = 99 видалено успішно"
        })
        mock_client = _make_http_mock(token_resp, user_resp, logout_resp)
        icei = IdICEI()
        with patch("httpx.AsyncClient", return_value=mock_client):
            profile = asyncio.run(icei.fetch_person("code_xyz"))
        assert isinstance(profile, UserProfile)
        assert profile.givenname == "Олена"
        assert profile.lastname == "Коваль"
        assert profile.identifier == "5544332211"

    def test_fetch_person_proceeds_even_if_logout_fails(self):
        """fetch_person() повертає UserProfile навіть якщо logout не вдається."""
        token_resp = _mock_resp(200, {
            "access_token": "AT", "token_type": "bearer",
            "expires_in": 3600, "refresh_token": "RT", "user_id": 99,
        })
        user_resp = _mock_resp(200, {
            "givenname": "Тест", "lastname": "Тестенко",
            "drfocode": "9999", "auth_type": "dig_sign",
        })
        logout_fail = _mock_resp(500, {"error": "server error"})
        mock_client = _make_http_mock(token_resp, user_resp, logout_fail)
        icei = IdICEI()
        with patch("httpx.AsyncClient", return_value=mock_client):
            profile = asyncio.run(icei.fetch_person("code_xyz"))
        # Навіть якщо logout не вдався, отримуємо profile
        assert profile.givenname == "Тест"
        assert profile.identifier == "9999"


# ---------------------------------------------------------------------------
# HTTP route integration tests
# ---------------------------------------------------------------------------

def _make_fake_redis(state_data=None, edm_data=None):
    """Return FakeRedisClient with configurable get_from_redis side_effect."""
    fake = FakeRedisClient()

    def _get(key):
        if "icei:state:" in key and state_data is not None:
            return state_data
        if "request:edm:" in key and edm_data is not None:
            return edm_data
        return None

    fake.get_from_redis = AsyncMock(side_effect=_get)
    return fake


class TestIceiRoutes:
    def test_start_redirects_to_idgov(self, monkeypatch):
        """GET /auth/icei/start/{message_id} → 307 to id.gov.ua."""
        fake = _make_fake_redis(edm_data=[{"process_queue": "q"}])
        monkeypatch.setattr(main, "get_redis_client", lambda: fake)

        with TestClient(main.app, follow_redirects=False) as c:
            resp = c.get("/auth/icei/start/11111111-1111-1111-1111-111111111111")

        assert resp.status_code == 307
        assert "id.gov.ua" in resp.headers["location"]
        assert "response_type=code" in resp.headers["location"]

    def test_start_returns_400_when_edm_missing(self, monkeypatch):
        """GET /auth/icei/start/{message_id} → 400 if EDM not in Redis."""
        fake = _make_fake_redis(edm_data=None)
        monkeypatch.setattr(main, "get_redis_client", lambda: fake)

        with TestClient(main.app) as c:
            resp = c.get("/auth/icei/start/22222222-2222-2222-2222-222222222222")

        assert resp.status_code == 400

    def test_callback_saves_person_and_redirects(self, monkeypatch):
        """GET /auth/icei/callback?code=...&state=... → saves Person, 307 to /preview/."""
        fake = _make_fake_redis(
            state_data={"message_id": "msg-callback"},
            edm_data=[{"process_queue": "q:proc"}],
        )
        monkeypatch.setattr(main, "get_redis_client", lambda: fake)

        profile = UserProfile(
            givenname="Тест", lastname="Тестенко", middlename=None,
            edrpoucode="9988776655", drfocode=None, unzr=None,
            auth_type="dig_sign", subjectcn=None,
        )

        with patch.object(IdICEI, "fetch_person", new=AsyncMock(return_value=profile)):
            with TestClient(main.app, follow_redirects=False) as c:
                resp = c.get("/auth/icei/callback", params={"code": "c123", "state": "s456"})

        assert resp.status_code == 307
        assert "/preview/msg-callback" in resp.headers["location"]
        fake.delete_from_redis.assert_awaited_once()

    def test_callback_invalid_state_returns_400(self, monkeypatch):
        """GET /auth/icei/callback with unknown state → 400."""
        fake = _make_fake_redis(state_data=None)
        monkeypatch.setattr(main, "get_redis_client", lambda: fake)

        with TestClient(main.app) as c:
            resp = c.get("/auth/icei/callback", params={"code": "x", "state": "unknown"})

        assert resp.status_code == 400

    def test_callback_icei_error_returns_502(self, monkeypatch):
        """GET /auth/icei/callback when id.gov.ua returns error → 502."""
        fake = _make_fake_redis(state_data={"message_id": "msg-err"})
        monkeypatch.setattr(main, "get_redis_client", lambda: fake)

        with patch.object(
            IdICEI,
            "fetch_person",
            new=AsyncMock(side_effect=ICEIError("invalid_grant: bad code")),
        ):
            with TestClient(main.app) as c:
                resp = c.get("/auth/icei/callback", params={"code": "bad", "state": "s"})

        assert resp.status_code == 502
