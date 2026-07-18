"""The Jebao Aqua integration."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryNotReady
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
        return await _async_setup_cloud(hass, entry)
    return await _async_setup_local(hass, entry)


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

    return unload_ok
