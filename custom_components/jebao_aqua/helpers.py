"""Helper functions for Jebao Aqua integration."""

import json
from pathlib import Path
from typing import Optional, Dict
from homeassistant.core import HomeAssistant
from .const import DOMAIN, LOGGER


def get_device_info(device):
    """Return standardized device information dictionary."""
    device_name = device.get("dev_alias") or f"Device {device['did']}"
    lan_ip = device.get("lan_ip")
    product_key = device.get("product_key", "")

    info = {
        "identifiers": {(DOMAIN, device["did"])},
        "name": device_name,
        "manufacturer": "Jebao",
    }

    if lan_ip:
        info["connections"] = {("ip", lan_ip)}

    LOGGER.debug(f"Device info for {device_name}: {info}")
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


def create_entity_name(device_name: str, attr_name: str) -> str:
    """Create standardized entity name."""
    # Only return the attribute name since we're using has_entity_name = True
    return attr_name


def create_entity_id(platform: str, device_name: str, attr_name: str) -> str:
    """Create standardized entity ID."""
    device_name_underscore = device_name.replace(" ", "_").lower()
    attr_name_underscore = attr_name.replace(" ", "_").lower()
    return f"{platform}.{device_name_underscore}_{attr_name_underscore}"


def create_unique_id(device_id: str, attr_name: str) -> str:
    """Create standardized unique ID."""
    return f"{device_id}_{attr_name.replace(' ', '_').lower()}"


def is_device_data_valid(device_data: Optional[Dict]) -> bool:
    """Validate the data structure has the expected format.

    This is used for:
    1. Validating data structure for safe attribute access
    2. Validating initial setup has returned proper data format
    """
    return (
        isinstance(device_data, dict)
        and isinstance(device_data.get('attr'), dict)
    )


def get_attribute_value(device_data: dict, attribute: str):
    """Safely get attribute value from device data."""
    if not is_device_data_valid(device_data):
        return None
    return device_data["attr"].get(attribute)
