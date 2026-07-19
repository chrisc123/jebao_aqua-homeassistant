"""Base entity for Jebao Aqua integration."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import callback
from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC, DeviceInfo
from homeassistant.helpers.entity import Entity

from .const import DOMAIN
from .hub import JebaoDevice


class JebaoEntity(Entity):
    """Base entity class for Jebao devices."""

    _attr_should_poll = False
    _attr_has_entity_name = True

    def __init__(
        self,
        entry: ConfigEntry,
        device: JebaoDevice,
        attr_def: dict[str, Any],
        entity_type: str,  # e.g. "switch", "select", etc.
    ) -> None:
        """Initialize the entity."""
        self._entry = entry
        self._device = device
        self._attr_def = attr_def
        self._attribute_name = attr_def["name"]

        # Get the device's UID
        device_uid = device.uid

        # Make unique_id by combining device identifier and attribute name
        self._attr_unique_id = f"{device_uid}_{self._attribute_name}_{entity_type}"

        # Set translation key based on platform type and attribute name
        self._attr_translation_key = attr_def["name"].lower()

        # Use product key as model if available
        model = device.product_key or "Unknown Model"

        # Prefer the configured name (migrated cloud alias or manual entry);
        # otherwise create a stable name that doesn't change with IP, using a
        # UID suffix or MAC suffix for human-readable identification
        device_name = "Jebao Device"
        if device.name:
            device_name = device.name
        elif device.uid:
            # Use last 6 characters of UID for identification
            uid_suffix = device.uid[-6:] if len(device.uid) >= 6 else device.uid
            device_name = f"Jebao Device {uid_suffix}"
        elif device.mac:
            # Fallback to MAC suffix if no UID
            mac_suffix = device.mac.replace(":", "")[-6:] if device.mac else ""
            device_name = f"Jebao Device {mac_suffix}" if mac_suffix else device_name

        # Device info that will be shared between all entities for this device
        device_info = {
            "identifiers": {(DOMAIN, device_uid)},
            "name": device_name,
            "manufacturer": "Jebao",
            "model": model,
        }

        # Add MAC address if available
        if device.mac:
            device_info["connections"] = {(CONNECTION_NETWORK_MAC, device.mac)}

        # Add firmware version if available
        if device.firmware_version:
            device_info["sw_version"] = device.firmware_version

        self._attr_device_info = DeviceInfo(**device_info)

        self._attr_available = False

    async def async_added_to_hass(self) -> None:
        """Register callbacks when entity is added."""
        self._device.register_connection_callback(self._handle_connection_state)

    async def async_will_remove_from_hass(self) -> None:
        """Unregister callbacks when entity is removed."""
        self._device.remove_connection_callback(self._handle_connection_state)

    @callback
    def _handle_connection_state(self, connected: bool) -> None:
        """Update availability when connection state changes."""
        self._attr_available = connected
        self.async_write_ha_state()
