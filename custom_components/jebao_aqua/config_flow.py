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
from .cloud import GizwitsCloudApi, did_to_uid
from .const import (
    CONF_MODE,
    DEFAULT_REGION,
    DOMAIN,
    MODE_CLOUD,
    MODE_LOCAL,
)

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required("ip"): str,
        vol.Optional("name", default=""): str,
    }
)

REGION_OPTIONS = {
    "eu": "Europe",
    "us": "Americas / Asia-Pacific",
    "cn": "China",
}


def _cloud_schema(
    region: str = DEFAULT_REGION, email: str = ""
) -> vol.Schema:
    """Schema for the cloud credentials step."""
    return vol.Schema(
        {
            vol.Required("region", default=region): vol.In(REGION_OPTIONS),
            vol.Required("email", default=email): str,
            vol.Required("password"): str,
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

    VERSION = 2
    CONNECTION_CLASS = config_entries.CONN_CLASS_LOCAL_PUSH

    def __init__(self) -> None:
        """Initialize the config flow."""
        self.discovered_devices: list[DeviceCandidate] = []

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Let the user pick between local (LAN) and cloud control."""
        return self.async_show_menu(step_id="user", menu_options=["local", "cloud"])

    async def async_step_local(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Set up local (LAN push) mode: discover devices on the network."""
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
                # Add new devices to existing entry. Build a new list: mutating
                # the nested list in place makes async_update_entry see no
                # change and skip persisting it.
                new_data = dict(existing_entry.data)
                new_data["devices"] = [
                    *existing_entry.data.get("devices", []),
                    *new_devices,
                ]
                self.hass.config_entries.async_update_entry(existing_entry, data=new_data)
                return self.async_abort(reason="devices_added")
            else:
                # Create new entry with discovered devices
                return self.async_create_entry(
                    title="Jebao Devices",
                    data={CONF_MODE: MODE_LOCAL, "devices": new_devices},
                )

        # If no new devices found, show manual entry form
        return self.async_show_form(
            step_id="manual",
            data_schema=STEP_USER_DATA_SCHEMA,
        )

    async def async_step_cloud(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Set up cloud mode: log in to Gizwits and import bound devices."""
        errors: dict[str, str] = {}

        if user_input is not None:
            if self.hass.config_entries.async_entries(DOMAIN):
                return self.async_abort(reason="already_configured")

            api = GizwitsCloudApi(self.hass, user_input["region"])
            token, err = await api.async_login(
                user_input["email"], user_input["password"]
            )
            if not token:
                errors["base"] = err or "auth"
            else:
                response = await api.async_get_devices()
                cloud_devices = (response or {}).get("devices", [])
                if not cloud_devices:
                    errors["base"] = "no_devices"
                else:
                    devices = [
                        {
                            "uid": did_to_uid(dev["did"]),
                            "product_key": dev.get("product_key", ""),
                            "name": dev.get("dev_alias"),
                            "ip": None,
                            "mac": None,
                            "firmware_version": None,
                        }
                        for dev in cloud_devices
                        if dev.get("did")
                    ]
                    return self.async_create_entry(
                        title="Jebao Devices (Cloud)",
                        data={
                            CONF_MODE: MODE_CLOUD,
                            "region": user_input["region"],
                            "email": user_input["email"],
                            "password": user_input["password"],
                            "token": token,
                            "devices": devices,
                        },
                    )

        return self.async_show_form(
            step_id="cloud",
            data_schema=_cloud_schema(),
            errors=errors,
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
                            "name": friendly_name or None,
                        }

                        if existing_entry:
                            # Add to existing entry (new list, see note above)
                            new_data = dict(existing_entry.data)
                            new_data["devices"] = [
                                *existing_entry.data.get("devices", []),
                                new_device,
                            ]
                            self.hass.config_entries.async_update_entry(existing_entry, data=new_data)
                            return self.async_abort(reason="device_added")
                        else:
                            # Create new entry
                            return self.async_create_entry(
                                title=friendly_name or "Jebao Devices",
                                data={
                                    CONF_MODE: MODE_LOCAL,
                                    "devices": [new_device],
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

    @staticmethod
    def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> OptionsFlowHandler:
        """Return the options flow."""
        return OptionsFlowHandler()


class OptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options flow for Jebao Aqua integration.

    self.config_entry is provided by the OptionsFlow base class; assigning it
    explicitly has been rejected by Home Assistant since 2025.12.
    """

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage the options."""
        current_mode = self.config_entry.data.get(CONF_MODE, MODE_LOCAL)

        if user_input is not None:
            new_mode = user_input.get(CONF_MODE, current_mode)
            if new_mode != current_mode:
                if new_mode == MODE_CLOUD:
                    # Cloud mode needs credentials before we can switch.
                    return await self.async_step_cloud()
                # Switch to local: devices reconnect over LAN by UID via
                # discovery on reload. Cloud credentials are kept so the user
                # can switch back without re-entering them.
                self.hass.config_entries.async_update_entry(
                    self.config_entry,
                    data={**self.config_entry.data, CONF_MODE: MODE_LOCAL},
                )
                await self.hass.config_entries.async_reload(
                    self.config_entry.entry_id
                )
                return self.async_create_entry(title="", data={})
            if user_input.get("rediscover") and current_mode == MODE_LOCAL:
                return await self.async_step_rediscover()
            return self.async_create_entry(title="", data={})

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Required(CONF_MODE, default=current_mode): vol.In(
                    {
                        MODE_LOCAL: "Local (LAN, recommended)",
                        MODE_CLOUD: "Cloud (Gizwits API)",
                    }
                ),
                vol.Optional("rediscover", default=False): bool,
            }),
            description_placeholders={
                "device_count": str(len(self.config_entry.data.get("devices", []))),
            },
        )

    async def async_step_cloud(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Collect cloud credentials when switching an entry to cloud mode."""
        errors: dict[str, str] = {}
        data = self.config_entry.data

        if user_input is not None:
            api = GizwitsCloudApi(self.hass, user_input["region"])
            token, err = await api.async_login(
                user_input["email"], user_input["password"]
            )
            if not token:
                errors["base"] = err or "auth"
            else:
                self.hass.config_entries.async_update_entry(
                    self.config_entry,
                    data={
                        **data,
                        CONF_MODE: MODE_CLOUD,
                        "region": user_input["region"],
                        "email": user_input["email"],
                        "password": user_input["password"],
                        "token": token,
                    },
                )
                await self.hass.config_entries.async_reload(
                    self.config_entry.entry_id
                )
                return self.async_create_entry(title="", data={})

        return self.async_show_form(
            step_id="cloud",
            data_schema=_cloud_schema(
                region=data.get("region", DEFAULT_REGION),
                email=data.get("email") or "",
            ),
            errors=errors,
        )

    async def async_step_rediscover(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle rediscovery of devices."""
        # Perform discovery
        discovered = await hub.async_discover_devices(self.hass, timeout=10.0)
        
        # Get existing UIDs from this config entry
        existing_devices = {
            device["uid"]: device
            for device in self.config_entry.data.get("devices", [])
            if device.get("uid")
        }
        
        # Track changes
        updated_devices = []
        new_devices = []
        found_uids = set()
        
        for dev in discovered:
            uid = dev.get("uid")
            if not uid:
                continue
                
            found_uids.add(uid)
            mac = dev.get("mac")
            if mac:
                mac = format_mac(mac)
            
            device_data = {
                "ip": dev["ip"],
                "product_key": dev.get("product_key", ""),
                "uid": uid,
                "mac": mac,
                "firmware_version": dev.get("firmware_version"),
            }

            if uid in existing_devices:
                # Update existing device, keeping fields discovery doesn't
                # know about (e.g. the configured name)
                if existing_devices[uid].get("name"):
                    device_data["name"] = existing_devices[uid]["name"]
                updated_devices.append(device_data)
            else:
                # New device found
                new_devices.append(device_data)
        
        # Add devices that weren't found (keep original data)
        for uid, device in existing_devices.items():
            if uid not in found_uids:
                updated_devices.append(device)
        
        # Update config entry
        new_data = dict(self.config_entry.data)
        new_data["devices"] = updated_devices + new_devices
        
        self.hass.config_entries.async_update_entry(self.config_entry, data=new_data)
        
        # Reload the integration to pick up changes
        await self.hass.config_entries.async_reload(self.config_entry.entry_id)
        
        result_message = f"Rediscovery complete. Found {len(found_uids)} devices."
        if new_devices:
            result_message += f" Added {len(new_devices)} new devices."
        
        return self.async_create_entry(title="", data={}, description=result_message)
