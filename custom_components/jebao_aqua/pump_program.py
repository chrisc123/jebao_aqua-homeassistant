"""How the Jebao Aqua app runs the MDP-style return pumps, and their schedule.

For products with the app's "shuibeng" panel (6a5c47b3... and 02039876...). The app
sends several datapoints together for one action, and treats some as its own:

    Speed slider     Motor_Speed, and TimerON off if the schedule is on
    Schedule on      TimerON, FeedSwitch off, and AutoMode/AutoGears of the current slot
    Schedule off     TimerON off, Motor_Speed
    Feed on          FeedSwitch, TimerON off, FeedTime
    Feed off         FeedSwitch off, TimerON off, FeedTime, Motor_Speed
    Feed time        FeedTime, FeedSwitch

The speed range is 30-100 (0 stops the motor; the power button is for that). It never
writes Mode, and AutoMode/AutoGears only as above: the pump updates them itself at
each slot boundary.

AutoTime00..47 are 6-byte schedule slots, [start h, start m, end h, end m, mode, speed].
The app writes all 48 in one frame, with EE filler for unused ones, and the speed is 0
unless the mode is run. The schedule repeats daily, a slot can run past midnight, and
an end of 00:00 or 24:00 is the end of the day. Slots are never cleared, so besides the
filler they can hold leftovers that were never a schedule entry.

The schedule runs on the pump's own clock, set through YMDData [century, year, month,
day] and HMSData [0, hour, minute, second], in plain binary. The app only sets it by
hand. The datapoints read back the last value written; they don't tick.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, time
from enum import IntEnum
from typing import Any

SCHEDULE_SLOTS = 48
SLOT_SIZE = 6
UNUSED_SLOT = b"\xee" * SLOT_SIZE
MIN_SPEED = 30
MAX_SPEED = 100

# Fault datapoints, in the app's words
FAULTS = {
    "Fault_Overcurrent": "Overcurrent",
    "Fault_Overvoltage": "Overvoltage",
    "Fault_OverTemp": "Overtemperature",
    "Fault_Undervoltage": "Undervoltage",
    "Fault_Lockedrotor": "Pump stall",
    "Fault_no_liveload": "Running dry",
    "Fault_UART": "Wi-Fi module link fault",
}


class SlotMode(IntEnum):
    """What the pump does in a slot (the AutoMode datapoint)."""

    OFF = 0
    RUN = 1
    FEED = 2


def slot_name(index: int) -> str:
    """Datapoint of a schedule slot."""
    return f"AutoTime{index:02d}"


@dataclass(frozen=True)
class ScheduleSlot:
    """One schedule entry."""

    start_hour: int
    start_minute: int
    end_hour: int
    end_minute: int
    mode: SlotMode
    speed: int = 0

    def __post_init__(self) -> None:
        """Refuse a slot that doesn't make sense."""
        if not (0 <= self.start_hour < 24 and 0 <= self.start_minute < 60):
            raise ValueError("Slot start must be 00:00-23:59")
        if not (0 <= self.end_hour <= 24 and 0 <= self.end_minute < 60):
            raise ValueError("Slot end must be 00:00-24:00")
        if self.end_hour == 24 and self.end_minute:
            raise ValueError("Slot end must be 00:00-24:00")
        if self.mode == SlotMode.RUN and not 0 <= self.speed <= MAX_SPEED:
            raise ValueError(f"Slot speed must be up to {MAX_SPEED}")
        if self.mode != SlotMode.RUN and self.speed:
            raise ValueError("Only run slots have a speed")

    @classmethod
    def from_bytes(cls, data: Any) -> ScheduleSlot | None:
        """Decode a slot; None if it's unused or doesn't make sense."""
        if (
            not isinstance(data, (bytes, bytearray))
            or len(data) != SLOT_SIZE
            or bytes(data) == UNUSED_SLOT
            or data[4] not in tuple(SlotMode)
        ):
            return None
        try:
            return cls(data[0], data[1], data[2], data[3], SlotMode(data[4]), data[5])
        except ValueError:
            return None

    def to_bytes(self) -> bytes:
        """Encode the slot."""
        return bytes(
            (
                self.start_hour,
                self.start_minute,
                self.end_hour,
                self.end_minute,
                int(self.mode),
                self.speed,
            )
        )

    def _minutes(self) -> tuple[int, int]:
        start = self.start_hour * 60 + self.start_minute
        end = self.end_hour * 60 + self.end_minute
        return start, end or 24 * 60

    def covers(self, hour: int, minute: int) -> bool:
        """Whether the slot is active at this time of day."""
        start, end = self._minutes()
        now = hour * 60 + minute
        if start < end:
            return start <= now < end
        return now >= start or now < end

    @property
    def start(self) -> str:
        """Start as HH:MM."""
        return f"{self.start_hour:02d}:{self.start_minute:02d}"

    @property
    def end(self) -> str:
        """End as HH:MM."""
        return f"{self.end_hour:02d}:{self.end_minute:02d}"

    def as_dict(self) -> dict[str, Any]:
        """The slot in the form the set_schedule service takes."""
        slot: dict[str, Any] = {
            "start": self.start,
            "end": self.end,
            "mode": self.mode.name.lower(),
        }
        if self.mode == SlotMode.RUN:
            slot["speed"] = self.speed
        return slot


