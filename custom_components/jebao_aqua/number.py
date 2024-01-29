from homeassistant.components.number import NumberEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from .const import DOMAIN, LOGGER

class JebaoPumpNumber(CoordinatorEntity, NumberEntity):
    """Representation of a Jebao Pump Number Entity."""

    def __init__(self, coordinator, device, attribute):
        super().__init__(coordinator)
        self._device = device
        self._attribute = attribute
        device_id = device.get('did')

        # Use device alias if available, otherwise device ID
        device_name = device.get('dev_alias') or device.get('did')
        device_name_underscore = device_name.replace(" ", "_").lower()  # Replace spaces with underscores and make lowercase

        attribute_name = attribute['name'].replace(" ", "_").lower()

        # Set entity's default display name to include device name
        self._attr_name = f"{device_name} {attribute['display_name']}"
        
        self._attr_unique_id = f"{device_id}_{attribute_name}"
        self.entity_id = f"number.{device_name_underscore}_{attribute_name}"

        # Set native min, max, step, and unit from the attribute's specification
        self._attr_native_min_value = attribute['uint_spec']['min']
        self._attr_native_max_value = attribute['uint_spec']['max']
        self._attr_native_step = attribute['uint_spec'].get('step', 1)  # Default step to 1 if not specified
        # Set the unit of measurement if applicable
        self._attr_native_unit_of_measurement = attribute.get('unit')

    @property
    def native_value(self):
        """Return the current value."""
        device_data = self.coordinator.device_data.get(self._device['did'], {})
        return device_data.get('attr', {}).get(self._attribute['name'])

    async def async_set_native_value(self, value: float):
        """Set new value."""
        await self.coordinator.api.control_device(self._device['did'], {self._attribute['name']: value})
        await self.coordinator.async_request_refresh()

    @property
    def device_info(self):
        """Return information about the device this entity belongs to."""
        device_name = self._device.get('dev_alias') or f"Device {self._device['did']}"
        return {
            "identifiers": {(DOMAIN, self._device['did'])},
            "name": device_name,
            "manufacturer": "Jebao",
        }

async def async_setup_entry(hass, entry, async_add_entities):
    """Set up Jebao Pump number entities."""
    coordinator = hass.data[DOMAIN][entry.entry_id]['coordinator']
    attribute_models = hass.data[DOMAIN][entry.entry_id]['attribute_models']

    numbers = []
    for device in coordinator.device_inventory:
        LOGGER.debug("Device structure: %s", device)
        product_key = device.get('product_key')
        model = attribute_models.get(product_key)

        if model:
            for attr in model['attrs']:
                if attr['type'] == 'status_writable' and attr['data_type'] == 'uint8':
                    numbers.append(JebaoPumpNumber(coordinator, device, attr))

    async_add_entities(numbers)
