"""Tests for select value mapping."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


MODULE_PATH = (
    Path(__file__).parents[1]
    / "custom_components"
    / "jebao_aqua"
    / "select_mapping.py"
)
SPEC = importlib.util.spec_from_file_location("jebao_select_mapping", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
SelectValueMap = MODULE.SelectValueMap


class SelectValueMapTest(unittest.TestCase):
    """Test enum and configured numeric select mappings."""

    def test_native_enum_behavior_is_preserved(self) -> None:
        """Native enums accept indexes, device strings, slugs, and numeric strings."""
        mapping = SelectValueMap.from_enum(
            ["停机", "正弦造浪", "unmapped"],
            {"停机": "off", "正弦造浪": "sine_wave"},
        )

        self.assertEqual(["off", "sine_wave", "unmapped"], mapping.options)
        self.assertEqual(1, mapping.value_for_option("sine_wave"))
        self.assertEqual("sine_wave", mapping.option_for_value(1))
        self.assertEqual("sine_wave", mapping.option_for_value("1"))
        self.assertEqual("sine_wave", mapping.option_for_value("正弦造浪"))
        self.assertEqual("sine_wave", mapping.option_for_value("sine_wave"))

    def test_configured_numeric_values_are_sorted_and_bidirectional(self) -> None:
        """Configured mappings provide stable options and device write values."""
        mapping = SelectValueMap.from_config(
            {"8": "custom_wave", "0": "pulse_wave", "2": "constant_flow"}
        )

        self.assertEqual(
            ["pulse_wave", "constant_flow", "custom_wave"], mapping.options
        )
        self.assertEqual(0, mapping.value_for_option("pulse_wave"))
        self.assertEqual(8, mapping.value_for_option("custom_wave"))
        self.assertEqual("constant_flow", mapping.option_for_value(2))
        self.assertEqual("custom_wave", mapping.option_for_value("custom_wave"))

    def test_numeric_string_status(self) -> None:
        """Cloud numeric strings resolve like LAN integer values."""
        mapping = SelectValueMap.from_config({"0": "off", "8": "custom_wave"})

        self.assertEqual("custom_wave", mapping.option_for_value("8"))

    def test_invalid_configurations_are_rejected(self) -> None:
        """Malformed or ambiguous configured mappings fail validation."""
        invalid_maps = (
            None,
            [],
            {},
            {"invalid": "option"},
            {"-1": "option"},
            {"256": "option"},
            {"0": ""},
            {"0": 0},
            {"0": "Invalid option"},
            {"0": "same", "1": "same"},
            {"1": "one", "01": "also_one"},
        )

        for raw_value_map in invalid_maps:
            with self.subTest(raw_value_map=raw_value_map):
                with self.assertRaises(ValueError):
                    SelectValueMap.from_config(raw_value_map)

    def test_unknown_values_have_no_current_option(self) -> None:
        """Unexpected status values do not select an incorrect option."""
        mapping = SelectValueMap.from_config({"0": "off", "1": "on"})

        for raw_value in (2, "2", "unknown", True, None):
            with self.subTest(raw_value=raw_value):
                self.assertIsNone(mapping.option_for_value(raw_value))
        self.assertIsNone(mapping.value_for_option("unknown"))


if __name__ == "__main__":
    unittest.main()
