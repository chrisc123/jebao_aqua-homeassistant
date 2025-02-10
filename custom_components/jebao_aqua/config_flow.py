"""Home Assistant integration for Jebao Aquarium Pumps (example integration).

This file contains the configuration flow and options flow for the integration.
"""

import asyncio
from dataclasses import dataclass, field
from functools import lru_cache
import ipaddress
import logging
from typing import Any, Dict, List, Optional, Tuple

import pycountry
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
import homeassistant.helpers.config_validation as cv

from .api import GizwitsApi
from .const import (
    DEFAULT_REGION,
    DISCOVERY_TIMEOUT,
    DOMAIN,
    GITHUB_ISSUE_URL,
    GIZWITS_API_URLS,
    MODEL_CHECK_FAILED,
    SERVICE_MAP,
)
from .discovery import discover_devices
from .util import load_attribute_models

_LOGGER = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def get_country_choices() -> List[Tuple[str, str]]:
    """Cache the country choices to avoid repeated file operations."""
    countries = list(pycountry.countries)
    choices = [
        (country.alpha_2, country.name)
        for country in countries
        if country.alpha_2 in SERVICE_MAP
    ]
    return sorted(choices, key=lambda x: x[1])


@dataclass
class ConfigData:
    token: Optional[str] = None
    devices: List[Dict[str, Any]] = field(default_factory=list)
    region: Optional[str] = None
    email: Optional[str] = None
    country: Optional[str] = None


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for the integration."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._api: Optional[GizwitsApi] = None
        self._devices: Optional[Dict[str, Any]] = None
        self._device_index: int = 0
        self._config: ConfigData = ConfigData()
        self._country_choices: Optional[List[Tuple[str, str]]] = None

    async def _check_device_models(
        self, devices: List[Dict[str, Any]]
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, Any]]:
        """Check if all devices have corresponding model files."""
        attribute_models = await load_attribute_models(self.hass)
        supported_devices: List[Dict[str, Any]] = []
        unsupported_devices: List[Dict[str, Any]] = []

        for device in devices:
            if device["product_key"] in attribute_models:
                supported_devices.append(device)
            else:
                unsupported_devices.append(device)

        return supported_devices, unsupported_devices, attribute_models

    async def async_step_user(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Handle the initial step."""
        errors: Dict[str, str] = {}

        if self._country_choices is None:
            self._country_choices = await self.hass.async_add_executor_job(
                get_country_choices
            )

        # Get user's configured country from Home Assistant settings
        ha_country: str = self.hass.config.country or ""
        default_country: Optional[str] = next(
            (
                code
                for code, name in self._country_choices
                if code == ha_country.upper()
            ),
            next((code for code, name in self._country_choices if code == "US"), None),
        )

        country_schema = vol.Schema(
            {
                vol.Required("country", default=default_country): vol.In(
                    {code: name for code, name in self._country_choices}
                ),
                vol.Required("email"): str,
                vol.Required("password"): str,
            }
        )

        if user_input is not None:
            country_code: str = user_input["country"]
            self._config.country = country_code
            region: str = SERVICE_MAP.get(country_code.upper(), DEFAULT_REGION)
            self._config.region = region
            self._config.email = user_input["email"]

            self._api = GizwitsApi(
                GIZWITS_API_URLS[region]["LOGIN_URL"],
                GIZWITS_API_URLS[region]["DEVICES_URL"],
                GIZWITS_API_URLS[region]["DEVICE_DATA_URL"],
                GIZWITS_API_URLS[region]["CONTROL_URL"],
            )

            try:
                async with self._api as api:
                    token, error_code = await api.async_login(
                        user_input["email"], user_input["password"]
                    )
                    if token:
                        api.set_token(token)
                        self._config.token = token
                        self._devices = await api.get_devices()

                        if self._devices and "devices" in self._devices:
                            (
                                supported,
                                unsupported,
                                models,
                            ) = await self._check_device_models(
                                self._devices["devices"]
                            )

                            if not supported:
                                errors["base"] = MODEL_CHECK_FAILED
                                description_placeholders = {
                                    "supported_devices": ", ".join(
                                        d.get("dev_alias", d["did"]) for d in supported
                                    ),
                                    "unsupported_devices": ", ".join(
                                        f"{d.get('dev_alias', d['did'])} ({d['product_key']})"
                                        for d in unsupported
                                    ),
                                    "issue_url": GITHUB_ISSUE_URL,
                                }
                                return self.async_show_form(
                                    step_id="user",
                                    data_schema=country_schema,
                                    errors=errors,
                                    description_placeholders=description_placeholders,
                                )

                            # Update devices list to only include supported devices
                            self._devices["devices"] = supported
                            api.add_attribute_models(models)

                            try:
                                discovered_devices = await asyncio.wait_for(
                                    discover_devices(), timeout=DISCOVERY_TIMEOUT + 2
                                )
                                # Update each device with its discovered IP, if any
                                for device in self._devices["devices"]:
                                    device_id = device["did"]
                                    device["lan_ip"] = discovered_devices.get(device_id)

                                _LOGGER.debug(
                                    "Devices after discovery: %s", self._devices
                                )
                                return await self.async_step_device_setup()

                            except asyncio.TimeoutError:
                                _LOGGER.warning(
                                    "Device discovery timed out, proceeding with cloud-only setup"
                                )
                                for device in self._devices["devices"]:
                                    device["lan_ip"] = None
                                return await self.async_step_device_setup()

                            except Exception as e:
                                _LOGGER.error("Error during discovery", exc_info=True)
                                errors["base"] = "discovery_failed"
                        else:
                            _LOGGER.error(
                                "Invalid device data structure: %s", self._devices
                            )
                            errors["base"] = "no_devices"
                    else:
                        errors["base"] = error_code if error_code else "auth"
            except Exception as ex:
                _LOGGER.error(
                    "Error during API login or device retrieval", exc_info=True
                )
                errors["base"] = "unknown"

        return self.async_show_form(
            step_id="user", data_schema=country_schema, errors=errors
        )

    async def async_step_device_setup(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Handle device setup."""
        errors: Dict[str, str] = {}
        assert self._devices is not None  # For type checking
        # Map device alias to device info
        device_map: Dict[str, Dict[str, Any]] = {
            device.get("dev_alias", device["did"]): device
            for device in self._devices["devices"]
        }

        if user_input is not None:
            devices: List[Dict[str, Any]] = []
            for alias, device in device_map.items():
                ip: str = user_input.get(alias, "")
                if ip:
                    try:
                        ipaddress.ip_address(ip)
                    except ValueError:
                        errors[alias] = "invalid_ip"
                        continue

                device_data = device.copy()
                device_data["lan_ip"] = ip if ip else None
                devices.append(device_data)

            if not errors:
                self._config.devices = devices
                _LOGGER.debug("Final device configuration: %s", devices)
                return self.async_create_entry(
                    title="Jebao Aquarium Pumps", data=self._config.__dict__
                )

        # Build the schema dynamically using device aliases
        data_schema: Dict[Any, Any] = {}
        for device in self._devices["devices"]:
            alias: str = device.get("dev_alias", device["did"])
            data_schema[vol.Optional(alias, default=device.get("lan_ip", ""))] = str

        return self.async_show_form(
            step_id="device_setup",
            data_schema=vol.Schema(data_schema),
            description_placeholders={
                "number_of_devices": len(self._devices["devices"])
            },
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Get the options flow for this handler."""
        return JebaoPumpOptionsFlowHandler(config_entry)


class JebaoPumpOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options flow for Jebao Pump integration."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize the options flow."""
        self.config_entry = config_entry
        self._api: Optional[GizwitsApi] = None
        self._devices: Optional[Dict[str, Any]] = None
        self._device_index: int = 0
        self._country_choices: Optional[List[Tuple[str, str]]] = None
        self._config: Dict[str, Any] = {}

    async def _check_device_models(
        self, devices: List[Dict[str, Any]]
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, Any]]:
        """Check if all devices have corresponding model files."""
        attribute_models = await load_attribute_models(self.hass)
        supported_devices: List[Dict[str, Any]] = []
        unsupported_devices: List[Dict[str, Any]] = []

        for device in devices:
            if device["product_key"] in attribute_models:
                supported_devices.append(device)
            else:
                unsupported_devices.append(device)

        return supported_devices, unsupported_devices, attribute_models

    async def async_step_init(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Manage options."""
        if user_input is not None:
            if user_input["next_step"] == "reconfigure":
                return await self.async_step_reconfigure()
            return self.async_create_entry(title="", data=user_input)

        email = self.config_entry.data.get("email")
        region = self.config_entry.data.get("region")
        _LOGGER.debug("Current settings - Email: %s, Region: %s", email, region)

        schema = vol.Schema(
            {
                vol.Required("next_step"): vol.In(
                    {"reconfigure": "Update credentials and rediscover devices"}
                )
            }
        )
        return self.async_show_form(
            step_id="init",
            data_schema=schema,
            description_placeholders={
                "current_email": email or "Not set",
                "current_region": region or "Not set",
            },
        )

    async def async_step_reconfigure(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Handle reconfiguration."""
        errors: Dict[str, str] = {}

        if self._country_choices is None:
            self._country_choices = await self.hass.async_add_executor_job(
                get_country_choices
            )

        # Define a schema for reconfiguration
        reconfigure_schema = vol.Schema(
            {
                vol.Required(
                    "country", default=self.config_entry.data.get("country", "US")
                ): vol.In({code: name for code, name in self._country_choices}),
                vol.Required(
                    "email", default=self.config_entry.data.get("email", "")
                ): str,
                vol.Required("password"): str,
            }
        )

        if user_input is not None:
            country_code: str = user_input["country"]
            region: str = SERVICE_MAP.get(country_code.upper(), DEFAULT_REGION)
            self._config = {
                "email": user_input["email"],
                "country": country_code,
                "region": region,
                "devices": [],
            }

            self._api = GizwitsApi(
                GIZWITS_API_URLS[region]["LOGIN_URL"],
                GIZWITS_API_URLS[region]["DEVICES_URL"],
                GIZWITS_API_URLS[region]["DEVICE_DATA_URL"],
                GIZWITS_API_URLS[region]["CONTROL_URL"],
            )

            try:
                async with self._api as api:
                    token, error_code = await api.async_login(
                        user_input["email"], user_input["password"]
                    )
                    if token:
                        self._config["token"] = token
                        api.set_token(token)
                        self._devices = await api.get_devices()

                        if self._devices and "devices" in self._devices:
                            (
                                supported,
                                unsupported,
                                models,
                            ) = await self._check_device_models(
                                self._devices["devices"]
                            )

                            if not supported:
                                errors["base"] = MODEL_CHECK_FAILED
                                description_placeholders = {
                                    "supported_devices": ", ".join(
                                        d.get("dev_alias", d["did"]) for d in supported
                                    ),
                                    "unsupported_devices": ", ".join(
                                        f"{d.get('dev_alias', d['did'])} ({d['product_key']})"
                                        for d in unsupported
                                    ),
                                    "issue_url": GITHUB_ISSUE_URL,
                                }
                                return self.async_show_form(
                                    step_id="reconfigure",
                                    data_schema=reconfigure_schema,
                                    errors=errors,
                                    description_placeholders=description_placeholders,
                                )

                            self._devices["devices"] = supported
                            api.add_attribute_models(models)

                            try:
                                discovered_devices = await asyncio.wait_for(
                                    discover_devices(), timeout=DISCOVERY_TIMEOUT + 2
                                )
                                for device in self._devices["devices"]:
                                    device_id = device["did"]
                                    device["lan_ip"] = discovered_devices.get(device_id)
                                self._device_index = 0
                                return await self.async_step_device_setup()
                            except (asyncio.TimeoutError, Exception) as e:
                                _LOGGER.warning(
                                    "Discovery failed, falling back to manual setup: %s",
                                    e,
                                    exc_info=True,
                                )
                                for device in self._devices["devices"]:
                                    device["lan_ip"] = None
                                self._device_index = 0
                                return await self.async_step_device_setup()
                        else:
                            errors["base"] = "no_devices"
                    else:
                        errors["base"] = error_code if error_code else "auth"
            except Exception as ex:
                _LOGGER.error("Error during reconfiguration", exc_info=True)
                errors["base"] = "unknown"

        return self.async_show_form(
            step_id="reconfigure", data_schema=reconfigure_schema, errors=errors
        )

    async def async_step_device_setup(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Handle device setup during reconfiguration."""
        errors: Dict[str, str] = {}
        assert self._devices is not None  # For type checking

        # Map device alias to device ID
        device_map: Dict[str, str] = {
            device.get("dev_alias", device["did"]): device["did"]
            for device in self._devices["devices"]
        }

        if user_input is not None:
            try:
                existing_devices = {
                    device["did"]: device
                    for device in self.config_entry.data.get("devices", [])
                }
                new_devices: List[Dict[str, Any]] = []
                for alias, device_id in device_map.items():
                    ip: str = user_input.get(alias, "")
                    if ip:
                        try:
                            ipaddress.ip_address(ip)
                        except ValueError:
                            errors[alias] = "invalid_ip"
                            continue
                    if device_id in existing_devices:
                        device_data = existing_devices[device_id].copy()
                        device_data["lan_ip"] = ip or None
                        new_devices.append(device_data)
                    else:
                        new_devices.append({"did": device_id, "lan_ip": ip or None})

                if not errors:
                    new_data = {
                        "email": self._config["email"],
                        "token": self._config["token"],
                        "region": self._config["region"],
                        "country": self._config["country"],
                        "devices": new_devices,
                    }
                    try:
                        self.hass.config_entries.async_update_entry(
                            self.config_entry,
                            data=new_data,
                            options={},
                        )
                        await self.hass.config_entries.async_reload(
                            self.config_entry.entry_id
                        )
                    except Exception as ex:
                        _LOGGER.error("Error during entry reload", exc_info=True)
                        errors["base"] = "reload_failed"
                        # Rebuild dynamic schema below
                        data_schema = {
                            vol.Optional(
                                device.get("dev_alias", device["did"]),
                                default=device.get("lan_ip", ""),
                            ): str
                            for device in self._devices["devices"]
                        }
                        return self.async_show_form(
                            step_id="device_setup",
                            data_schema=vol.Schema(data_schema),
                            errors=errors,
                        )

                    return self.async_create_entry(title="", data={})
            except Exception as ex:
                _LOGGER.error("Error processing device IPs", exc_info=True)
                errors["base"] = "unknown"

        data_schema = {
            vol.Optional(
                device.get("dev_alias", device["did"]),
                default=device.get("lan_ip", ""),
            ): str
            for device in self._devices["devices"]
        }
        return self.async_show_form(
            step_id="device_setup",
            data_schema=vol.Schema(data_schema),
            description_placeholders={
                "number_of_devices": len(self._devices["devices"])
            },
            errors=errors,
        )
