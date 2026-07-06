"""Helper functions for Jebao Aqua integration."""

import json
from pathlib import Path
from homeassistant.core import HomeAssistant
from .const import DOMAIN, LOGGER


def get_device_info(device):
    """Return standardized device information dictionary."""
    device_name = device.get("dev_alias") or f"Device {device['did']}"
    lan_ip = device.get("lan_ip")

    info = {
        "identifiers": {(DOMAIN, device["did"])},
        "name": device_name,
        "manufacturer": "Jebao",
    }

    if lan_ip:
        info["connections"] = {("ip", lan_ip)}

    return info


async def load_attribute_models(hass: HomeAssistant) -> dict:
    """Load attribute models asynchronously."""
    models_path = Path(hass.config.path("custom_components/jebao_aqua/models"))
    attribute_models = {}

    def _load_model(file_path):
        """Load a single model file."""
        with open(file_path, "r") as file:
            model = json.load(file)
            return model["product_key"], model

    def _get_model_files():
        """Get list of model files."""
        return list(models_path.glob("*.json"))

    # Load all model files in executor
    model_files = await hass.async_add_executor_job(_get_model_files)
    for model_file in model_files:
        try:
            product_key, model = await hass.async_add_executor_job(
                _load_model, model_file
            )
            attribute_models[product_key] = model
        except Exception as e:
            LOGGER.error(f"Error loading model file {model_file}: {e}")

    return attribute_models


def create_unique_id(device_id: str, attr_name: str) -> str:
    """Create standardized unique ID."""
    return f"{device_id}_{attr_name.replace(' ', '_').lower()}"


def is_device_data_valid(device_data: dict) -> bool:
    """Check if device data is valid."""
    if not device_data:
        return False
    if not isinstance(device_data, dict):
        return False
    if "attr" not in device_data:
        return False
    if not device_data.get("attr"):
        return False
    return True


def get_attribute_value(device_data: dict, attribute: str):
    """Safely get attribute value from device data."""
    if not is_device_data_valid(device_data):
        return None
    return device_data.get("attr", {}).get(attribute)
