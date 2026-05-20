from homeassistant.components.number import NumberEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from .const import DOMAIN, LOGGER
from .helpers import (
    get_device_info,
    create_entity_name,
    create_entity_id,
    create_unique_id,
    is_device_data_valid,
    get_attribute_value,
    parse_channel_names,
    get_channel_name_from_attribute,
)
import asyncio


class JebaoPumpNumber(CoordinatorEntity, NumberEntity):
    """Representation of a Jebao Pump Number Entity."""

    def __init__(self, coordinator, device, attribute, attribute_models, custom_name=None):
        super().__init__(coordinator)
        self._device = device
        self._attribute = attribute
        self._attribute_models = attribute_models
        device_id = device.get("did")
        device_name = device.get("dev_alias") or device.get("did")

        display_name = custom_name if custom_name else attribute["display_name"]

        # Use helper functions for consistent entity properties
        self._attr_name = create_entity_name(device_name, display_name)
        self._attr_unique_id = create_unique_id(device_id, attribute["name"])
        self.entity_id = create_entity_id("number", device_name, attribute["name"])

        # Set native min, max, step, and unit from the attribute's specification
        self._attr_native_min_value = attribute.get("min", 0)
        self._attr_native_max_value = attribute.get("max", 100)
        self._attr_native_step = attribute.get("step", 1)  # Default step to 1 if not specified
        # Set the unit of measurement if applicable
        self._attr_native_unit_of_measurement = attribute.get("unit")

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        device_data = self.coordinator.device_data.get(self._device["did"])
        return is_device_data_valid(device_data)

    @property
    def native_value(self):
        """Return the current value."""
        device_data = self.coordinator.device_data.get(self._device["did"])
        value = get_attribute_value(device_data, self._attribute["name"])
        return value if value is not None else self._attr_native_min_value

    async def async_set_native_value(self, value: float):
        """Set new value."""
        LOGGER.debug(f"Sending set_native_value command for {self._attr_name}: {value}")
        await self.coordinator.api.control_device(
            self._device["did"], {self._attribute["name"]: value}
        )
        
        # Initial wait for device to process command
        await asyncio.sleep(5)
        
        # Poll with retries to verify state change
        for attempt in range(3):
            await self.coordinator.async_request_refresh()
            device_data = self.coordinator.device_data.get(self._device["did"])
            current_value = get_attribute_value(device_data, self._attribute["name"])
            
            LOGGER.debug(
                f"Polling attempt {attempt + 1} for {self._attr_name}: current_value={current_value}, expected={value}"
            )
            
            if current_value == value:
                LOGGER.info(f"Number {self._attr_name} state verified as {value} after {attempt + 1} attempts")
                return
            
            if attempt < 2:  # Don't sleep after last attempt
                await asyncio.sleep(2)
        
        LOGGER.warning(
            f"Number {self._attr_name} state did not update to {value} after 3 polling attempts"
        )

    @property
    def device_info(self):
        """Return information about the device this entity belongs to."""
        return get_device_info(self._device, self._attribute_models)

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
    """Set up Jebao Pump number entities."""
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    attribute_models = hass.data[DOMAIN][entry.entry_id]["attribute_models"]

    numbers = []
    for device in coordinator.device_inventory:
        LOGGER.debug("Device structure: %s", device)
        product_key = device.get("product_key")
        model = attribute_models.get(product_key)

        # Parse custom channel names for this device
        channel_names = parse_channel_names(device)

        if model:
            for attr in model["attrs"]:
                if attr["type"] == "status_writable" and attr["data_type"] == "uint8":
                    custom_name = None
                    if attr["name"].startswith("IntervalT"):
                        channel_name = get_channel_name_from_attribute(attr["name"], channel_names)
                        if channel_name:
                            custom_name = f"{channel_name} Interval"
                    numbers.append(JebaoPumpNumber(coordinator, device, attr, attribute_models, custom_name))

    async_add_entities(numbers)
