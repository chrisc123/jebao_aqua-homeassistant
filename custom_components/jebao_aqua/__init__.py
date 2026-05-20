import asyncio
import json
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.config_entries import ConfigEntries  # Add this import
import async_timeout
from pathlib import Path
from homeassistant.helpers.entity_registry import async_get as async_get_entity_registry
from homeassistant.helpers.device_registry import async_get as async_get_device_registry

from .const import DOMAIN, PLATFORMS, UPDATE_INTERVAL, LOGGER, GIZWITS_API_URLS
from .api import GizwitsApi
from .discovery import discover_devices
from .helpers import is_device_data_valid  # Add this import

PLATFORMS = ["switch", "binary_sensor", "select", "number", "sensor"]


async def async_setup(hass: HomeAssistant, config: dict):
    """Set up the Jebao Pump component."""
    hass.data[DOMAIN] = {}  # Initialize the DOMAIN space in hass.data
    return True


async def load_attribute_models(hass: HomeAssistant) -> dict:
    """Load attribute models asynchronously."""
    models_path = Path(hass.config.path("custom_components/jebao_aqua/models"))
    attribute_models = {}

    def _load_model(file_path):
        """Load a single model file."""
        with open(file_path, "r") as file:
            model = json.load(file)
            return model["product_key"], model

    # Load all model files in executor
    for model_file in models_path.glob("*.json"):
        try:
            product_key, model = await hass.async_add_executor_job(
                _load_model, model_file
            )
            attribute_models[product_key] = model
        except Exception as e:
            LOGGER.error(f"Error loading model file {model_file}: {e}")

    return attribute_models


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Set up Jebao Pump from a config entry."""
    token = entry.data.get("token")
    region = entry.data.get("region")  # Get region from config entry

    if not token or not region:
        LOGGER.error("API token or region not found in configuration entry")
        return False

    # Load attribute models asynchronously
    attribute_models = await load_attribute_models(hass)
    LOGGER.debug(f"Setting up API object with token: {token} and region: {region}")

    # Initialize API with correct regional URLs
    api = GizwitsApi(
        login_url=GIZWITS_API_URLS[region]["LOGIN_URL"],
        devices_url=GIZWITS_API_URLS[region]["DEVICES_URL"],
        device_data_url=GIZWITS_API_URLS[region]["DEVICE_DATA_URL"],
        control_url=GIZWITS_API_URLS[region]["CONTROL_URL"],
        token=token,
    )

    # Initialize the API session (don't use async with - we need it to persist)
    await api.__aenter__()
    
    try:
        api.add_attribute_models(attribute_models)
        coordinator = GizwitsDataUpdateCoordinator(hass, api)
        await coordinator.fetch_initial_device_list(entry)

        try:
            await coordinator.async_config_entry_first_refresh()
        except Exception as err:
            LOGGER.error("Error setting up entry: %s", err)
            await api.__aexit__(None, None, None)
            raise ConfigEntryNotReady from err

        hass.data[DOMAIN][entry.entry_id] = {
            "api": api,
            "coordinator": coordinator,
            "attribute_models": attribute_models,
        }

        # Auto-discover devices in the background so it doesn't block startup.
        # Discovery always waits DISCOVERY_TIMEOUT seconds for broadcast responses,
        # so running it as a background task avoids adding that delay to setup.
        if entry.data.get("auto_discover", True):  # Default to True if not specified
            async def _background_discovery():
                discovered_devices = await discover_devices()
                if discovered_devices:
                    hass.data[DOMAIN][entry.entry_id]["discovered_devices"] = (
                        discovered_devices
                    )
                    LOGGER.debug(f"Discovered devices during setup: {discovered_devices}")

                    # Update coordinator's device inventory with discovered IPs
                    for device in coordinator.device_inventory:
                        device_id = device.get("did")
                        if device_id in discovered_devices:
                            device["lan_ip"] = discovered_devices[device_id]
                            LOGGER.debug(
                                f"Updated device {device_id} with discovered IP {discovered_devices[device_id]}"
                            )

            hass.async_create_task(_background_discovery())

        # Replace multiple async_forward_entry_setup calls with single async_forward_entry_setups
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

        return True
    except Exception as e:
        # Clean up API session if setup fails
        await api.__aexit__(None, None, None)
        raise


class GizwitsDataUpdateCoordinator(DataUpdateCoordinator):
    def __init__(self, hass, api):
        """Initialize."""
        super().__init__(hass, LOGGER, name=DOMAIN, update_interval=UPDATE_INTERVAL)
        self.api = api
        self.device_inventory = []
        self.device_data = {}
        self._device_update_locks = {}  # Add locks per device

    async def fetch_initial_device_list(self, entry: ConfigEntry):
        """Fetch the initial list of devices and add LAN IPs."""
        try:
            response = await self.api.get_devices()
            if response and "devices" in response:
                self.device_inventory = response["devices"]

                # Add LAN IPs from ConfigEntry
                config_devices = entry.data.get("devices", [])
                for device in self.device_inventory:
                    device_id = device.get("did")
                    # Find matching device in config entry data
                    matching_device = next(
                        (d for d in config_devices if d.get("did") == device_id), None
                    )
                    if matching_device:
                        device["lan_ip"] = matching_device.get("lan_ip")

                LOGGER.debug(
                    f"Fetched device list with LAN IPs: {self.device_inventory}"
                )
            else:
                LOGGER.error("No 'devices' key in response")
        except Exception as e:
            LOGGER.error(f"Error fetching initial device list: {e}")

    async def get_device_data(self, device_id):
        """Get device data either locally or from the cloud with lock protection."""
        # Get or create lock for this device
        if device_id not in self._device_update_locks:
            self._device_update_locks[device_id] = asyncio.Lock()

        async with self._device_update_locks[device_id]:
            device_info = next(
                (
                    device
                    for device in self.device_inventory
                    if device["did"] == device_id
                ),
                None,
            )
            
            # Try local first if we have IP and model
            if device_info and "lan_ip" in device_info:
                product_key = device_info.get("product_key")
                # Check if we have an attribute model for this device
                has_model = self.api._attribute_models and product_key in self.api._attribute_models
                
                if has_model:
                    LOGGER.debug(
                        f"Getting local data for device {device_id} at {device_info['lan_ip']}"
                    )
                    local_data = await self.api.get_local_device_data(
                        device_info["lan_ip"], product_key, device_id
                    )

                    if local_data and is_device_data_valid(local_data):
                        # Also fetch cloud data to pick up fields that only exist there
                        # (e.g. CHxSWTime schedule blobs, calibration history, timer config).
                        # The local LAN payload only encodes instantaneous run state (is the
                        # pump/channel actively running right now?).  Timer-enabled flags and
                        # other configuration attributes reported by the cloud are authoritative
                        # for their configured values; we must NOT let a local "False" (meaning
                        # "not running right now") overwrite a cloud "True" (meaning "enabled").
                        # Only override cloud with local for genuine live-state keys: the main
                        # power switch and the per-channel running status (channe*).
                        cloud_data = await self.api.get_device_data(device_id)
                        if cloud_data and is_device_data_valid(cloud_data):
                            LIVE_STATE_PREFIXES = ("switch", "channe", "SwitchON")
                            live_overrides = {
                                k: v for k, v in local_data["attr"].items()
                                if any(k == p or k.startswith(p) for p in LIVE_STATE_PREFIXES)
                            }
                            merged_attrs = {**cloud_data["attr"], **live_overrides}
                            data = {**cloud_data, "attr": merged_attrs}
                            LOGGER.debug(
                                f"Merged local+cloud for {device_id}: live overrides={list(live_overrides.keys())}"
                            )
                        else:
                            data = local_data
                    else:
                        LOGGER.warning(
                            f"Local data failed for {device_id}, falling back to cloud API"
                        )
                        data = await self.api.get_device_data(device_id)
                else:
                    LOGGER.info(
                        f"No attribute model for {device_id} (product_key: {product_key}), using cloud API"
                    )
                    data = await self.api.get_device_data(device_id)
            else:
                LOGGER.debug(f"Getting cloud data for device {device_id}")
                data = await self.api.get_device_data(device_id)

            if data:
                LOGGER.debug(f"Got data for device {device_id}: {data}")
            return data

    async def _async_update_data(self):
        """Fetch the latest status for each device."""
        new_data = {}

        async def update_single_device(device_id: str):
            """Update a single device's data."""
            try:
                device_data = await self.get_device_data(device_id)
                if device_data and isinstance(device_data.get("attr"), dict):
                    LOGGER.debug(
                        f"Got fresh data for device {device_id}: {device_data}"
                    )
                    return device_id, device_data
                elif device_id in self.device_data:
                    LOGGER.warning(f"Using cached data for device {device_id}")
                    return device_id, self.device_data[device_id]
                else:
                    LOGGER.warning(f"No valid data for device {device_id}")
                    return None, None
            except Exception as e:
                LOGGER.error(f"Error updating device {device_id}: {e}")
                if device_id in self.device_data:
                    return device_id, self.device_data[device_id]
                return None, None

        # Create tasks for all devices
        tasks = []
        for device in self.device_inventory:
            if device_id := device.get("did"):
                tasks.append(update_single_device(device_id))

        # Wait for all updates to complete
        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=False)

            # Process results and log them
            for device_id, data in results:
                if device_id and data:
                    new_data[device_id] = data
                    LOGGER.debug(
                        f"Successfully updated device {device_id} with data: {data}"
                    )

        if not new_data:
            LOGGER.error("No device data was updated successfully")
            # Instead of raising UpdateFailed, return last known good data if available
            if self.device_data:
                LOGGER.warning("Using last known good data")
                return self.device_data
            raise UpdateFailed("Failed to update any devices")

        LOGGER.debug(f"Final update data for all devices: {new_data}")
        self.device_data = new_data
        return new_data

    async def async_config_entry_first_refresh(self) -> None:
        """Perform first refresh and make sure we get valid data."""
        await self._async_refresh(log_failures=True)
        # Verify we have valid data after first refresh
        if not any(is_device_data_valid(data) for data in self.device_data.values()):
            raise ConfigEntryNotReady("No valid device data received during setup")


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    try:
        # First unload the platforms
        unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

        if unload_ok:
            # Close the API session
            if DOMAIN in hass.data and entry.entry_id in hass.data[DOMAIN]:
                api = hass.data[DOMAIN][entry.entry_id].get("api")
                if api:
                    await api.__aexit__(None, None, None)
            
            # Clean up the entity registry
            ent_reg = async_get_entity_registry(hass)
            entities = [
                entry_id
                for entry_id, entity_entry in ent_reg.entities.items()
                if entity_entry.config_entry_id == entry.entry_id
            ]

            # Remove all entities
            for entity_id in entities:
                ent_reg.async_remove(entity_id)

            # Clean up the device registry
            dev_reg = async_get_device_registry(hass)
            devices = [
                device_entry.id
                for device_entry in dev_reg.devices.values()
                if entry.entry_id in device_entry.config_entries
            ]

            # Remove all devices
            for device_id in devices:
                dev_reg.async_remove_device(device_id)

            # Clean up hass.data
            if DOMAIN in hass.data and entry.entry_id in hass.data[DOMAIN]:
                hass.data[DOMAIN].pop(entry.entry_id)

        return unload_ok
    except Exception as ex:
        LOGGER.error(f"Error unloading entry: {ex}")
        return False


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the config entry."""
    await async_unload_entry(hass, entry)
    await async_setup_entry(hass, entry)
