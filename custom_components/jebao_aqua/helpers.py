"""Helper functions for Jebao Aqua integration."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo

from .const import DOMAIN, LOGGER


def get_device_info(device: dict[str, Any]) -> DeviceInfo:
    """Return standardized device information dictionary.
    
    Args:
        device: Device dictionary containing device metadata
        
    Returns:
        DeviceInfo dictionary for Home Assistant device registry
    """
    device_name = device.get("dev_alias") or f"Device {device['did']}"
    lan_ip = device.get("lan_ip")

    info: DeviceInfo = {
        "identifiers": {(DOMAIN, device["did"])},
        "name": device_name,
        "manufacturer": "Jebao",
    }

    if lan_ip:
        info["connections"] = {("ip", lan_ip)}

    return info


async def load_attribute_models(hass: HomeAssistant) -> dict[str, dict[str, Any]]:
    """Load attribute models asynchronously.
    
    Args:
        hass: Home Assistant instance
        
    Returns:
        Dictionary mapping product_key to model configuration
    """
    models_path = Path(hass.config.path("custom_components/jebao_aqua/models"))
    attribute_models: dict[str, dict[str, Any]] = {}

    def _load_model(file_path: Path) -> tuple[str, dict[str, Any]]:
        """Load a single model file.
        
        Args:
            file_path: Path to model JSON file
            
        Returns:
            Tuple of (product_key, model_data)
        """
        with open(file_path, "r", encoding="utf-8") as file:
            model = json.load(file)
            return model["product_key"], model

    def _get_model_files() -> list[Path]:
        """Get list of model files.
        
        Returns:
            List of Path objects for model JSON files
        """
        return list(models_path.glob("*.json"))

    # Load all model files in executor
    model_files = await hass.async_add_executor_job(_get_model_files)
    for model_file in model_files:
        try:
            product_key, model = await hass.async_add_executor_job(
                _load_model, model_file
            )
            attribute_models[product_key] = model
        except Exception:
            LOGGER.exception("Error loading model file %s", model_file)

    return attribute_models


def create_unique_id(device_id: str, attr_name: str) -> str:
    """Create standardized unique ID for entities.
    
    Args:
        device_id: Device identifier
        attr_name: Attribute name
        
    Returns:
        Unique ID string for the entity
    """
    return f"{device_id}_{attr_name.replace(' ', '_').lower()}"


def is_device_data_valid(device_data: dict[str, Any] | None) -> bool:
    """Check if device data is valid and contains required fields.
    
    Args:
        device_data: Device data dictionary from API
        
    Returns:
        True if data is valid, False otherwise
    """
    if not device_data:
        return False
    if not isinstance(device_data, dict):
        return False
    if "attr" not in device_data:
        return False
    if not device_data.get("attr"):
        return False
    return True


def get_attribute_value(device_data: dict[str, Any] | None, attribute: str) -> Any:
    """Safely get attribute value from device data.
    
    Args:
        device_data: Device data dictionary from API
        attribute: Attribute name to retrieve
        
    Returns:
        Attribute value or None if not found/invalid
    """
    if not is_device_data_valid(device_data):
        return None
    return device_data.get("attr", {}).get(attribute)
