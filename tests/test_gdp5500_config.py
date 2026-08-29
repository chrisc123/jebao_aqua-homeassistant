"""Tests for the GDP-5500 device configuration."""

from __future__ import annotations

import json
from pathlib import Path
import unittest


ROOT = Path(__file__).parents[1]
INTEGRATION = ROOT / "custom_components" / "jebao_aqua"
MODE_OPTIONS = {
    "0": "constant_flow",
    "1": "pulse_wave",
    "2": "sine_wave",
    "3": "random_wave",
    "4": "feeding",
}
PRODUCT_KEY = "0696a19599bc484f8e1866f5ccf4ee7e"


def load_json(path: Path) -> dict:
    """Load a repository JSON file."""
    return json.loads(path.read_text(encoding="utf-8-sig"))


class Gdp5500ConfigTest(unittest.TestCase):
    """Test the model, entity configuration, and option translations."""

    @classmethod
    def setUpClass(cls) -> None:
        """Load the GDP-5500 definition and device configuration."""
        cls.model = load_json(INTEGRATION / "models" / f"{PRODUCT_KEY}.json")
        configs = load_json(INTEGRATION / "models" / "device_configs.json")
        cls.config = configs["device_configs"][PRODUCT_KEY]
        cls.attrs = {
            attr["name"]: attr for attr in cls.model["entities"][0]["attrs"]
        }

    def test_configured_entities_exist_in_model(self) -> None:
        """Every exposed GDP-5500 entity has a matching Gizwits datapoint."""
        for platform, names in self.config["platforms"].items():
            if platform == "select_value_maps":
                continue
            with self.subTest(platform=platform):
                self.assertLessEqual(set(names), self.attrs.keys())

    def test_mode_and_automode_use_clamped_uint8_select_maps(self) -> None:
        """Mode/AutoMode are named selects; the vendor's 0..255 range is
        clamped to the 5 documented values (0..4)."""
        platforms = self.config["platforms"]

        for attr_name in ("Mode", "AutoMode"):
            with self.subTest(attr=attr_name):
                attr = self.attrs[attr_name]
                self.assertNotIn(attr_name, platforms["number"])
                self.assertIn(attr_name, platforms["select"])
                self.assertEqual(
                    MODE_OPTIONS, platforms["select_value_maps"][attr_name]
                )
                self.assertEqual("uint8", attr["data_type"])
                self.assertEqual("status_writable", attr["type"])
                self.assertEqual(0, attr["uint_spec"]["min"])
                self.assertEqual(4, attr["uint_spec"]["max"])

    def test_mode_options_have_translations(self) -> None:
        """Every configured Mode option is present in source and locale
        strings."""
        translation_files = (
            INTEGRATION / "strings.json",
            INTEGRATION / "translations" / "en.json",
            INTEGRATION / "translations" / "es.json",
        )

        for path in translation_files:
            states = load_json(path)["entity"]["select"]["mode"]["state"]
            with self.subTest(path=path):
                self.assertLessEqual(set(MODE_OPTIONS.values()), states.keys())

    def test_automode_options_have_translations(self) -> None:
        """Every configured AutoMode option is present in source and locale
        strings."""
        translation_files = (
            INTEGRATION / "strings.json",
            INTEGRATION / "translations" / "en.json",
            INTEGRATION / "translations" / "es.json",
        )

        for path in translation_files:
            states = load_json(path)["entity"]["select"]["automode"]["state"]
            with self.subTest(path=path):
                self.assertLessEqual(set(MODE_OPTIONS.values()), states.keys())


if __name__ == "__main__":
    unittest.main()
