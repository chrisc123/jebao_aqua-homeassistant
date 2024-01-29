from homeassistant.components.binary_sensor import BinarySensorDeviceClass
from homeassistant.components.binary_sensor import BinarySensorEntity

from homeassistant.helpers.update_coordinator import CoordinatorEntity
from .const import DOMAIN, LOGGER

class JebaoPumpSensor(CoordinatorEntity, BinarySensorEntity):
    """Representation of a Jebao Pump Sensor."""

    def __init__(self, coordinator, device, attribute):
        super().__init__(coordinator)
        self._device = device
        self._attribute = attribute
        device_id = device.get('did')

        # Use device alias if available, otherwise device ID
        device_name = device.get('dev_alias') or device.get('did')
        device_name_underscore = device_name.replace(" ", "_").lower()  # Replace spaces with underscores and make lowercase

        attribute_name = attribute['name'].replace(" ", "_").lower()  # Replace spaces with underscores and make lowercase

        # Set entity's default display name to include device name
        self._attr_name = f"{device_name} {attribute['display_name']}"
        
        # Construct a unique ID for the entity
        self._attr_unique_id = f"{device_id}_{attribute_name}"

        # Set a unique entity ID
        self.entity_id = f"sensor.{device_name_underscore}_{attribute_name}"

    @property
    def device_class(self):
        """Return the class of this device."""
        return BinarySensorDeviceClass.PROBLEM

    @property
    def is_on(self):
        """Return True if the binary sensor is on."""
        device_data = self.coordinator.device_data.get(self._device['did'], {})
        return device_data.get('attr', {}).get(self._attribute['name'], False)

    @property
    def device_info(self):
        """Return information about the device this entity belongs to."""
        device_name = self._device.get('dev_alias') or f"Device {self._device['did']}"
        return {
            "identifiers": {(DOMAIN, self._device['did'])},
            "name": device_name,
            "manufacturer": "Jebao",
            # Include other relevant device info if available
        }

async def async_setup_entry(hass, entry, async_add_entities):
    """Set up Jebao Pump sensor entities."""
    coordinator = hass.data[DOMAIN][entry.entry_id]['coordinator']
    attribute_models = hass.data[DOMAIN][entry.entry_id]['attribute_models']

    sensors = []
    for device in coordinator.device_inventory:  # Use device_inventory for the setup
        LOGGER.debug("Device structure: %s", device)
        product_key = device.get('product_key')
        model = attribute_models.get(product_key)

        if model:
            for attr in model['attrs']:
                if attr['type'] == 'fault' and attr['data_type'] == 'bool':
                    sensors.append(JebaoPumpSensor(coordinator, device, attr))

    async_add_entities(sensors)