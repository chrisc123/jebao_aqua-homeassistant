from homeassistant.components.select import SelectEntity
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
import asyncio


class JebaoPumpSelect(CoordinatorEntity, SelectEntity):
    """Representation of a Jebao Pump Select Entity."""

    def __init__(self, coordinator, device, attribute, attribute_models):
        super().__init__(coordinator)
        self._device = device
        self._attribute = attribute
        self._attribute_models = attribute_models
        device_id = device.get("did")
        device_name = device.get("dev_alias") or device.get("did")

        # Use helper functions for consistent entity properties
        self._attr_name = create_entity_name(device_name, attribute["display_name"])
        self._attr_unique_id = create_unique_id(device_id, attribute["name"])
        self.entity_id = create_entity_id("select", device_name, attribute["name"])

        # Build option list for display. Prefer "desc" when it's a list of English labels,
        # otherwise fall back to "enum". The API always expects the integer index.
        desc = attribute.get("desc")
        enum_values = attribute.get("enum")
        if isinstance(desc, list):
            options = desc
        elif isinstance(enum_values, list):
            options = enum_values
        else:
            options = []
        self._option_mapping = {opt: idx for idx, opt in enumerate(options)}
        self._options = list(self._option_mapping.keys())

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        device_data = self.coordinator.device_data.get(self._device["did"])
        return is_device_data_valid(device_data)

    @property
    def current_option(self):
        """Return the current selected option."""
        device_data = self.coordinator.device_data.get(self._device["did"])
        current_value = get_attribute_value(device_data, self._attribute["name"])
        return next(
            (
                desc
                for desc, value in self._option_mapping.items()
                if value == current_value
            ),
            None,
        )

    async def async_select_option(self, option: str):
        """Change the selected option."""
        # Convert the English description back to the enum value for the API call
        enum_value = self._option_mapping.get(option)
        LOGGER.debug(f"Sending select_option command for {self._attr_name}: {option} (enum_value={enum_value})")
        await self.coordinator.api.control_device(
            self._device["did"], {self._attribute["name"]: enum_value}
        )
        
        # Initial wait for device to process command
        await asyncio.sleep(5)
        
        # Poll with retries to verify state change
        for attempt in range(3):
            await self.coordinator.async_request_refresh()
            device_data = self.coordinator.device_data.get(self._device["did"])
            current_value = get_attribute_value(device_data, self._attribute["name"])
            
            LOGGER.debug(
                f"Polling attempt {attempt + 1} for {self._attr_name}: current_value={current_value}, expected={enum_value}"
            )
            
            if current_value == enum_value:
                LOGGER.info(f"Select {self._attr_name} state verified as {option} after {attempt + 1} attempts")
                return
            
            if attempt < 2:  # Don't sleep after last attempt
                await asyncio.sleep(2)
        
        LOGGER.warning(
            f"Select {self._attr_name} state did not update to {option} after 3 polling attempts"
        )

    @property
    def options(self):
        """Return a set of selectable options."""
        return self._options

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
    """Set up Jebao Pump select entities."""
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    attribute_models = hass.data[DOMAIN][entry.entry_id]["attribute_models"]

    selects = []
    for device in coordinator.device_inventory:
        LOGGER.debug("Device structure: %s", device)
        product_key = device.get("product_key")
        model = attribute_models.get(product_key)

        if model:
            for attr in model["attrs"]:
                if attr["type"] == "status_writable" and attr["data_type"] == "enum":
                    selects.append(JebaoPumpSelect(coordinator, device, attr, attribute_models))

    async_add_entities(selects)
