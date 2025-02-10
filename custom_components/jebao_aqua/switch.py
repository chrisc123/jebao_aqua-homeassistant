from homeassistant.components.switch import SwitchEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from .const import DOMAIN, LOGGER
from .helpers import (
    get_device_info,
    create_entity_name,
    create_entity_id,
    create_unique_id,
    get_attribute_value,
)
import asyncio


class JebaoPumpSwitch(CoordinatorEntity, SwitchEntity):
    """Representation of a Jebao Pump Switch."""

    def __init__(self, coordinator, device, attribute):
        super().__init__(coordinator)
        self._device = device
        self._attribute = attribute
        device_id = device.get("did")
        device_name = device.get("dev_alias") or device.get("did")

        # Use helper functions for consistent entity properties
        self._attr_name = create_entity_name(device_name, attribute["display_name"])
        self._attr_unique_id = create_unique_id(device_id, attribute["name"])
        self.entity_id = create_entity_id("switch", device_name, attribute["name"])

    @property
    def available(self) -> bool:
        """Return if entity is available based on actual device communication."""
        return self.coordinator.is_device_available(self._device["did"])

    @property
    def is_on(self) -> bool:
        """Return the on/off state of the switch."""
        device_data = self.coordinator.device_data.get(self._device["did"])
        return get_attribute_value(device_data, self._attribute["name"]) or False

    async def async_turn_on(self, **kwargs):
        """Turn the switch on."""
        await self.coordinator.api.control_device(
            self._device["did"], {self._attribute["name"]: True}
        )
        await asyncio.sleep(3)  # Wait for 3 seconds
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs):
        """Turn the switch off."""
        await self.coordinator.api.control_device(
            self._device["did"], {self._attribute["name"]: False}
        )
        await asyncio.sleep(3)  # Wait for 3 seconds
        await self.coordinator.async_request_refresh()

    @property
    def device_info(self):
        """Return information about the device this entity belongs to."""
        return get_device_info(self._device)

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
    """Set up the Jebao Pump switch entities."""
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    attribute_models = hass.data[DOMAIN][entry.entry_id]["attribute_models"]

    switches = []
    for device in coordinator.device_inventory:  # Use device_inventory for the setup
        LOGGER.debug("Device structure: %s", device)
        product_key = device.get("product_key")
        model = attribute_models.get(product_key)

        if model:
            for attr in model["attrs"]:
                if attr["type"] == "status_writable" and attr["data_type"] == "bool":
                    switches.append(JebaoPumpSwitch(coordinator, device, attr))

    async_add_entities(switches)
