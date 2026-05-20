"""Sensor platform for Jebao Aqua."""
from __future__ import annotations

import json

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN

async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Jebao Aqua sensors."""
    from .const import LOGGER
    
    coordinator = hass.data[DOMAIN][config_entry.entry_id]["coordinator"]
    attribute_models = hass.data[DOMAIN][config_entry.entry_id]["attribute_models"]
    
    LOGGER.debug(f"Setting up sensor platform with {len(coordinator.device_inventory)} devices")
    
    entities = []
    # Iterate through device inventory to get product_key
    for device_info in coordinator.device_inventory:
        device_id = device_info.get("did")
        product_key = device_info.get("product_key")
        
        LOGGER.debug(f"Checking device {device_id} with product_key {product_key}")
        
        # Check if this is an MD-4.5 doser with schedule data
        if product_key == "5ab6019f2dbb4ae7a42b48d2b8ce0530":
            LOGGER.info(f"Creating schedule sensors for MD-4.5 device {device_id}")
            
            # Parse channel names from remark field
            channel_names = {}
            remark = device_info.get("remark", "")
            if remark:
                try:
                    remark_data = json.loads(remark)
                    names = remark_data.get("names", {})
                    # Convert CHANNEL_1 format to channel number
                    for key, value in names.items():
                        if key.startswith("CHANNEL_"):
                            channel_num = int(key.split("_")[1])
                            channel_names[channel_num] = value
                    LOGGER.info(f"Loaded channel names: {channel_names}")
                except (json.JSONDecodeError, ValueError, KeyError) as e:
                    LOGGER.warning(f"Failed to parse channel names from remark: {e}")
            
            # Create schedule sensors for each channel
            for channel in range(1, 6):  # Channels 1-5
                channel_name = channel_names.get(channel)
                entities.append(
                    JebaoChannelScheduleSensor(coordinator, device_id, channel, attribute_models, channel_name)
                )
    
    LOGGER.info(f"Adding {len(entities)} schedule sensor entities")
    if entities:
        async_add_entities(entities)


class JebaoChannelScheduleSensor(CoordinatorEntity, SensorEntity):
    """Sensor showing channel dosing schedule."""

    def __init__(self, coordinator, device_id: str, channel: int, attribute_models, channel_name: str = None) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._device_id = device_id
        self._channel = channel
        self._attribute_models = attribute_models
        self._channel_name = channel_name or f"Channel {channel}"
        self._attr_name = f"{self._channel_name} Schedule"
        self._attr_unique_id = f"{device_id}_ch{channel}_schedule"
        
    @property
    def device_info(self):
        """Return device information."""
        from .helpers import get_device_info
        
        # Get device info from inventory
        device_info = next(
            (d for d in self.coordinator.device_inventory if d["did"] == self._device_id),
            None
        )
        if device_info:
            return get_device_info(device_info, self._attribute_models)
        return {
            "identifiers": {(DOMAIN, self._device_id)},
        }

    @property
    def state(self) -> str:
        """Return the state."""
        schedule_data = self._parse_schedule()
        if not schedule_data:
            return "Not configured"
        
        # Calculate total daily volume
        total_ml = sum(entry["dose_ml"] for entry in schedule_data)
        return f"{total_ml} mL/day"
    
    @property
    def extra_state_attributes(self):
        """Return the state attributes."""
        schedule_data = self._parse_schedule()
        
        # Calculate totals
        total_doses = len(schedule_data)
        total_ml = sum(entry["dose_ml"] for entry in schedule_data) if schedule_data else 0
        
        attrs = {
            "channel": self._channel,
            "total_doses_per_day": total_doses,
            "total_volume_ml_per_day": total_ml,
            "schedule_entries": schedule_data,
            "raw_data": self._get_raw_schedule(),
        }
        return attrs
    
    def _get_raw_schedule(self) -> str:
        """Get raw CHxSWTime data."""
        device = self.coordinator.data.get(self._device_id, {})
        attr = device.get("attr", {})
        field_name = f"CH{self._channel}SWTime"
        return attr.get(field_name, "")
    
    def _parse_schedule(self) -> list[dict]:
        """Parse CHxSWTime hex string into schedule entries.
        
        The protocol encodes schedule data in 8-byte (16 hex char) blocks.
        Each block contains TWO time/dose pairs:
          Bytes 0-1: hour, minute of first dosing time
          Byte  2:   unknown/padding
          Byte  3:   dose amount in mL for first time
          Bytes 4-5: hour, minute of second dosing time
          Byte  6:   unknown/padding
          Byte  7:   dose amount in mL for second time
        
        A block of all zeros signals the end of the schedule.
        """
        raw = self._get_raw_schedule()
        if not raw or raw == "0" * len(raw):
            return []
        
        entries = []
        # Parse hex string in 16-character (8-byte) blocks; max 12 blocks = 24 entries
        for i in range(0, min(len(raw), 192), 16):
            block = raw[i:i+16]
            if len(block) < 16:
                break
            if block == "0" * 16:
                break  # End of schedule entries
                
            try:
                # First time/dose pair in this block
                hour1 = int(block[0:2], 16)
                minute1 = int(block[2:4], 16)
                dose1 = int(block[6:8], 16)
                
                # Second time/dose pair in this block
                hour2 = int(block[8:10], 16)
                minute2 = int(block[10:12], 16)
                dose2 = int(block[14:16], 16)
                
                if 0 <= hour1 <= 23 and dose1 > 0:
                    entries.append({
                        "time": f"{hour1:02d}:{minute1:02d}",
                        "dose_ml": dose1,
                        "raw": block[0:8],
                    })
                
                if 0 <= hour2 <= 23 and dose2 > 0:
                    entries.append({
                        "time": f"{hour2:02d}:{minute2:02d}",
                        "dose_ml": dose2,
                        "raw": block[8:16],
                    })
            except ValueError:
                continue
        
        return entries