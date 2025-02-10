from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from .const import DOMAIN, LOGGER
from .helpers import (
    get_device_info,
    create_entity_name,
    create_entity_id,
    create_unique_id,
    is_device_data_valid,
    get_attribute_value,
)


class JebaoPumpSensor(CoordinatorEntity, BinarySensorEntity):
    """Representation of a Jebao Pump Sensor."""

    def __init__(self, coordinator, device, attribute):
        super().__init__(coordinator)
        self._device = device
        self._attribute = attribute
        device_id = device.get("did")
        device_name = device.get("dev_alias") or device.get("did")

        # Use helper functions for consistent entity properties
        self._attr_name = create_entity_name(device_name, attribute["display_name"])
        self._attr_unique_id = create_unique_id(device_id, attribute["name"])
        self.entity_id = create_entity_id(
            "binary_sensor", device_name, attribute["name"]
        )

    @property
    def device_class(self):
        """Return the class of this device."""
        return BinarySensorDeviceClass.PROBLEM

    @property
    def is_on(self):
        """Return True if the binary sensor is on."""
        device_data = self.coordinator.device_data.get(self._device["did"])
        return get_attribute_value(device_data, self._attribute["name"]) or False

    @property
    def device_info(self):
        """Return information about the device this entity belongs to."""
        return get_device_info(self._device)

    @property
    def available(self) -> bool:
        """Return if entity is available based on actual device communication."""
        return self.coordinator.is_device_available(self._device["did"])

    @property
    def name(self) -> str:
        """Return the display name of this entity."""
        return self._attr_name

    @property
    def has_entity_name(self) -> bool:
        """Indicate that we are using the device name as the entity name."""
        return True

    @property
    def translation_key(self) -> str:
        """Return the translation key to use in logbook."""
        return self._attribute["name"].lower()


async def async_setup_entry(hass, entry, async_add_entities):
    """Set up Jebao Pump sensor entities."""
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    attribute_models = hass.data[DOMAIN][entry.entry_id]["attribute_models"]

    sensors = []
    for device in coordinator.device_inventory:  # Use device_inventory for the setup
        LOGGER.debug("Device structure: %s", device)
        product_key = device.get("product_key")
        model = attribute_models.get(product_key)

        if model:
            for attr in model["attrs"]:
                if attr["type"] == "fault" and attr["data_type"] == "bool":
                    sensors.append(JebaoPumpSensor(coordinator, device, attr))

    async_add_entities(sensors)
