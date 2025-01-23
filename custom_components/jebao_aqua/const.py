"""Constants for the Jebao Aqua Pump integration."""

DOMAIN = "jebao_aqua"
# Logger
import logging
LOGGER = logging.getLogger(__package__)

# API constants
GIZWITS_APP_ID = "c3703c4888ec4736a3a0d9425c321604" # This i used by the Android app, iOS may use a different one?
GIZWITS_LOGIN_URL = "https://euaepapp.gizwits.com/app/smart_home/login/pwd" # EU Cloud endpoints
GIZWITS_DEVICES_URL = "https://euapi.gizwits.com/app/bindings"
GIZWITS_DEVICE_DATA_URL = "https://euapi.gizwits.com/app/devdata/{device_id}/latest"
GIZWITS_CONTROL_URL = "https://euapi.gizwits.com/app/control/{device_id}"
TIMEOUT = 10
LAN_PORT=12416

# Update interval
from datetime import timedelta
UPDATE_INTERVAL = timedelta(seconds=2)

# Platform types
PLATFORMS = ["switch", "sensor", "select", "number"]
