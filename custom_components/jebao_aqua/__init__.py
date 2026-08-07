"""The Jebao Aqua integration."""

from __future__ import annotations

import json
import logging
from pathlib import Path
import re

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import ConfigEntryNotReady, HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr, entity_registry as er

from .cloud import GizwitsCloudApi, JebaoCloudDevice, parse_channel_names
from .const import (
    CONF_MODE,
    DEFAULT_REGION,
    DOMAIN,
    MODE_CLOUD,
    MODE_LOCAL,
    PLATFORMS,
)
from .hub import JebaoDevice, _load_device_configs, async_discover_devices

_LOGGER = logging.getLogger(__name__)

CONFIG_ENTRY_VERSION = 2
# Service name exposed as jebao_aqua.set_doser_schedule
SERVICE_SET_DOSER_SCHEDULE = "set_doser_schedule"
# CHxSWTime uses a fixed 96-byte payload in all known doser models.
SCHEDULE_BYTES_LEN = 96
# 96 bytes = 12 blocks * 8 bytes, each block holds 2 schedule slots.
MAX_DOSER_SLOTS = 24


def _validate_schedule_service_target(data: dict) -> dict:
    """Validate target/channel requirements for schedule writes."""
    if not data.get("device_uid") and not data.get("entity_id"):
        raise vol.Invalid("Either device_uid or entity_id is required")

    # For UID-only calls we cannot infer the channel, so require it explicitly.
    if data.get("device_uid") and not data.get("entity_id") and "channel" not in data:
        raise vol.Invalid("channel is required when entity_id is not provided")
    return data


SET_DOSER_SCHEDULE_SCHEMA = vol.All(
    vol.Schema(
        {
            vol.Optional("device_uid"): cv.string,
            vol.Optional("entity_id"): cv.entity_id,
            vol.Optional("channel"): vol.All(vol.Coerce(int), vol.Range(min=1, max=8)),
            vol.Required("slots"): [dict],
            vol.Optional("enable_timer"): cv.boolean,
            vol.Optional("interval_days"): vol.All(
                vol.Coerce(int), vol.Range(min=0, max=30)
            ),
        }
    ),
    _validate_schedule_service_target,
)


def _parse_schedule_slot(slot: dict, index: int) -> tuple[int, int, int]:
    """Validate and normalize a schedule slot entry."""
    if not isinstance(slot, dict):
        raise HomeAssistantError(f"Slot {index} must be an object")

    ml_raw = slot.get("dose_ml", slot.get("ml"))
    if ml_raw is None:
        raise HomeAssistantError(f"Slot {index} requires ml or dose_ml")
    try:
        ml = int(ml_raw)
    except (TypeError, ValueError) as exc:
        raise HomeAssistantError(f"Slot {index} has invalid ml value") from exc
    if not 1 <= ml <= 255:
        raise HomeAssistantError(f"Slot {index} ml must be between 1 and 255")

    time_raw = slot.get("time")
    if time_raw is not None:
        if not isinstance(time_raw, str) or ":" not in time_raw:
            raise HomeAssistantError(f"Slot {index} time must be HH:MM")
        hh, mm = time_raw.split(":", 1)
        try:
            hour = int(hh)
            minute = int(mm)
        except ValueError as exc:
            raise HomeAssistantError(f"Slot {index} time must be HH:MM") from exc
    else:
        if "hour" not in slot or "minute" not in slot:
            raise HomeAssistantError(
                f"Slot {index} requires time or both hour and minute"
            )
        try:
            hour = int(slot["hour"])
            minute = int(slot["minute"])
        except (TypeError, ValueError) as exc:
            raise HomeAssistantError(
                f"Slot {index} hour/minute must be integers"
            ) from exc

    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        raise HomeAssistantError(f"Slot {index} has invalid time {hour:02d}:{minute:02d}")

    return hour, minute, ml


