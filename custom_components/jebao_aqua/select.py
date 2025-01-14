from homeassistant.components.switch import SwitchEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from .const import DOMAIN, LOGGER
import asyncio

class JebaoPumpSwitch(CoordinatorEntity, SwitchEntity):
    """Representation of a Jebao Pump Switch."""

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
        self.entity_id = f"switch.{device_name_underscore}_{attribute_name}"

    @property
    def is_on(self) -> bool:
        """Return the on/off state of the switch."""
        device_data = self.coordinator.device_data.get(self._device['did'])
        if device_data is None:
            LOGGER.warning("No device data available for device %s; returning False", self._device['did'])
            return False
        state = device_data.get('attr', {}).get(self._attribute['name'], False)
        LOGGER.debug("Switch (%s) state for device %s: %s", self._attribute['name'], self._device['did'], state)
        return state

    async def async_turn_on(self, **kwargs):
        """Turn the switch on."""
        LOGGER.debug("Turning ON %s for device %s", self._attribute['name'], self._device['did'])
        await self.coordinator.api.control_device(self._device['did'], {self._attribute['name']: True})
        await asyncio.sleep(3)  # Delay to allow state change to propagate.
        await self.coordinator.async_request_refresh()
        LOGGER.debug("Refresh requested after turning ON.")

    async def async_turn_off(self, **kwargs):
        """Turn the switch off."""
        LOGGER.debug("Turning OFF %s for device %s", self._attribute['name'], self._device['did'])
        await self.coordinator.api.control_device(self._device['did'], {self._attribute['name']: False})
        await asyncio.sleep(3)
        await self.coordinator.async_request_refresh()
        LOGGER.debug("Refresh requested after turning OFF.")

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
    """Set up the Jebao Pump switch entities."""
    coordinator = hass.data[DOMAIN][entry.entry_id]['coordinator']
    attribute_models = hass.data[DOMAIN][entry.entry_id]['attribute_models']
    switches = []
    for device in coordinator.device_inventory:
        LOGGER.debug("Processing device: %s", device)
        product_key = device.get('product_key')
        model = attribute_models.get(product_key)
        if model:
            for attr in model['attrs']:
                if attr['type'] == 'status_writable' and attr['data_type'] == 'bool':
                    switches.append(JebaoPumpSwitch(coordinator, device, attr))
    async_add_entities(switches)
