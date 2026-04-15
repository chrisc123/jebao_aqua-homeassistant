"""L3 tests for Jebao Aqua number platform entities."""

import pytest
from unittest.mock import AsyncMock

from homeassistant.core import HomeAssistant

from custom_components.jebao_aqua.const import DOMAIN

from .conftest import MOCK_DEVICE_ID, MOCK_DEVICE_DATA


# ---------------------------------------------------------------------------
# Tests – number entity creation
# ---------------------------------------------------------------------------


class TestNumberSetup:
    @pytest.mark.asyncio
    async def test_number_entities_created(
        self, hass: HomeAssistant, mock_setup_entry
    ):
        """Number entities should be created for uint8 status_writable attrs."""
        states = hass.states.async_all("number")
        entity_ids = [s.entity_id for s in states]

        # We have Flow and Frequency in the mock model
        assert len(states) >= 2
        assert any("flow" in eid.lower() for eid in entity_ids)
        assert any("frequency" in eid.lower() for eid in entity_ids)

    @pytest.mark.asyncio
    async def test_number_initial_value(
        self, hass: HomeAssistant, mock_setup_entry
    ):
        """Number entities should show current device values."""
        flow_states = [
            s for s in hass.states.async_all("number")
            if "flow" in s.entity_id.lower() and "frequency" not in s.entity_id.lower()
        ]
        assert len(flow_states) == 1
        assert float(flow_states[0].state) == 75.0

        freq_states = [
            s for s in hass.states.async_all("number")
            if "frequency" in s.entity_id.lower()
        ]
        assert len(freq_states) == 1
        assert float(freq_states[0].state) == 50.0

    @pytest.mark.asyncio
    async def test_number_min_max_step(
        self, hass: HomeAssistant, mock_setup_entry
    ):
        """Number entities should have correct min/max/step from model."""
        flow_states = [
            s for s in hass.states.async_all("number")
            if "flow" in s.entity_id.lower() and "frequency" not in s.entity_id.lower()
        ]
        assert len(flow_states) == 1
        attrs = flow_states[0].attributes
        assert attrs.get("min") == 30
        assert attrs.get("max") == 100
        assert attrs.get("step") == 1


# ---------------------------------------------------------------------------
# Tests – number control
# ---------------------------------------------------------------------------


class TestNumberControl:
    @pytest.mark.asyncio
    async def test_set_value(self, hass: HomeAssistant, mock_setup_entry):
        """Setting a number value should call control_device."""
        api = mock_setup_entry["api"]

        flow_states = [
            s for s in hass.states.async_all("number")
            if "flow" in s.entity_id.lower() and "frequency" not in s.entity_id.lower()
        ]
        entity_id = flow_states[0].entity_id

        await hass.services.async_call(
            "number",
            "set_value",
            {"entity_id": entity_id, "value": 85},
            blocking=True,
        )

        api.control_device.assert_awaited_with(
            MOCK_DEVICE_ID, {"Flow": 85}
        )

    @pytest.mark.asyncio
    async def test_set_frequency(self, hass: HomeAssistant, mock_setup_entry):
        """Setting frequency should call control_device."""
        api = mock_setup_entry["api"]

        freq_states = [
            s for s in hass.states.async_all("number")
            if "frequency" in s.entity_id.lower()
        ]
        entity_id = freq_states[0].entity_id

        await hass.services.async_call(
            "number",
            "set_value",
            {"entity_id": entity_id, "value": 30},
            blocking=True,
        )

        api.control_device.assert_awaited_with(
            MOCK_DEVICE_ID, {"Frequency": 30}
        )


# ---------------------------------------------------------------------------
# Tests – number state changes
# ---------------------------------------------------------------------------


class TestNumberStateChanges:
    @pytest.mark.asyncio
    async def test_number_updates_on_coordinator_refresh(
        self, hass: HomeAssistant, mock_setup_entry
    ):
        """Number value should update when coordinator data changes."""
        coordinator = mock_setup_entry["coordinator"]

        new_data = {
            MOCK_DEVICE_ID: {
                "did": MOCK_DEVICE_ID,
                "attr": {
                    **MOCK_DEVICE_DATA[MOCK_DEVICE_ID]["attr"],
                    "Flow": 90,
                },
            }
        }
        coordinator.device_data = new_data
        coordinator.async_set_updated_data(new_data)
        await hass.async_block_till_done()

        flow_states = [
            s for s in hass.states.async_all("number")
            if "flow" in s.entity_id.lower() and "frequency" not in s.entity_id.lower()
        ]
        assert float(flow_states[0].state) == 90.0


# ---------------------------------------------------------------------------
# Tests – number availability
# ---------------------------------------------------------------------------


class TestNumberAvailability:
    @pytest.mark.asyncio
    async def test_unavailable_without_data(
        self, hass: HomeAssistant, mock_setup_entry
    ):
        """Number should become unavailable when device data is missing."""
        coordinator = mock_setup_entry["coordinator"]

        coordinator.device_data = {}
        coordinator.async_set_updated_data({})
        await hass.async_block_till_done()

        states = hass.states.async_all("number")
        for state in states:
            assert state.state == "unavailable"

    @pytest.mark.asyncio
    async def test_number_falls_back_to_min_value(
        self, hass: HomeAssistant, mock_setup_entry
    ):
        """When attribute value is None, number should show min value."""
        coordinator = mock_setup_entry["coordinator"]

        data_with_none = {
            MOCK_DEVICE_ID: {
                "did": MOCK_DEVICE_ID,
                "attr": {
                    **MOCK_DEVICE_DATA[MOCK_DEVICE_ID]["attr"],
                    "Flow": None,
                },
            }
        }
        coordinator.device_data = data_with_none
        coordinator.async_set_updated_data(data_with_none)
        await hass.async_block_till_done()

        flow_states = [
            s for s in hass.states.async_all("number")
            if "flow" in s.entity_id.lower() and "frequency" not in s.entity_id.lower()
        ]
        # Should fall back to min value (30)
        assert float(flow_states[0].state) == 30.0
