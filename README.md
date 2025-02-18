# Home Assistant Custom Integration: Jebao Aquarium Pumps

![Logo](jebao-m-series-pump-controller.png)

This custom integration for Home Assistant allows users to control and monitor certain models of Wi-Fi enabled Jebao Aquarium Wavemakers/Pumps. Currently tested with the M series devices (with white and purple controller), though in theory it should be possible to get working with any device that supports Wi-Fi and makes use of the "Jebao Aqua" app for control.

The integration runs locally and does not require any cloud connectivity.

## Compatibility
> [!IMPORTANT]
> As of late 2024, it seems two different hardware versions of some model series may be available. The newer versions include support for Bluetooth (BLE) in addition to WiFi and use an ESP32C3 microcontroller rather than the legacy ESP8266.
> The WiFi+BLE devices do not yet work with this plugin - I'm investigating what's changed in the communication protocol and hope to add support soon.

| Device Model            | Compatibility  |
|-------------------------|----------------|
TBC

## Background
* The pump control unit houses an Espressif ESP8266 microcontroller, this is running a version of the [Gizwits GAgent](https://docs.gizwits.com/en-us/DeviceDev/GAgent.html#Features) code.
* Both the mobile app and pumps appear to communicate exclusively with Gizwits cloud - there is no indication of any Jebao specific infrastructure in use.
* Gizwits is, apparently, "The largest IoT development platform in Asia" - The [Bestway/Lay-Z-Spa](https://github.com/cdpuk/ha-bestway) and [PH-803W pH Controller](https://github.com/dala318/python_ph803w) projects are a examples of other Home Assistant integrations that interact with Gizwits platform via cloud and local methods, respectively. 
* Comprehensive documentation on the Gizwits protocol is available from the [node-ph803w](https://github.com/Apollon77/node-ph803w/blob/main/PROTOCOL.md) project.
  

## Why?
Although these pumps are fairly quiet, I wanted integration with Home Assistant to be able to easily turn the flow rate (and consequently noise) down in certain circumstances. The fact we can also monitor for fault conditions on the pumps is also helpful. 

## Features

- Control and monitor Jebao aquarium devices.
- Fully local with no dependency on the Gizwits cloud for operation.
- Supports various entities like switches, sensors, selectors, and numeric inputs for comprehensive control.
- Does not support the native 'scheduling' features that the app has (beyond (de)activating a programmed schedule) - using HA automations may be a better alternative in some cases.


## Installation

### Manual Installation

1. The devices must already have been setup with the Jebao Aqua app and connected to a Wi-Fi network that is routable from your Home Assistant installation.
3. Use HACS or clone the repo locally to install the integration code to /custom_components/
4. Add the "Jebao Aqua" integration via Home Assistant integrations dashboard. The integration should then discover the devices on your network automatically. You can change the device display name in Home Assistant after discovery. 

### Configuration

TODO

## Usage

Once installed and configured, the integration allows you to:

- Turn pumps on and off.
- Adjust flow, frequency settings, mode. 
- Monitor status and any fault indicators.

## Troubleshooting

If you encounter issues, enable Debug logging, and check the Home Assistant logs. You can also raise an issue in this repository.

