import logging
import voluptuous as vol
import homeassistant.helpers.config_validation as cv
from homeassistant import config_entries
from homeassistant.core import callback
from functools import lru_cache
import pycountry
import asyncio
import ipaddress
from .const import (
    DOMAIN,
    LOGGER,
    GIZWITS_API_URLS,
    DEFAULT_REGION,
    SERVICE_MAP,
    DISCOVERY_TIMEOUT,
)
from .api import GizwitsApi
from .discovery import discover_devices

_LOGGER = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def get_country_choices():
    """Cache the country choices to avoid repeated file operations."""
    countries = list(pycountry.countries)
    # Create list of tuples and sort by country name
    choices = [
        (country.alpha_2, country.name)
        for country in countries
        if country.alpha_2 in SERVICE_MAP
    ]
    return sorted(
        choices, key=lambda x: x[1]
    )  # Sort by country name (second element in tuple)


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self):
        self._api = None  # Initialize _api to None
        self._devices = None
        self._device_index = 0
        self._config = {
            "token": None,
            "devices": [],
            "region": None,
            "email": None,
            "country": None,  # Add country to config
        }  # Add email to config
        # Pre-load country choices during initialization
        self._country_choices = None

    async def async_step_user(self, user_input=None):
        """Handle user step."""
        errors = {}

        # Load country choices in executor if not already loaded
        if self._country_choices is None:
            self._country_choices = await self.hass.async_add_executor_job(
                get_country_choices
            )

        if user_input is not None:
            country_code = user_input["country"]
            self._config["country"] = country_code
            region = SERVICE_MAP.get(country_code.upper(), DEFAULT_REGION)
            self._config["region"] = region
            self._config["email"] = user_input["email"]

            self._api = GizwitsApi(
                GIZWITS_API_URLS[region]["LOGIN_URL"],
                GIZWITS_API_URLS[region]["DEVICES_URL"],
                GIZWITS_API_URLS[region]["DEVICE_DATA_URL"],
                GIZWITS_API_URLS[region]["CONTROL_URL"],
            )

            async with self._api as api:
                token, error_code = await api.async_login(
                    user_input["email"], user_input["password"]
                )

                if token:
                    api.set_token(token)
                    self._config["token"] = token  # Store token in config
                    self._devices = await api.get_devices()

                    if self._devices and "devices" in self._devices:
                        try:
                            # Set timeout for device discovery
                            discovered_devices = await asyncio.wait_for(
                                discover_devices(),
                                timeout=DISCOVERY_TIMEOUT + 2,  # Add 2 seconds buffer
                            )

                            # Continue even if no devices are discovered
                            for device in self._devices["devices"]:
                                device_id = device["did"]
                                device["lan_ip"] = discovered_devices.get(device_id)

                            _LOGGER.debug(f"Devices after discovery: {self._devices}")
                            return await self.async_step_device_setup()

                        except asyncio.TimeoutError:
                            _LOGGER.warning(
                                "Device discovery timed out, proceeding with cloud-only setup"
                            )
                            # Mark all devices as needing manual IP entry
                            for device in self._devices["devices"]:
                                device["lan_ip"] = None
                            return await self.async_step_device_setup()

                        except Exception as e:
                            _LOGGER.error(f"Error during discovery: {e}")
                            errors["base"] = "discovery_failed"

                    else:
                        _LOGGER.error(f"Invalid device data structure: {self._devices}")
                        errors["base"] = "no_devices"
                else:
                    if error_code:
                        errors["base"] = error_code  # Don't strip prefix
                    else:
                        errors["base"] = "auth"

        # Get user's configured country from Home Assistant
        ha_country = self.hass.config.country or ""
        default_country = next(
            (
                code
                for code, name in self._country_choices
                if code == ha_country.upper()
            ),
            next(
                (code for code, name in self._country_choices if code == "US"), None
            ),  # Fallback to US if no match
        )

        # Use the cached country choices
        country_schema = vol.Schema(
            {
                vol.Required("country", default=default_country): vol.In(
                    {code: name for code, name in self._country_choices}
                ),
                vol.Required("email"): str,
                vol.Required("password"): str,
            }
        )

        return self.async_show_form(
            step_id="user",
            data_schema=country_schema,
            errors=errors,
        )

    async def async_step_device_setup(self, user_input=None):
        """Handle device setup."""
        errors = {}

        # Create a mapping of device aliases to IDs for form processing
        device_map = {
            device.get("dev_alias", device["did"]): device["did"]
            for device in self._devices["devices"]
        }

        if user_input is not None:
            try:
                devices = []
                # Map the alias back to device ID when processing input
                for alias, device_id in device_map.items():
                    ip = user_input.get(alias, "")

                    if ip:  # Only validate if IP is provided
                        try:
                            ipaddress.ip_address(ip)
                        except ValueError:
                            errors[alias] = "invalid_ip"
                            continue

                    devices.append({"did": device_id, "lan_ip": ip or None})

                if not errors:
                    self._config["devices"] = devices
                    return self.async_create_entry(
                        title="Jebao Aquarium Pumps", data=self._config
                    )

            except Exception as ex:
                _LOGGER.error(f"Error processing device IPs: {ex}")
                errors["base"] = "unknown"

        # Create schema using aliases as field names
        data_schema = {}
        for device in self._devices["devices"]:
            alias = device.get("dev_alias") or device["did"]
            data_schema[
                vol.Optional(
                    alias,
                    default=device.get("lan_ip", ""),
                )
            ] = str

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
    def async_get_options_flow(config_entry):
        """Get the options flow for this handler."""
        return JebaoPumpOptionsFlowHandler()  # Remove config_entry parameter


class JebaoPumpOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options flow for Jebao Pump integration."""

    def __init__(self):  # Remove config_entry parameter
        """Initialize options flow."""
        # Remove self.config_entry assignment
        self._api = None
        self._devices = None
        self._device_index = 0
        self._country_choices = None
        self._config = {}  # Add this to store temporary configuration

    async def async_step_init(self, user_input=None):
        """Manage options."""
        if user_input is not None:
            if user_input["next_step"] == "reconfigure":
                return await self.async_step_reconfigure()
            return self.async_create_entry(title="", data=user_input)

        email = self.config_entry.data.get("email")
        region = self.config_entry.data.get("region")
        _LOGGER.debug(
            f"Current settings - Email: {email}, Region: {region}"
        )  # Add debug logging

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required("next_step"): vol.In(
                        {"reconfigure": "Update credentials and rediscover devices"}
                    )
                }
            ),
            description_placeholders={
                "current_email": email or "Not set",
                "current_region": region or "Not set",
            },
        )

    async def async_step_reconfigure(self, user_input=None):
        """Handle reconfiguration."""
        errors = {}

        # Load country choices in executor if not already loaded
        if self._country_choices is None:
            self._country_choices = await self.hass.async_add_executor_job(
                get_country_choices
            )

        if user_input is not None:
            country_code = user_input["country"]
            region = SERVICE_MAP.get(country_code.upper(), DEFAULT_REGION)

            # Store configuration for later use
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

            async with self._api as api:
                token, error_code = await api.async_login(  # Change this line
                    user_input["email"], user_input["password"]
                )
                if token:  # Just check for token
                    self._config["token"] = token
                    api.set_token(token)
                    self._devices = await api.get_devices()

                    if self._devices and "devices" in self._devices:
                        try:
                            discovered_devices = await asyncio.wait_for(
                                discover_devices(), timeout=DISCOVERY_TIMEOUT + 2
                            )

                            # Set discovered IPs or None for manual entry
                            for device in self._devices["devices"]:
                                device_id = device["did"]
                                device["lan_ip"] = discovered_devices.get(device_id)

                            # Reset device index for setup
                            self._device_index = 0
                            return await self.async_step_device_setup()

                        except (asyncio.TimeoutError, Exception) as e:
                            LOGGER.warning(
                                f"Discovery failed, falling back to manual setup: {e}"
                            )
                            # Mark all devices for manual IP entry
                            for device in self._devices["devices"]:
                                device["lan_ip"] = None
                            self._device_index = 0
                            return await self.async_step_device_setup()
                    else:
                        errors["base"] = "no_devices"
                else:
                    if error_code:
                        errors["base"] = error_code  # Don't strip prefix
                    else:
                        errors["base"] = "auth"

        stored_country = self.config_entry.data.get("country", "US")

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema(
                {
                    vol.Required("country", default=stored_country): vol.In(
                        {code: name for code, name in self._country_choices}
                    ),
                    vol.Required(
                        "email", default=self.config_entry.data.get("email", "")
                    ): str,
                    vol.Required("password"): str,
                }
            ),
            errors=errors,
        )

    async def async_step_device_setup(self, user_input=None):
        """Handle device setup during reconfiguration."""
        errors = {}

        # Create a mapping of device aliases to IDs for form processing
        device_map = {
            device.get("dev_alias", device["did"]): device["did"]
            for device in self._devices["devices"]
        }

        if user_input is not None:
            try:
                # Get existing devices from config entry
                existing_devices = {
                    device["did"]: device
                    for device in self.config_entry.data.get("devices", [])
                }

                new_devices = []
                # Map the alias back to device ID when processing input
                for alias, device_id in device_map.items():
                    ip = user_input.get(alias, "")

                    if ip:
                        try:
                            ipaddress.ip_address(ip)
                        except ValueError:
                            errors[alias] = "invalid_ip"
                            continue

                    # If device existed before, preserve any additional properties
                    if device_id in existing_devices:
                        device_data = existing_devices[device_id].copy()
                        device_data["lan_ip"] = ip or None
                        new_devices.append(device_data)
                    else:
                        new_devices.append({"did": device_id, "lan_ip": ip or None})

                if not errors:
                    # Create new config data first
                    new_data = {
                        "email": self._config["email"],
                        "token": self._config["token"],
                        "region": self._config["region"],
                        "country": self._config["country"],
                        "devices": new_devices,
                    }

                    try:
                        # First update the entry with new data
                        self.hass.config_entries.async_update_entry(
                            self.config_entry,
                            data=new_data,
                            options={},  # Reset options
                        )

                        # Now reload the entry
                        await self.hass.config_entries.async_reload(
                            self.config_entry.entry_id
                        )

                    except Exception as ex:
                        _LOGGER.error(f"Error during entry reload: {ex}")
                        errors["base"] = "reload_failed"
                        return self.async_show_form(
                            step_id="device_setup",
                            data_schema=vol.Schema(data_schema),
                            errors=errors,
                        )

                    return self.async_create_entry(title="", data={})

            except Exception as ex:
                _LOGGER.error(f"Error processing device IPs: {ex}")
                errors["base"] = "unknown"

        # Create schema using aliases as field names
        data_schema = {}
        for device in self._devices["devices"]:
            alias = device.get("dev_alias") or device["did"]
            data_schema[
                vol.Optional(
                    alias,
                    default=device.get("lan_ip", ""),
                )
            ] = str

        return self.async_show_form(
            step_id="device_setup",
            data_schema=vol.Schema(data_schema),
            description_placeholders={
                "number_of_devices": len(self._devices["devices"])
            },
            errors=errors,
        )
