"""Shared fixtures for Jebao Aqua integration tests."""

import json
import pathlib
import sys
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.core import HomeAssistant

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.jebao_aqua.const import DOMAIN


# ---------------------------------------------------------------------------
# Remove editable-install namespace placeholder from sys.path so that
# homeassistant.loader._get_custom_components can iterate
# custom_components.__path__ without hitting a FileNotFoundError on the
# fake "__editable__….__path_hook__" entry injected by the editable install.
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session", autouse=True)
def clean_editable_namespace_path():
    """Strip non-existent editable-install placeholders from sys.path."""
    placeholders = [p for p in sys.path if not pathlib.Path(p).exists()]
    # Rebuild sys.path without the invalid placeholders
    sys.path[:] = [p for p in sys.path if pathlib.Path(p).exists()]
    yield
    # Restore on teardown so we don't affect other test sessions
    sys.path.extend(placeholders)


# ---------------------------------------------------------------------------
# Auto-enable custom integrations for all tests in this directory
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable custom integrations for all tests."""
    yield


# ---------------------------------------------------------------------------
# Test constants
# ---------------------------------------------------------------------------

MOCK_PRODUCT_KEY = "f0d844ab0d4947ac9527a286160bc705"
MOCK_DEVICE_ID = "mock_device_001"
MOCK_DEVICE_ALIAS = "Test Pump"
MOCK_TOKEN = "test_token_abc123"
MOCK_EMAIL = "test@example.com"
MOCK_PASSWORD = "testpass123"
MOCK_REGION = "eu"
MOCK_COUNTRY = "GB"
MOCK_LAN_IP = "192.168.1.100"


# ---------------------------------------------------------------------------
# Attribute model (trimmed version of a real model for testing)
# ---------------------------------------------------------------------------

MOCK_ATTRIBUTE_MODEL = {
    "product_key": MOCK_PRODUCT_KEY,
    "attrs": [
        {
            "display_name": "Switch",
            "name": "SwitchON",
            "data_type": "bool",
            "position": {"byte_offset": 0, "unit": "bit", "len": 1, "bit_offset": 0},
            "type": "status_writable",
            "id": 0,
            "desc": ["Off", "On"],
        },
        {
            "display_name": "Feed Switch",
            "name": "FeedSwitch",
            "data_type": "bool",
            "position": {"byte_offset": 0, "unit": "bit", "len": 1, "bit_offset": 2},
            "type": "status_writable",
            "id": 2,
            "desc": ["Off", "On"],
        },
        {
            "display_name": "Mode",
            "name": "Mode",
            "data_type": "enum",
            "enum": ["经典造浪", "正弦造浪", "随机造浪", "恒流造浪"],
            "position": {"byte_offset": 0, "unit": "bit", "len": 2, "bit_offset": 5},
            "type": "status_writable",
            "id": 5,
            "desc": ["Classic Wave", "Sine Wave", "Random Wave", "Constant Current Wave"],
        },
        {
            "display_name": "Flow",
            "name": "Flow",
            "data_type": "uint8",
            "position": {"byte_offset": 2, "unit": "byte", "len": 1, "bit_offset": 0},
            "uint_spec": {"addition": 0, "max": 100, "ratio": 1, "min": 30},
            "type": "status_writable",
            "id": 8,
            "desc": ["Flow Value"],
        },
        {
            "display_name": "Frequency",
            "name": "Frequency",
            "data_type": "uint8",
            "position": {"byte_offset": 3, "unit": "byte", "len": 1, "bit_offset": 0},
            "uint_spec": {"addition": 0, "max": 100, "ratio": 1, "min": 0},
            "type": "status_writable",
            "id": 9,
            "desc": ["Frequency Value"],
        },
        {
            "display_name": "Motor Overcurrent",
            "name": "Fault_Overcurrent",
            "data_type": "bool",
            "position": {"byte_offset": 392, "unit": "bit", "len": 1, "bit_offset": 0},
            "type": "fault",
            "id": 62,
            "desc": ["Motor current too high, including short circuit fault"],
        },
        {
            "display_name": "Motor Overvoltage",
            "name": "Fault_Overvoltage",
            "data_type": "bool",
            "position": {"byte_offset": 392, "unit": "bit", "len": 1, "bit_offset": 1},
            "type": "fault",
            "id": 63,
            "desc": ["Motor Overvoltage"],
        },
    ],
}


MOCK_DEVICE = {
    "did": MOCK_DEVICE_ID,
    "dev_alias": MOCK_DEVICE_ALIAS,
    "product_key": MOCK_PRODUCT_KEY,
    "lan_ip": MOCK_LAN_IP,
    "is_online": True,
    "mac": "AA:BB:CC:DD:EE:FF",
}


MOCK_DEVICE_DATA = {
    MOCK_DEVICE_ID: {
        "did": MOCK_DEVICE_ID,
        "attr": {
            "SwitchON": True,
            "FeedSwitch": False,
            "Mode": "经典造浪",
            "Flow": 75,
            "Frequency": 50,
            "Fault_Overcurrent": False,
            "Fault_Overvoltage": False,
        },
    }
}


def make_config_entry_data() -> dict:
    """Return a config entry data dict matching what the config flow produces."""
    return {
        "token": MOCK_TOKEN,
        "email": MOCK_EMAIL,
        "password": MOCK_PASSWORD,
        "region": MOCK_REGION,
        "country": MOCK_COUNTRY,
        "devices": [
            {
                "did": MOCK_DEVICE_ID,
                "dev_alias": MOCK_DEVICE_ALIAS,
                "product_key": MOCK_PRODUCT_KEY,
                "lan_ip": MOCK_LAN_IP,
            }
        ],
    }


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_config_entry() -> MockConfigEntry:
    """Create a mock config entry."""
    return MockConfigEntry(
        domain=DOMAIN,
        data=make_config_entry_data(),
        title="Jebao Aquarium Pumps",
        unique_id=MOCK_EMAIL,
    )


@pytest.fixture
def mock_api():
    """Create a mocked GizwitsApi instance."""
    api = AsyncMock()
    api.get_devices = AsyncMock(return_value={"devices": [MOCK_DEVICE.copy()]})
    api.get_device_data = AsyncMock(
        return_value=MOCK_DEVICE_DATA[MOCK_DEVICE_ID].copy()
    )
    api.get_local_device_data = AsyncMock(
        return_value=MOCK_DEVICE_DATA[MOCK_DEVICE_ID].copy()
    )
    api.control_device = AsyncMock(return_value={"ok": True})
    api.async_init_session = AsyncMock()
    api.close = AsyncMock()
    api.add_attribute_models = MagicMock()
    api._attribute_models = {MOCK_PRODUCT_KEY: MOCK_ATTRIBUTE_MODEL}
    api.async_login = AsyncMock(return_value=(MOCK_TOKEN, None))
    api.set_token = MagicMock()
    return api


@pytest.fixture
def mock_attribute_models():
    """Return attribute models keyed by product_key."""
    return {MOCK_PRODUCT_KEY: MOCK_ATTRIBUTE_MODEL}


@pytest.fixture
async def mock_setup_entry(hass: HomeAssistant, mock_config_entry, mock_api, mock_attribute_models):
    """Set up the integration with mocked API - returns coordinator for direct inspection."""
    mock_config_entry.add_to_hass(hass)

    with patch(
        "custom_components.jebao_aqua.GizwitsApi",
        return_value=mock_api,
    ), patch(
        "custom_components.jebao_aqua.load_attribute_models",
        return_value=mock_attribute_models,
    ), patch(
        "custom_components.jebao_aqua.discover_devices",
        return_value={},
    ):
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    return hass.data[DOMAIN][mock_config_entry.entry_id]
