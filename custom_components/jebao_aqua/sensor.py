"""Platform for sensor entities for Jebao Aqua integration."""

from __future__ import annotations

import base64
import logging
from typing import Any

from homeassistant.components.sensor import (
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util
from homeassistant.util.color import value_to_brightness  # Add this import

from .entity import JebaoEntity
from .gizwits_lan.device_status import DeviceStatus
from .hub import JebaoDevice

_LOGGER = logging.getLogger(__name__)


def _schedule_to_bytes(raw: Any) -> bytes | None:
    """Normalize a CHxSWTime value to bytes.

    LAN status delivers raw bytes; the cloud API delivers a string (hex or
    base64 depending on firmware).
    """
    if raw is None:
        return None
    if isinstance(raw, (bytes, bytearray)):
        return bytes(raw)
    if isinstance(raw, str):
        s = raw.strip()
        try:
            return bytes.fromhex(s)
        except ValueError:
            try:
                return base64.b64decode(s, validate=True)
            except Exception:
                return None
    return None


def parse_dosing_schedule(raw: Any) -> list[dict]:
    """Parse a CHxSWTime blob into a chronologically sorted dose list.

    Each 8-byte block holds two entries: [hour, minute, ?, dose_ml] twice.
    An all-zero block terminates the list. (Format from PR #49.)
    """
    data = _schedule_to_bytes(raw)
    if not data or not any(data):
        return []

    entries = []
    for i in range(0, len(data) - 7, 8):
        block = data[i : i + 8]
        if not any(block):
            break
        for h, m, d in ((block[0], block[1], block[3]), (block[4], block[5], block[7])):
            if 0 <= h <= 23 and 0 <= m <= 59 and d > 0:
                entries.append(
                    {"time": f"{h:02d}:{m:02d}", "hour": h, "minute": m, "dose_ml": d}
                )

    entries.sort(key=lambda e: (e["hour"], e["minute"]))
    return entries


def next_dose(schedule: list[dict]) -> dict | None:
    """Return the next upcoming dose relative to now (daily schedules)."""
    if not schedule:
        return None
    now = dt_util.now()
    current_minutes = now.hour * 60 + now.minute
    for entry in schedule:
        if entry["hour"] * 60 + entry["minute"] > current_minutes:
            return entry
    # All doses passed today; the first one runs tomorrow.
    return schedule[0]


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up sensor entities for a given config entry."""
    devices: list[JebaoDevice] = entry.runtime_data  # type: ignore
    if not devices:
        _LOGGER.warning("No Jebao devices found for entry %s", entry.title)
        return

    entities = []
    for device in devices:
        if not device.giz_device:
            continue

        device_cfg = device.device_config
        if not device_cfg:
            continue
        device_type = device_cfg.get("device_type")
        platforms_cfg = device_cfg.get("platforms", {})

        if device_type == "light":
            allowed_sensor_attrs = set(platforms_cfg.get("sensor", []))
            for attr_def in device.giz_device.all_attrs:
                attr_name = attr_def["name"]
                if attr_name not in allowed_sensor_attrs:
                    continue
                # Must be uint8
                if attr_def.get("data_type") != "uint8":
                    continue
                entities.append(JebaoLightLevelSensor(entry, device, attr_def))

        elif device_type == "doser":
            # Schedule/volume sensors for each channel that is both exposed
            # (channeN in the switch whitelist) and has a CHnSWTime blob.
            attr_names = {a["name"] for a in device.giz_device.all_attrs}
            exposed = set(platforms_cfg.get("switch", []))
            for channel in range(1, 9):
                if f"CH{channel}SWTime" not in attr_names:
                    continue
                if f"channe{channel}" not in exposed:
                    continue
                entities.append(JebaoDoserScheduleSensor(entry, device, channel))
                entities.append(JebaoDoserVolumeSensor(entry, device, channel))

    if entities:
        async_add_entities(entities)


class JebaoLightLevelSensor(JebaoEntity, SensorEntity):
    """Sensor showing light level as 0-255."""

    def __init__(
        self, entry: ConfigEntry, device: JebaoDevice, attr_def: dict[str, Any]
    ) -> None:
        """Initialize the sensor entity."""
        # Append "Level" to the name
        attr_def = dict(attr_def)
        if "name" in attr_def:
            attr_def["name"] = f"{attr_def['name']} Level"

        self.entity_description = SensorEntityDescription(
            key=f"{attr_def['name'].lower()}_level",
            name=attr_def.get("name"),
            native_unit_of_measurement=None,
            state_class=SensorStateClass.MEASUREMENT,
        )

        super().__init__(entry, device, attr_def, "sensor")
        self._value = None

        # Get min/max from uint_spec if available
        uint_spec = attr_def.get("uint_spec") or {}
        self._value_min = uint_spec.get("min", 0)
        self._value_max = uint_spec.get(
            "max", 100
        )  # Default to 0-100 range if not specified

    @property
    def native_value(self) -> int | None:
        """Return the sensor value."""
        return self._value

    async def async_added_to_hass(self) -> None:
        """Register callback when entity is added."""
        await super().async_added_to_hass()
        self._device.register_status_callback(self._update_state_from_device)

    async def async_will_remove_from_hass(self) -> None:
        """Unregister callbacks when entity is removed."""
        await super().async_will_remove_from_hass()
        self._device.remove_status_callback(self._update_state_from_device)

    @callback
    def _update_state_from_device(self, status: DeviceStatus) -> None:
        """Update state from device status."""
        if self._attribute_name not in status.data:
            return
        device_value = status.data[self._attribute_name]
        # Convert the device's value range to 0-255, like light.py does
        self._value = value_to_brightness(
            (self._value_min, self._value_max), device_value
        )
        self.async_write_ha_state()


class JebaoDoserChannelSensor(JebaoEntity, SensorEntity):
    """Base for per-channel dosing sensors built on the CHxSWTime blob."""

    def __init__(
        self, entry: ConfigEntry, device: JebaoDevice, channel: int, kind: str
    ) -> None:
        """Initialize with a synthetic attribute for unique_id purposes."""
        self._channel = channel
        self._schedule_attr = f"CH{channel}SWTime"
        self._interval_attr = f"IntervalT{channel}"
        super().__init__(entry, device, {"name": f"CH{channel}{kind}"}, "sensor")
        # These are derived entities without model translations; name them
        # directly, using the channel name from the Jebao app when known.
        self._attr_translation_key = None
        channel_names = getattr(device, "channel_names", {}) or {}
        self._channel_name = channel_names.get(channel) or f"Channel {channel}"

    def _schedule(self) -> list[dict]:
        return parse_dosing_schedule(self._device.get_attribute(self._schedule_attr))

    def _interval(self) -> int:
        try:
            return int(self._device.get_attribute(self._interval_attr) or 0)
        except (TypeError, ValueError):
            return 0

    async def async_added_to_hass(self) -> None:
        """Register status callback when entity is added."""
        await super().async_added_to_hass()
        self._device.register_status_callback(self._update_state_from_device)

    async def async_will_remove_from_hass(self) -> None:
        """Unregister status callback when entity is removed."""
        await super().async_will_remove_from_hass()
        self._device.remove_status_callback(self._update_state_from_device)

    @callback
    def _update_state_from_device(self, status: DeviceStatus) -> None:
        """Refresh when this channel's schedule or interval changes."""
        if self._schedule_attr in status.data or self._interval_attr in status.data:
            self.async_write_ha_state()


class JebaoDoserScheduleSensor(JebaoDoserChannelSensor):
    """Shows a channel's dosing schedule and the next upcoming dose."""

    _attr_icon = "mdi:clock-outline"

    def __init__(self, entry: ConfigEntry, device: JebaoDevice, channel: int) -> None:
        """Initialize the schedule sensor."""
        super().__init__(entry, device, channel, "Schedule")
        self._attr_name = f"{self._channel_name} Schedule"

    @property
    def native_value(self) -> str:
        """Next dose for daily schedules, or a compact summary otherwise."""
        schedule = self._schedule()
        if not schedule:
            return "Not configured"

        if self._interval() == 0:
            entry = next_dose(schedule)
            if entry:
                return f"{entry['time']} → {entry['dose_ml']} mL"

        # With pause days between cycles we can't know which day the device
        # is on, so show the whole cycle instead of a next-dose prediction.
        return "  |  ".join(f"{e['time']} → {e['dose_ml']} mL" for e in schedule)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        schedule = self._schedule()
        interval = self._interval()
        attrs: dict[str, Any] = {
            "channel": self._channel,
            "channel_name": self._channel_name,
            "total_doses_per_cycle": len(schedule),
            "total_volume_ml_per_cycle": sum(e["dose_ml"] for e in schedule),
            "pause_days_between_cycles": interval,
            "schedule": [{"time": e["time"], "dose_ml": e["dose_ml"]} for e in schedule],
        }
        if interval == 0:
            entry = next_dose(schedule)
            if entry:
                attrs["next_dose_time"] = entry["time"]
                attrs["next_dose_ml"] = entry["dose_ml"]
        return attrs


class JebaoDoserVolumeSensor(JebaoDoserChannelSensor):
    """Shows the total volume dosed per cycle day for a channel."""

    _attr_icon = "mdi:cup-water"
    _attr_native_unit_of_measurement = "mL"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, entry: ConfigEntry, device: JebaoDevice, channel: int) -> None:
        """Initialize the volume sensor."""
        super().__init__(entry, device, channel, "Volume")
        self._attr_name = f"{self._channel_name} Daily Volume"

    @property
    def native_value(self) -> int | None:
        schedule = self._schedule()
        if not schedule:
            return None
        return sum(e["dose_ml"] for e in schedule)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        schedule = self._schedule()
        return {
            "channel": self._channel,
            "channel_name": self._channel_name,
            "doses_per_cycle": len(schedule),
            "pause_days_between_cycles": self._interval(),
            "schedule": [{"time": e["time"], "dose_ml": e["dose_ml"]} for e in schedule],
        }
