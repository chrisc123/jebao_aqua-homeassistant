"""Binary sensor platform for Jebao Aqua integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, LOGGER
from .helpers import (
    get_device_info,
    create_unique_id,
    is_device_data_valid,
    get_attribute_value,
)


class JebaoPumpSensor(CoordinatorEntity, BinarySensorEntity):
    """Representation of a Jebao Pump Fault Sensor.
    
    Binary sensors are used to indicate fault conditions on the pump.
    """

    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_has_entity_name = True

    def __init__(self, coordinator, device: dict[str, Any], attribute: dict[str, Any]) -> None:
        """Initialize the binary sensor.
        
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

    @property
    def is_on(self) -> bool:
        """Return True if the binary sensor is on (fault detected).
        
        Returns:
            True if fault is active, False otherwise
        """
        device_data = self.coordinator.device_data.get(self._device["did"])
        return get_attribute_value(device_data, self._attribute["name"]) or False

    @property
    def device_info(self):
        """Return information about the device this entity belongs to."""
        return get_device_info(self._device)

    @property
    def available(self) -> bool:
        """Return if entity is available.
        
        Returns:
            True if device data is valid and entity can be controlled
        """
        device_data = self.coordinator.device_data.get(self._device["did"])
        return is_device_data_valid(device_data)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Jebao Pump binary sensor entities.
    
    Args:
        hass: Home Assistant instance
        entry: Config entry
        async_add_entities: Callback to add entities
    """
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    attribute_models = hass.data[DOMAIN][entry.entry_id]["attribute_models"]

    sensors: list[JebaoPumpSensor] = []
    for device in coordinator.device_inventory:
        product_key = device.get("product_key")
        model = attribute_models.get(product_key)

        if model:
            for attr in model["attrs"]:
                if attr["type"] == "fault" and attr["data_type"] == "bool":
                    sensors.append(JebaoPumpSensor(coordinator, device, attr))
        else:
            LOGGER.warning(
                "No model found for device %s with product_key %s",
                device.get("did"),
                product_key,
            )

    async_add_entities(sensors)