def _build_schedule_blob(slots: list[dict]) -> bytes:
    """Encode up to 24 schedule slots into the CHxSWTime 96-byte payload."""
    if len(slots) > MAX_DOSER_SLOTS:
        raise HomeAssistantError(
            f"Maximum {MAX_DOSER_SLOTS} slots are supported per channel"
        )

    payload = bytearray(SCHEDULE_BYTES_LEN)
    for idx, slot in enumerate(slots):
        hour, minute, ml = _parse_schedule_slot(slot, idx + 1)
        # Two slots are packed per 8-byte block: [h,m,0,ml, h,m,0,ml].
        pair = idx // 2
        in_pair_offset = 0 if idx % 2 == 0 else 4
        base = pair * 8 + in_pair_offset
        payload[base] = hour
        payload[base + 1] = minute
        payload[base + 2] = 0
        payload[base + 3] = ml

    return bytes(payload)


def _resolve_target_from_entity_id(
    hass: HomeAssistant, entity_id: str
) -> tuple[str, int | None]:
    """Resolve target device UID and (when possible) channel from an entity."""
    entity_registry = er.async_get(hass)
    entry = entity_registry.async_get(entity_id)
    if entry is None:
        raise HomeAssistantError(f"Entity {entity_id} was not found")
    if not entry.unique_id or "_" not in entry.unique_id:
        raise HomeAssistantError(
            f"Entity {entity_id} does not expose a parsable unique_id"
        )
    try:
        uid, attr_name, _platform = entry.unique_id.rsplit("_", 2)
    except ValueError as exc:
        raise HomeAssistantError(
            f"Entity {entity_id} does not expose a parsable unique_id"
        ) from exc
    if not uid:
        raise HomeAssistantError(f"Could not extract device UID from {entity_id}")

    # Infer channel from common doser attribute naming patterns so selecting an
    # entity in the UI usually removes the need to manually set channel.
    inferred_channel: int | None = None
    channel_patterns = (
        r"^CH([1-8])(?:Schedule|Volume)$",  # derived HA schedule/volume sensors
        r"^CH([1-8])SWTime$",               # raw schedule datapoint
        r"^channe([1-8])$",                 # model typo used by the device defs
        r"^Timer([1-8])ON$",                # per-channel timer switch
        r"^IntervalT([1-8])$",              # per-channel pause-days number
    )
    for pattern in channel_patterns:
        match = re.match(pattern, attr_name)
        if match:
            inferred_channel = int(match.group(1))
            break
    return uid, inferred_channel


def _get_loaded_devices(hass: HomeAssistant) -> list[JebaoDevice | JebaoCloudDevice]:
    """Collect all currently loaded devices across config entries."""
    devices: list[JebaoDevice | JebaoCloudDevice] = []
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.runtime_data:
            devices.extend(entry.runtime_data)
    return devices


def _find_device_by_uid(
    hass: HomeAssistant, device_uid: str
) -> JebaoDevice | JebaoCloudDevice:
    """Return the loaded device matching the requested UID."""
    for device in _get_loaded_devices(hass):
        if getattr(device, "uid", None) == device_uid:
            return device
    raise HomeAssistantError(
        f"Device UID {device_uid} is not loaded by the {DOMAIN} integration"
    )


async def _refresh_device_state(device: JebaoDevice | JebaoCloudDevice) -> None:
    """Best-effort refresh so entities reflect schedule changes quickly."""
    try:
        if hasattr(device, "request_status_update"):
            # Cloud wrapper and some device wrappers expose this directly.
            await device.request_status_update()
            return
        giz_device = getattr(device, "giz_device", None)
        if giz_device and hasattr(giz_device, "request_status_update"):
            # LAN device path: refresh through underlying protocol device.
            await giz_device.request_status_update()
    except Exception as exc:
        _LOGGER.debug("Could not refresh device status after schedule update: %s", exc)


