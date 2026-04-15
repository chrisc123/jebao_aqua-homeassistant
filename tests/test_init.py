"""L2 tests for the Jebao Aqua integration setup (async_setup_entry, coordinator)."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant

from custom_components.jebao_aqua.const import DOMAIN
from custom_components.jebao_aqua.api import AuthenticationError

from pytest_homeassistant_custom_component.common import MockConfigEntry

from .conftest import (
    MOCK_DEVICE,
    MOCK_DEVICE_DATA,
    MOCK_DEVICE_ID,
    MOCK_LAN_IP,
    MOCK_PRODUCT_KEY,
    MOCK_TOKEN,
    make_config_entry_data,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _patch_setup(mock_api, mock_models, discovered=None):
    """Context manager that patches all external dependencies for setup."""
    return (
        patch("custom_components.jebao_aqua.GizwitsApi", return_value=mock_api),
        patch("custom_components.jebao_aqua.load_attribute_models", return_value=mock_models),
        patch("custom_components.jebao_aqua.discover_devices", return_value=discovered or {}),
    )


# ---------------------------------------------------------------------------
# Tests – async_setup_entry success
# ---------------------------------------------------------------------------


class TestSetupEntry:
    @pytest.mark.asyncio
    async def test_successful_setup(
        self, hass: HomeAssistant, mock_config_entry, mock_api, mock_attribute_models
    ):
        """Integration should set up successfully with valid config."""
        mock_config_entry.add_to_hass(hass)

        p1, p2, p3 = _patch_setup(mock_api, mock_attribute_models)
        with p1, p2, p3:
            await hass.config_entries.async_setup(mock_config_entry.entry_id)
            await hass.async_block_till_done()

        assert mock_config_entry.state == ConfigEntryState.LOADED
        assert DOMAIN in hass.data
        assert mock_config_entry.entry_id in hass.data[DOMAIN]

    @pytest.mark.asyncio
    async def test_setup_stores_api_and_coordinator(
        self, hass: HomeAssistant, mock_config_entry, mock_api, mock_attribute_models
    ):
        """After setup, hass.data should contain api, coordinator, attribute_models."""
        mock_config_entry.add_to_hass(hass)

        p1, p2, p3 = _patch_setup(mock_api, mock_attribute_models)
        with p1, p2, p3:
            await hass.config_entries.async_setup(mock_config_entry.entry_id)
            await hass.async_block_till_done()

        entry_data = hass.data[DOMAIN][mock_config_entry.entry_id]
        assert "api" in entry_data
        assert "coordinator" in entry_data
        assert "attribute_models" in entry_data

    @pytest.mark.asyncio
    async def test_setup_initializes_session(
        self, hass: HomeAssistant, mock_config_entry, mock_api, mock_attribute_models
    ):
        """API session init should be called during setup."""
        mock_config_entry.add_to_hass(hass)

        p1, p2, p3 = _patch_setup(mock_api, mock_attribute_models)
        with p1, p2, p3:
            await hass.config_entries.async_setup(mock_config_entry.entry_id)
            await hass.async_block_till_done()

        mock_api.async_init_session.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_setup_loads_attribute_models(
        self, hass: HomeAssistant, mock_config_entry, mock_api, mock_attribute_models
    ):
        """Attribute models should be loaded and added to API."""
        mock_config_entry.add_to_hass(hass)

        p1, p2, p3 = _patch_setup(mock_api, mock_attribute_models)
        with p1, p2, p3:
            await hass.config_entries.async_setup(mock_config_entry.entry_id)
            await hass.async_block_till_done()

        mock_api.add_attribute_models.assert_called_once_with(mock_attribute_models)


# ---------------------------------------------------------------------------
# Tests – async_setup_entry failure paths
# ---------------------------------------------------------------------------


class TestSetupEntryFailure:
    @pytest.mark.asyncio
    async def test_setup_fails_without_token(self, hass: HomeAssistant, mock_api, mock_attribute_models):
        """Missing token should cause setup to return False (not ready)."""
        data = make_config_entry_data()
        data.pop("token")
        entry = MockConfigEntry(domain=DOMAIN, data=data)
        entry.add_to_hass(hass)

        p1, p2, p3 = _patch_setup(mock_api, mock_attribute_models)
        with p1, p2, p3:
            await hass.config_entries.async_setup(entry.entry_id)
            await hass.async_block_till_done()

        assert entry.state == ConfigEntryState.SETUP_ERROR

    @pytest.mark.asyncio
    async def test_setup_fails_without_region(self, hass: HomeAssistant, mock_api, mock_attribute_models):
        """Missing region should cause setup to return False."""
        data = make_config_entry_data()
        data.pop("region")
        entry = MockConfigEntry(domain=DOMAIN, data=data)
        entry.add_to_hass(hass)

        p1, p2, p3 = _patch_setup(mock_api, mock_attribute_models)
        with p1, p2, p3:
            await hass.config_entries.async_setup(entry.entry_id)
            await hass.async_block_till_done()

        assert entry.state == ConfigEntryState.SETUP_ERROR

    @pytest.mark.asyncio
    async def test_setup_retries_on_first_refresh_failure(
        self, hass: HomeAssistant, mock_api, mock_attribute_models
    ):
        """If first refresh fails, ConfigEntryNotReady should be raised."""
        mock_api.get_devices = AsyncMock(return_value={"devices": [MOCK_DEVICE.copy()]})
        mock_api.get_device_data = AsyncMock(side_effect=Exception("Network down"))
        mock_api.get_local_device_data = AsyncMock(return_value=None)

        entry = MockConfigEntry(domain=DOMAIN, data=make_config_entry_data())
        entry.add_to_hass(hass)

        p1, p2, p3 = _patch_setup(mock_api, mock_attribute_models)
        with p1, p2, p3:
            await hass.config_entries.async_setup(entry.entry_id)
            await hass.async_block_till_done()

        # ConfigEntryNotReady → state is SETUP_RETRY
        assert entry.state == ConfigEntryState.SETUP_RETRY
        mock_api.close.assert_awaited_once()


# ---------------------------------------------------------------------------
# Tests – coordinator update logic
# ---------------------------------------------------------------------------


class TestCoordinatorUpdate:
    @pytest.mark.asyncio
    async def test_coordinator_fetches_device_data(self, mock_setup_entry):
        """Coordinator should populate device_data after setup."""
        coordinator = mock_setup_entry["coordinator"]
        assert coordinator.device_data is not None
        assert MOCK_DEVICE_ID in coordinator.device_data

    @pytest.mark.asyncio
    async def test_coordinator_device_inventory(self, mock_setup_entry):
        """Coordinator should have device inventory populated."""
        coordinator = mock_setup_entry["coordinator"]
        assert len(coordinator.device_inventory) == 1
        assert coordinator.device_inventory[0]["did"] == MOCK_DEVICE_ID

    @pytest.mark.asyncio
    async def test_coordinator_lan_ip_from_config(self, mock_setup_entry):
        """Coordinator should pick up LAN IPs from config entry."""
        coordinator = mock_setup_entry["coordinator"]
        device = coordinator.device_inventory[0]
        assert device.get("lan_ip") == MOCK_LAN_IP

    @pytest.mark.asyncio
    async def test_coordinator_cloud_fallback_on_lan_failure(
        self, hass: HomeAssistant, mock_config_entry, mock_api, mock_attribute_models
    ):
        """When LAN poll fails, coordinator should fall back to cloud."""
        mock_api.get_local_device_data = AsyncMock(return_value=None)
        cloud_data = {"did": MOCK_DEVICE_ID, "attr": {"SwitchON": False}}
        mock_api.get_device_data = AsyncMock(return_value=cloud_data)
        mock_config_entry.add_to_hass(hass)

        p1, p2, p3 = _patch_setup(mock_api, mock_attribute_models)
        with p1, p2, p3:
            await hass.config_entries.async_setup(mock_config_entry.entry_id)
            await hass.async_block_till_done()

        coordinator = hass.data[DOMAIN][mock_config_entry.entry_id]["coordinator"]
        assert MOCK_DEVICE_ID in coordinator.device_data
        mock_api.get_device_data.assert_awaited()

    @pytest.mark.asyncio
    async def test_coordinator_preserves_cached_data_on_failure(
        self, hass: HomeAssistant, mock_config_entry, mock_api, mock_attribute_models
    ):
        """If update fails, coordinator should preserve last known good data."""
        mock_config_entry.add_to_hass(hass)

        p1, p2, p3 = _patch_setup(mock_api, mock_attribute_models)
        with p1, p2, p3:
            await hass.config_entries.async_setup(mock_config_entry.entry_id)
            await hass.async_block_till_done()

        coordinator = hass.data[DOMAIN][mock_config_entry.entry_id]["coordinator"]
        initial_data = coordinator.device_data.copy()

        # Now make both LAN and cloud fail
        mock_api.get_local_device_data = AsyncMock(return_value=None)
        mock_api.get_device_data = AsyncMock(return_value=None)

        await coordinator.async_refresh()
        await hass.async_block_till_done()

        # Data should be preserved
        assert coordinator.device_data.get(MOCK_DEVICE_ID) is not None

    @pytest.mark.asyncio
    async def test_coordinator_auto_discovery_updates_inventory(
        self, hass: HomeAssistant, mock_api, mock_attribute_models
    ):
        """Discovery should update device inventory with discovered IPs."""
        # Config entry WITHOUT LAN IP
        data = make_config_entry_data()
        data["devices"][0]["lan_ip"] = None
        entry = MockConfigEntry(domain=DOMAIN, data=data)
        entry.add_to_hass(hass)

        discovered = {MOCK_DEVICE_ID: "192.168.1.200"}

        with patch(
            "custom_components.jebao_aqua.GizwitsApi", return_value=mock_api,
        ), patch(
            "custom_components.jebao_aqua.load_attribute_models", return_value=mock_attribute_models,
        ), patch(
            "custom_components.jebao_aqua.discover_devices", return_value=discovered,
        ):
            await hass.config_entries.async_setup(entry.entry_id)
            await hass.async_block_till_done()

        coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
        device = next(
            d for d in coordinator.device_inventory if d["did"] == MOCK_DEVICE_ID
        )
        assert device.get("lan_ip") == "192.168.1.200"
