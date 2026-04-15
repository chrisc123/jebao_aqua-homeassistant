"""L3 tests for Jebao Aqua switch platform entities."""

import pytest
from unittest.mock import AsyncMock, patch

from homeassistant.core import HomeAssistant
from homeassistant.const import STATE_ON, STATE_OFF

from custom_components.jebao_aqua.const import DOMAIN

from .conftest import MOCK_DEVICE_ID, MOCK_DEVICE_DATA


# ---------------------------------------------------------------------------
# Tests – switch entity creation
# ---------------------------------------------------------------------------


class TestSwitchSetup:
    @pytest.mark.asyncio
    async def test_switch_entities_created(self, hass: HomeAssistant, mock_setup_entry):
        """Switch entities should be created for bool status_writable attrs."""
        # SwitchON and FeedSwitch are both bool status_writable
        states = hass.states.async_all("switch")
        entity_ids = [s.entity_id for s in states]

        # Should have at least 2 switch entities
        assert len(states) >= 2

        # Check that our expected switches exist (entity IDs are lower-cased)
        switch_names = [s.attributes.get("friendly_name", "") for s in states]
        # The entities should have the attribute names in them
        assert any("switch" in eid.lower() for eid in entity_ids)

    @pytest.mark.asyncio
    async def test_switch_initial_state(self, hass: HomeAssistant, mock_setup_entry):
        """Switch state should reflect device data."""
        states = hass.states.async_all("switch")

        # Find the SwitchON entity - it should be ON per MOCK_DEVICE_DATA
        switch_on_states = [
            s for s in states if "switchon" in s.entity_id.lower()
        ]
        assert len(switch_on_states) == 1
        assert switch_on_states[0].state == STATE_ON

        # FeedSwitch should be OFF per MOCK_DEVICE_DATA
        feed_states = [
            s for s in states if "feedswitch" in s.entity_id.lower()
        ]
        assert len(feed_states) == 1
        assert feed_states[0].state == STATE_OFF


# ---------------------------------------------------------------------------
# Tests – switch control
# ---------------------------------------------------------------------------


class TestSwitchControl:
    @pytest.mark.asyncio
    async def test_turn_on_switch(self, hass: HomeAssistant, mock_setup_entry):
        """Turning on a switch should call control_device with True."""
        api = mock_setup_entry["api"]

        # Find the FeedSwitch entity (currently OFF)
        feed_states = [
            s for s in hass.states.async_all("switch")
            if "feedswitch" in s.entity_id.lower()
        ]
        assert len(feed_states) == 1
        entity_id = feed_states[0].entity_id

        with patch("custom_components.jebao_aqua.switch.asyncio.sleep", new_callable=AsyncMock):
            await hass.services.async_call(
                "switch",
                "turn_on",
                {"entity_id": entity_id},
                blocking=True,
            )

        api.control_device.assert_awaited_with(
            MOCK_DEVICE_ID, {"FeedSwitch": True}
        )

    @pytest.mark.asyncio
    async def test_turn_off_switch(self, hass: HomeAssistant, mock_setup_entry):
        """Turning off a switch should call control_device with False."""
        api = mock_setup_entry["api"]

        # Find the SwitchON entity (currently ON)
        switch_states = [
            s for s in hass.states.async_all("switch")
            if "switchon" in s.entity_id.lower()
        ]
        assert len(switch_states) == 1
        entity_id = switch_states[0].entity_id

        with patch("custom_components.jebao_aqua.switch.asyncio.sleep", new_callable=AsyncMock):
            await hass.services.async_call(
                "switch",
                "turn_off",
                {"entity_id": entity_id},
                blocking=True,
            )

        api.control_device.assert_awaited_with(
            MOCK_DEVICE_ID, {"SwitchON": False}
        )


# ---------------------------------------------------------------------------
# Tests – switch availability
# ---------------------------------------------------------------------------


class TestSwitchAvailability:
    @pytest.mark.asyncio
    async def test_switch_unavailable_without_data(
        self, hass: HomeAssistant, mock_setup_entry
    ):
        """Switch should become unavailable when device data is missing."""
        coordinator = mock_setup_entry["coordinator"]

        # Clear device data
        coordinator.device_data = {}
        coordinator.async_set_updated_data({})
        await hass.async_block_till_done()

        states = hass.states.async_all("switch")
        for state in states:
            assert state.state == "unavailable"

    @pytest.mark.asyncio
    async def test_switch_recovers_with_data(
        self, hass: HomeAssistant, mock_setup_entry
    ):
        """Switch should recover when device data comes back."""
        coordinator = mock_setup_entry["coordinator"]

        # Clear data first
        coordinator.device_data = {}
        coordinator.async_set_updated_data({})
        await hass.async_block_till_done()

        # Restore data
        coordinator.device_data = MOCK_DEVICE_DATA.copy()
        coordinator.async_set_updated_data(MOCK_DEVICE_DATA.copy())
        await hass.async_block_till_done()

        states = hass.states.async_all("switch")
        for state in states:
            assert state.state in (STATE_ON, STATE_OFF)
