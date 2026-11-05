"""Platform for button entities for Jebao Aqua integration."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity import JebaoEntity
from .hub import JebaoDevice


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up button entities for a given config entry."""
    devices: list[JebaoDevice] = entry.runtime_data  # type: ignore
    async_add_entities(
        JebaoSetClockButton(entry, device)
        for device in devices or []
        if device.program_control
    )


class JebaoSetClockButton(JebaoEntity, ButtonEntity):
    """Set the pump's clock, which its schedule runs on, to Home Assistant's time."""

    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, entry: ConfigEntry, device: JebaoDevice) -> None:
        """Initialize the button."""
        super().__init__(entry, device, {"name": "set_clock"}, "button")

    async def async_press(self) -> None:
        """Set the clock."""
        await self._device.async_sync_clock()
