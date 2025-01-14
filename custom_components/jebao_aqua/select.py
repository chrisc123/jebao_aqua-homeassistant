from homeassistant.components.select import SelectEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from .const import DOMAIN, LOGGER

class JebaoPumpSelect(CoordinatorEntity, SelectEntity):
    """Representation of a Jebao Pump Select Entity."""

    def __init__(self, coordinator, device, attribute):
        super().__init__(coordinator)
        self._device = device
        self._attribute = attribute
        device_id = device.get('did')
        device_name = device.get('dev_alias') or device.get('did')
        device_name_underscore = device_name.replace(" ", "_").lower()
        attribute_name = attribute['name'].replace(" ", "_").lower()
        self._attr_name = f"{device_name} {attribute['display_name']}"
        self._attr_unique_id = f"{device_id}_{attribute_name}"
        self.entity_id = f"select.{device_name_underscore}_{attribute_name}"
        self._option_mapping = dict(zip(attribute['desc'], attribute['enum']))
        self._options = list(self._option_mapping.keys())

    @property
    def current_option(self):
        """Return the currently selected option."""
        device_data = self.coordinator.device_data.get(self._device['did'])
        if device_data is None:
            LOGGER.warning("No device data available for device %s; returning default option", self._device['did'])
            return self._options[0] if self._options else None
        current_value = device_data.get('attr', {}).get(self._attribute['name'])
        LOGGER.debug("Select (%s) current value for device %s: %s", self._attribute['name'], self._device['did'], current_value)
        # Find the description corresponding to the current enum value.
        selected_option = next(
            (desc for desc, value in self._option_mapping.items() if value == current_value),
            self._options[0] if self._options else None
        )
        LOGGER.debug("Selected option for device %s: %s", self._device['did'], selected_option)
        return selected_option

    async def async_select_option(self, option: str):
        """Change the selected option."""
        enum_value = self._option_mapping.get(option)
        LOGGER.debug("Selecting option %s (enum value: %s) for device %s", option, enum_value, self._device['did'])
        await self.coordinator.api.control_device(self._device['did'], {self._attribute['name']: enum_value})
        await self.coordinator.async_request_refresh()
        LOGGER.debug("Refresh requested after selecting option.")

    @property
    def options(self):
        """Return a list of selectable options."""
        return self._options

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
    """Set up Jebao Pump select entities."""
    coordinator = hass.data[DOMAIN][entry.entry_id]['coordinator']
    attribute_models = hass.data[DOMAIN][entry.entry_id]['attribute_models']
    selects = []
    for device in coordinator.device_inventory:
        LOGGER.debug("Processing device for select: %s", device)
        product_key = device.get('product_key')
        model = attribute_models.get(product_key)
        if model:
            for attr in model['attrs']:
                if attr['type'] == 'status_writable' and attr['data_type'] == 'enum':
                    selects.append(JebaoPumpSelect(coordinator, device, attr))
    async_add_entities(selects)
