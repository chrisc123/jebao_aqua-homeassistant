import logging
import voluptuous as vol
import homeassistant.helpers.config_validation as cv
from homeassistant import config_entries
from homeassistant.core import callback
from .const import DOMAIN, LOGGER
from .api import GizwitsApi
from .discovery import discover_devices

_LOGGER = logging.getLogger(__name__)

class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self):
        self._api = GizwitsApi()  # Initialize the API object here
        self._devices = None
        self._device_index = 0
        self._config = {"token": None, "devices": []}

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            async with GizwitsApi() as api:
                self._token = await api.async_login(user_input["email"], user_input["password"])

                if self._token:
                    # Set the token for the API and fetch devices
                    api.set_token(self._token)
                    self._devices = await api.get_devices()

                    if self._devices:
                        # Save the token in the configuration
                        self._config["token"] = self._token

                        # Call the discover_devices function and log the result
                        _LOGGER.debug("Calling discover_devices()")
                        discovered_devices = await discover_devices()
                        _LOGGER.debug(f"Discovered devices: {discovered_devices}")

                        if discovered_devices:
                            for device in self._devices['devices']:
                                device_id = device["did"]
                                if device_id in discovered_devices:
                                    device["lan_ip"] = discovered_devices[device_id]
                                else:
                                    # Flag for manual IP entry if discovery failed
                                    device["lan_ip"] = None

                            return await self.async_step_device_setup()

                        else:
                            errors["base"] = "no_devices"
                    else:
                        errors["base"] = "no_devices"
                else:
                    errors["base"] = "auth"

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required("email"): str,
                vol.Required("password"): str
            }),
            errors=errors
        )

    async def async_step_device_setup(self, user_input=None):
        errors = {}

        if user_input is not None:
            # Store the LAN IP Address for the current device
            device_id = self._devices['devices'][self._device_index]["did"]
            self._config["devices"].append({"did": device_id, "lan_ip": user_input["lan_ip"]})

            # Increment the index to setup the next device
            self._device_index += 1

            # Check if there are more devices to setup
            if self._device_index < len(self._devices['devices']):
                return await self._show_device_form()

            # If all devices are set up, finish the flow
            return self.async_create_entry(title="Jebao Aquarium Pumps", data=self._config)

        return await self._show_device_form()

    async def _show_device_form(self, user_input=None):
        """Show the form to enter the LAN IP for a device."""
        device = self._devices['devices'][self._device_index]
        device_name = device.get("dev_alias") or device["did"]
        errors = {}

        if device["lan_ip"]:
            # If device already has a LAN IP from discovery, skip to the next device
            return await self.async_step_device_setup({"lan_ip": device["lan_ip"]})

        if user_input is not None:
            # Validate the IP address
            try:
                ip_address = user_input["lan_ip"]
                valid_ip = cv.ipv4_address(ip_address)
                # Process the valid IP address as needed
                return self.async_step_device_setup({"lan_ip": ip_address})
            except vol.Invalid:
                errors["lan_ip"] = "invalid_ip"

        return self.async_show_form(
            step_id="device_setup",
            data_schema=vol.Schema({
                vol.Required("lan_ip", default=""): str
            }),
            description_placeholders={"device_name": device_name},
            errors=errors
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return JebaoPumpOptionsFlowHandler(config_entry)

class JebaoPumpOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle an options flow for Jebao Pump integration."""

    def __init__(self, config_entry):
        """Initialize options flow."""
        self.config_entry = config_entry

    async def async_step_init(self, user_input=None):
        """Manage the options."""
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Optional("option1", default=self.config_entry.options.get("option1", False)): bool,
            })
        )
