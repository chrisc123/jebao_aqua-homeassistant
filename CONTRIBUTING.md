# Contributing to Jebao Aqua Integration

Thank you for your interest in contributing to the Jebao Aqua Home Assistant integration! This document provides guidelines and instructions for contributing.

## Ways to Contribute

### 1. Testing New Devices

If you have a Jebao device that isn't listed as tested, you can help by:

1. Installing the integration
2. Testing it with your device
3. Reporting your findings via GitHub Issues

**Information to Include:**

- Device model and version
- Hardware type (ESP8266 vs ESP32C3) - check the Jebao Aqua app under Device Information
- What works and what doesn't
- Any error messages from Home Assistant logs

### 2. Adding Support for New Devices

To add support for a new device model, you need to:

1. **Obtain the device model JSON** from Gizwits API:
   - The model file defines all available attributes, data types, and binary protocol positions
   - Location: `custom_components/jebao_aqua/models/{product_key}.json`

2. **Test the device** with the integration

3. **Submit a Pull Request** with:
   - The new model JSON file
   - Updated compatibility table in README.md
   - Any code changes required for special device features

### 3. Protocol Reverse Engineering

We're particularly interested in:

- ESP32C3 (WiFi+BLE) device support
- Local control commands (avoiding cloud API dependency)
- MQTT protocol analysis

**Tools and Resources:**

- Wireshark for network packet capture
- Gizwits documentation: https://docs.gizwits.com/
- Existing implementations:
  - https://github.com/tancou/jebao-dosing-pump-md-4.4
  - https://github.com/Apollon77/node-ph803w

### 4. Bug Fixes and Code Improvements

#### Setting Up Development Environment

```bash
# Clone the repository
git clone https://github.com/chrisc123/jebao_aqua-homeassistant.git
cd jebao_aqua-homeassistant

# Install Home Assistant in development mode (optional)
# Follow: https://developers.home-assistant.io/docs/development_environment

# Create a symbolic link to your HA config for testing
ln -s $(pwd)/custom_components/jebao_aqua ~/.homeassistant/custom_components/jebao_aqua
```

#### Code Style

This integration follows Home Assistant code style guidelines:

- Use `async`/`await` for all I/O operations
- Follow PEP 8 style guide
- Use type hints where possible
- Keep functions focused and under 15 cognitive complexity
- Use Home Assistant helpers and utilities

**Linting:**

```bash
# Install pre-commit hooks (recommended)
pip install pre-commit
pre-commit install

# Run linters manually
ruff check custom_components/jebao_aqua/
black custom_components/jebao_aqua/
```

#### Testing

Before submitting a PR:

1. Test with actual hardware if possible
2. Enable debug logging and verify no errors
3. Test all entity types (switch, sensor, number, select)
4. Test both local and cloud-only modes
5. Test reconfiguration flow

**Enable Debug Logging:**

```yaml
logger:
  default: info
  logs:
    custom_components.jebao_aqua: debug
```

### 5. Documentation

Documentation improvements are always welcome:

- Typo fixes
- Clarifications
- Additional examples
- Troubleshooting tips
- Translation improvements

## Submitting Changes

### Pull Request Process

1. **Fork the repository** and create a feature branch:

   ```bash
   git checkout -b feature/your-feature-name
   ```

2. **Make your changes** following the code style guidelines

3. **Test thoroughly** with your hardware

4. **Update documentation**:
   - README.md if adding features or device support
   - CHANGELOG.md with your changes
   - Code comments and docstrings

5. **Commit with clear messages**:

   ```bash
   git commit -m "Add support for Jebao XYZ pump"
   ```

6. **Push and create Pull Request**:

   ```bash
   git push origin feature/your-feature-name
   ```

7. **Fill out the PR template** with:
   - Description of changes
   - Devices tested
   - Breaking changes (if any)
   - Related issues

### Commit Message Guidelines

Use clear, descriptive commit messages:

**Good:**

- `Add support for Jebao MLW-20 wavemaker`
- `Fix: Device discovery timeout handling`
- `Docs: Add troubleshooting section for ESP32C3 devices`

**Bad:**

- `Update code`
- `Fix bug`
- `Changes`

### Code Review

All submissions require review. We'll:

- Test your changes if possible
- Provide constructive feedback
- Request changes if needed
- Merge once approved

Be patient - this is a community project maintained by volunteers.

## Project Structure

```
custom_components/jebao_aqua/
├── __init__.py           # Integration setup and coordinator
├── api.py                # Gizwits API client and local protocol
├── binary_sensor.py      # Fault sensors
├── config_flow.py        # Setup and options flows
├── const.py              # Constants and configuration
├── discovery.py          # UDP device discovery
├── helpers.py            # Helper functions
├── manifest.json         # Integration metadata
├── number.py             # Number entities (flow, frequency)
├── select.py             # Select entities (modes)
├── switch.py             # Switch entities (on/off controls)
├── models/               # Device model definitions (JSON)
│   └── *.json           # Per-device attribute models
└── translations/         # Localization files
    ├── en.json
    ├── de.json
    └── it.json
```

## Common Issues

### Local Protocol Questions

The local protocol uses the Gizwits GAgent format:

- TCP port 12416
- Binary protocol with LEB128 encoding
- Requires binding key exchange

See `api.py` `get_local_device_data()` for implementation details.

### Adding New Entity Types

To add a new entity type:

1. Create a new platform file (e.g., `light.py`)
2. Implement the entity class extending Home Assistant base classes
3. Use `CoordinatorEntity` for automatic updates
4. Add platform to `PLATFORMS` constant in `const.py`
5. Update device model JSON files with new attribute types

### Translation

To add a new language:

1. Copy `translations/en.json` to `translations/{lang_code}.json`
2. Translate all strings (keep keys unchanged)
3. Test the translation by changing Home Assistant language settings

## Questions?

- Check existing [Issues](https://github.com/chrisc123/jebao_aqua-homeassistant/issues)
- Read the [Home Assistant Developer Docs](https://developers.home-assistant.io/)
- Ask in the [Home Assistant Community Forum](https://community.home-assistant.io/)

## License

By contributing, you agree that your contributions will be licensed under the same MIT License that covers this project.

## Thanks!

Your contributions help make this integration better for everyone in the aquarium hobby using Home Assistant. 🐠
