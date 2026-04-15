"""L3 tests for Jebao Aqua binary_sensor platform entities."""

import pytest
from unittest.mock import AsyncMock

from homeassistant.core import HomeAssistant
from homeassistant.const import STATE_ON, STATE_OFF
from homeassistant.components.binary_sensor import BinarySensorDeviceClass

from custom_components.jebao_aqua.const import DOMAIN

from .conftest import MOCK_DEVICE_ID, MOCK_DEVICE_DATA


# ---------------------------------------------------------------------------
# Tests – binary sensor creation
# ---------------------------------------------------------------------------


class TestBinarySensorSetup:
    @pytest.mark.asyncio
    async def test_binary_sensor_entities_created(
        self, hass: HomeAssistant, mock_setup_entry
    ):
        """Fault binary sensors should be created for fault-type bool attrs."""
        states = hass.states.async_all("binary_sensor")
        entity_ids = [s.entity_id for s in states]

        # We have Fault_Overcurrent and Fault_Overvoltage in the mock model
        assert len(states) >= 2
        assert any("overcurrent" in eid.lower() for eid in entity_ids)
        assert any("overvoltage" in eid.lower() for eid in entity_ids)

    @pytest.mark.asyncio
    async def test_binary_sensor_initial_state(
        self, hass: HomeAssistant, mock_setup_entry
    ):
        """Fault sensors should be OFF when no fault is present."""
        states = hass.states.async_all("binary_sensor")
        for state in states:
            assert state.state == STATE_OFF

    @pytest.mark.asyncio
    async def test_binary_sensor_device_class(
        self, hass: HomeAssistant, mock_setup_entry
    ):
        """Fault sensors should have PROBLEM device class."""
        states = hass.states.async_all("binary_sensor")
        for state in states:
            assert state.attributes.get("device_class") == BinarySensorDeviceClass.PROBLEM


# ---------------------------------------------------------------------------
# Tests – binary sensor state changes
# ---------------------------------------------------------------------------


class TestBinarySensorState:
    @pytest.mark.asyncio
    async def test_fault_active(self, hass: HomeAssistant, mock_setup_entry):
        """When a fault is active, binary sensor should be ON."""
        coordinator = mock_setup_entry["coordinator"]

        # Simulate fault
        fault_data = {
            MOCK_DEVICE_ID: {
                "did": MOCK_DEVICE_ID,
                "attr": {
                    **MOCK_DEVICE_DATA[MOCK_DEVICE_ID]["attr"],
                    "Fault_Overcurrent": True,
                },
            }
        }
        coordinator.device_data = fault_data
        coordinator.async_set_updated_data(fault_data)
        await hass.async_block_till_done()

        overcurrent_states = [
            s for s in hass.states.async_all("binary_sensor")
            if "overcurrent" in s.entity_id.lower()
        ]
        assert len(overcurrent_states) == 1
        assert overcurrent_states[0].state == STATE_ON

    @pytest.mark.asyncio
    async def test_fault_cleared(self, hass: HomeAssistant, mock_setup_entry):
        """When a fault is cleared, binary sensor should go back to OFF."""
        coordinator = mock_setup_entry["coordinator"]

        # First set fault active
        fault_data = {
            MOCK_DEVICE_ID: {
                "did": MOCK_DEVICE_ID,
                "attr": {
                    **MOCK_DEVICE_DATA[MOCK_DEVICE_ID]["attr"],
                    "Fault_Overcurrent": True,
                },
            }
        }
        coordinator.device_data = fault_data
        coordinator.async_set_updated_data(fault_data)
        await hass.async_block_till_done()

        # Now clear it
        coordinator.device_data = MOCK_DEVICE_DATA.copy()
        coordinator.async_set_updated_data(MOCK_DEVICE_DATA.copy())
        await hass.async_block_till_done()

        overcurrent_states = [
            s for s in hass.states.async_all("binary_sensor")
            if "overcurrent" in s.entity_id.lower()
        ]
        assert len(overcurrent_states) == 1
        assert overcurrent_states[0].state == STATE_OFF


# ---------------------------------------------------------------------------
# Tests – binary sensor availability
# ---------------------------------------------------------------------------


class TestBinarySensorAvailability:
    @pytest.mark.asyncio
    async def test_unavailable_without_data(
        self, hass: HomeAssistant, mock_setup_entry
    ):
        """Binary sensor should become unavailable when device data is missing."""
        coordinator = mock_setup_entry["coordinator"]

        coordinator.device_data = {}
        coordinator.async_set_updated_data({})
        await hass.async_block_till_done()

        states = hass.states.async_all("binary_sensor")
        for state in states:
            assert state.state == "unavailable"
