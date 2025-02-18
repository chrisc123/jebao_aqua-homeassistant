"""The Jebao Aqua integration."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import DOMAIN, PLATFORMS
from .hub import JebaoDevice, _load_device_configs

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up a config entry."""
    await _load_device_configs()

    # Create device instances for all devices in this entry
    devices = []
    for device_data in entry.data["devices"]:
        device = JebaoDevice(
            hass=hass,
            ip=device_data["ip"],
            product_key=device_data.get("product_key", ""),
            uid=device_data.get("uid"),  # Pass the UID from discovery
            mac=device_data.get("mac"),
            firmware_version=device_data.get("firmware_version"),
        )

        try:
            await device.async_connect()
            devices.append(device)
        except Exception as exc:
            _LOGGER.error(
                "Failed to connect to Jebao device at %s: %s", device_data["ip"], exc
            )
            # Continue with other devices even if one fails

    if not devices:
        return False

    # Store all devices in runtime_data
    entry.runtime_data = devices  # type: ignore

    # Set up all platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Request initial status from all devices
    for device in devices:
        try:
            await device.giz_device.request_status_update()
        except Exception as exc:
            _LOGGER.error(
                "Failed to get initial status from device at %s: %s", device.ip, exc
            )

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        devices: list[JebaoDevice] = entry.runtime_data  # type: ignore
        for device in devices:
            await device.async_disconnect()
        entry.runtime_data = None

    return unload_ok