def _async_register_services(hass: HomeAssistant) -> None:
    """Register integration-level services once."""
    if hass.services.has_service(DOMAIN, SERVICE_SET_DOSER_SCHEDULE):
        return

    async def _async_handle_set_doser_schedule(call: ServiceCall) -> None:
        # Validate and normalize service data once at entry.
        data = SET_DOSER_SCHEDULE_SCHEMA(dict(call.data))
        device_uid = data.get("device_uid")
        channel = data.get("channel")

        if data.get("entity_id"):
            # Allow targeting by any integration entity from the same device,
            # while auto-selecting the channel for CHx schedule/volume sensors.
            uid_from_entity, channel_from_entity = _resolve_target_from_entity_id(
                hass, data["entity_id"]
            )
            if device_uid and device_uid != uid_from_entity:
                raise HomeAssistantError(
                    "device_uid does not match the selected entity_id device"
                )
            device_uid = uid_from_entity

            if channel_from_entity is not None:
                if channel is not None and channel != channel_from_entity:
                    raise HomeAssistantError(
                        "Selected entity channel does not match the provided channel"
                    )
                channel = channel_from_entity

        if not device_uid:
            raise HomeAssistantError("Could not resolve target device")
        if channel is None:
            raise HomeAssistantError(
                "channel is required when it cannot be inferred from entity_id"
            )

        attr_name = f"CH{channel}SWTime"
        # Encode to hex so both LAN and cloud writers can consume it.
        payload_hex = _build_schedule_blob(data["slots"]).hex()

        device = _find_device_by_uid(hass, device_uid)
        attr_names = {
            attr.get("name")
            for attr in getattr(device.giz_device, "all_attrs", [])
            if isinstance(attr, dict)
        }
        if attr_name not in attr_names:
            raise HomeAssistantError(
                f"Device {device_uid} does not support {attr_name}"
            )

        # Main write: replace the full channel schedule in one command.
        await device.async_set_attribute(attr_name, payload_hex)

        if "interval_days" in data:
            interval_attr = f"IntervalT{channel}"
            if interval_attr not in attr_names:
                raise HomeAssistantError(
                    f"Device {device_uid} does not support {interval_attr}"
                )
            await device.async_set_attribute(interval_attr, int(data["interval_days"]))

        if "enable_timer" in data:
            timer_attr = f"Timer{channel}ON"
            if timer_attr in attr_names:
                # Optional convenience write to align timer mode with schedule changes.
                await device.async_set_attribute(timer_attr, bool(data["enable_timer"]))

        # Trigger a refresh so sensors reflect the new schedule quickly.
        await _refresh_device_state(device)

    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_DOSER_SCHEDULE,
        _async_handle_set_doser_schedule,
        schema=SET_DOSER_SCHEDULE_SCHEMA,
    )


def _async_unregister_services(hass: HomeAssistant) -> None:
    """Remove integration services when the last entry unloads."""
    if hass.services.has_service(DOMAIN, SERVICE_SET_DOSER_SCHEDULE):
        hass.services.async_remove(DOMAIN, SERVICE_SET_DOSER_SCHEDULE)


def _did_to_uid(did: str) -> str:
    """Convert a v1 cloud device id (22-char ASCII) to the v2 LAN uid (hex).

    LAN discovery reports the same 22 bytes the cloud used as the ``did``,
    but v2 stores them hex-encoded.
    """
    return did.encode("ascii", "ignore").hex()


