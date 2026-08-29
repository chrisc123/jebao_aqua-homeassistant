"""Tests for the GMP-40 device configuration."""

from __future__ import annotations

import json
from pathlib import Path
import unittest


ROOT = Path(__file__).parents[1]
INTEGRATION = ROOT / "custom_components" / "jebao_aqua"
MODE_OPTIONS = {
    "0": "pulse_wave",
    "1": "sine_wave",
    "2": "constant_flow",
    "3": "random_wave",
    "4": "tide",
    "5": "nutrient_transport",
    "6": "circulation",
    "7": "feeding",
    "8": "custom_wave",
}
LINKAGE_OPTIONS = {
    "independent",
    "primary",
    "synchronous_secondary",
    "asynchronous_secondary",
}
PRODUCT_KEY = "50dbc92221fd4d33ae69a1fedd43b555"


def load_json(path: Path) -> dict:
    """Load a repository JSON file."""
    return json.loads(path.read_text(encoding="utf-8-sig"))


class Gmp40ConfigTest(unittest.TestCase):
    """Test the model, entity configuration, and option translations."""

    @classmethod
    def setUpClass(cls) -> None:
        """Load the GMP-40 definition and device configuration."""
        cls.model = load_json(INTEGRATION / "models" / f"{PRODUCT_KEY}.json")
        configs = load_json(INTEGRATION / "models" / "device_configs.json")
        cls.config = configs["device_configs"][PRODUCT_KEY]
        cls.attrs = {
            attr["name"]: attr for attr in cls.model["entities"][0]["attrs"]
        }

    def test_configured_entities_exist_in_model(self) -> None:
        """Every exposed GMP-40 entity has a matching Gizwits datapoint."""
        for platform, names in self.config["platforms"].items():
            if platform == "select_value_maps":
                continue
            with self.subTest(platform=platform):
                self.assertLessEqual(set(names), self.attrs.keys())

    def test_mode_uses_complete_uint8_select_map(self) -> None:
        """Mode is exposed as the documented named select with values 0..8."""
        platforms = self.config["platforms"]
        mode_attr = self.attrs["Mode"]

        self.assertNotIn("Mode", platforms["number"])
        self.assertIn("Mode", platforms["select"])
        self.assertEqual(MODE_OPTIONS, platforms["select_value_maps"]["Mode"])
        self.assertEqual("uint8", mode_attr["data_type"])
        self.assertEqual("status_writable", mode_attr["type"])
        self.assertEqual(0, mode_attr["uint_spec"]["min"])
        self.assertEqual(8, mode_attr["uint_spec"]["max"])

    def test_mode_options_have_translations(self) -> None:
        """Every configured option is present in source and locale strings."""
        translation_files = (
            INTEGRATION / "strings.json",
            INTEGRATION / "translations" / "en.json",
            INTEGRATION / "translations" / "es.json",
        )

        for path in translation_files:
            states = load_json(path)["entity"]["select"]["mode"]["state"]
            with self.subTest(path=path):
                self.assertLessEqual(set(MODE_OPTIONS.values()), states.keys())

    def test_linkage_options_have_translations(self) -> None:
        """Every GMP-40 linkage option is present in each locale."""
        translation_files = (
            INTEGRATION / "strings.json",
            INTEGRATION / "translations" / "en.json",
            INTEGRATION / "translations" / "es.json",
        )

        for path in translation_files:
            states = load_json(path)["entity"]["select"]["linkage"]["state"]
            with self.subTest(path=path):
                self.assertLessEqual(LINKAGE_OPTIONS, states.keys())


if __name__ == "__main__":
    unittest.main()
