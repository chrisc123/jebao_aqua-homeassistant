"""Sensor platform for Jebao Aqua."""
from __future__ import annotations

import json
from datetime import datetime, time as dt_time

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import DOMAIN


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Jebao Aqua sensors."""
    from .const import LOGGER
    from .helpers import parse_channel_names

    coordinator = hass.data[DOMAIN][config_entry.entry_id]["coordinator"]
    attribute_models = hass.data[DOMAIN][config_entry.entry_id]["attribute_models"]

    LOGGER.debug(f"Setting up sensor platform with {len(coordinator.device_inventory)} devices")

    entities = []
    for device_info in coordinator.device_inventory:
        device_id = device_info.get("did")
        product_key = device_info.get("product_key")

        if product_key == "5ab6019f2dbb4ae7a42b48d2b8ce0530":
            LOGGER.info(f"Creating schedule sensors for MD-4.5 device {device_id}")

            channel_names = parse_channel_names(device_info)

            for channel in range(1, 6):
                channel_name = channel_names.get(channel) or f"Channel {channel}"
                entities.append(
                    JebaoChannelScheduleSensor(
                        coordinator, device_id, channel, attribute_models, channel_name
                    )
                )
                entities.append(
                    JebaoChannelVolumeSensor(
                        coordinator, device_id, channel, attribute_models, channel_name
                    )
                )

    LOGGER.info(f"Adding {len(entities)} schedule sensor entities")
    if entities:
        async_add_entities(entities)


class JebaoChannelScheduleSensor(CoordinatorEntity, SensorEntity):
    """Sensor showing a channel's dosing schedule and next upcoming dose."""

    def __init__(
        self,
        coordinator,
        device_id: str,
        channel: int,
        attribute_models,
        channel_name: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._device_id = device_id
        self._channel = channel
        self._attribute_models = attribute_models
        self._channel_name = channel_name
        self._attr_name = f"{channel_name} Schedule"
        self._attr_unique_id = f"{device_id}_ch{channel}_schedule"
        self._attr_icon = "mdi:clock-outline"

    @property
    def device_info(self):
        """Return device information."""
        from .helpers import get_device_info

        device_info = next(
            (d for d in self.coordinator.device_inventory if d["did"] == self._device_id),
            None,
        )
        if device_info:
            return get_device_info(device_info, self._attribute_models)
        return {"identifiers": {(DOMAIN, self._device_id)}}

    # ------------------------------------------------------------------
    # State: next upcoming dose  e.g. "15:00 → 4 mL"
    # Falls back to total mL/day summary when interval > 0 (can't predict date)
    # ------------------------------------------------------------------
    @property
    def state(self) -> str:
        schedule = self._parse_schedule()
        if not schedule:
            return "Not configured"

        interval = self._get_interval()
        if interval == 0:
            # Daily schedule — find the next dose from now
            next_entry = self._next_dose(schedule)
            if next_entry:
                return f"{next_entry['time']} → {next_entry['dose_ml']} mL"

        # Interval > 0: we don't know which day in the cycle we're on,
        # so show a compact summary of all doses instead
        parts = [f"{e['time']} → {e['dose_ml']} mL" for e in schedule]
        return "  |  ".join(parts)

    @property
    def extra_state_attributes(self):
        schedule = self._parse_schedule()
        total_ml = sum(e["dose_ml"] for e in schedule) if schedule else 0
        interval = self._get_interval()

        attrs = {
            "channel": self._channel,
            "channel_name": self._channel_name,
            "total_doses_per_cycle": len(schedule),
            "total_volume_ml_per_cycle": total_ml,
            "pause_days_between_cycles": interval,
            "schedule": [
                {"time": e["time"], "dose_ml": e["dose_ml"]}
                for e in schedule
            ],
        }

        if interval == 0 and schedule:
            next_entry = self._next_dose(schedule)
            if next_entry:
                attrs["next_dose_time"] = next_entry["time"]
                attrs["next_dose_ml"] = next_entry["dose_ml"]

        return attrs

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_interval(self) -> int:
        """Return the pause-days interval for this channel (0 = daily)."""
        device = self.coordinator.data.get(self._device_id, {})
        attr = device.get("attr", {})
        return int(attr.get(f"IntervalT{self._channel}", 0) or 0)

    def _get_raw_schedule(self) -> str:
        device = self.coordinator.data.get(self._device_id, {})
        attr = device.get("attr", {})
        return attr.get(f"CH{self._channel}SWTime", "")

    def _parse_schedule(self) -> list[dict]:
        """Parse CHxSWTime hex string into sorted schedule entries.

        Each 8-byte (16 hex char) block encodes two time/dose pairs:
          Bytes 0-1: hour, minute  Byte 3: dose mL
          Bytes 4-5: hour, minute  Byte 7: dose mL
        A block of all zeros ends the list.
        """
        raw = self._get_raw_schedule()
        if not raw or all(c == "0" for c in raw):
            return []

        entries = []
        for i in range(0, min(len(raw), 192), 16):
            block = raw[i : i + 16]
            if len(block) < 16 or block == "0" * 16:
                break
            try:
                h1, m1, d1 = int(block[0:2], 16), int(block[2:4], 16), int(block[6:8], 16)
                h2, m2, d2 = int(block[8:10], 16), int(block[10:12], 16), int(block[14:16], 16)
                if 0 <= h1 <= 23 and d1 > 0:
                    entries.append({"time": f"{h1:02d}:{m1:02d}", "hour": h1, "minute": m1, "dose_ml": d1})
                if 0 <= h2 <= 23 and d2 > 0:
                    entries.append({"time": f"{h2:02d}:{m2:02d}", "hour": h2, "minute": m2, "dose_ml": d2})
            except ValueError:
                continue

        # Sort chronologically
        entries.sort(key=lambda e: (e["hour"], e["minute"]))
        return entries

    def _next_dose(self, schedule: list[dict]) -> dict | None:
        """Return the next upcoming dose entry relative to now (daily schedule)."""
        now = dt_util.now()
        current_minutes = now.hour * 60 + now.minute
        # Find the first entry later than now today
        for entry in schedule:
            if entry["hour"] * 60 + entry["minute"] > current_minutes:
                return entry
        # All doses already passed today — return the first one tomorrow
        return schedule[0] if schedule else None


class JebaoChannelVolumeSensor(CoordinatorEntity, SensorEntity):
    """Sensor showing total volume dosed per cycle for a channel."""

    def __init__(
        self,
        coordinator,
        device_id: str,
        channel: int,
        attribute_models,
        channel_name: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._device_id = device_id
        self._channel = channel
        self._attribute_models = attribute_models
        self._channel_name = channel_name
        self._attr_name = f"{channel_name} Daily Volume"
        self._attr_unique_id = f"{device_id}_ch{channel}_volume"
        self._attr_native_unit_of_measurement = "mL"
        self._attr_icon = "mdi:cup-water"

    @property
    def device_info(self):
        """Return device information."""
        from .helpers import get_device_info

        device_info = next(
            (d for d in self.coordinator.device_inventory if d["did"] == self._device_id),
            None,
        )
        if device_info:
            return get_device_info(device_info, self._attribute_models)
        return {"identifiers": {(DOMAIN, self._device_id)}}

    @property
    def state(self):
        """Return total mL dosed per active cycle day."""
        schedule = self._parse_schedule()
        if not schedule:
            return None
        return sum(e["dose_ml"] for e in schedule)

    @property
    def extra_state_attributes(self):
        schedule = self._parse_schedule()
        interval = self._get_interval()
        total_ml = sum(e["dose_ml"] for e in schedule) if schedule else 0
        return {
            "channel": self._channel,
            "channel_name": self._channel_name,
            "doses_per_cycle": len(schedule),
            "pause_days_between_cycles": interval,
            "schedule": [{"time": e["time"], "dose_ml": e["dose_ml"]} for e in schedule],
        }

    def _get_interval(self) -> int:
        device = self.coordinator.data.get(self._device_id, {})
        attr = device.get("attr", {})
        return int(attr.get(f"IntervalT{self._channel}", 0) or 0)

    def _get_raw_schedule(self) -> str:
        device = self.coordinator.data.get(self._device_id, {})
        attr = device.get("attr", {})
        return attr.get(f"CH{self._channel}SWTime", "")

    def _parse_schedule(self) -> list[dict]:
        raw = self._get_raw_schedule()
        if not raw or all(c == "0" for c in raw):
            return []
        entries = []
        for i in range(0, min(len(raw), 192), 16):
            block = raw[i : i + 16]
            if len(block) < 16 or block == "0" * 16:
                break
            try:
                h1, m1, d1 = int(block[0:2], 16), int(block[2:4], 16), int(block[6:8], 16)
                h2, m2, d2 = int(block[8:10], 16), int(block[10:12], 16), int(block[14:16], 16)
                if 0 <= h1 <= 23 and d1 > 0:
                    entries.append({"time": f"{h1:02d}:{m1:02d}", "hour": h1, "minute": m1, "dose_ml": d1})
                if 0 <= h2 <= 23 and d2 > 0:
                    entries.append({"time": f"{h2:02d}:{m2:02d}", "hour": h2, "minute": m2, "dose_ml": d2})
            except ValueError:
                continue
        entries.sort(key=lambda e: (e["hour"], e["minute"]))
        return entries