def _load_attr_name_map(product_key: str) -> dict[str, str]:
    """Map v1 unique_id attribute suffixes (lowercased) to raw attribute names."""
    model_file = Path(__file__).parent / "models" / f"{product_key}.json"
    if not model_file.is_file():
        return {}
    data = json.loads(model_file.read_text(encoding="utf-8-sig"))
    name_map: dict[str, str] = {}
    for entity in data.get("entities", []):
        for attr in entity.get("attrs", []):
            raw = attr.get("name")
            if raw:
                name_map[raw.replace(" ", "_").lower()] = raw
    return name_map


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate old config entries to the current version."""
    if entry.version > CONFIG_ENTRY_VERSION:
        # Downgrade from a future version - can't handle.
        return False

    if entry.version == 1:
        old_devices = entry.data.get("devices", [])

        # v1 entries created by the cloud-based integration hold devices keyed
        # by "did"/"lan_ip"; entries created by early local builds already use
        # "uid"/"ip" and only need the version bump.
        needs_conversion = any("did" in dev for dev in old_devices)

        new_devices = []
        did_to_uid: dict[str, str] = {}
        for dev in old_devices:
            if "did" not in dev:
                new_devices.append(dev)
                continue
            did = dev["did"]
            uid = _did_to_uid(did)
            did_to_uid[did] = uid
            new_devices.append(
                {
                    "ip": dev.get("lan_ip"),
                    "product_key": dev.get("product_key", ""),
                    "uid": uid,
                    "mac": None,
                    "firmware_version": None,
                    "name": dev.get("dev_alias"),
                }
            )

        if needs_conversion:
            # Build per-device attribute name maps so old unique_ids
            # ({did}_{attr_lower}) can be rewritten to the new format
            # ({uid_hex}_{AttrRaw}_{platform}).
            attr_maps: dict[str, dict[str, str]] = {}
            for dev in old_devices:
                if "did" in dev and dev.get("product_key"):
                    attr_maps[dev["did"]] = await hass.async_add_executor_job(
                        _load_attr_name_map, dev["product_key"]
                    )

            @callback
            def _migrate_unique_id(reg_entry: er.RegistryEntry) -> dict | None:
                for did, uid in did_to_uid.items():
                    prefix = f"{did}_"
                    if not reg_entry.unique_id.startswith(prefix):
                        continue
                    suffix = reg_entry.unique_id[len(prefix) :]
                    raw_name = attr_maps.get(did, {}).get(suffix)
                    if raw_name is None:
                        _LOGGER.warning(
                            "Could not map attribute '%s' for entity %s during "
                            "migration; entity will be recreated with a new id",
                            suffix,
                            reg_entry.entity_id,
                        )
                        return None
                    new_unique_id = f"{uid}_{raw_name}_{reg_entry.domain}"
                    _LOGGER.debug(
                        "Migrating unique_id of %s: %s -> %s",
                        reg_entry.entity_id,
                        reg_entry.unique_id,
                        new_unique_id,
                    )
                    return {"new_unique_id": new_unique_id}
                return None

            await er.async_migrate_entries(hass, entry.entry_id, _migrate_unique_id)

            # Re-point device registry entries at the new identifiers so
            # devices (names, areas, automations targeting the device) survive.
            device_registry = dr.async_get(hass)
            for device_entry in dr.async_entries_for_config_entry(
                device_registry, entry.entry_id
            ):
                new_identifiers = {
                    (DOMAIN, did_to_uid.get(ident, ident))
                    for domain, ident in device_entry.identifiers
                    if domain == DOMAIN
                }
                if new_identifiers and new_identifiers != set(
                    device_entry.identifiers
                ):
                    device_registry.async_update_device(
                        device_entry.id, new_identifiers=new_identifiers
                    )

        # Users who never had LAN IPs configured were running cloud-only;
        # keep them on cloud mode so their devices continue to work.
        cloud_only = (
            needs_conversion
            and entry.data.get("token")
            and not any(dev.get("lan_ip") for dev in old_devices if "did" in dev)
        )
        if cloud_only:
            new_data = {
                CONF_MODE: MODE_CLOUD,
                "region": entry.data.get("region", DEFAULT_REGION),
                "email": entry.data.get("email"),
                "token": entry.data.get("token"),
                "devices": new_devices,
            }
        else:
            # Local mode: drop cloud credentials, they are no longer used.
            new_data = {CONF_MODE: MODE_LOCAL, "devices": new_devices}
        hass.config_entries.async_update_entry(
            entry, data=new_data, version=CONFIG_ENTRY_VERSION
        )
        _LOGGER.info(
            "Migrated config entry %s to version %s (%d devices)",
            entry.entry_id,
            CONFIG_ENTRY_VERSION,
            len(new_devices),
        )

    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up a config entry."""
    if entry.data.get(CONF_MODE, MODE_LOCAL) == MODE_CLOUD:
        setup_ok = await _async_setup_cloud(hass, entry)
    else:
        setup_ok = await _async_setup_local(hass, entry)

    if setup_ok:
        _async_register_services(hass)
    return setup_ok


