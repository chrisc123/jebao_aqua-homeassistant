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
        self.discovered_devices = []
        discovered = await hub.async_discover_devices(self.hass, timeout=5.0)

        for dev in discovered:
            uid = dev.get("uid")
            if not uid:
                continue

            # Check if device is already configured
            if await self.async_set_unique_id(uid, raise_on_progress=False):
                continue  # Skip already configured devices

            mac = dev.get("mac")
            if mac:
                mac = format_mac(mac)

            self.discovered_devices.append(
                DeviceCandidate(
                    ip=dev["ip"],
                    product_key=dev.get("product_key", ""),
                    uid=uid,
                    mac=mac,
                    firmware_version=dev.get("firmware_version"),
                )
            )

        if self.discovered_devices:
            # Create single entry with all discovered devices
            return self.async_create_entry(
                title="Jebao Devices",
                data={
                    "devices": [
                        {
                            "ip": dev.ip,
                            "product_key": dev.product_key,
                            "uid": dev.uid,
                            "mac": dev.mac,
                            "firmware_version": dev.firmware_version,
                        }
                        for dev in self.discovered_devices
                    ]
                },
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
                    await self.async_set_unique_id(dev["uid"])
                    self._abort_if_unique_id_configured()

                    mac = dev.get("mac")
                    if mac:
                        mac = format_mac(mac)

                    # Create single entry with manually added device
                    return self.async_create_entry(
                        title=friendly_name or "Jebao Devices",
                        data={
                            "devices": [
                                {
                                    "ip": ip,
                                    "product_key": dev.get("product_key", ""),
                                    "uid": dev["uid"],
                                    "mac": mac,
                                    "firmware_version": dev.get("firmware_version"),
                                }
                            ]
                        },
                    )
            except Exception:
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"

        return self.async_show_form(
            step_id="manual",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
        )
