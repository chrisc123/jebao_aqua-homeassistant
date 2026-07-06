"""Number platform for Jebao Aqua integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.number import NumberEntity
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


class JebaoPumpNumber(CoordinatorEntity, NumberEntity):
    """Representation of a Jebao Pump Number Entity.
    
    Number entities control numeric values like flow rate percentage,
    wave frequency, timer settings, etc.
    """

    _attr_has_entity_name = True

    def __init__(self, coordinator, device: dict[str, Any], attribute: dict[str, Any]) -> None:
        """Initialize the number entity.
        
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

        # Set native min, max, step, and unit from the attribute's specification
        self._attr_native_min_value = attribute["uint_spec"]["min"]
        self._attr_native_max_value = attribute["uint_spec"]["max"]
        self._attr_native_step = attribute["uint_spec"].get(
            "step", 1
        )  # Default step to 1 if not specified
        # Set the unit of measurement if applicable
        self._attr_native_unit_of_measurement = attribute.get("unit")

    @property
    def available(self) -> bool:
        """Return if entity is available.
        
        Returns:
            True if device data is valid and entity can be controlled
        """
        device_data = self.coordinator.device_data.get(self._device["did"])
        return is_device_data_valid(device_data)

    @property
    def native_value(self) -> float | None:
        """Return the current value.
        
        Returns:
            Current numeric value or minimum value if not set
        """
        device_data = self.coordinator.device_data.get(self._device["did"])
        value = get_attribute_value(device_data, self._attribute["name"])
        return value if value is not None else self._attr_native_min_value

    async def async_set_native_value(self, value: float) -> None:
        """Set new value.
        
        Args:
            value: New numeric value to set
        """
        await self.coordinator.api.control_device(
            self._device["did"], {self._attribute["name"]: value}
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
    """Set up Jebao Pump number entities.
    
    Args:
        hass: Home Assistant instance
        entry: Config entry
        async_add_entities: Callback to add entities
    """
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    attribute_models = hass.data[DOMAIN][entry.entry_id]["attribute_models"]

    numbers: list[JebaoPumpNumber] = []
    for device in coordinator.device_inventory:
        product_key = device.get("product_key")
        model = attribute_models.get(product_key)

        if model:
            for attr in model["attrs"]:
                if attr["type"] == "status_writable" and attr["data_type"] == "uint8":
                    numbers.append(JebaoPumpNumber(coordinator, device, attr))
        else:
            LOGGER.warning(
                "No model found for device %s with product_key %s",
                device.get("did"),
                product_key,
            )

    async_add_entities(numbers)
