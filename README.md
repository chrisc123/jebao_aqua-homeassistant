# Jebao Aqua Aquarium Pumps for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)

Home Assistant custom integration for [Jebao](https://www.jebao-aqua.com/) Wi-Fi enabled aquarium wavemakers, pumps, and dosing pumps — with local LAN polling and Gizwits cloud control.

## How It Works

Jebao Wi-Fi devices use the **Gizwits IoT platform** under the hood.

| Capability | How it works |
|---|---|
| Device discovery | Bound to your Jebao Aqua / Gizwits account via cloud API |
| State polling | Local LAN (TCP port 12416) — fast, no cloud needed for reads |
| Commands (on/off, mode, flow) | Gizwits cloud API |

**Cloud credentials are required** to link devices and send control commands. Once set up, status updates are read locally.

## Supported Devices

> [!IMPORTANT]
> As of late 2024, some model series ship in two hardware variants. The newer variant adds Bluetooth (BLE) alongside Wi-Fi and uses an ESP32C3 microcontroller instead of the legacy ESP8266. **WiFi+BLE devices are not yet supported** — protocol investigation is ongoing.

| Status | Device | Type |
|---|---|---|
| ✅ Confirmed | Jebao MCP Series Crossflow Wavemaker | Pump |
| ✅ Confirmed | Jebao MLW Series Wavemaker | Pump |
| ✅ Confirmed | Jebao Smart Doser 3.1 | Dosing pump |
| ✅ Confirmed | Jebao MD 4.4 Dosing Pump | Dosing pump |
| ✅ Confirmed | Jebao MD 2.4 Dosing Pump | Dosing pump |
| ⚠️ Untested | Jebao SLW Series Wavemaker | Pump |
| ⚠️ Untested | Jebao EP Series Pump | Pump |
| ❌ Not working | Any WiFi+Bluetooth (BLE) Jebao device | — |

**Legend:** ✅ tested and confirmed working — ⚠️ implemented but untested — ❌ not yet supported

## Features

- **Local LAN polling** — device state is read directly over your network every 2 s; no cloud polling during normal operation
- **Cloud control** — on/off, flow rate, frequency, and mode changes sent via the Gizwits API
- **Multi-region support** — EU, US, and CN Gizwits endpoints automatically selected by country
- **Pump control** — switch entities for power and other boolean states
- **Flow & frequency** — numeric slider entities for fine-grained speed control
- **Mode selection** — select entities for operating modes (wave, constant, pulse, etc.)
- **Fault monitoring** — sensor and binary sensor entities expose error/fault states reported by the device
- **No scheduling lock-in** — native app schedules are not imported; use Home Assistant automations instead

## Installation

### HACS (Recommended)

1. Open HACS in Home Assistant
2. Go to **Integrations** → **⋮** → **Custom repositories**
3. Add this repository URL and select **Integration** as the category
4. Search for "Jebao Aqua" and install
5. Restart Home Assistant

### Manual

1. Copy the `custom_components/jebao_aqua` folder to your Home Assistant `config/custom_components/` directory
2. Restart Home Assistant

## Configuration

1. Make sure your pumps are already set up in the **Jebao Aqua** app and connected to a Wi-Fi network reachable from your Home Assistant host
2. Note the local IP address of each pump (open the pump in the app → **Settings** icon → **Device Information**)
3. Go to **Settings** → **Devices & Services** → **Add Integration**
4. Search for **Jebao Aqua Aquarium Pump**
5. Enter your Jebao Aqua app credentials (email, password, and region/country)
6. The integration will discover all devices linked to your account and prompt you to enter the local IP for each

## Entities

The entities created for each device depend on its model definition. Common entities include:

| Entity | Type | Description |
|--------|------|-------------|
| Power | `switch` | Turn the pump on or off |
| Flow rate | `number` | Pump flow speed (%) |
| Frequency | `number` | Wave frequency setting |
| Mode | `select` | Operating mode (constant, wave, pulse, …) |
| Status / fault | `sensor` / `binary_sensor` | Device health and error indicators |

## Troubleshooting

Enable debug logging to capture detailed output:

```yaml
logger:
  default: warning
  logs:
    custom_components.jebao_aqua: debug
```

Restart Home Assistant and check **Settings → System → Logs**. If you encounter a bug or your device is not working, please [open an issue](../../issues/new) and include the debug log.

## Contributing & Adding New Devices

If you own a device listed as ⚠️ untested, please try the integration and open an issue with:
- Your device model and the product key shown in the debug log
- Which entities appeared and whether they responded correctly

Code contributions are welcome. Key files:

- API & cloud: [`api.py`](custom_components/jebao_aqua/api.py)
- Entity platforms: [`switch.py`](custom_components/jebao_aqua/switch.py), [`select.py`](custom_components/jebao_aqua/select.py), [`number.py`](custom_components/jebao_aqua/number.py), [`binary_sensor.py`](custom_components/jebao_aqua/binary_sensor.py)
- Device models: [`models/`](custom_components/jebao_aqua/models)

---

MIT

