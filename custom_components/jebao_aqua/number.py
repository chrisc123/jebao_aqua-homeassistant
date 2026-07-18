"""Platform for number entities for Jebao Aqua integration."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.number import NumberEntity, NumberEntityDescription
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
    """Set up number entities for a given config entry."""
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
        allowed_number_attrs = set()
        if device_cfg and "platforms" in device_cfg:
            allowed_number_attrs = set(device_cfg["platforms"].get("number", []))

        # Create entities for each device's attributes
        for attr_def in device.giz_device.all_attrs:
            attr_name = attr_def["name"]
            if attr_name not in allowed_number_attrs:
                continue
            if attr_def.get("type") != "status_writable":
                continue
            if attr_def.get("data_type") != "uint8":
                continue

            entities.append(JebaoNumberEntity(entry, device, attr_def))

    if entities:
        async_add_entities(entities)


class JebaoNumberEntity(JebaoEntity, NumberEntity):
    """A number entity for a writable uint8 attribute."""

    def __init__(
        self, entry: ConfigEntry, device: JebaoDevice, attr_def: dict[str, Any]
    ) -> None:
        """Initialize the number entity."""
        uint_spec = attr_def.get("uint_spec") or {}

        # Create the number specific entity description
        self.entity_description = NumberEntityDescription(
            key=attr_def["name"].lower(),
            name=attr_def.get("name"),
            native_min_value=uint_spec.get("min", 0),
            native_max_value=uint_spec.get("max", 255),
            native_step=1 / uint_spec.get("ratio", 1) if uint_spec.get("ratio") else 1,
        )

        super().__init__(entry, device, attr_def, "number")

        self._current_value: float | None = None

    @property
    def native_value(self) -> float | None:
        """Return the current value."""
        return self._current_value

    async def async_set_native_value(self, value: float) -> None:
        """Set new value."""
        # Clamp within allowed range
        int_value = int(max(min(value, self.native_max_value), self.native_min_value))
        await self._device.async_set_attribute(self._attribute_name, int_value)

    async def async_added_to_hass(self) -> None:
        await (
            super().async_added_to_hass()
        )  # Call parent to handle connection state callback
        """Register callback."""
        self._device.register_status_callback(self._update_state_from_device)

    async def async_will_remove_from_hass(self) -> None:
        """Unregister callback."""
        await (
            super().async_will_remove_from_hass()
        )  # Call parent to handle connection state
        self._device.remove_status_callback(self._update_state_from_device)

    @callback
    def _update_state_from_device(self, status: DeviceStatus) -> None:
        if self._attribute_name not in status.data:
            return
        self._current_value = float(status.data[self._attribute_name])
        self.async_write_ha_state()
