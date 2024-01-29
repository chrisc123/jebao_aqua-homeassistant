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

        # Use device alias if available, otherwise device ID
        device_name = device.get('dev_alias') or device.get('did')
        device_name_underscore = device_name.replace(" ", "_").lower()  # Replace spaces with underscores and make lowercase

        attribute_name = attribute['name'].replace(" ", "_").lower()  # Replace spaces with underscores and make lowercase

        # Set entity's default display name to include device name
        self._attr_name = f"{device_name} {attribute['display_name']}"

        # Construct a unique ID for the entity
        self._attr_unique_id = f"{device_id}_{attribute_name}"

        # Set a unique entity ID
        self.entity_id = f"switch.{device_name_underscore}_{attribute_name}"

    @property
    def is_on(self) -> bool:
        """Return the on/off state of the switch."""
        # Fetch the device data using DID from the coordinator's device data
        device_data = self.coordinator.device_data.get(self._device['did'], {})
        return device_data.get('attr', {}).get(self._attribute['name'], False)

    async def async_turn_on(self, **kwargs):
        """Turn the switch on."""
        await self.coordinator.api.control_device(self._device['did'], {self._attribute['name']: True})
        await asyncio.sleep(3)  # Wait for 3 seconds
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs):
        """Turn the switch off."""
        await self.coordinator.api.control_device(self._device['did'], {self._attribute['name']: False})
        await asyncio.sleep(3)  # Wait for 3 seconds
        await self.coordinator.async_request_refresh()

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
    """Set up the Jebao Pump switch entities."""
    coordinator = hass.data[DOMAIN][entry.entry_id]['coordinator']
    attribute_models = hass.data[DOMAIN][entry.entry_id]['attribute_models']

    switches = []
    for device in coordinator.device_inventory:  # Use device_inventory for the setup
        LOGGER.debug("Device structure: %s", device)
        product_key = device.get('product_key')
        model = attribute_models.get(product_key)

        if model:
            for attr in model['attrs']:
                if attr['type'] == 'status_writable' and attr['data_type'] == 'bool':
                    switches.append(JebaoPumpSwitch(coordinator, device, attr))

    async_add_entities(switches)
