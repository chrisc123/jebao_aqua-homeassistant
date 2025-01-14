import asyncio
import json
from aiofiles import open as aio_open
from pathlib import Path
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from .const import DOMAIN, PLATFORMS, UPDATE_INTERVAL, LOGGER
from .api import GizwitsApi
from .discovery import discover_devices

PLATFORMS = ["switch", "binary_sensor", "select", "number"]

async def async_setup(hass: HomeAssistant, config: dict):
    """Set up the Jebao Pump component."""
    hass.data[DOMAIN] = {}  # Initialize the DOMAIN space in hass.data
    return True

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Set up the Jebao Aquarium Pumps integration."""
    # Load attribute models asynchronously for different products.
    models_path = Path(hass.config.path("custom_components/jebao_aqua/models"))
    attribute_models = {}
    for model_file in models_path.glob("*.json"):
        async with aio_open(model_file, mode="r") as file:
            content = await file.read()
            model = json.loads(content)
            attribute_models[model["product_key"]] = model
    LOGGER.debug("Loaded attribute models: %s", attribute_models)

    token = entry.data.get("token")
    if not token:
        LOGGER.error("API token not found in configuration entry")
        return False

    LOGGER.debug("Setting up API with token: %s", token)
    # Create a persistent API instance (without using async context managers)
    api = GizwitsApi(token)
    api.add_attribute_models(attribute_models)

    # Create the coordinator with the persistent API instance.
    coordinator = GizwitsDataUpdateCoordinator(hass, api)
    await coordinator.fetch_initial_device_list(entry)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "api": api,
        "coordinator": coordinator,
        "attribute_models": attribute_models,
    }

    # Optionally auto-discover devices.
    if entry.data.get("auto_discover"):
        discovered_devices = await discover_devices()
        if discovered_devices:
            hass.data[DOMAIN][entry.entry_id]["discovered_devices"] = discovered_devices
            LOGGER.debug("Discovered devices: %s", discovered_devices)

    # Forward entry setups to each platform.
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True

class GizwitsDataUpdateCoordinator(DataUpdateCoordinator):
    """Class to manage fetching data from the Gizwits API."""

    def __init__(self, hass, api):
        """Initialize."""
        super().__init__(hass, LOGGER, name=DOMAIN, update_interval=UPDATE_INTERVAL)
        self.api = api
        self.device_inventory = []  # List of devices.
        self.device_data = {}       # Dictionary of device status data.

    async def fetch_initial_device_list(self, entry: ConfigEntry):
        """Fetch the initial list of devices and add LAN IPs."""
        try:
            response = await self.api.get_devices()
            if response and "devices" in response:
                self.device_inventory = response["devices"]
                # Add LAN IPs from config entry
                config_devices = entry.data.get("devices", [])
                for device in self.device_inventory:
                    device_id = device.get("did")
                    matching_device = next(
                        (d for d in config_devices if d.get("did") == device_id), None
                    )
                    if matching_device:
                        device["lan_ip"] = matching_device.get("lan_ip")
                LOGGER.debug("Fetched device list with LAN IPs: %s", self.device_inventory)
            else:
                LOGGER.error("No 'devices' key in response")
        except Exception as e:
            LOGGER.error("Error fetching initial device list: %s", e)

    async def get_device_data(self, device_id):
        """Get device data either locally or from the cloud."""
        device_info = next((device for device in self.device_inventory if device["did"] == device_id), None)
        if device_info and "lan_ip" in device_info:
            return await self.api.get_local_device_data(device_info["lan_ip"], device_info["product_key"], device_id)
        else:
            return await self.api.get_device_data(device_id)

    async def _async_update_data(self):
        """Fetch the latest status for each device."""
        for device in self.device_inventory:
            device_id = device.get("did")
            try:
                self.device_data[device_id] = await self.get_device_data(device_id)
                LOGGER.debug("Updated device data: %s", self.device_data[device_id])
            except Exception as e:
                LOGGER.error("Error updating data for device %s: %s", device_id, e)
        return self.device_data

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry):
    unload_ok = all(
        await asyncio.gather(
            *[hass.config_entries.async_forward_entry_unload(entry, platform) for platform in PLATFORMS]
        )
    )
    if unload_ok:
        api = hass.data[DOMAIN][entry.entry_id]["api"]
        await api.close()
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok
