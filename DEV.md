# Local Development & Troubleshooting Guide

## 1. Set Up a Local Home Assistant Dev Environment

### Option A: Home Assistant Container (quickest)

```bash
# Run HA Core in Docker, mounting your custom component in
docker run -d \
  --name homeassistant \
  --restart=unless-stopped \
  -v /home/raphael/ha-config:/config \
  -v /home/raphael/Coded/jebao_aqua-homeassistant/custom_components:/config/custom_components \
  --network=host \
  ghcr.io/home-assistant/home-assistant:stable
```

This mounts your working code directly into HA's config, so edits are reflected on restart.

### Option B: HA Core in a Python venv (best for debugging)

```bash
# Create a venv and install HA Core
python3 -m venv ha-venv
source ha-venv/bin/activate
pip install homeassistant

# Create a config directory and symlink your component
mkdir -p ha-config/custom_components
ln -s /home/raphael/Coded/jebao_aqua-homeassistant/custom_components/jebao_aqua \
      ha-config/custom_components/jebao_aqua

# Install extra deps your code uses
pip install pycountry aiohttp

# Run HA
hass -c ha-config
```

HA will start on `http://localhost:8123`. You can go through onboarding, then add "Jebao Aqua Aquarium Pump" from the Integrations page.

---

## 2. Enable Debug Logging

Add this to `ha-config/configuration.yaml`:

```yaml
logger:
  default: warning
  logs:
    custom_components.jebao_aqua: debug
```

This enables verbose output from the integration (all `LOGGER.debug(...)` calls in the code). Logs appear in:
- **Terminal** (if running `hass` directly)
- **HA UI** → Settings → System → Logs
- **File**: `ha-config/home-assistant.log`

---

## 3. Key Troubleshooting Points

| Area | What to check |
|---|---|
| **Login/Auth** | The config flow (`config_flow.py`) calls the Gizwits API. Check logs for `Login response status` and error codes. |
| **Device models** | `__init__.py` loads JSON model files from `models/`. If your pump's `product_key` doesn't match any model file, entities won't appear. |
| **LAN polling** | The integration polls devices locally on **TCP port 12416** (`const.py`). Your HA host must be on the same network/VLAN as the pumps. |
| **Control commands** | Verified MCP150 commands try LAN first; unsupported devices and failed/unconfirmed LAN commands use Gizwits cloud. Token expiry or regional mismatch affects the cloud path. |
| **Coordinator updates** | The `DataUpdateCoordinator` refreshes every **2 seconds** (`const.py`). `UpdateFailed` exceptions in logs indicate polling issues. |

---

## 4. Live Editing & Reloading

After making code changes:

1. **Quick reload**: Go to HA UI → Settings → Integrations → Jebao Aqua → ⋮ menu → **Reload**
2. **Full restart**: Stop and re-run `hass -c ha-config` (needed for changes to `__init__.py` setup or `manifest.json`)

---

## 5. Interactive Debugging (Option B only)

For breakpoint debugging with the venv approach:

```bash
# Install debugpy
pip install debugpy

# Run HA with debugger attached
python -m debugpy --listen 5678 --wait-for-client -m homeassistant -c ha-config
```

Then attach VS Code's debugger with this `launch.json`:

```json
{
  "name": "Attach to HA",
  "type": "debugpy",
  "request": "attach",
  "connect": { "host": "localhost", "port": 5678 }
}
```

You can then set breakpoints in any file under `custom_components/jebao_aqua/`.

---

## 6. Testing

### Without real hardware

If you don't have pumps available, you can mock the API layer. A quick approach:

```python
# In api.py, temporarily add mock responses to test the UI flow
async def get_device_data(self, device_id):
    return {"Power": 1, "Speed": 50, "Mode": 1, "Fault": 0}  # fake data
```

---

### Standalone MCP150 LAN control experiment

The standard-library-only [MCP150 probe](scripts/mcp150_local.py) loads the
integration's shared [LAN client](custom_components/jebao_aqua/local.py)
without importing Home Assistant. It accepts only product key
`54114ccdac1e41c0bb17e222887c07ba`; other devices are rejected before login.
It does not use cloud credentials.

Verified on an MCP150 with ESP32-C3 Wi-Fi firmware `04D30Q29`: all nine HA
controls, both boolean states, all four modes, and all three linkage options.
The full test made 12 temporary changes with independent-connection verification and
restoration after each. Native schedules and fault status stayed unchanged.
Numeric controls were tested with neighboring values, not every possible value;
encoding limits are covered by automated tests. This is evidence for this
device/firmware, not all Jebao variants. Cloud/app verification remains manual.

```bash
# Read status only (the default; no settings are written)
python3 scripts/mcp150_local.py 192.168.50.42

# Requires the pump's native timer OFF; changes/restores only Flow
python3 scripts/mcp150_local.py 192.168.50.42 --test-flow

# Allow more time to observe the temporary setting in the Jebao app
python3 scripts/mcp150_local.py 192.168.50.42 --test-flow --hold 10

# WARNING: temporarily disables/restores the timer; tests power/feeding/linkage
python3 scripts/mcp150_local.py 192.168.50.42 --test-all --hold 0.5
```

