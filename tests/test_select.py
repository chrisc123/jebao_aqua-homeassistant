"""L3 tests for Jebao Aqua select platform entities."""

import pytest
from unittest.mock import AsyncMock

from homeassistant.core import HomeAssistant

from custom_components.jebao_aqua.const import DOMAIN

from .conftest import MOCK_DEVICE_ID, MOCK_DEVICE_DATA


# ---------------------------------------------------------------------------
# Tests – select entity creation
# ---------------------------------------------------------------------------


class TestSelectSetup:
    @pytest.mark.asyncio
    async def test_select_entities_created(
        self, hass: HomeAssistant, mock_setup_entry
    ):
        """Select entities should be created for enum status_writable attrs."""
        states = hass.states.async_all("select")
        entity_ids = [s.entity_id for s in states]

        # We have Mode enum in the mock model
        assert len(states) >= 1
        assert any("mode" in eid.lower() for eid in entity_ids)

    @pytest.mark.asyncio
    async def test_select_initial_state(
        self, hass: HomeAssistant, mock_setup_entry
    ):
        """Select should reflect the current device attribute value."""
        mode_states = [
            s for s in hass.states.async_all("select")
            if "mode" in s.entity_id.lower()
        ]
        assert len(mode_states) == 1
        # "经典造浪" maps to "Classic Wave" in desc
        assert mode_states[0].state == "Classic Wave"

    @pytest.mark.asyncio
    async def test_select_options(
        self, hass: HomeAssistant, mock_setup_entry
    ):
        """Select should expose the English descriptions as options."""
        mode_states = [
            s for s in hass.states.async_all("select")
            if "mode" in s.entity_id.lower()
        ]
        assert len(mode_states) == 1
        options = mode_states[0].attributes.get("options", [])
        assert "Classic Wave" in options
        assert "Sine Wave" in options
        assert "Random Wave" in options
        assert "Constant Current Wave" in options


# ---------------------------------------------------------------------------
# Tests – select control
# ---------------------------------------------------------------------------


class TestSelectControl:
    @pytest.mark.asyncio
    async def test_select_option(self, hass: HomeAssistant, mock_setup_entry):
        """Selecting an option should call control_device with the enum value."""
        api = mock_setup_entry["api"]

        mode_states = [
            s for s in hass.states.async_all("select")
            if "mode" in s.entity_id.lower()
        ]
        entity_id = mode_states[0].entity_id

        await hass.services.async_call(
            "select",
            "select_option",
            {"entity_id": entity_id, "option": "Sine Wave"},
            blocking=True,
        )

        # "Sine Wave" maps to "正弦造浪"
        api.control_device.assert_awaited_with(
            MOCK_DEVICE_ID, {"Mode": "正弦造浪"}
        )


# ---------------------------------------------------------------------------
# Tests – select state changes
# ---------------------------------------------------------------------------


class TestSelectStateChanges:
    @pytest.mark.asyncio
    async def test_select_updates_on_coordinator_refresh(
        self, hass: HomeAssistant, mock_setup_entry
    ):
        """Select state should update when coordinator data changes."""
        coordinator = mock_setup_entry["coordinator"]

        new_data = {
            MOCK_DEVICE_ID: {
                "did": MOCK_DEVICE_ID,
                "attr": {
                    **MOCK_DEVICE_DATA[MOCK_DEVICE_ID]["attr"],
                    "Mode": "随机造浪",
                },
            }
        }
        coordinator.device_data = new_data
        coordinator.async_set_updated_data(new_data)
        await hass.async_block_till_done()

        mode_states = [
            s for s in hass.states.async_all("select")
            if "mode" in s.entity_id.lower()
        ]
        assert mode_states[0].state == "Random Wave"


# ---------------------------------------------------------------------------
# Tests – select availability
# ---------------------------------------------------------------------------


class TestSelectAvailability:
    @pytest.mark.asyncio
    async def test_unavailable_without_data(
        self, hass: HomeAssistant, mock_setup_entry
    ):
        """Select should become unavailable when device data is missing."""
        coordinator = mock_setup_entry["coordinator"]

        coordinator.device_data = {}
        coordinator.async_set_updated_data({})
        await hass.async_block_till_done()

        states = hass.states.async_all("select")
        for state in states:
            assert state.state == "unavailable"
