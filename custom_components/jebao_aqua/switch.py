"""Platform for switch entities for Jebao Aqua integration."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.switch import (
    SwitchEntity,
    SwitchEntityDescription,
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
    """Set up switch entities for a given config entry."""
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
        allowed_switch_attrs = set()
        if device_cfg and "platforms" in device_cfg:
            allowed_switch_attrs = set(device_cfg["platforms"].get("switch", []))

        # Create entities for each device's attributes
        for attr_def in device.giz_device.all_attrs:
            attr_name = attr_def["name"]
            if attr_name not in allowed_switch_attrs:
                continue
            if attr_def.get("type") != "status_writable":
                continue
            if attr_def.get("data_type") != "bool":
                continue
            
            entities.append(JebaoSwitchEntity(entry, device, attr_def))

    if entities:
        async_add_entities(entities)


class JebaoSwitchEntity(JebaoEntity, SwitchEntity):
    """A switch entity for a writable bool attribute."""

    def __init__(self, entry: ConfigEntry, device: JebaoDevice, attr_def: dict[str, Any]) -> None:
        """Initialize the switch entity."""
        # Create the switch specific entity description first
        # We will fall back to this (the gizwits datapoint attribute name, which is always in English?) if no translation key is matched
        self.entity_description = SwitchEntityDescription(
            key=attr_def["name"].lower(),
            name=attr_def.get("name"),
        )

        super().__init__(entry, device, attr_def, "switch")
        self._is_on = False

    @property
    def is_on(self) -> bool:
        return self._is_on

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._device.async_set_attribute(self._attribute_name, True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._device.async_set_attribute(self._attribute_name, False)

    async def async_added_to_hass(self) -> None:
        """Register callback when entity is added."""
        await super().async_added_to_hass()  # Call parent to handle connection state
        self._device.register_status_callback(self._update_state_from_device)

    async def async_will_remove_from_hass(self) -> None:
        """Unregister callback when entity is removed."""
        await super().async_will_remove_from_hass()  # Call parent to handle connection state
        self._device.remove_status_callback(self._update_state_from_device)

    @callback
    def _update_state_from_device(self, status: DeviceStatus) -> None:
        """Push update from device status callback."""
        if self._attribute_name not in status.data:
            return  # attribute not in this status update
        val = status.data[self._attribute_name]
        self._is_on = bool(val)
        self.async_write_ha_state()