Each write flags only the selected attributes in the 64-bit mask, copying the
current 400-byte writable block to preserve unselected values. The Flow-only
test checks unrelated bytes except the device clock. The full test checks
schedules/faults and restores any related exposed settings the device changes.
Both changes and restoration must also be confirmed over a separate TCP
connection; an immediate same-session value alone is not sufficient.
Matching request serial numbers ensure read-back is fresh. Do not change settings
from the app or automations while testing. Linkage tests may affect paired pumps.

Restoration is attempted over a fresh connection even after an error or Ctrl+C.
If restoration cannot be verified, the script exits unsuccessfully and prints
the original settings to restore manually. Keep the pump/app accessible during
testing; a disconnected device or a forcibly terminated process cannot be
guaranteed to restore. Never treat a successful TCP send as a successful test:
the script reports success only after both changed and restored values are read.

The device's native timer was found to overwrite a manual Flow change immediately:
with `TimerON=true`, an immediate response showed 99 but independent reads showed
100 again. With the timer off, 99 persisted across repeated independent reads.
The Flow-only probe therefore refuses an enabled timer. The full probe disables
it temporarily, tests all controls, and restores the user's original timer setting
even after an error. Normal integration commands do **not** disable it
automatically. Turn off Timer in HA before manual control when necessary;
cloud fallback cannot be assumed to defeat a native schedule.

The integration runs this same bounded socket client in a worker thread so
network I/O does not block Home Assistant's event loop. Its coordinator shares
one lock per device between polling and commands, publishes confirmed local
status immediately, and resets LAN backoff after a successful local command.
Unconfirmed local commands fall back to the existing cloud API; failure of both
paths is a service error, not a successful update. Other product keys retain
their existing cloud-control and LAN-polling paths.

## 7. Authentication Flow

The integration authenticates with the Gizwits cloud API using email/password credentials. The auth flow is designed for robustness:

### Token Lifecycle

1. **Initial login**: During config flow setup, the user provides email + password. The integration calls the Gizwits `/login/pwd` endpoint, which returns a `userToken`.
2. **Storage**: The token, email, and password are stored in the HA config entry (encrypted at rest by HA's storage layer).
3. **Runtime usage**: All cloud API calls (`get_devices`, `get_device_data`, `control_device`) include the token in the `X-Gizwits-User-token` header.
4. **Expiry detection**: If any API call returns HTTP 401, the token is considered expired.
5. **Auto re-auth**: The `_try_reauth()` method re-logs-in with stored credentials and updates the token. A cooldown (30s) prevents concurrent/repeated re-auth.
6. **Token persistence**: On successful re-auth, the `on_token_refresh` callback updates the HA config entry so the new token survives restarts.

### Retry & Reconnect Strategy

- **HTTP retries**: All cloud API requests are wrapped in `_api_request()` which retries up to 3 times with exponential backoff (1s, 2s, 4s) on connection errors or timeouts.
- **Session recovery**: If the `aiohttp` session is closed or broken, `_ensure_session()` transparently recreates it before each request.
- **Auth lock**: An `asyncio.Lock` ensures only one re-authentication runs at a time, even when multiple device polls trigger 401 simultaneously.
- **Graceful degradation**: If re-auth fails, the coordinator preserves the last known device data so entities stay available with stale values rather than going unavailable.

### Key Classes

| Class | File | Role |
|---|---|---|
| `GizwitsApi` | `api.py` | Handles all Gizwits HTTP calls, token management, retry logic |
| `AuthenticationError` | `api.py` | Raised when auth fails permanently (re-auth unsuccessful) |
| `GizwitsDataUpdateCoordinator` | `__init__.py` | Polls devices on a 2s interval, handles auth errors gracefully |

### Sequence Diagram (Token Refresh)

```
Coordinator -> api._api_request: GET /devdata/{id}/latest
api._api_request -> Gizwits: HTTP request (with expired token)
Gizwits -> api._api_request: 401 Unauthorized
api._api_request -> api._try_reauth: Token expired
api._try_reauth -> api.async_login: Re-login with email/password
api.async_login -> Gizwits: POST /login/pwd
Gizwits -> api.async_login: New userToken
api._try_reauth -> on_token_refresh callback: Save new token to config entry
api._api_request -> Gizwits: Retry HTTP request (with new token)
Gizwits -> api._api_request: 200 OK
api._api_request -> Coordinator: Device data
```

### Upgrading from Older Versions

Users who configured the integration before password storage was added will see a warning:
> "Password not stored in config entry. Automatic token refresh will not be available."

They should reconfigure via Settings → Integrations → Jebao Aqua → ⋮ → Reconfigure.

---

## 8. Running Tests

```bash
# From the project root, with the venv activated:
pip install pytest pytest-asyncio aiohttp
pytest tests/ -v
```
