"""Select platform for Jebao Aqua integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, LOGGER
from .helpers import (
    get_device_info,
    create_unique_id,
    is_device_data_valid,
    get_attribute_value,
)


class JebaoPumpSelect(CoordinatorEntity, SelectEntity):
    """Representation of a Jebao Pump Select Entity.
    
    Select entities allow choosing from predefined options like
    operating modes, schedules, wave patterns, etc.
    """

    _attr_has_entity_name = True

    def __init__(self, coordinator, device: dict[str, Any], attribute: dict[str, Any]) -> None:
        """Initialize the select entity.
        
        Args:
            coordinator: Data update coordinator
            device: Device configuration dictionary
            attribute: Attribute configuration from device model
        """
        super().__init__(coordinator)
        self._device = device
        self._attribute = attribute
        device_id = device.get("did")

        # Use helper functions for consistent entity properties
        self._attr_name = attribute["display_name"]
        self._attr_unique_id = create_unique_id(device_id, attribute["name"])
        self._attr_translation_key = attribute["name"].lower()

        # Mapping the enum values to their descriptions
        self._option_mapping = dict(zip(attribute["desc"], attribute["enum"]))
        self._attr_options = list(self._option_mapping.keys())

    @property
    def available(self) -> bool:
        """Return if entity is available.
        
        Returns:
            True if device data is valid and entity can be controlled
        """
        device_data = self.coordinator.device_data.get(self._device["did"])
        return is_device_data_valid(device_data)

    @property
    def current_option(self) -> str | None:
        """Return the current selected option.
        
        Returns:
            Human-readable option string or None if not set
        """
        device_data = self.coordinator.device_data.get(self._device["did"])
        current_value = get_attribute_value(device_data, self._attribute["name"])
        return next(
            (
                desc
                for desc, value in self._option_mapping.items()
                if value == current_value
            ),
            None,
        )

    async def async_select_option(self, option: str) -> None:
        """Change the selected option.
        
        Args:
            option: Human-readable option to select
        """
        # Convert the English description back to the enum value for the API call
        enum_value = self._option_mapping.get(option)
        await self.coordinator.api.control_device(
            self._device["did"], {self._attribute["name"]: enum_value}
        )
        await self.coordinator.async_request_refresh()

    @property
    def device_info(self):
        """Return information about the device this entity belongs to."""
        return get_device_info(self._device)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Jebao Pump select entities.
    
    Args:
        hass: Home Assistant instance
        entry: Config entry
        async_add_entities: Callback to add entities
    """
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    attribute_models = hass.data[DOMAIN][entry.entry_id]["attribute_models"]

    selects: list[JebaoPumpSelect] = []
    for device in coordinator.device_inventory:
        product_key = device.get("product_key")
        model = attribute_models.get(product_key)

        if model:
            for attr in model["attrs"]:
                if attr["type"] == "status_writable" and attr["data_type"] == "enum":
                    selects.append(JebaoPumpSelect(coordinator, device, attr))
        else:
            LOGGER.warning(
                "No model found for device %s with product_key %s",
                device.get("did"),
                product_key,
            )

    async_add_entities(selects)
