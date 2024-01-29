# Home Assistant Custom Integration: Jebao Aquarium Pumps

This custom integration for Home Assistant allows users to control and monitor certain models of Wi-Fi enabled Jebao Aquarium Pumps. Currently tested with the M series devices (with white and purple controller), though in theory it should be possible to get working with any device that supports WiFI and makes use of the "Jebao Aqua" app for control.

The integration currently polls devices via the LAN for status updates but uses the Gizwits Cloud API for remote control.

_Note: I'm not a developer. This code was almost entirely written by ChatGPT based on my packet captures, the Gizwits documentation and some resources from the mobile app APK. I now realise it doesn't conform to eastablished practices for Home Assistant to directly interface with the API from an integration, sorry._


## Background
_TODO_
* Overview of Gizwits cloud platform.
* Note they use some form of unencrypted MQTT between device and cloud - have a feeling it _might_ be possible to reconfigure the devices to point to arbitrary MQTT server instead.
* Explain 'bindings', 'datapoint', 'devdata' and 'control' API endpoints. 
* Local interface on TCP/12416 - cloud helpfully provides payload structure
  

## Why?
Although these pumps are fairly quiet, I wanted integration with Home Assistant to be able to easily turn the flow rate (and consequently noise) down in certain circumstances. The fact we can also monitor for fault conditions on the pumps is also helpful. 

## Features

- Control Jebao Aquarium Pumps remotely via the Gizwits API.
- Poll device status locally for real-time updates (primarily so that we don't annoy Gizwits with excessive requests, but also provides faster response to control commands).
- Supports various entities like switches, sensors, selectors, and numeric inputs for comprehensive control.
- Does not support the native 'scheduling' features that the app has - just use HA instead.

TODO:
- LAN IP Auto discovery - this is easy to do at a protocol level, just need to figure out how to get a Home Assistant integration to listen for UDP packets on a given port.
- Local Control - In theory it would be more robust to avoid interacting with the GizWits API at all. Currently we use the local interface for _polling_ but not for _control_. Need to check: https://github.com/tancou/jebao-dosing-pump-md-4.4 and associated https://github.com/Apollon77/node-ph803w as now realise they have already done this...

## Installation

### Manual Installation

1. Use HACS or clone the repo locally.

### Configuration

TODO - Explain how the JSON for each pump model needs to be obtained from Gizwits '/app/datapoint' endpoint and which Chinese strings need to be translated.


## Usage

Once installed and configured, the integration allows you to:

- Turn pumps on and off.
- Adjust flow, frequency settings, mode. 
- Monitor status and any fault indicators.

## Troubleshooting

If you encounter issues, enable Debug logging, and check the Home Assistant logs. You can also raise an issue in this repository.