def _parse_time(value: Any) -> tuple[int, int]:
    if isinstance(value, time):
        return value.hour, value.minute
    hour, _, minute = str(value).partition(":")
    return int(hour), int(minute[:2] or 0)


def parse_slots(slots: Iterable[Mapping[str, Any]]) -> list[ScheduleSlot]:
    """ScheduleSlots from dicts like {"start": "08:00", "end": "20:00", "speed": 70}.

    The mode is run (the default), feed or off. A run slot's speed defaults to 100.
    """
    parsed = []
    for item in slots:
        mode = SlotMode[str(item.get("mode", "run")).upper()]
        speed = int(item.get("speed", MAX_SPEED)) if mode == SlotMode.RUN else 0
        parsed.append(
            ScheduleSlot(*_parse_time(item["start"]), *_parse_time(item["end"]), mode, speed)
        )
    return parsed


def read_schedule(status: Mapping[str, Any]) -> list[ScheduleSlot | None]:
    """All 48 slots from a status; None for those without an entry."""
    return [
        ScheduleSlot.from_bytes(status.get(slot_name(n))) for n in range(SCHEDULE_SLOTS)
    ]


def schedule_updates(slots: Sequence[ScheduleSlot]) -> dict[str, bytes]:
    """All 48 slot datapoints for a schedule: the given slots, then filler.

    Raises ValueError for anything the app's editor wouldn't save.
    """
    if len(slots) > SCHEDULE_SLOTS:
        raise ValueError(f"A schedule has at most {SCHEDULE_SLOTS} slots")
    for slot in slots:
        if (slot.start_hour, slot.start_minute) == (slot.end_hour % 24, slot.end_minute):
            raise ValueError(f"Slot {slot.start}-{slot.end} has no length")
        if slot.mode == SlotMode.RUN and not MIN_SPEED <= slot.speed <= MAX_SPEED:
            raise ValueError(f"Slot speed must be {MIN_SPEED}-{MAX_SPEED}")
    for index, first in enumerate(slots):
        for second in slots[index + 1 :]:
            if first.covers(second.start_hour, second.start_minute) or second.covers(
                first.start_hour, first.start_minute
            ):
                raise ValueError(
                    f"Slots {first.start}-{first.end} and "
                    f"{second.start}-{second.end} overlap"
                )
    return {
        slot_name(n): slots[n].to_bytes() if n < len(slots) else UNUSED_SLOT
        for n in range(SCHEDULE_SLOTS)
    }


def schedule_on_updates(
    slots: Iterable[ScheduleSlot | None], when: datetime
) -> dict[str, Any]:
    """What the app writes to start the schedule: includes the slot active now."""
    updates: dict[str, Any] = {"TimerON": True, "FeedSwitch": False}
    for slot in slots:
        if slot is not None and slot.covers(when.hour, when.minute):
            updates["AutoMode"] = int(slot.mode)
            updates["AutoGears"] = slot.speed
            return updates
    updates["AutoMode"] = int(SlotMode.OFF)
    return updates


def command_updates(
    attr_name: str, value: Any, status: Mapping[str, Any], when: datetime
) -> dict[str, Any]:
    """The datapoints the app writes to set this one."""
    speed = status.get("Motor_Speed")
    feed_time = status.get("FeedTime")
    if attr_name == "Motor_Speed":
        if status.get("TimerON"):
            return {"Motor_Speed": value, "TimerON": False}
    elif attr_name == "TimerON":
        if value:
            return schedule_on_updates(read_schedule(status), when)
        return {"TimerON": False, "Motor_Speed": speed}
    elif attr_name == "FeedSwitch":
        if value:
            return {"FeedSwitch": True, "TimerON": False, "FeedTime": feed_time}
        return {
            "FeedSwitch": False,
            "TimerON": False,
            "FeedTime": feed_time,
            "Motor_Speed": speed,
        }
    elif attr_name == "FeedTime":
        return {"FeedTime": value, "FeedSwitch": bool(status.get("FeedSwitch"))}
    return {attr_name: value}


def read_faults(status: Mapping[str, Any]) -> list[str]:
    """The faults a status reports."""
    return [label for name, label in FAULTS.items() if status.get(name)]


def schedule_attributes(status: Mapping[str, Any]) -> dict[str, Any]:
    """The schedule's slots and, while it runs, what it's doing."""
    mode = status.get("AutoMode")
    running = status.get("TimerON") and mode in tuple(SlotMode)
    return {
        "current_mode": SlotMode(mode).name.lower() if running else None,
        "slots": [slot.as_dict() for slot in read_schedule(status) if slot is not None],
    }


def clock_updates(when: datetime) -> dict[str, bytes]:
    """The datapoints that set the pump's clock."""
    return {
        "YMDData": bytes((when.year // 100, when.year % 100, when.month, when.day)),
        "HMSData": bytes((0, when.hour, when.minute, when.second)),
    }


def read_clock(status: Mapping[str, Any]) -> datetime | None:
    """What the clock was last set to, if it makes sense."""
    ymd = status.get("YMDData")
    hms = status.get("HMSData")
    if not ymd or not hms or len(ymd) != 4 or len(hms) != 4:
        return None
    try:
        return datetime(ymd[0] * 100 + ymd[1], ymd[2], ymd[3], hms[1], hms[2], hms[3])
    except ValueError:
        return None
