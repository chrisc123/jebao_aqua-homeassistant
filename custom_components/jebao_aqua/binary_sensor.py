"""Platform for binary sensor entities for Jebao Aqua integration."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity import JebaoEntity
from .gizwits_lan.device_status import DeviceStatus
from .hub import JebaoDevice

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up binary sensor entities for a given config entry."""
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
        allowed_binary_sensor_attrs = set()
        if device_cfg and "platforms" in device_cfg:
            allowed_binary_sensor_attrs = set(
                device_cfg["platforms"].get("binary_sensor", [])
            )

        # Create entities for each device's attributes
        for attr_def in device.giz_device.all_attrs:
            attr_name = attr_def["name"]
            if attr_name not in allowed_binary_sensor_attrs:
                continue
            if attr_def.get("type") != "fault":
                continue
            if attr_def.get("data_type") != "bool":
                continue

            entities.append(JebaoFaultSensorEntity(entry, device, attr_def))

    if entities:
        async_add_entities(entities)


class JebaoFaultSensorEntity(JebaoEntity, BinarySensorEntity):
    """A binary sensor for fault bool attributes."""

    def __init__(
        self, entry: ConfigEntry, device: JebaoDevice, attr_def: dict[str, Any]
    ) -> None:
        """Initialize the fault binary sensor entity."""
        self.entity_description = BinarySensorEntityDescription(
            key=attr_def["name"].lower(),
            name=attr_def.get("name"),
        )

        super().__init__(entry, device, attr_def, "binary_sensor")
        self._is_on = None

    @property
    def is_on(self) -> bool:
        """Return True if fault is present."""
        return self._is_on

    @property
    def device_class(self):
        """Return the class of this device."""
        return BinarySensorDeviceClass.PROBLEM

    async def async_added_to_hass(self) -> None:
        """Register callback when entity is added."""
        await super().async_added_to_hass()  # Call parent to handle connection state
        self._device.register_status_callback(self._update_state_from_device)

    async def async_will_remove_from_hass(self) -> None:
        """Unregister callbacks."""
        await (
            super().async_will_remove_from_hass()
        )  # Call parent to handle connection state
        self._device.remove_status_callback(self._update_state_from_device)

    @callback
    def _update_state_from_device(self, status: DeviceStatus) -> None:
        if self._attribute_name not in status.data:
            return
        val = status.data[self._attribute_name]
        self._is_on = bool(val)
        self.async_write_ha_state()
