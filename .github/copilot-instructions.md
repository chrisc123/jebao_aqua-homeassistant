# Copilot Instructions for Jebao Aqua Home Assistant Integration

## Project Overview
This is a Home Assistant custom integration for controlling Jebao aquarium pumps/wavemakers locally via WiFi. The integration communicates with ESP8266-based controllers using the Gizwits IoT protocol, bypassing cloud connectivity.

## Key Architecture Components

### Three-Layer Architecture
1. **Home Assistant Layer**: Standard HA integration with platforms (`switch.py`, `number.py`, `select.py`, etc.)
2. **Device Management Layer**: `hub.py` with `JebaoDevice` wrapper and discovery logic
3. **Protocol Layer**: `gizwits_lan/` package handling the Gizwits LAN protocol

### Critical Singleton Pattern
- `hub.py` maintains `_GLOBAL_MANAGER` (DeviceManager singleton) - always reuse this instance
- Multiple devices share the same manager for efficiency

### Device Model System
- Each device has a `product_key` (hex string) that maps to JSON configuration files in `models/`
- Files like `1d8c63eaccac4205b92c84d77d5a08fb.json` define device capabilities and datapoints
- `device_configs.json` maps product keys to Home Assistant platform configurations using inheritance
- Example: `"1d8c63eaccac4205b92c84d77d5a08fb": {"inherits": "wavemaker_default"}`

## Entity Creation Pattern
All platform files follow this pattern:
1. Get devices from `entry.runtime_data` (list of `JebaoDevice`)
2. Filter attributes using device config: `device_cfg["platforms"]["switch"]` contains allowed attribute names
3. Filter by `data_type` ("bool" for switches, "uint8" for numbers, "enum" for selects)
4. Filter by `type` ("status_writable" for controllable entities, "status_readonly" for sensors)
5. Extend `JebaoEntity` base class with platform-specific functionality

## Device Discovery & Setup
- Discovery uses UDP broadcast on port 12414 with `DISCOVERY_REQUEST` packet
- Devices respond with product_key, UID, IP, and firmware info
- Config flow supports both auto-discovery and manual IP entry
- Multiple devices can be added to a single config entry

## Protocol Implementation
- `gizwits_lan/protocol.py` handles packet construction and parsing
- Uses binary protocol with checksums and sequence numbers
- Device status updates arrive via callbacks registered in `JebaoDevice.async_connect()`
- Commands sent via `device.send_cmd()` with attribute name and value

## Translation & Localization
- Entity names use translation keys based on attribute names (e.g., `fault_overcurrent` → "Motor Overcurrent")
- All strings defined in `translations/en.json` with nested structure: `entity.platform_type.attribute_name.name`
- Config flow strings in separate `config` section

## Development Patterns
- Use async throughout - all device communication is async
- Error handling via `GizwitsError` and subclasses from `gizwits_lan/errors.py`
- Logging with module-level `_LOGGER = logging.getLogger(__name__)`
- Device attributes accessed via `device.giz_device.all_attrs` list of dicts
- Entity unique IDs format: `{device_uid}_{attribute_name}_{entity_type}`

## Testing Considerations
- Integration requires physical Jebao devices or network simulation
- ESP8266 devices respond to UDP discovery on local network
- Device model files contain actual hardware specifications from Gizwits cloud

## Common Pitfalls
- Never create multiple DeviceManager instances - use the singleton
- Device configs must match exactly with product_key from device discovery
- Binary sensor fault attributes use "Fault_" prefix in model files but "fault_" in translations
- Platform filtering happens at both device config level and data_type level