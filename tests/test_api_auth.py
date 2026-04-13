"""Tests for the GizwitsApi authentication and retry logic."""

import asyncio
import json
import time
import sys
import types
import os
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

import pytest

# ---------------------------------------------------------------------------
# Bootstrap: stub out dependencies so we can import api.py in isolation
# ---------------------------------------------------------------------------
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Ensure the project root is on sys.path
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

# Create package stubs with proper __path__ so Python treats them as packages
_cc = types.ModuleType("custom_components")
_cc.__path__ = [os.path.join(_PROJECT_ROOT, "custom_components")]
sys.modules.setdefault("custom_components", _cc)

_ja = types.ModuleType("custom_components.jebao_aqua")
_ja.__path__ = [os.path.join(_PROJECT_ROOT, "custom_components", "jebao_aqua")]
sys.modules["custom_components.jebao_aqua"] = _ja

# Stub the const module with test values
_const = types.ModuleType("custom_components.jebao_aqua.const")
_const.GIZWITS_APP_ID = "test_app_id"
_const.TIMEOUT = 5
_const.LOGGER = __import__("logging").getLogger("test_jebao")
_const.LAN_PORT = 12416
_const.LAN_CONNECT_TIMEOUT = 5
_const.LAN_COMMAND_TIMEOUT = 5
_const.GIZWITS_API_URLS = {
    "eu": {
        "LOGIN_URL": "https://euaepapp.gizwits.com/app/smart_home/login/pwd",
        "DEVICES_URL": "https://euapi.gizwits.com/app/bindings",
        "DEVICE_DATA_URL": "https://euapi.gizwits.com/app/devdata/{device_id}/latest",
        "CONTROL_URL": "https://euapi.gizwits.com/app/control/{device_id}",
    }
}
_const.DEFAULT_REGION = "eu"
sys.modules["custom_components.jebao_aqua.const"] = _const

