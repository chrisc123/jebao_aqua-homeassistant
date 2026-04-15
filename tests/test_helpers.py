"""L2/L3 tests for Jebao Aqua helper functions."""

import pytest

from custom_components.jebao_aqua.helpers import (
    get_device_info,
    create_entity_name,
    create_entity_id,
    create_unique_id,
    is_device_data_valid,
    get_attribute_value,
)
from custom_components.jebao_aqua.const import DOMAIN


class TestGetDeviceInfo:
    def test_basic_device_info(self):
        device = {"did": "dev001", "dev_alias": "My Pump", "product_key": "pk1"}
        info = get_device_info(device)
        assert info["name"] == "My Pump"
        assert (DOMAIN, "dev001") in info["identifiers"]
        assert info["manufacturer"] == "Jebao"

    def test_device_info_without_alias(self):
        device = {"did": "dev002", "product_key": "pk1"}
        info = get_device_info(device)
        assert info["name"] == "Device dev002"

    def test_device_info_with_lan_ip(self):
        device = {"did": "dev003", "dev_alias": "Pump", "lan_ip": "192.168.1.5"}
        info = get_device_info(device)
        assert ("ip", "192.168.1.5") in info["connections"]

    def test_device_info_without_lan_ip(self):
        device = {"did": "dev004", "dev_alias": "Pump"}
        info = get_device_info(device)
        assert "connections" not in info


class TestCreateEntityName:
    def test_returns_attr_name(self):
        assert create_entity_name("My Pump", "Switch") == "Switch"

    def test_returns_attr_name_regardless_of_device(self):
        assert create_entity_name("Anything", "Flow Rate") == "Flow Rate"


class TestCreateEntityId:
    def test_formats_correctly(self):
        result = create_entity_id("switch", "My Pump", "SwitchON")
        assert result == "switch.my_pump_switchon"

    def test_handles_spaces(self):
        result = create_entity_id("number", "Test Device", "Flow Rate")
        assert result == "number.test_device_flow_rate"


class TestCreateUniqueId:
    def test_formats_correctly(self):
        result = create_unique_id("dev001", "SwitchON")
        assert result == "dev001_switchon"

    def test_handles_spaces(self):
        result = create_unique_id("dev001", "Flow Rate")
        assert result == "dev001_flow_rate"


class TestIsDeviceDataValid:
    def test_valid_data(self):
        assert is_device_data_valid({"attr": {"SwitchON": True}}) is True

    def test_none(self):
        assert is_device_data_valid(None) is False

    def test_empty_dict(self):
        assert is_device_data_valid({}) is False

    def test_missing_attr(self):
        assert is_device_data_valid({"other": "data"}) is False

    def test_empty_attr(self):
        assert is_device_data_valid({"attr": {}}) is False

    def test_not_a_dict(self):
        assert is_device_data_valid("string") is False


class TestGetAttributeValue:
    def test_returns_value(self):
        data = {"attr": {"Flow": 75}}
        assert get_attribute_value(data, "Flow") == 75

    def test_returns_none_for_missing_attr(self):
        data = {"attr": {"Flow": 75}}
        assert get_attribute_value(data, "Missing") is None

    def test_returns_none_for_invalid_data(self):
        assert get_attribute_value(None, "Flow") is None
        assert get_attribute_value({}, "Flow") is None
