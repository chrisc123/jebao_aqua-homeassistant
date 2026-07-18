"""Constants for the Jebao Aqua integration."""

DOMAIN = "jebao_aqua"

# List of platforms that will be set up if the device has relevant datapoints.
PLATFORMS = ["light", "sensor", "number", "select", "switch", "binary_sensor"]

# Connection mode: fully local (LAN push, default) or fully cloud (Gizwits API).
CONF_MODE = "mode"
MODE_LOCAL = "local"
MODE_CLOUD = "cloud"
DEFAULT_MODE = MODE_LOCAL

# Gizwits cloud API
GIZWITS_APP_ID = "c3703c4888ec4736a3a0d9425c321604"
CLOUD_TIMEOUT = 10
# Poll the cloud every 30s; 2s hammered the Gizwits API (~260k req/day for
# six devices) and provides no benefit for slow-changing pump state.
CLOUD_UPDATE_INTERVAL = 30

DEFAULT_REGION = "eu"
GIZWITS_API_URLS = {
    "eu": {
        "LOGIN_URL": "https://euaepapp.gizwits.com/app/smart_home/login/pwd",
        "DEVICES_URL": "https://euapi.gizwits.com/app/bindings",
        "DEVICE_DATA_URL": "https://euapi.gizwits.com/app/devdata/{device_id}/latest",
        "CONTROL_URL": "https://euapi.gizwits.com/app/control/{device_id}",
    },
    "us": {
        "LOGIN_URL": "https://usaepapp.gizwits.com/app/smart_home/login/pwd",
        "DEVICES_URL": "https://usapi.gizwits.com/app/bindings",
        "DEVICE_DATA_URL": "https://usapi.gizwits.com/app/devdata/{device_id}/latest",
        "CONTROL_URL": "https://usapi.gizwits.com/app/control/{device_id}",
    },
    "cn": {
        "LOGIN_URL": "https://aep-app.gizwits.com/app/smart_home/login/pwd",
        "DEVICES_URL": "https://api.gizwits.com/app/bindings",
        "DEVICE_DATA_URL": "https://api.gizwits.com/app/devdata/{device_id}/latest",
        "CONTROL_URL": "https://api.gizwits.com/app/control/{device_id}",
    },
}
