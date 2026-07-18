# Home Assistant Custom Integration: Jebao Aquarium Pumps

![Logo](jebao-m-series-pump-controller.png)

This custom integration for Home Assistant allows you to control and monitor Wi-Fi enabled Jebao/Jecod aquarium devices — wavemakers, return/DC pumps, dosing pumps, and LED lights — anything set up through the "Jebao Aqua" app.

By default the integration runs **fully locally** using push-based updates: state changes arrive instantly over your LAN with no cloud dependency. An optional **cloud mode** is available for setups where the devices are not reachable from Home Assistant over the local network (polls the Gizwits cloud every 30 seconds).

## Compatibility

Both hardware generations are supported:

- **Legacy Wi-Fi devices** (ESP8266-based, white/purple controllers)
- **Newer Wi-Fi + Bluetooth (BLE) devices** (ESP32-C3-based, sold from ~late 2024)

| Device type | Examples | Status |
|---|---|---|
| Wavemakers | M/MW series, SLW, MLW series (incl. Wi-Fi+BLE) | Tested |
| Return / DC pumps | EP series, MDP series (incl. Wi-Fi+BLE) | Reported working by users |
| Dosing pumps | MD-4.4, Doser 2.4 (4-channel), MD-4.5 (5-channel, Wi-Fi+BLE) | **Beta — see caution below** |
| LED lights | Local-timer LED models | Reported working by users |

> [!CAUTION]
> **Dosing pump support is community-contributed and not tested by the maintainer** (I don't own a doser). The model definitions, protocol handling for these devices, and the dosing schedule sensors are based on pull requests and protocol captures from users who do ([#54](https://github.com/chrisc123/jebao_aqua-homeassistant/pull/54), [#49](https://github.com/chrisc123/jebao_aqua-homeassistant/pull/49)). Exercise caution: verify switches and schedules do what you expect before relying on them — a misbehaving doser can harm livestock. Feedback and issue reports from doser owners are very welcome.

### Adding support for a new device

If your device isn't recognised (log shows `Device definition not found`), support can usually be added quickly — the device's *product key* (a 32-character hex string) is all that's needed, since the full device definition can be fetched from the Gizwits API using it. Please [open an issue](https://github.com/chrisc123/jebao_aqua-homeassistant/issues) including the product key and your device's model name.

**Where to find the product key:**

- **In the error itself** — the `Device definition not found: .../models/<product_key>.json` log message contains it.
- **In the discovery log** — enable debug logging for `custom_components.jebao_aqua` (Settings → Devices & Services → Jebao Aqua → Enable debug logging), reload the integration, and look for lines like `Found device: ip=... mac=... uid=... product_key=...`.

## Features

- Instant, push-based state updates over the LAN (no polling, no cloud) — or optional cloud mode where LAN access isn't possible.
- Switches, mode selectors, flow/speed controls, and fault sensors per device.
- Dosing pumps: per-channel schedule sensors showing the next upcoming dose and daily dose volume (read-only; schedules are still programmed in the app).
- Automatic recovery when a device's IP address changes (e.g. DHCP lease renewal) — devices are re-discovered by their unique ID and reconnected.
- Native app scheduling is not replicated (beyond enabling/disabling a programmed schedule) — Home Assistant automations are usually the better tool.

## Installation

1. Set the devices up with the Jebao Aqua app first, connected to a Wi-Fi network routable from your Home Assistant installation.
2. Install via [HACS](https://hacs.xyz/) (or copy `custom_components/jebao_aqua/` into your config manually).
3. Add the **Jebao Aqua** integration from the Home Assistant integrations dashboard.
4. Choose your connection mode:
   - **Local control (recommended):** devices on your network are discovered automatically; you can also add one manually by IP.
   - **Cloud control:** sign in with your Jebao Aqua app account and devices are imported from the cloud.

You can switch between local and cloud mode at any time from the integration's **Configure** menu — entities keep their identity across the switch.

### Beta versions

Pre-release versions are published as GitHub pre-releases and are **not** installed automatically. To try them in HACS: open the integration in HACS → ⋮ menu → **Redownload** → enable **Show beta versions** and pick the pre-release.

## Removal

1. Go to **Settings → Devices & Services**, open the **Jebao Aqua** integration, and delete it. This removes all its devices and entities, and deletes any stored data — including cloud login credentials if you used cloud mode.
2. If installed via HACS, remove the repository from HACS to delete the integration files, then restart Home Assistant.

The devices themselves are unaffected and continue to work with the Jebao Aqua app.

## Upgrading from v0.1.x

v0.4.0 migrates old installs automatically: config entries, devices, entities, and their `entity_id`s are preserved, so automations and dashboards keep working. Installs that were running cloud-only (no LAN IPs configured) are migrated to the new cloud mode automatically. Cloud login credentials from v0.1.x are no longer used in local mode and are removed from storage during migration.

## Background

- The pump control unit houses an Espressif ESP8266 (newer models: ESP32-C3) running a version of the [Gizwits GAgent](https://docs.gizwits.com/en-us/DeviceDev/GAgent.html#Features) firmware.
- Both the mobile app and pumps communicate with the Gizwits cloud — there is no Jebao-specific infrastructure — and the devices expose the standard Gizwits LAN protocol, which this integration speaks directly.
- Gizwits is, apparently, "The largest IoT development platform in Asia" — the [Bestway/Lay-Z-Spa](https://github.com/cdpuk/ha-bestway) and [PH-803W pH Controller](https://github.com/dala318/python_ph803w) projects are examples of other Home Assistant integrations that interact with the Gizwits platform via cloud and local methods, respectively.
- Comprehensive documentation on the Gizwits protocol is available from the [node-ph803w](https://github.com/Apollon77/node-ph803w/blob/main/PROTOCOL.md) project.

## Why?

Although these pumps are fairly quiet, I wanted integration with Home Assistant to be able to easily turn the flow rate (and consequently noise) down in certain circumstances. The fact we can also monitor for fault conditions on the pumps is also helpful.

## Troubleshooting

If you encounter issues, enable debug logging for `custom_components.jebao_aqua` and check the Home Assistant logs. You can also raise an issue in this repository.

## Credits

Device support and fixes contributed by the community, including
[@franknh-design](https://github.com/franknh-design) and tewing (MD-4.5 doser),
[@Sangoku](https://github.com/Sangoku) (dosing schedule sensors, MLW fixes),
[@XavierTerrell](https://github.com/XavierTerrell) (cloud-mode fixes),
[@cp296944](https://github.com/cp296944), [@rbickel](https://github.com/rbickel),
[@jeffcybulski](https://github.com/jeffcybulski), [@gcosta74](https://github.com/gcosta74),
and [@joluan01](https://github.com/joluan01).