from custom_components.jebao_aqua.api import (
    GizwitsApi,
    AuthenticationError,
    MAX_API_RETRIES,
    REAUTH_COOLDOWN,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_api(**kwargs) -> GizwitsApi:
    """Create a GizwitsApi with test URLs and optional overrides."""
    defaults = dict(
        login_url="https://example.com/login",
        devices_url="https://example.com/devices",
        device_data_url="https://example.com/devdata/{device_id}/latest",
        control_url="https://example.com/control/{device_id}",
        token="old_token",
        email="user@example.com",
        password="secret123",
    )
    defaults.update(kwargs)
    return GizwitsApi(**defaults)


class FakeResponse:
    """Minimal stand-in for an aiohttp response used in context-manager form."""

    def __init__(self, status: int, body: str | dict):
        self.status = status
        self._body = json.dumps(body) if isinstance(body, dict) else body
        self.headers = {}

    async def text(self):
        return self._body

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass


def _mock_session_with_responses(*responses):
    """Return a mock aiohttp session whose .request() yields *responses* in order."""
    session = AsyncMock()
    session.closed = False
    call_iter = iter(responses)

    def _request(*args, **kwargs):
        try:
            return next(call_iter)
        except StopIteration:
            raise RuntimeError("No more mocked responses")

    session.request = MagicMock(side_effect=_request)
    return session


# ---------------------------------------------------------------------------
# Tests – constructor / credentials
# ---------------------------------------------------------------------------


class TestApiInit:
    def test_default_construction(self):
        api = _make_api()
        assert api._token == "old_token"
        assert api._email == "user@example.com"
        assert api._password == "secret123"
        assert api._last_auth_time is None

    def test_construction_without_credentials(self):
        api = _make_api(email=None, password=None)
        assert api._email is None
        assert api._password is None

    def test_set_token(self):
        api = _make_api()
        api.set_token("new_tok")
        assert api._token == "new_tok"

    def test_set_credentials(self):
        api = _make_api(email=None, password=None)
        api.set_credentials("a@b.com", "pw")
        assert api._email == "a@b.com"
        assert api._password == "pw"


# ---------------------------------------------------------------------------
# Tests – _api_request success path
# ---------------------------------------------------------------------------


class TestApiRequestSuccess:
    @pytest.mark.asyncio
    async def test_200_returns_parsed_json(self):
        api = _make_api()
        resp = FakeResponse(200, {"devices": [1, 2]})
        api._session = _mock_session_with_responses(resp)

        result = await api._api_request("GET", "https://example.com/devices")
        assert result == {"devices": [1, 2]}

    @pytest.mark.asyncio
    async def test_post_includes_content_type(self):
        api = _make_api()
        resp = FakeResponse(200, {"ok": True})
        api._session = _mock_session_with_responses(resp)

        await api._api_request("POST", "https://example.com/ctrl", json={"a": 1})
        call_kwargs = api._session.request.call_args
        # The headers are passed as a keyword argument
        headers = call_kwargs.kwargs.get("headers") or call_kwargs[1].get("headers", {})
        assert headers.get("Content-Type") == "application/json"


# ---------------------------------------------------------------------------
# Tests – _api_request 401 + re-auth
# ---------------------------------------------------------------------------


class TestApiRequestReauth:
    @pytest.mark.asyncio
    async def test_401_triggers_reauth_and_retries(self):
        """After a 401, _api_request should re-login and retry the request."""
        api = _make_api()
        # First call: 401 → triggers re-auth. Second call: 200.
        resp_401 = FakeResponse(401, {"error": "token expired"})
        resp_200 = FakeResponse(200, {"data": "ok"})
        api._session = _mock_session_with_responses(resp_401, resp_200)

        # Mock async_login to return a fresh token
        api.async_login = AsyncMock(return_value=("fresh_token", None))

        result = await api._api_request("GET", "https://example.com/devices")

        assert result == {"data": "ok"}
        assert api._token == "fresh_token"
        api.async_login.assert_awaited_once_with("user@example.com", "secret123")

    @pytest.mark.asyncio
    async def test_401_reauth_failure_raises(self):
        """If re-auth fails after 401, AuthenticationError must be raised."""
        api = _make_api()
        resp_401 = FakeResponse(401, {"error": "token expired"})
        api._session = _mock_session_with_responses(resp_401)

        api.async_login = AsyncMock(return_value=(None, "invalid_password"))

        with pytest.raises(AuthenticationError):
            await api._api_request("GET", "https://example.com/devices")

    @pytest.mark.asyncio
    async def test_401_without_credentials_raises(self):
        """If no credentials stored and 401 received, raise AuthenticationError."""
        api = _make_api(email=None, password=None)
        resp_401 = FakeResponse(401, {})
        api._session = _mock_session_with_responses(resp_401)

        with pytest.raises(AuthenticationError):
            await api._api_request("GET", "https://example.com/devices")

    @pytest.mark.asyncio
    async def test_token_refresh_callback_called(self):
        """on_token_refresh callback should be invoked with the new token."""
        callback = MagicMock()
        api = _make_api(on_token_refresh=callback)
        resp_401 = FakeResponse(401, {})
        resp_200 = FakeResponse(200, {"ok": True})
        api._session = _mock_session_with_responses(resp_401, resp_200)
        api.async_login = AsyncMock(return_value=("new_token_123", None))

        await api._api_request("GET", "https://example.com/devices")

        callback.assert_called_once_with("new_token_123")

    @pytest.mark.asyncio
    async def test_reauth_cooldown_prevents_repeated_logins(self):
        """Within REAUTH_COOLDOWN, _try_reauth should skip the actual login."""
        api = _make_api()
        # Simulate a recent successful auth
        api._last_auth_time = time.monotonic()
        api._token = "still_valid"
        api.async_login = AsyncMock()

        result = await api._try_reauth()

        assert result is True
        api.async_login.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_reauth_runs_after_cooldown_expires(self):
        """After REAUTH_COOLDOWN passes, _try_reauth should actually login."""
        api = _make_api()
        api._last_auth_time = time.monotonic() - REAUTH_COOLDOWN - 1
        api.async_login = AsyncMock(return_value=("refreshed", None))

        result = await api._try_reauth()

        assert result is True
        assert api._token == "refreshed"
        api.async_login.assert_awaited_once()


# ---------------------------------------------------------------------------
# Tests – _api_request retry on connection errors
# ---------------------------------------------------------------------------


class TestApiRequestRetry:
    @pytest.mark.asyncio
    async def test_retries_on_timeout(self):
        """Connection timeouts should be retried with backoff."""
        import aiohttp

        api = _make_api()
        session = AsyncMock()
        session.closed = False
        call_count = 0

        def _request(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise asyncio.TimeoutError()
            return FakeResponse(200, {"recovered": True})

        session.request = MagicMock(side_effect=_request)
        api._session = session

        with patch("custom_components.jebao_aqua.api.asyncio.sleep", new_callable=AsyncMock):
            result = await api._api_request("GET", "https://example.com/devices")

        assert result == {"recovered": True}
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_returns_none_after_all_retries_exhausted(self):
        """If all retries fail, _api_request returns None."""
        api = _make_api()
        session = AsyncMock()
        session.closed = False
        session.request = MagicMock(side_effect=asyncio.TimeoutError())
        api._session = session

        with patch("custom_components.jebao_aqua.api.asyncio.sleep", new_callable=AsyncMock):
            result = await api._api_request("GET", "https://example.com/devices")

        assert result is None
        assert session.request.call_count == MAX_API_RETRIES

    @pytest.mark.asyncio
    async def test_non_200_non_401_returns_none(self):
        """A 500 response should return None without retrying."""
        api = _make_api()
        resp_500 = FakeResponse(500, "Internal Server Error")
        api._session = _mock_session_with_responses(resp_500)

        result = await api._api_request("GET", "https://example.com/devices")

        assert result is None


# ---------------------------------------------------------------------------
# Tests – session management
# ---------------------------------------------------------------------------


class TestSessionManagement:
    @pytest.mark.asyncio
    async def test_ensure_session_recreates_closed_session(self):
        """_ensure_session should recreate the session if it was closed."""
        api = _make_api()
        api._session = MagicMock()
        api._session.closed = True

        with patch.object(api, "async_init_session", new_callable=AsyncMock) as mock_init:
            await api._ensure_session()
            mock_init.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_ensure_session_noop_when_active(self):
        """_ensure_session should not recreate a healthy session."""
        api = _make_api()
        api._session = MagicMock()
        api._session.closed = False

        with patch.object(api, "async_init_session", new_callable=AsyncMock) as mock_init:
            await api._ensure_session()
            mock_init.assert_not_awaited()


# ---------------------------------------------------------------------------
# Tests – simplified public methods
# ---------------------------------------------------------------------------


class TestPublicMethods:
    @pytest.mark.asyncio
    async def test_get_devices_delegates_to_api_request(self):
        api = _make_api()
        api._api_request = AsyncMock(return_value={"devices": []})

        result = await api.get_devices()

        assert result == {"devices": []}
        api._api_request.assert_awaited_once_with("GET", api.devices_url)

    @pytest.mark.asyncio
    async def test_get_device_data_formats_url(self):
        api = _make_api()
        api._api_request = AsyncMock(return_value={"attr": {"Power": 1}})

        result = await api.get_device_data("dev123")

        assert result == {"attr": {"Power": 1}}
        expected_url = api.device_data_url.format(device_id="dev123")
        api._api_request.assert_awaited_once_with("GET", expected_url)

    @pytest.mark.asyncio
    async def test_control_device_sends_attrs(self):
        api = _make_api()
        api._api_request = AsyncMock(return_value={"ok": True})

        result = await api.control_device("dev123", {"Power": 0})

        assert result == {"ok": True}
        expected_url = api.control_url.format(device_id="dev123")
        api._api_request.assert_awaited_once_with(
            "POST", expected_url, json={"attrs": {"Power": 0}}
        )


# ---------------------------------------------------------------------------
# Tests – async_login
# ---------------------------------------------------------------------------


class TestAsyncLogin:
    @pytest.mark.asyncio
    async def test_successful_login_returns_token(self):
        api = _make_api()
        login_resp = FakeResponse(
            200,
            {"error": False, "data": {"userToken": "tok_abc"}},
        )
        session = AsyncMock()
        session.post = MagicMock(return_value=login_resp)
        api._session = session

        token, error = await api.async_login("user@example.com", "pass")

        assert token == "tok_abc"
        assert error is None

    @pytest.mark.asyncio
    async def test_login_with_error_code(self):
        api = _make_api()
        login_resp = FakeResponse(
            200,
            {"error": True, "code": "1000033"},
        )
        session = AsyncMock()
        session.post = MagicMock(return_value=login_resp)
        api._session = session

        token, error = await api.async_login("user@example.com", "wrong")

        assert token is None
        assert error == "invalid_password"

    @pytest.mark.asyncio
    async def test_login_connection_error(self):
        api = _make_api()
        session = AsyncMock()
        session.post = MagicMock(side_effect=Exception("Network down"))
        api._session = session

        token, error = await api.async_login("user@example.com", "pass")

        assert token is None
        assert error == "connection_error"


# ---------------------------------------------------------------------------
# Tests – _try_reauth concurrency
# ---------------------------------------------------------------------------


class TestReauthConcurrency:
    @pytest.mark.asyncio
    async def test_concurrent_reauths_only_login_once(self):
        """Multiple concurrent _try_reauth calls should only call login once."""
        api = _make_api()
        call_count = 0

        async def _slow_login(email, password):
            nonlocal call_count
            call_count += 1
            await asyncio.sleep(0.05)
            return ("concurrent_token", None)

        api.async_login = _slow_login

        # Launch several concurrent re-auth attempts
        results = await asyncio.gather(
            api._try_reauth(),
            api._try_reauth(),
            api._try_reauth(),
        )

        # Only one should have actually called login; others hit the cooldown
        assert call_count == 1
        assert all(r is True for r in results)
        assert api._token == "concurrent_token"
