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
| **Cloud control** | Control commands go through Gizwits cloud API. Token expiry or regional mismatch (EU/US/CN) will cause failures. |
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

## 6. Testing Without Real Hardware

If you don't have pumps available, you can mock the API layer. A quick approach:

```python
# In api.py, temporarily add mock responses to test the UI flow
async def get_device_data(self, device_id):
    return {"Power": 1, "Speed": 50, "Mode": 1, "Fault": 0}  # fake data
```

---

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
