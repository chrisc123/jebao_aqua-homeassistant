"""Tests for return pump commands and schedules."""

from __future__ import annotations

from datetime import datetime
import importlib.util
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).parents[1]
INTEGRATION = ROOT / "custom_components" / "jebao_aqua"


def _load(name: str, path: Path, **kwargs):
    spec = importlib.util.spec_from_file_location(name, path, **kwargs)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


pump = _load("jebao_pump_program", INTEGRATION / "pump_program.py")
_load(
    "gizwits_lan_program",
    INTEGRATION / "gizwits_lan" / "__init__.py",
    submodule_search_locations=[str(INTEGRATION / "gizwits_lan")],
)
Device = sys.modules["gizwits_lan_program.device"].Device

NOON = datetime(2026, 11, 5, 12, 0)
PRODUCT_KEYS = ("6a5c47b3ea364ecb841b47f5997a1775", "02039876751049deb404d1d89221ec4b")


def attrs() -> list[dict]:
    model = json.loads(
        (INTEGRATION / "models" / f"{PRODUCT_KEYS[0]}.json").read_text(encoding="utf-8-sig")
    )
    return [attr for entity in model["entities"] for attr in entity["attrs"]]


def encode(updates: dict) -> bytes:
    """Attribute flags + values of the write for these updates."""
    device = Device(ip="127.0.0.1", attributes=attrs())
    writable = {attr["name"]: attr for attr in device.writable_attrs}
    flags = bytearray(8)
    values = bytearray(301)
    for name, value in updates.items():
        device._set_one_writable_attribute(writable[name], value, flags, values)
    return bytes(flags + values)


class CommandTest(unittest.TestCase):
    def test_speed_ends_a_running_schedule(self) -> None:
        self.assertEqual(
            {"Motor_Speed": 60, "TimerON": False},
            pump.command_updates("Motor_Speed", 60, {"TimerON": True}, NOON),
        )
        self.assertEqual(
            {"Motor_Speed": 60},
            pump.command_updates("Motor_Speed", 60, {"TimerON": False}, NOON),
        )

    def test_schedule_on_writes_the_active_slot(self) -> None:
        status = {pump.slot_name(0): bytes((8, 0, 20, 0, 1, 70))}
        self.assertEqual(
            {"TimerON": True, "FeedSwitch": False, "AutoMode": 1, "AutoGears": 70},
            pump.command_updates("TimerON", True, status, NOON),
        )

    def test_schedule_on_outside_any_slot(self) -> None:
        status = {pump.slot_name(0): bytes((1, 0, 2, 0, 1, 70))}
        self.assertEqual(
            {"TimerON": True, "FeedSwitch": False, "AutoMode": 0},
            pump.command_updates("TimerON", True, status, NOON),
        )

    def test_schedule_off_keeps_the_speed(self) -> None:
        self.assertEqual(
            {"TimerON": False, "Motor_Speed": 50},
            pump.command_updates("TimerON", False, {"Motor_Speed": 50}, NOON),
        )

    def test_feed(self) -> None:
        status = {"Motor_Speed": 50, "FeedTime": 10, "FeedSwitch": False}
        self.assertEqual(
            {"FeedSwitch": True, "TimerON": False, "FeedTime": 10},
            pump.command_updates("FeedSwitch", True, status, NOON),
        )
        self.assertEqual(
            {"FeedSwitch": False, "TimerON": False, "FeedTime": 10, "Motor_Speed": 50},
            pump.command_updates("FeedSwitch", False, status, NOON),
        )
        self.assertEqual(
            {"FeedTime": 20, "FeedSwitch": False},
            pump.command_updates("FeedTime", 20, status, NOON),
        )

    def test_other_datapoints_pass_through(self) -> None:
        self.assertEqual(
            {"SwitchON": True}, pump.command_updates("SwitchON", True, {}, NOON)
        )


class FrameTest(unittest.TestCase):
    """The flags byte of ids 0-7 is the classic pump opcode."""

    def assert_write(self, updates: dict, flags: int, *values: int) -> None:
        payload = encode(updates)
        self.assertEqual(309, len(payload))
        self.assertEqual(bytes(7) + bytes([flags]), payload[:8])
        self.assertEqual(bytes(values), payload[8 : 8 + len(values)])

    def test_classic_frames(self) -> None:
        self.assert_write({"SwitchON": True}, 0x01, 1)
        self.assert_write({"SwitchON": False}, 0x01, 0)
        self.assert_write({"Motor_Speed": 60}, 0x20, 0, 60)
        self.assert_write({"Motor_Speed": 60, "TimerON": False}, 0x28, 0, 60)
        self.assert_write(
            {"FeedSwitch": True, "TimerON": False, "FeedTime": 10}, 0x4C, 4, 0, 10
        )
        self.assert_write(
            {"FeedSwitch": False, "TimerON": False, "FeedTime": 10, "Motor_Speed": 50},
            0x6C,
            0,
            50,
            10,
        )

    def test_clock(self) -> None:
        payload = encode(pump.clock_updates(datetime(2026, 11, 5, 3, 17, 9)))
        self.assertEqual(bytes(6) + bytes((0x06, 0x00)), payload[:8])
        self.assertEqual(bytes((20, 26, 11, 5, 0, 3, 17, 9)), payload[8 + 5 : 8 + 13])

    def test_schedule_fills_all_slots(self) -> None:
        slots = pump.parse_slots([{"start": "08:00", "end": "20:00", "speed": 70}])
        payload = encode(pump.schedule_updates(slots))
        self.assertEqual(bytes((0x07,)) + b"\xff" * 5 + bytes((0xf8, 0x00)), payload[:8])
        self.assertEqual(bytes((8, 0, 20, 0, 1, 70)), payload[8 + 13 : 8 + 19])
        self.assertEqual(b"\xee" * (6 * 47), payload[8 + 19 :])


class ScheduleTest(unittest.TestCase):
    def test_slots_round_trip(self) -> None:
        slots = pump.parse_slots(
            [
                {"start": "08:00", "end": "20:00", "mode": "run", "speed": 70},
                {"start": "20:00", "end": "21:00", "mode": "feed"},
                {"start": "21:00", "end": "08:00", "mode": "off"},
            ]
        )
        status = pump.schedule_updates(slots)
        read = pump.read_schedule(status)
        self.assertEqual(slots, [slot for slot in read if slot])
        self.assertEqual(
            {"start": "08:00", "end": "20:00", "mode": "run", "speed": 70},
            read[0].as_dict(),
        )

    def test_unused_and_leftover_slots_read_as_empty(self) -> None:
        self.assertIsNone(pump.ScheduleSlot.from_bytes(b"\xee" * 6))
        self.assertIsNone(pump.ScheduleSlot.from_bytes(bytes((99, 0, 0, 0, 1, 50))))
        self.assertIsNone(pump.ScheduleSlot.from_bytes(bytes((1, 0, 2, 0, 7, 50))))
        self.assertIsNone(pump.ScheduleSlot.from_bytes(None))

    def test_end_of_day_and_past_midnight(self) -> None:
        whole_day = pump.ScheduleSlot(0, 0, 24, 0, pump.SlotMode.RUN, 100)
        self.assertTrue(whole_day.covers(23, 59))
        overnight = pump.ScheduleSlot(22, 0, 6, 0, pump.SlotMode.RUN, 40)
        self.assertTrue(overnight.covers(23, 0))
        self.assertTrue(overnight.covers(5, 59))
        self.assertFalse(overnight.covers(6, 0))

    def test_refuses_what_the_app_would_not_save(self) -> None:
        for slots in (
            [{"start": "08:00", "end": "08:00"}],
            [{"start": "08:00", "end": "20:00", "speed": 20}],
            [{"start": "08:00", "end": "20:00"}, {"start": "19:00", "end": "21:00"}],
            [{"start": "22:00", "end": "06:00"}, {"start": "05:00", "end": "07:00"}],
        ):
            with self.subTest(slots=slots), self.assertRaises(ValueError):
                pump.schedule_updates(pump.parse_slots(slots))

    def test_whole_day_slot_is_allowed(self) -> None:
        for end in ("00:00", "24:00"):
            slots = pump.parse_slots([{"start": "00:00", "end": end, "speed": 100}])
            self.assertIn("AutoTime00", pump.schedule_updates(slots))

    def test_schedule_resumes_when_the_feed_ends(self) -> None:
        resume = pump.ScheduleResume()
        self.assertFalse(resume.update(False))
        resume.arm()
        self.assertFalse(resume.update(False))  # A status from before the feed
        self.assertFalse(resume.update(True))
        self.assertFalse(resume.update(True))
        self.assertTrue(resume.update(False))
        self.assertFalse(resume.update(False))

    def test_cancelled_resume_does_nothing(self) -> None:
        resume = pump.ScheduleResume()
        resume.arm()
        resume.update(True)
        resume.cancel()
        self.assertFalse(resume.update(False))

    def test_attributes_while_running(self) -> None:
        status = {
            "TimerON": True,
            "AutoMode": 1,
            pump.slot_name(0): bytes((8, 0, 20, 0, 1, 70)),
        }
        self.assertEqual(
            {
                "current_mode": "run",
                "slots": [{"start": "08:00", "end": "20:00", "mode": "run", "speed": 70}],
            },
            pump.schedule_attributes(status),
        )
        status["TimerON"] = False
        self.assertIsNone(pump.schedule_attributes(status)["current_mode"])

    def test_faults(self) -> None:
        self.assertEqual([], pump.read_faults({"Fault_Overcurrent": False}))
        self.assertEqual(
            ["Pump stall", "Running dry"],
            pump.read_faults({"Fault_Lockedrotor": True, "Fault_no_liveload": True}),
        )

    def test_clock_round_trip(self) -> None:
        when = datetime(2026, 11, 5, 3, 17, 9)
        self.assertEqual(when, pump.read_clock(pump.clock_updates(when)))
        self.assertIsNone(pump.read_clock({"YMDData": b"\xee" * 4, "HMSData": b"\xee" * 4}))


class ConfigTest(unittest.TestCase):
    def test_app_panel_products(self) -> None:
        configs = json.loads(
            (INTEGRATION / "models" / "device_configs.json").read_text(encoding="utf-8-sig")
        )["device_configs"]
        for key in PRODUCT_KEYS:
            with self.subTest(key=key):
                base = configs[configs[key]["inherits"]]
                self.assertTrue(base["program_control"])
                self.assertEqual(30, base["number_limits"]["Motor_Speed"]["min"])
                self.assertNotIn("Mode", base["platforms"]["switch"])
                self.assertNotIn("select", base["platforms"])


if __name__ == "__main__":
    unittest.main()
