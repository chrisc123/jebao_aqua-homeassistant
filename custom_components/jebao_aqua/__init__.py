import asyncio
import json
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator, UpdateFailed
)
import async_timeout
from pathlib import Path

from .const import DOMAIN, PLATFORMS, UPDATE_INTERVAL, LOGGER
from .api import GizwitsApi
from .discovery import discover_devices

PLATFORMS = ["switch", "binary_sensor", "select", "number"]

async def async_setup(hass: HomeAssistant, config: dict):
    """Set up the Jebao Pump component."""
    hass.data[DOMAIN] = {}  # Initialize the DOMAIN space in hass.data
    return True

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
    # Load attribute models for different products
    models_path = Path(hass.config.path('custom_components/jebao_aqua/models'))
    attribute_models = {}
    for model_file in models_path.glob('*.json'):
        with open(model_file, 'r') as file:
            model = json.load(file)
            attribute_models[model['product_key']] = model
    LOGGER.debug("Attribute model: %s", attribute_models)

    token = entry.data.get("token")
    if not token:
        LOGGER.error("API token not found in configuration entry")
        return False

    LOGGER.debug(f"Setting up API object with token: {token}")
    
    async with GizwitsApi(token) as api:
        api.add_attribute_models(attribute_models)
        coordinator = GizwitsDataUpdateCoordinator(hass, api)
        await coordinator.fetch_initial_device_list(entry)

        LOGGER.debug(f"Trying to get data")
        await coordinator.async_config_entry_first_refresh()
        LOGGER.debug(f"First refresh completed..")

        if entry.entry_id not in hass.data[DOMAIN]:
            hass.data[DOMAIN][entry.entry_id] = {
                "api": api,
                "coordinator": coordinator,
                "attribute_models": attribute_models
            }

        # Auto-discover devices and update config entry if needed
        if entry.data.get("auto_discover"):
            discovered_devices = await discover_devices()
            if discovered_devices:
                hass.data[DOMAIN][entry.entry_id]["discovered_devices"] = discovered_devices
                LOGGER.debug(f"Discovered devices: {discovered_devices}")

        for platform in PLATFORMS:
            hass.async_create_task(
                hass.config_entries.async_forward_entry_setup(entry, platform)
            )

    return True

class GizwitsDataUpdateCoordinator(DataUpdateCoordinator):
    def __init__(self, hass, api):
        """Initialize."""
        super().__init__(hass, LOGGER, name=DOMAIN, update_interval=UPDATE_INTERVAL)
        self.api = api
        self.device_inventory = []  # List of devices
        self.device_data = {}       # Dictionary of device status data

    async def fetch_initial_device_list(self, entry: ConfigEntry):
        """Fetch the initial list of devices and add LAN IPs."""
        try:
            response = await self.api.get_devices()
            if response and "devices" in response:
                self.device_inventory = response["devices"]
                
                # Add LAN IPs from ConfigEntry
                config_devices = entry.data.get('devices', [])
                for device in self.device_inventory:
                    device_id = device.get('did')
                    # Find matching device in config entry data
                    matching_device = next((d for d in config_devices if d.get('did') == device_id), None)
                    if matching_device:
                        device['lan_ip'] = matching_device.get('lan_ip')

                LOGGER.debug(f"Fetched device list with LAN IPs: {self.device_inventory}")
            else:
                LOGGER.error("No 'devices' key in response")
        except Exception as e:
            LOGGER.error(f"Error fetching initial device list: {e}")

    async def get_device_data(self, device_id):
        """Get device data either locally or from the cloud."""
        device_info = next((device for device in self.device_inventory if device['did'] == device_id), None)
        if device_info and 'lan_ip' in device_info:
            return await self.api.get_local_device_data(device_info['lan_ip'], device_info['product_key'], device_id)
        else:
            return await self.api.get_device_data(device_id)
            
    async def _async_update_data(self):
        """Fetch the latest status for each device."""
        for device in self.device_inventory:
            device_id = device.get('did')
            try:
                self.device_data[device_id] = await self.get_device_data(device_id)
                LOGGER.debug(f"Coordinator ran _async_update_data and updated device data: {self.device_data[device_id]}")
            except Exception as e:
                LOGGER.error(f"Error updating data for device {device_id}: {e}")
        return self.device_data

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Unload a config entry."""
    unload_ok = all(
        await asyncio.gather(
            *[
                hass.config_entries.async_forward_entry_unload(entry, platform)
                for platform in PLATFORMS
            ]
        )
    )
    if unload_ok:
        api = hass.data[DOMAIN][entry.entry_id]["api"]
        await api.close()
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok
