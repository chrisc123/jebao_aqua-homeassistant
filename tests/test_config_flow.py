"""L2 tests for the Jebao Aqua config flow."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.jebao_aqua.const import DOMAIN

from .conftest import (
    MOCK_TOKEN,
    MOCK_EMAIL,
    MOCK_PASSWORD,
    MOCK_DEVICE_ID,
    MOCK_DEVICE_ALIAS,
    MOCK_PRODUCT_KEY,
    MOCK_LAN_IP,
    MOCK_DEVICE,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_api_successful_login():
    """Return a mock API that logs in and returns devices.

    The config flow uses ``async with self._api as api:``, so the mock must
    support the async-context-manager protocol and return *itself* on enter.
    """
    api = AsyncMock()
    api.async_login = AsyncMock(return_value=(MOCK_TOKEN, None))
    api.set_token = MagicMock()
    api.get_devices = AsyncMock(
        return_value={"devices": [MOCK_DEVICE.copy()]}
    )
    api.async_init_session = AsyncMock()
    api.close = AsyncMock()
    # __aenter__ returns the api itself, __aexit__ is a no-op
    api.__aenter__ = AsyncMock(return_value=api)
    api.__aexit__ = AsyncMock(return_value=False)
    return api


def _mock_api_failed_login(error_code: str):
    """Return a mock API that fails login with the given error code."""
    api = AsyncMock()
    api.async_login = AsyncMock(return_value=(None, error_code))
    api.async_init_session = AsyncMock()
    api.close = AsyncMock()
    api.__aenter__ = AsyncMock(return_value=api)
    api.__aexit__ = AsyncMock(return_value=False)
    return api


# ---------------------------------------------------------------------------
# Tests – user step
# ---------------------------------------------------------------------------


class TestConfigFlowUserStep:
    """Tests for the initial user step (country, email, password)."""

    @pytest.mark.asyncio
    async def test_user_step_shows_form(self, hass: HomeAssistant):
        """First call without input should show the user form."""
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "user"
        assert "country" in result["data_schema"].schema
        assert "email" in result["data_schema"].schema
        assert "password" in result["data_schema"].schema

    @pytest.mark.asyncio
    async def test_user_step_invalid_credentials(self, hass: HomeAssistant):
        """Login failure should show an error on the user form."""
        api = _mock_api_failed_login("invalid_password")

        with patch(
            "custom_components.jebao_aqua.config_flow.GizwitsApi",
            return_value=api,
        ), patch(
            "custom_components.jebao_aqua.config_flow.discover_devices",
            return_value={},
        ):
            result = await hass.config_entries.flow.async_init(
                DOMAIN, context={"source": config_entries.SOURCE_USER}
            )
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {"country": "GB", "email": MOCK_EMAIL, "password": "wrong"},
            )

        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "user"
        assert result["errors"]["base"] == "invalid_password"

    @pytest.mark.asyncio
    async def test_user_step_connection_error(self, hass: HomeAssistant):
        """A connection error during login should show an error."""
        api = _mock_api_failed_login("connection_error")

        with patch(
            "custom_components.jebao_aqua.config_flow.GizwitsApi",
            return_value=api,
        ), patch(
            "custom_components.jebao_aqua.config_flow.discover_devices",
            return_value={},
        ):
            result = await hass.config_entries.flow.async_init(
                DOMAIN, context={"source": config_entries.SOURCE_USER}
            )
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {"country": "GB", "email": MOCK_EMAIL, "password": MOCK_PASSWORD},
            )

        assert result["type"] == FlowResultType.FORM
        assert result["errors"]["base"] == "connection_error"

    @pytest.mark.asyncio
    async def test_user_step_no_devices(self, hass: HomeAssistant):
        """Login succeeds but no devices found should show error."""
        api = _mock_api_successful_login()
        api.get_devices = AsyncMock(return_value=None)

        with patch(
            "custom_components.jebao_aqua.config_flow.GizwitsApi",
            return_value=api,
        ), patch(
            "custom_components.jebao_aqua.config_flow.discover_devices",
            return_value={},
        ):
            result = await hass.config_entries.flow.async_init(
                DOMAIN, context={"source": config_entries.SOURCE_USER}
            )
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {"country": "GB", "email": MOCK_EMAIL, "password": MOCK_PASSWORD},
            )

        # Empty devices list — the code checks `if self._devices and "devices" in self._devices:`
        # With an empty list this is falsy, so it falls through to "no_devices"
        assert result["type"] == FlowResultType.FORM
        assert result["errors"]["base"] == "no_devices"

    @pytest.mark.asyncio
    async def test_user_step_success_advances_to_device_setup(self, hass: HomeAssistant):
        """Successful login with devices should advance to device_setup step."""
        api = _mock_api_successful_login()

        with patch(
            "custom_components.jebao_aqua.config_flow.GizwitsApi",
            return_value=api,
        ), patch(
            "custom_components.jebao_aqua.config_flow.discover_devices",
            return_value={MOCK_DEVICE_ID: MOCK_LAN_IP},
        ):
            result = await hass.config_entries.flow.async_init(
                DOMAIN, context={"source": config_entries.SOURCE_USER}
            )
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {"country": "GB", "email": MOCK_EMAIL, "password": MOCK_PASSWORD},
            )

        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "device_setup"

    @pytest.mark.asyncio
    async def test_user_step_discovery_timeout_still_proceeds(self, hass: HomeAssistant):
        """If discovery times out, flow should still proceed to device_setup."""
        import asyncio

        api = _mock_api_successful_login()

        async def _timeout_discover():
            raise asyncio.TimeoutError()

        with patch(
            "custom_components.jebao_aqua.config_flow.GizwitsApi",
            return_value=api,
        ), patch(
            "custom_components.jebao_aqua.config_flow.discover_devices",
            side_effect=_timeout_discover,
        ):
            result = await hass.config_entries.flow.async_init(
                DOMAIN, context={"source": config_entries.SOURCE_USER}
            )
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {"country": "GB", "email": MOCK_EMAIL, "password": MOCK_PASSWORD},
            )

        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "device_setup"


# ---------------------------------------------------------------------------
# Tests – device_setup step
# ---------------------------------------------------------------------------


class TestConfigFlowDeviceSetup:
    """Tests for the device_setup step (LAN IP configuration)."""

    async def _get_to_device_setup(self, hass: HomeAssistant, discovered_ip=None):
        """Helper: advance the flow to the device_setup step and return the result."""
        api = _mock_api_successful_login()
        discovered = {MOCK_DEVICE_ID: discovered_ip} if discovered_ip else {}

        with patch(
            "custom_components.jebao_aqua.config_flow.GizwitsApi",
            return_value=api,
        ), patch(
            "custom_components.jebao_aqua.config_flow.discover_devices",
            return_value=discovered,
        ):
            result = await hass.config_entries.flow.async_init(
                DOMAIN, context={"source": config_entries.SOURCE_USER}
            )
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {"country": "GB", "email": MOCK_EMAIL, "password": MOCK_PASSWORD},
            )
        assert result["step_id"] == "device_setup"
        return result

    @pytest.mark.asyncio
    async def test_device_setup_shows_discovered_ips(self, hass: HomeAssistant):
        """Device setup form should pre-fill discovered IPs."""
        result = await self._get_to_device_setup(hass, discovered_ip=MOCK_LAN_IP)

        # The form should contain the device alias as a field key
        schema_keys = [str(k) for k in result["data_schema"].schema]
        assert MOCK_DEVICE_ALIAS in schema_keys

    @pytest.mark.asyncio
    async def test_device_setup_creates_entry(self, hass: HomeAssistant):
        """Submitting device IPs should create a config entry."""
        api = _mock_api_successful_login()

        with patch(
            "custom_components.jebao_aqua.config_flow.GizwitsApi",
            return_value=api,
        ), patch(
            "custom_components.jebao_aqua.config_flow.discover_devices",
            return_value={MOCK_DEVICE_ID: MOCK_LAN_IP},
        ):
            result = await hass.config_entries.flow.async_init(
                DOMAIN, context={"source": config_entries.SOURCE_USER}
            )
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {"country": "GB", "email": MOCK_EMAIL, "password": MOCK_PASSWORD},
            )
            # Now submit the device_setup form
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {MOCK_DEVICE_ALIAS: MOCK_LAN_IP},
            )

        assert result["type"] == FlowResultType.CREATE_ENTRY
        assert result["title"] == "Jebao Aquarium Pumps"
        assert result["data"]["token"] == MOCK_TOKEN
        assert result["data"]["email"] == MOCK_EMAIL
        assert result["data"]["region"] == "eu"
        assert result["data"]["country"] == "GB"
        assert len(result["data"]["devices"]) == 1
        assert result["data"]["devices"][0]["did"] == MOCK_DEVICE_ID
        assert result["data"]["devices"][0]["lan_ip"] == MOCK_LAN_IP

    @pytest.mark.asyncio
    async def test_device_setup_empty_ip(self, hass: HomeAssistant):
        """Submitting empty IP should create entry with lan_ip=None."""
        api = _mock_api_successful_login()

        with patch(
            "custom_components.jebao_aqua.config_flow.GizwitsApi",
            return_value=api,
        ), patch(
            "custom_components.jebao_aqua.config_flow.discover_devices",
            return_value={},
        ):
            result = await hass.config_entries.flow.async_init(
                DOMAIN, context={"source": config_entries.SOURCE_USER}
            )
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {"country": "US", "email": MOCK_EMAIL, "password": MOCK_PASSWORD},
            )
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {MOCK_DEVICE_ALIAS: ""},
            )

        assert result["type"] == FlowResultType.CREATE_ENTRY
        assert result["data"]["devices"][0]["lan_ip"] is None
        assert result["data"]["region"] == "us"

    @pytest.mark.asyncio
    async def test_device_setup_region_mapping(self, hass: HomeAssistant):
        """Country code should map to the correct region."""
        api = _mock_api_successful_login()

        test_cases = [("GB", "eu"), ("US", "us"), ("CN", "cn"), ("FR", "eu"), ("JP", "us")]

        for country, expected_region in test_cases:
            with patch(
                "custom_components.jebao_aqua.config_flow.GizwitsApi",
                return_value=api,
            ), patch(
                "custom_components.jebao_aqua.config_flow.discover_devices",
                return_value={},
            ):
                result = await hass.config_entries.flow.async_init(
                    DOMAIN, context={"source": config_entries.SOURCE_USER}
                )
                result = await hass.config_entries.flow.async_configure(
                    result["flow_id"],
                    {"country": country, "email": MOCK_EMAIL, "password": MOCK_PASSWORD},
                )
                result = await hass.config_entries.flow.async_configure(
                    result["flow_id"],
                    {MOCK_DEVICE_ALIAS: ""},
                )

            assert result["data"]["region"] == expected_region, (
                f"Country {country} should map to region {expected_region}"
            )
