"""Platform for select entities for Jebao Aqua integration."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import ENUM_OPTION_SLUGS
from .entity import JebaoEntity
from .gizwits_lan.device_status import DeviceStatus
from .hub import JebaoDevice
from .select_mapping import SelectValueMap

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
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

        # Most selects are native Gizwits enums. Some devices expose mode-like
        # values as uint8; select_value_maps represents those as HA selects.
        device_cfg = device.device_config
        allowed_select_attrs: set[str] = set()
        select_value_maps: dict[str, Any] = {}
        if device_cfg and "platforms" in device_cfg:
            platforms = device_cfg["platforms"]
            allowed_select_attrs = set(platforms.get("select", []))
            raw_value_maps = platforms.get("select_value_maps", {})
            if isinstance(raw_value_maps, dict):
                select_value_maps = raw_value_maps
            else:
                _LOGGER.warning(
                    "Invalid select_value_maps config for device %s",
                    device.product_key,
                )

        # Create entities for each device's attributes
        for attr_def in device.giz_device.all_attrs:
            attr_name = attr_def["name"]
            if attr_name not in allowed_select_attrs:
                continue
            if attr_def.get("data_type") == "enum":
                if not attr_def.get("enum"):
                    _LOGGER.debug(
                        "Enum attribute %s has no enum list, skipping", attr_name
                    )
                    continue
                entities.append(JebaoSelectEntity(entry, device, attr_def))
                continue

            if (
                attr_def.get("data_type") == "uint8"
                and attr_def.get("type") == "status_writable"
                and attr_name in select_value_maps
            ):
                try:
                    value_map = SelectValueMap.from_config(
                        select_value_maps[attr_name]
                    )
                except ValueError as err:
                    _LOGGER.warning(
                        "Invalid select value map for %s: %s", attr_name, err
                    )
                    continue
                entities.append(
                    JebaoSelectEntity(entry, device, attr_def, value_map=value_map)
                )
                continue

            _LOGGER.debug(
                "Select attribute %s has unsupported data type %s, skipping",
                attr_name,
                attr_def.get("data_type"),
            )

    if entities:
        async_add_entities(entities)


class JebaoSelectEntity(JebaoEntity, SelectEntity):
    """A select entity for an enum or configured numeric value map."""

    def __init__(
        self,
        entry: ConfigEntry,
        device: JebaoDevice,
        attr_def: dict[str, Any],
        value_map: SelectValueMap | None = None,
    ) -> None:
        """Initialize the select entity."""
        # Create the select specific entity description first
        self.entity_description = SelectEntityDescription(
            key=attr_def["name"],
            name=attr_def.get("name"),
        )

        super().__init__(entry, device, attr_def, "select")

        # Native enums are addressed by their integer index. Configured uint8
        # selects use their explicit integer-to-option mapping instead.
        self._value_map = value_map or SelectValueMap.from_enum(
            attr_def["enum"], ENUM_OPTION_SLUGS
        )
        self._attr_options = self._value_map.options
        self._current_option: str | None = None

    @property
    def current_option(self) -> str | None:
        """Return the current selected option."""
        return self._current_option

    async def async_select_option(self, option: str) -> None:
        """User selected a new option from the dropdown."""
        value = self._value_map.value_for_option(option)
        if value is None:
            _LOGGER.warning(
                "Option '%s' not in valid list %s", option, self._attr_options
            )
            return
        await self._device.async_set_attribute(self._attribute_name, value)

    async def async_added_to_hass(self) -> None:
        """Register callback."""
        await super().async_added_to_hass()  # Call parent to handle connection state
        self._device.register_status_callback(self._update_state_from_device)

    async def async_will_remove_from_hass(self) -> None:
        await (
            super().async_will_remove_from_hass()
        )  # Call parent to handle connection state
        self._device.remove_status_callback(self._update_state_from_device)

    @callback
    def _update_state_from_device(self, status: DeviceStatus) -> None:
        """Update state from device status.

        The LAN protocol reports enums as integer indexes; the cloud API
        reports the native enum value string. Accept either.
        """
        if self._attribute_name not in status.data:
            return

        self._current_option = self._value_map.option_for_value(
            status.data[self._attribute_name]
        )
        self.async_write_ha_state()