async def _async_setup_cloud(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up all devices in cloud (Gizwits API polling) mode."""
    api = GizwitsCloudApi(
        hass,
        entry.data.get("region", DEFAULT_REGION),
        token=entry.data.get("token"),
        email=entry.data.get("email"),
        password=entry.data.get("password"),
    )

    # Refresh the token when we have credentials; fall back to the stored
    # token otherwise (migrated v1 entries have a token but no password).
    if entry.data.get("password"):
        token, err = await api.async_login()
        if token:
            if token != entry.data.get("token"):
                hass.config_entries.async_update_entry(
                    entry, data={**entry.data, "token": token}
                )
        elif not entry.data.get("token"):
            raise ConfigEntryNotReady(f"Cloud login failed: {err}")
    elif not entry.data.get("token"):
        raise ConfigEntryNotReady("No cloud token or credentials configured")

    # Fetch bindings once for extras only the cloud knows, e.g. the
    # user-assigned doser channel names stored in the binding's remark.
    bindings: dict[str, dict] = {}
    try:
        response = await api.async_get_devices()
        for dev in (response or {}).get("devices", []):
            if dev.get("did"):
                bindings[dev["did"]] = dev
    except Exception as exc:
        _LOGGER.debug("Could not fetch cloud bindings: %s", exc)

    devices: list[JebaoCloudDevice] = []
    for device_data in entry.data.get("devices", []):
        uid = device_data.get("uid")
        if not uid:
            _LOGGER.warning("Skipping device without UID in cloud mode")
            continue
        device = JebaoCloudDevice(
            hass,
            api,
            uid=uid,
            product_key=device_data.get("product_key", ""),
            name=device_data.get("name"),
        )
        binding = bindings.get(device.did)
        if binding:
            device.channel_names = parse_channel_names(binding.get("remark"))
        try:
            await device.async_connect()
        except FileNotFoundError as exc:
            _LOGGER.error(
                "No device definition for product key %s (device %s): %s",
                device_data.get("product_key"),
                uid,
                exc,
            )
            continue
        devices.append(device)

    if not devices:
        raise ConfigEntryNotReady("No Jebao devices could be prepared; will retry")

    entry.runtime_data = devices

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    for device in devices:
        try:
            await device.request_status_update()
        except Exception as exc:
            _LOGGER.error(
                "Failed to get initial cloud status for %s: %s", device.did, exc
            )

    return True


async def _async_setup_local(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up all devices in local (LAN push) mode."""
    await _load_device_configs()

    # Discover devices up front so stale IPs (e.g. after a DHCP lease change
    # while HA was off) are corrected before we try to connect.
    discovered_devices: dict[str, dict] = {}
    try:
        discovered = await async_discover_devices(hass, timeout=10.0)
        for dev in discovered:
            if dev.get("uid"):
                discovered_devices[dev["uid"]] = dev
        _LOGGER.debug("Discovered %d devices during setup", len(discovered_devices))
    except Exception as exc:
        _LOGGER.warning("Failed to perform discovery during setup: %s", exc)

    devices: list[JebaoDevice] = []
    updated_devices: list[dict] = []
    devices_updated = False

    for device_data in entry.data.get("devices", []):
        device_data = dict(device_data)
        device_uid = device_data.get("uid")
        stored_ip = device_data.get("ip")

        # Devices without a stored UID: match by IP against discovery results.
        if not device_uid and stored_ip:
            for dev in discovered_devices.values():
                if dev["ip"] == stored_ip:
                    device_uid = dev["uid"]
                    device_data["uid"] = device_uid
                    devices_updated = True
                    _LOGGER.info(
                        "Found UID %s for device at %s", device_uid, stored_ip
                    )
                    break

        # Prefer the freshly discovered IP over the stored one.
        current_ip = stored_ip
        if device_uid and device_uid in discovered_devices:
            discovered_dev = discovered_devices[device_uid]
            if discovered_dev["ip"] != stored_ip:
                _LOGGER.info(
                    "Device %s IP changed from %s to %s",
                    device_uid,
                    stored_ip,
                    discovered_dev["ip"],
                )
                current_ip = discovered_dev["ip"]
                device_data["ip"] = current_ip
                devices_updated = True
            for key in ("product_key", "mac", "firmware_version"):
                if discovered_dev.get(key) and discovered_dev[key] != device_data.get(
                    key
                ):
                    device_data[key] = discovered_dev[key]
                    devices_updated = True
        elif device_uid:
            _LOGGER.warning(
                "Device %s not found during discovery, will keep trying at %s",
                device_uid,
                stored_ip,
            )

        updated_devices.append(device_data)

        if not current_ip:
            _LOGGER.warning(
                "No known IP for device %s and it did not answer discovery; "
                "it will be retried on next reload",
                device_uid or "unknown",
            )
            continue

        device = JebaoDevice(
            hass=hass,
            ip=current_ip,
            product_key=device_data.get("product_key", ""),
            uid=device_uid,
            mac=device_data.get("mac"),
            firmware_version=device_data.get("firmware_version"),
            name=device_data.get("name"),
        )

        try:
            await device.async_connect()
        except FileNotFoundError as exc:
            # No model definition for this product key - retrying won't help.
            _LOGGER.error(
                "No device definition for product key %s (device %s): %s",
                device_data.get("product_key"),
                device_uid or current_ip,
                exc,
            )
            continue
        except Exception as exc:
            # Keep the device: its connection manager retries in the
            # background and rediscovery will pick up any new IP.
            _LOGGER.warning(
                "Initial connection to Jebao device at %s (UID: %s) failed: %s; "
                "will keep retrying in the background",
                current_ip,
                device_uid or "unknown",
                exc,
            )

        if device.giz_device is not None:
            devices.append(device)

    if devices_updated:
        new_data = dict(entry.data)
        new_data["devices"] = updated_devices
        hass.config_entries.async_update_entry(entry, data=new_data)
        _LOGGER.info("Updated stored device details in configuration")

    if not devices:
        raise ConfigEntryNotReady(
            "No Jebao devices could be prepared; will retry"
        )

    # Persist IP changes found by runtime rediscovery (DHCP lease changes).
    def _persist_ip_change(uid: str, new_ip: str) -> None:
        data = dict(entry.data)
        changed = False
        new_list = []
        for dev in data.get("devices", []):
            if dev.get("uid") == uid and dev.get("ip") != new_ip:
                dev = {**dev, "ip": new_ip}
                changed = True
            new_list.append(dev)
        if changed:
            data["devices"] = new_list
            hass.config_entries.async_update_entry(entry, data=data)

    for device in devices:
        device.set_ip_changed_callback(_persist_ip_change)

    entry.runtime_data = devices

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Request initial status from devices that connected.
    for device in devices:
        if not device.available:
            continue
        try:
            await device.giz_device.request_status_update()
        except Exception as exc:
            _LOGGER.error(
                "Failed to get initial status from device at %s: %s", device.ip, exc
            )

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        devices: list[JebaoDevice | JebaoCloudDevice] = entry.runtime_data
        for device in devices:
            await device.async_disconnect()
        entry.runtime_data = None

        other_loaded = any(
            e.entry_id != entry.entry_id and e.runtime_data
            for e in hass.config_entries.async_entries(DOMAIN)
        )
        if not other_loaded:
            _async_unregister_services(hass)

    return unload_ok


async def async_remove_config_entry_device(
    hass: HomeAssistant, entry: ConfigEntry, device_entry: dr.DeviceEntry
) -> bool:
    """Allow removing a device from the UI.

    Strips the device from the config entry so stale/ghost devices (e.g. a
    pump that was replaced or re-added under a new identity) stop being
    retried forever. The entry is reloaded so the connection is torn down.
    """
    uids = {
        ident for domain, ident in device_entry.identifiers if domain == DOMAIN
    }
    if not uids:
        return False

    remaining = [
        dev
        for dev in entry.data.get("devices", [])
        if dev.get("uid") not in uids
    ]
    if len(remaining) == len(entry.data.get("devices", [])):
        # Not in the config entry (already stale); just let HA remove it.
        return True

    _LOGGER.info("Removed device %s from configuration", ", ".join(uids))
    if not remaining:
        # Last device removed; a reload would just fail ConfigEntryNotReady,
        # so remove the whole entry instead.
        hass.async_create_task(hass.config_entries.async_remove(entry.entry_id))
        return True

    hass.config_entries.async_update_entry(
        entry, data={**entry.data, "devices": remaining}
    )
    hass.async_create_task(hass.config_entries.async_reload(entry.entry_id))
    return True
