# Kilo Code Project Rules — Jebao Aqua Home Assistant Integration

## Project Overview

This is a **Home Assistant custom integration** for Jebao Aqua aquarium pumps (Gizwits-based protocol).
The integration communicates via local LAN (TCP 12416) for polling and Gizwits Cloud API (HTTPS) for control.

---

## Development Environment

### Home Assistant is Already Running in Docker

A Home Assistant instance is **already mounted and running inside this project** via Docker Compose.
Do NOT suggest setting up a separate HA instance or symlinking files elsewhere.

- **Container name**: `ha-jebao-dev`
- **HA Web UI**: http://localhost:8123
- **HA config directory** (host): `./ha-config/` → mounted as `/config` inside container
- **Integration source** (host): `./custom_components/jebao_aqua/` → mounted live as `/config/custom_components/jebao_aqua/` inside container
- **Timezone**: `Europe/Vienna`
- **Network mode**: bridged (ports exposed, NOT host mode)
- **Port mapping**: `8123:8123`

### Live Code Editing

Because `./custom_components/jebao_aqua/` is **volume-mounted directly** into the container,
any Python file edits in `custom_components/jebao_aqua/` are immediately reflected inside HA.
**A container restart is required** for HA to reload the changed Python modules.

---

## Docker Compose Usage Rules

### Starting / Stopping

```bash
# Start Home Assistant (detached)
docker compose up -d

# Stop Home Assistant
docker compose stop

# Restart to pick up code changes
docker compose restart homeassistant

# Full teardown (keeps volumes)
docker compose down

# Full teardown including volumes (wipes HA data)
docker compose down -v
```

### Viewing Logs

```bash
# Stream all logs
docker compose logs -f homeassistant

# Last 100 lines
docker compose logs --tail=100 homeassistant

# Filter for integration logs only
docker compose logs -f homeassistant | grep jebao_aqua

# Filter for errors
docker compose logs homeassistant | grep -i error | grep jebao
```

### Accessing the Container Shell

```bash
# Open a shell inside the running container
docker exec -it ha-jebao-dev bash

# Check that integration files are mounted correctly
docker exec -it ha-jebao-dev ls -la /config/custom_components/jebao_aqua/

# Syntax-check a Python file without restarting
docker exec -it ha-jebao-dev python3 -m py_compile /config/custom_components/jebao_aqua/api.py

# Tail the HA log file from inside the container
docker exec -it ha-jebao-dev tail -f /config/home-assistant.log
```

### Updating the HA Image

```bash
docker compose pull
docker compose up -d
```

---

## Project Structure

```
.
├── docker-compose.yml                  # HA dev environment definition
├── ha-config/                          # HA configuration (mounted as /config)
│   ├── configuration.yaml              # Debug logging enabled for jebao_aqua
│   ├── automations.yaml
│   ├── scripts.yaml
│   ├── scenes.yaml
│   └── custom_components/              # (managed by HA internally, do not edit manually)
├── custom_components/
│   └── jebao_aqua/                     # Integration source — live-mounted into HA
│       ├── __init__.py                 # Main coordinator & setup
│       ├── api.py                      # Gizwits API & local LAN protocol
│       ├── config_flow.py              # Setup wizard (UI)
│       ├── const.py                    # Constants, API URLs, platform list
│       ├── discovery.py                # UDP device discovery (port 12414)
│       ├── helpers.py                  # Utility functions
│       ├── binary_sensor.py            # Binary sensor entities
│       ├── sensor.py                   # Sensor entities
│       ├── switch.py                   # Switch entities
│       ├── select.py                   # Mode selector entities
│       ├── number.py                   # Numeric control entities
│       └── models/                     # Device model JSON files (one per product_key)
├── scripts/                            # Standalone utility scripts
│   ├── fetch_device_models.py          # Fetch model definitions from Gizwits
│   └── test_mode_debug.py              # Mode debugging helper
└── docs/                               # Developer documentation
```

---

## Development Workflow

### After Editing Python Files

1. Edit files in `custom_components/jebao_aqua/`
2. Restart HA to reload: `docker compose restart homeassistant`
3. Watch logs: `docker compose logs -f homeassistant | grep jebao_aqua`
4. Verify in UI: http://localhost:8123 → Settings → Devices & Services

### After Editing `ha-config/configuration.yaml`

Restart HA: `docker compose restart homeassistant`

### Debug Logging

Debug logging for the integration is **already enabled** in `ha-config/configuration.yaml`:

```yaml
logger:
  default: info
  logs:
    custom_components.jebao_aqua: debug
    custom_components.jebao_aqua.api: debug
    custom_components.jebao_aqua.config_flow: debug
    custom_components.jebao_aqua.discovery: debug
```

### Key Log Patterns

| Pattern | Meaning |
|---------|---------|
| `Got fresh data for device` | Local LAN polling works ✅ |
| `Response from Gizwits API` | Cloud control works ✅ |
| `Failed to fetch device data` | Connection issue ❌ |
| `Error parsing device status payload` | Model JSON mapping issue ❌ |

---

## Integration Architecture

- **Polling**: Local LAN TCP port `12416` every 2 seconds
- **Control**: Gizwits Cloud API (HTTPS) — three regions: `eu`, `us`, `cn`
- **Discovery**: UDP broadcast port `12414`
- **Device models**: JSON files in `models/` keyed by Gizwits `product_key`

### Adding a New Device Model

1. Create `custom_components/jebao_aqua/models/<PRODUCT_KEY>.json`
2. Map binary protocol byte/bit positions to entity attributes
3. Restart HA and test with a real device
4. Update `README.md` compatibility table

---

## Important Constraints

- **Do NOT** suggest installing HA separately — it is already running via Docker in this project.
- **Do NOT** suggest symlinking `custom_components/` to `~/.homeassistant/` — the volume mount handles this.
- **Do NOT** use `network_mode: host` — the current setup uses bridged networking with explicit port mapping `8123:8123`.
- **Always restart** the container after Python changes: `docker compose restart homeassistant`
- The `ha-config/custom_components/` subdirectory is managed by HA internally — do not manually place files there.
- The database is SQLite at `/config/home-assistant_v2.db` (inside container), kept small with `purge_keep_days: 1`.
