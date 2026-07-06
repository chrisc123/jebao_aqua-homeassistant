# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.0] - 2026-07-06

### Added

- Comprehensive README with installation instructions, troubleshooting, and automation examples
- CHANGELOG.md for tracking version history
- `CONTENT_TYPE_JSON` constant to avoid string duplication
- `CONTROL_COMMAND_DELAY` constant for configurable control command delays
- Issue tracker link in manifest.json
- `iot_class` and `integration_type` fields in manifest.json
- pycountry dependency explicitly listed in manifest.json

### Changed

- Updated minimum Home Assistant version to 2024.1.0
- Improved README with better structure, examples, and troubleshooting guides
- Enhanced hacs.json metadata (removed duplicate keys, added render_readme and zip_release)
- Version bumped to 0.2.0

### Fixed

- Removed duplicate `homeassistant` key in hacs.json
- Removed duplicate constant declarations in const.py (TIMEOUT, DISCOVERY_TIMEOUT, LAN_PORT)
- Fixed hardcoded sleep duration in switch.py - now uses CONTROL_COMMAND_DELAY constant
- Improved error handling in discovery.py using logging.exception
- Improved error handling in config_flow.py using logging.exception
- Fixed dict comprehension in config_flow.py to use dict() constructor
- Removed unused `async_setup` function in **init**.py
- Removed unused imports (ConfigEntries, async_timeout)
- Cleaned up import organization in **init**.py
- Used CONTENT_TYPE_JSON constant throughout api.py

### Removed

- Unused `get_session()` method in api.py
- Unused `async_setup()` function from **init**.py
- Redundant PLATFORMS constant from **init**.py (already in const.py)

## [0.1.0] - 2024-XX-XX

### Added

- Initial release
- Support for Jebao MCP, MLW, SLW, EP series pumps
- Support for Jebao Smart Doser 3.1, MD 4.4, and MD 2.4
- Local LAN polling for device status
- Cloud-based control via Gizwits API
- Automatic device discovery
- Multi-region support (EU, US, CN)
- Config flow for easy setup
- Options flow for reconfiguration
- Switch, binary_sensor, number, and select entities
- Proper device and entity registry management
