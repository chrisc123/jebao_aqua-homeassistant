"""Pure schedule adjustment helpers for doser services.

This module intentionally avoids Home Assistant imports so logic can be
unit-tested in isolation.
"""

from __future__ import annotations

import base64
from typing import Any


def schedule_to_bytes(raw: Any) -> bytes | None:
    """Normalize a CHxSWTime value to bytes."""
    if raw is None:
        return None
    if isinstance(raw, (bytes, bytearray)):
        return bytes(raw)
    if isinstance(raw, str):
        value = raw.strip()
        try:
            return bytes.fromhex(value)
        except ValueError:
            try:
                return base64.b64decode(value, validate=True)
            except Exception:
                return None
    return None


def parse_schedule_from_attr(raw: Any, schedule_bytes_len: int = 96) -> list[dict[str, int]]:
    """Parse CHxSWTime payload into slot dictionaries sorted by time."""
    data = schedule_to_bytes(raw)
    if not data or not any(data):
        return []

    parsed: list[dict[str, int]] = []
    for i in range(0, min(len(data), schedule_bytes_len) - 7, 8):
        block = data[i : i + 8]
        if not any(block):
            break

        for hour, minute, dose_ml in (
            (block[0], block[1], block[3]),
            (block[4], block[5], block[7]),
        ):
            if 0 <= hour <= 23 and 0 <= minute <= 59 and dose_ml > 0:
                parsed.append(
                    {"hour": int(hour), "minute": int(minute), "dose_ml": int(dose_ml)}
                )

    parsed.sort(key=lambda s: (s["hour"], s["minute"]))
    return parsed


def pick_uniform_positions(total: int, pick: int) -> list[int]:
    """Pick evenly-spaced positions across a fixed-size list."""
    if pick <= 0 or total <= 0:
        return []
    if pick >= total:
        return list(range(total))
    return [int(i * total / pick) for i in range(pick)]


def new_slot_times(existing_slots: list[dict[str, int]], count: int) -> list[tuple[int, int]]:
    """Return uniformly spaced empty slot times for newly created entries."""
    used = {(slot["hour"], slot["minute"]) for slot in existing_slots}
    candidates = [(hour, 0) for hour in range(24) if (hour, 0) not in used]
    if count > len(candidates):
        raise ValueError("Not enough empty slot times available")
    positions = pick_uniform_positions(len(candidates), count)
    return [candidates[pos] for pos in positions]


def apply_volume_delta_to_slots(
    current_slots: list[dict[str, int]],
    delta_ml: int,
    fill_empty_first: bool,
    max_doser_slots: int = 24,
    min_slot_ml: int = 1,
    max_slot_ml: int = 255,
) -> list[dict[str, int]]:
    """Adjust slot doses by signed mL delta, preserving schedule ordering."""
    slots = [dict(slot) for slot in current_slots]
    if delta_ml == 0:
        return slots

    if delta_ml > 0:
        remaining = delta_ml

        if fill_empty_first and len(slots) < max_doser_slots:
            to_create = min(remaining, max_doser_slots - len(slots))
            for hour, minute in new_slot_times(slots, to_create):
                slots.append({"hour": hour, "minute": minute, "dose_ml": min_slot_ml})
            remaining -= to_create

        if not slots:
            raise ValueError("Could not allocate schedule slots for positive delta")

        idx = 0
        while remaining > 0:
            progressed = False
            for _ in range(len(slots)):
                pos = idx % len(slots)
                idx += 1
                if slots[pos]["dose_ml"] >= max_slot_ml:
                    continue
                slots[pos]["dose_ml"] += 1
                remaining -= 1
                progressed = True
                if remaining == 0:
                    break
            if not progressed:
                raise ValueError(
                    "Cannot apply positive delta: all slots reached maximum dose"
                )

        slots.sort(key=lambda s: (s["hour"], s["minute"]))
        return slots

    removal = abs(delta_ml)
    total_volume = sum(slot["dose_ml"] for slot in slots)
    if removal > total_volume:
        raise ValueError(
            f"Cannot remove {removal} mL from schedule with total {total_volume} mL"
        )

    if not slots:
        raise ValueError("Cannot apply negative delta to an empty schedule")

    idx = 0
    while removal > 0:
        for _ in range(len(slots)):
            pos = idx % len(slots)
            idx += 1
            if slots[pos]["dose_ml"] <= 0:
                continue
            slots[pos]["dose_ml"] -= 1
            removal -= 1
            if removal == 0:
                break

    slots = [slot for slot in slots if slot["dose_ml"] > 0]
    slots.sort(key=lambda s: (s["hour"], s["minute"]))
    return slots


def slots_to_service_payload(slots: list[dict[str, int]]) -> list[dict[str, int]]:
    """Convert parsed slots back to service payload shape."""
    return [
        {
            "hour": slot["hour"],
            "minute": slot["minute"],
            "dose_ml": slot["dose_ml"],
        }
        for slot in slots
    ]
