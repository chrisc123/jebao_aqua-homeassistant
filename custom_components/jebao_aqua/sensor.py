"""Platform for sensor entities for Jebao Aqua integration."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.sensor import (
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util.color import value_to_brightness  # Add this import

from .gizwits_lan.device_status import DeviceStatus
from .entity import JebaoEntity
from .hub import JebaoDevice
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up sensor entities for a given config entry."""
    devices: list[JebaoDevice] = entry.runtime_data  # type: ignore
    if not devices:
        _LOGGER.warning("No Jebao devices found for entry %s", entry.title)
        return

    entities = []
    for device in devices:
        if not device.giz_device:
            continue

        # Only create level sensors if this is a light-type device
        device_cfg = device.device_config
        if not device_cfg or device_cfg.get("device_type") != "light":
            continue

        allowed_sensor_attrs = set()
        if "platforms" in device_cfg:
            allowed_sensor_attrs = set(device_cfg["platforms"].get("sensor", []))

        # Create entities for each device's attributes
        for attr_def in device.giz_device.all_attrs:
            attr_name = attr_def["name"]

            # If not in the device_config sensor list, skip
            if attr_name not in allowed_sensor_attrs:
                continue

            # Must be uint8
            if attr_def.get("data_type") != "uint8":
                continue

            entities.append(JebaoLightLevelSensor(entry, device, attr_def))

    if entities:
        async_add_entities(entities)


class JebaoLightLevelSensor(JebaoEntity, SensorEntity):
    """Sensor showing light level as 0-255."""

    def __init__(self, entry: ConfigEntry, device: JebaoDevice, attr_def: dict[str, Any]) -> None:
        """Initialize the sensor entity."""
        # Append "Level" to the name
        attr_def = dict(attr_def)
        if "name" in attr_def:
            attr_def["name"] = f"{attr_def['name']} Level"

        self.entity_description = SensorEntityDescription(
            key=f"{attr_def['name'].lower()}_level",
            name=attr_def.get("name"),
            native_unit_of_measurement=None,
            state_class=SensorStateClass.MEASUREMENT,
        )

        super().__init__(entry, device, attr_def, "sensor")
        self._value = None

        # Get min/max from uint_spec if available
        uint_spec = attr_def.get("uint_spec") or {}
        self._value_min = uint_spec.get("min", 0)
        self._value_max = uint_spec.get("max", 100)  # Default to 0-100 range if not specified

    @property
    def native_value(self) -> int | None:
        """Return the sensor value."""
        return self._value

    async def async_added_to_hass(self) -> None:
        """Register callback when entity is added."""
        await super().async_added_to_hass()
        self._device.register_status_callback(self._update_state_from_device)

    async def async_will_remove_from_hass(self) -> None:
        """Unregister callbacks when entity is removed."""
        await super().async_will_remove_from_hass()
        self._device.remove_status_callback(self._update_state_from_device)

    @callback
    def _update_state_from_device(self, status: DeviceStatus) -> None:
        """Update state from device status."""
        if self._attribute_name not in status.data:
            return
        device_value = status.data[self._attribute_name]
        # Use HA's built-in value_to_brightness like we do in light.py
        self._value = value_to_brightness(device_value, self._value_max)
        self.async_write_ha_state()
