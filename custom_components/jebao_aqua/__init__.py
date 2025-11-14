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

    # Rediscover devices to handle IP changes
    discovered_devices = {}
    try:
        from .hub import async_discover_devices
        discovered = await async_discover_devices(hass, timeout=10.0)
        for dev in discovered:
            if dev.get("uid"):
                discovered_devices[dev["uid"]] = dev
        _LOGGER.debug("Discovered %d devices during setup", len(discovered_devices))
    except Exception as exc:
        _LOGGER.warning("Failed to perform discovery during setup: %s", exc)

    # Create device instances for all devices in this entry
    devices = []
    updated_devices = []
    devices_updated = False

    for device_data in entry.data["devices"]:
        device_uid = device_data.get("uid")
        original_ip = device_data["ip"]
        
        # Migration: if device doesn't have UID, try to find it via discovery
        if not device_uid:
            _LOGGER.info("Device at %s lacks UID, attempting to discover", original_ip)
            # Try to find this device by IP in discovered devices
            discovered_device = None
            for dev in discovered_devices.values():
                if dev["ip"] == original_ip:
                    discovered_device = dev
                    break
            
            if discovered_device and discovered_device.get("uid"):
                device_uid = discovered_device["uid"]
                _LOGGER.info(
                    "Found UID %s for device at %s during migration", 
                    device_uid, original_ip
                )
                devices_updated = True
        
        # Try to find current IP for this device
        current_ip = original_ip
        if device_uid and device_uid in discovered_devices:
            discovered_ip = discovered_devices[device_uid]["ip"]
            if discovered_ip != original_ip:
                _LOGGER.info(
                    "Device %s IP changed from %s to %s", 
                    device_uid, original_ip, discovered_ip
                )
                current_ip = discovered_ip
                devices_updated = True
                
                # Update device data for saving
                updated_device_data = device_data.copy()
                updated_device_data["ip"] = discovered_ip
                # Update other fields that might have changed
                discovered_dev = discovered_devices[device_uid]
                if discovered_dev.get("product_key"):
                    updated_device_data["product_key"] = discovered_dev["product_key"]
                if discovered_dev.get("mac"):
                    updated_device_data["mac"] = discovered_dev["mac"]
                if discovered_dev.get("firmware_version"):
                    updated_device_data["firmware_version"] = discovered_dev["firmware_version"]
                if device_uid and not device_data.get("uid"):
                    updated_device_data["uid"] = device_uid  # Add UID if missing
                updated_devices.append(updated_device_data)
            else:
                # No IP change, but maybe need to add UID
                if device_uid and not device_data.get("uid"):
                    updated_device_data = device_data.copy()
                    updated_device_data["uid"] = device_uid
                    updated_devices.append(updated_device_data)
                else:
                    updated_devices.append(device_data)
        else:
            # Device UID-based lookup failed, but maybe we added a UID during migration
            updated_device_data = device_data.copy()
            if device_uid and not device_data.get("uid"):
                updated_device_data["uid"] = device_uid
            updated_devices.append(updated_device_data)
            
            if device_uid:
                _LOGGER.warning(
                    "Device %s with UID %s not found during discovery, trying original IP %s",
                    device_uid, device_uid, original_ip
                )

        device = JebaoDevice(
            hass=hass,
            ip=current_ip,
            product_key=device_data.get("product_key", ""),
            uid=device_uid,
            mac=device_data.get("mac"),
            firmware_version=device_data.get("firmware_version"),
        )

        try:
            await device.async_connect()
            devices.append(device)
            _LOGGER.debug(
                "Successfully connected to device %s at %s", 
                device_uid or "unknown", current_ip
            )
        except Exception as exc:
            _LOGGER.error(
                "Failed to connect to Jebao device at %s (UID: %s): %s", 
                current_ip, device_uid or "unknown", exc
            )
            # Continue with other devices even if one fails

    # Update config entry if any IPs changed
    if devices_updated:
        new_data = dict(entry.data)
        new_data["devices"] = updated_devices
        hass.config_entries.async_update_entry(entry, data=new_data)
        _LOGGER.info("Updated device IP addresses in configuration")

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
