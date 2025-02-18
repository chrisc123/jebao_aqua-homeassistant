"""Platform for select entities for Jebao Aqua integration."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.select import (
    SelectEntity,
    SelectEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .gizwits_lan.device_status import DeviceStatus

from .hub import JebaoDevice
from .const import DOMAIN
from .entity import JebaoEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback
) -> None:
    """Set up select entities for a given config entry."""
    devices: list[JebaoDevice] = entry.runtime_data  # type: ignore
    if not devices:
        _LOGGER.warning("No Jebao devices found for entry %s", entry.title)
        return

    entities = []
    for device in devices:
        if not device.giz_device:
            continue

        # Get device config and allowed attributes
        device_cfg = device.device_config
        allowed_select_attrs = set()
        if device_cfg and "platforms" in device_cfg:
            allowed_select_attrs = set(device_cfg["platforms"].get("select", []))

        # Create entities for each device's attributes
        for attr_def in device.giz_device.all_attrs:
            attr_name = attr_def["name"]
            if attr_name not in allowed_select_attrs:
                continue
            if attr_def.get("data_type") != "enum":
                continue
            if not attr_def.get("enum"):
                _LOGGER.debug("Enum attribute %s has no enum list, skipping", attr_name)
                continue

            entities.append(JebaoSelectEntity(entry, device, attr_def))

    if entities:
        async_add_entities(entities)


class JebaoSelectEntity(JebaoEntity, SelectEntity):
    """A select entity for a writable enum attribute."""

    def __init__(self, entry: ConfigEntry, device: JebaoDevice, attr_def: dict[str, Any]) -> None:
        """Initialize the select entity."""
        # Create the select specific entity description first
        self.entity_description = SelectEntityDescription(
            key=attr_def["name"],
            name=attr_def.get("name"),
        )

        super().__init__(entry, device, attr_def, "select")

        # Get enum options - these will be translated at runtime
        self._options = attr_def["enum"]
        self._current_option: str | None = None

    @property
    def options(self) -> list[str]:
        """Return the list of selectable options (strings)."""
        return self._options

    @property
    def current_option(self) -> str | None:
        """Return the current selected option."""
        return self._current_option

    async def async_select_option(self, option: str) -> None:
        """User selected a new option from the dropdown."""
        if option not in self._options:
            _LOGGER.warning("Option '%s' not in valid list %s", option, self._options)
            return
        # Map to integer index
        index_val = self._options.index(option)
        await self._device.async_set_attribute(self._attribute_name, index_val)

    async def async_added_to_hass(self) -> None:
        """Register callback."""
        await super().async_added_to_hass()  # Call parent to handle connection state
        self._device.register_status_callback(self._update_state_from_device)

    async def async_will_remove_from_hass(self) -> None:
        await super().async_will_remove_from_hass()  # Call parent to handle connection state
        self._device.remove_status_callback(self._update_state_from_device)

    @callback
    def _update_state_from_device(self, status: DeviceStatus) -> None:
        """Update state from device status."""
        if self._attribute_name not in status.data:
            return
            
        try:
            int_val = int(status.data[self._attribute_name])
            self._current_option = self._options[int_val] if 0 <= int_val < len(self._options) else None
        except (TypeError, ValueError, IndexError):
            self._current_option = None
            
        self.async_write_ha_state()
