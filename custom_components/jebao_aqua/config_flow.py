"""Config flow for Jebao Aqua integration."""

from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.device_registry import format_mac

from . import hub
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required("ip"): str,
        vol.Optional("name", default=""): str,
    }
)


@dataclass
class DeviceCandidate:
    """Discovered device information."""

    ip: str
    product_key: str
    uid: str
    mac: str | None = None
    firmware_version: str | None = None


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Jebao Aqua integration."""

    VERSION = 1
    CONNECTION_CLASS = config_entries.CONN_CLASS_LOCAL_PUSH

    def __init__(self) -> None:
        """Initialize the config flow."""
        self.discovered_devices: list[DeviceCandidate] = []

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        return self.async_show_form(step_id="introduction")

    async def async_step_introduction(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the introduction step."""
        if user_input is None:
            return self.async_show_form(step_id="introduction")

        # Do discovery
        discovered = await hub.async_discover_devices(self.hass, timeout=5.0)

        # Get existing entries
        existing_entry = next(
            (entry for entry in self.hass.config_entries.async_entries(DOMAIN)
             if entry.data.get("devices")), None)
        
        # Get set of existing UIDs
        existing_uids = {
            device["uid"]
            for entry in self.hass.config_entries.async_entries(DOMAIN)
            for device in entry.data.get("devices", [])
            if "uid" in device
        }

        new_devices = []
        for dev in discovered:
            uid = dev.get("uid")
            if not uid or uid in existing_uids:
                continue

            mac = dev.get("mac")
            if mac:
                mac = format_mac(mac)

            new_devices.append({
                "ip": dev["ip"],
                "product_key": dev.get("product_key", ""),
                "uid": uid,
                "mac": mac,
                "firmware_version": dev.get("firmware_version"),
            })

        if new_devices:
            if existing_entry:
                # Add new devices to existing entry
                new_data = dict(existing_entry.data)
                new_data["devices"].extend(new_devices)
                self.hass.config_entries.async_update_entry(existing_entry, data=new_data)
                return self.async_abort(reason="devices_added")
            else:
                # Create new entry with discovered devices
                return self.async_create_entry(
                    title="Jebao Devices",
                    data={"devices": new_devices},
                )

        # If no new devices found, show manual entry form
        return self.async_show_form(
            step_id="manual",
            data_schema=STEP_USER_DATA_SCHEMA,
        )

    async def async_step_manual(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle manual device entry."""
        errors: dict[str, str] = {}

        if user_input:
            ip = user_input["ip"]
            friendly_name = user_input["name"].strip()

            try:
                dev = await hub.async_directed_discovery(self.hass, ip, timeout=5.0)
                if not dev or not dev.get("uid"):
                    errors["base"] = "cannot_connect"
                else:
                    device_uid = dev["uid"]
                    # Simply check if any entry contains this device UID
                    existing_entry = None
                    for entry in self.hass.config_entries.async_entries(DOMAIN):
                        if any(d.get("uid") == device_uid for d in entry.data.get("devices", [])):
                            errors["base"] = "already_configured"
                            break
                        if not existing_entry and entry.data.get("devices"):
                            existing_entry = entry

                    if not errors:
                        mac = dev.get("mac")
                        if mac:
                            mac = format_mac(mac)

                        new_device = {
                            "ip": ip,
                            "product_key": dev.get("product_key", ""),
                            "uid": device_uid,
                            "mac": mac,
                            "firmware_version": dev.get("firmware_version"),
                        }

                        if existing_entry:
                            # Add to existing entry
                            new_data = dict(existing_entry.data)
                            new_data["devices"].append(new_device)
                            self.hass.config_entries.async_update_entry(existing_entry, data=new_data)
                            return self.async_abort(reason="device_added")
                        else:
                            # Create new entry
                            return self.async_create_entry(
                                title=friendly_name or "Jebao Devices",
                                data={"devices": [new_device]},
                            )

            except Exception:
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"

        return self.async_show_form(
            step_id="manual",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
        )
