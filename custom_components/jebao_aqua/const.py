"""Constants for the Jebao Aqua integration."""

DOMAIN = "jebao_aqua"

# List of platforms that will be set up if the device has relevant datapoints.
PLATFORMS = ["light", "sensor", "number", "select", "switch", "binary_sensor"]

# Device enum values (Chinese, from the Gizwits datapoint definitions) mapped
# to stable slugs used as select options. HA requires option/translation keys
# to be [a-z0-9-_]+; translations map the slugs to display names per language.
ENUM_OPTION_SLUGS = {
    "停机": "off",
    "喂食": "feeding",
    "恒流造浪": "constant_flow",
    "正弦造浪": "sine_wave",
    "经典造浪": "square_wave",
    "随机造浪": "random_wave",
    "自动": "auto",
    "手动": "manual",
    "早晨": "morning",
    "日出": "sunrise",
    "白天": "daytime",
    "日落": "sunset",
    "夜晚": "night",
    "定时": "timed",
    "主机": "primary",
    "从机": "secondary",
    "独立": "independent",
    "校准1": "calibration_1",
    "校准2": "calibration_2",
    "校准3": "calibration_3",
    "校准4": "calibration_4",
    "校准5": "calibration_5",
    "校准6": "calibration_6",
    "校准7": "calibration_7",
    "校准8": "calibration_8",
}

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
