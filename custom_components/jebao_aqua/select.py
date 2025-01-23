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


class JebaoPumpSelect(CoordinatorEntity, SelectEntity):
    """Representation of a Jebao Pump Select Entity."""

    def __init__(self, coordinator, device, attribute):
        super().__init__(coordinator)
        self._device = device
        self._attribute = attribute
        device_id = device.get("did")
        device_name = device.get("dev_alias") or device.get("did")

        # Use helper functions for consistent entity properties
        self._attr_name = create_entity_name(device_name, attribute["display_name"])
        self._attr_unique_id = create_unique_id(device_id, attribute["name"])
        self.entity_id = create_entity_id("select", device_name, attribute["name"])

        # Mapping the enum values to their descriptions
        self._option_mapping = dict(zip(attribute["desc"], attribute["enum"]))
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
        await self.coordinator.api.control_device(
            self._device["did"], {self._attribute["name"]: enum_value}
        )
        await self.coordinator.async_request_refresh()

    @property
    def options(self):
        """Return a set of selectable options."""
        return self._options

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
                    selects.append(JebaoPumpSelect(coordinator, device, attr))

    async_add_entities(selects)
