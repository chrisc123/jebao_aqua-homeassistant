"""Platform for light entities for Jebao Aqua integration."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.light import ColorMode, LightEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util.color import brightness_to_value, value_to_brightness

from .entity import JebaoEntity
from .gizwits_lan.device_status import DeviceStatus
from .hub import JebaoDevice

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up light entities for a given config entry."""
    devices: list[JebaoDevice] = entry.runtime_data  # type: ignore
    if not devices:
        _LOGGER.warning("No Jebao devices found for entry %s", entry.title)
        return

    entities = []
    for device in devices:
        if not device.giz_device:
            continue

        # Only create lights if this is a light-type device
        device_cfg = device.device_config
        if not device_cfg or device_cfg.get("device_type") != "light":
            continue

        allowed_light_attrs = set()
        if "platforms" in device_cfg:
            allowed_light_attrs = set(device_cfg["platforms"].get("light", []))

        # Create entities for each device's attributes
        for attr_def in device.giz_device.all_attrs:
            attr_name = attr_def["name"]

            # If not in the device_config light list, skip
            if attr_name not in allowed_light_attrs:
                continue

            # Must be writable uint8
            if attr_def.get("type") != "status_writable":
                continue
            if attr_def.get("data_type") != "uint8":
                continue

            entities.append(JebaoLightEntity(entry, device, attr_def))

    if entities:
        async_add_entities(entities)


class JebaoLightEntity(JebaoEntity, LightEntity):
    """Representation of a light channel."""

    _attr_supported_color_modes = {ColorMode.BRIGHTNESS}
    _attr_color_mode = ColorMode.BRIGHTNESS

    def __init__(
        self, entry: ConfigEntry, device: JebaoDevice, attr_def: dict[str, Any]
    ) -> None:
        """Initialize the light entity."""
        super().__init__(entry, device, attr_def, "light")
        self._brightness = None

        # Get min/max from uint_spec if available
        uint_spec = attr_def.get("uint_spec") or {}
        self._value_min = uint_spec.get("min", 0)
        self._value_max = uint_spec.get(
            "max", 100
        )  # Default to 0-100 range if not specified

    @property
    def is_on(self) -> bool:
        """Return true if light is on."""
        return self._brightness is not None and self._brightness > 0

    @property
    def brightness(self) -> int | None:
        """Return the brightness of this light between 0..255."""
        return self._brightness

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the light on."""
        brightness = kwargs.get("brightness", 255)
        # Convert HA brightness (0-255) to the device's value range
        device_value = round(
            brightness_to_value((self._value_min, self._value_max), brightness)
        )
        await self._device.async_set_attribute(self._attribute_name, device_value)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the light off."""
        await self._device.async_set_attribute(self._attribute_name, self._value_min)

    async def async_added_to_hass(self) -> None:
        """Register callback when entity is added."""
        await super().async_added_to_hass()
        self._device.register_status_callback(self._update_state_from_device)

    async def async_will_remove_from_hass(self) -> None:
        """Unregister callback when entity is removed."""
        await super().async_will_remove_from_hass()
        self._device.remove_status_callback(self._update_state_from_device)

    @callback
    def _update_state_from_device(self, status: DeviceStatus) -> None:
        """Update state from device status."""
        if self._attribute_name not in status.data:
            return
        device_value = status.data[self._attribute_name]
        # Convert the device's value range to HA brightness (0-255)
        self._brightness = value_to_brightness(
            (self._value_min, self._value_max), device_value
        )
        self.async_write_ha_state()
