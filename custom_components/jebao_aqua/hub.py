"""Hub and helpers for Jebao Aqua integration."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
import json
import logging
from pathlib import Path
from typing import Any

from homeassistant.core import HomeAssistant

from .gizwits_lan import DeviceManager, DeviceStatus, GizwitsError

_LOGGER = logging.getLogger(__name__)

_DEVICE_CONFIGS = None

# We'll keep a single global manager reference to reuse across the integration.
_GLOBAL_MANAGER: DeviceManager | None = None


async def get_manager(hass: HomeAssistant) -> DeviceManager:
    """Return a singleton DeviceManager for the integration, creating it if necessary."""
    global _GLOBAL_MANAGER
    if _GLOBAL_MANAGER is None:
        # For real usage, specify the path to the definitions folder or
        # some mechanism to locate your Jebao product definition JSON(s).
        # If your definitions are shipped inside the integration, you could
        # get a path with hass.config.path("custom_components/jebao_aqua/definitions")
        # or similar. For now, we just pass None to rely on direct device specs if needed.
        definitions_dir = Path(__file__).parent / "models"
        _GLOBAL_MANAGER = DeviceManager(definitions_dir=definitions_dir)
    return _GLOBAL_MANAGER


async def async_discover_devices(
    hass: HomeAssistant, timeout: float = 5.0
) -> list[dict[str, Any]]:
    """Perform a broadcast discovery for Jebao (Gizwits) devices on the network
    using the gizwits_lan library. Returns a list of device info dicts:
    [
      {
        "ip": "192.168.1.123",
        "uid": "some_unique_string",
        "product_key": "...",
      },
      ...
    ]
    """
    manager = await get_manager(hass)
    found = await manager.discover_devices(
        ip="255.255.255.255",
        port=12414,
        timeout=timeout,
        retry_count=10, # These things have naff antennas and are on 2.4GHz...
        retry_delay=0.3,
    )
    return found


async def async_directed_discovery(
    hass: HomeAssistant, ip: str, timeout: float = 5.0
) -> dict[str, Any] | None:
    """Perform a unicast discovery to the specified IP.
    Return the single matching device info dict, or None if not found.
    """
    manager = await get_manager(hass)
    found = await manager.discover_devices(
        ip=ip, port=12414, timeout=timeout, retry_count=3, retry_delay=0.3
    )
    # Filter out to find the device that exactly matches the IP (if any).
    for dev in found:
        if dev["ip"] == ip:
            return dev
    return None


async def _load_device_configs() -> dict:
    """Load device_configs.json from disk (only once)."""
    global _DEVICE_CONFIGS
    if _DEVICE_CONFIGS is not None:
        return _DEVICE_CONFIGS

    config_file = Path(__file__).parent / "models" / "device_configs.json"

    # Use aiofiles for async file operations
    try:
        # Use utf-8-sig to handle files with BOM
        _DEVICE_CONFIGS = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: json.loads(config_file.read_text(encoding="utf-8-sig")).get(
                "device_configs", {}
            ),
        )
        return _DEVICE_CONFIGS
    except Exception as e:
        _LOGGER.error("Failed to load device configs: %s", e)
        return {}


def _merge_config(base_config: dict, child_config: dict) -> dict:
    """Merge 'child_config' with 'base_config', returning a new dict."""
    # This helper stays sync since it's just dict operations
    merged = dict(base_config)
    base_platforms = base_config.get("platforms", {})
    child_platforms = child_config.get("platforms", {})

    merged_platforms = {}
    for platform_name, attrs in base_platforms.items():
        merged_platforms[platform_name] = list(attrs)

    for platform_name, attrs in child_platforms.items():
        if platform_name not in merged_platforms:
            merged_platforms[platform_name] = []
        merged_platforms[platform_name].extend(attrs)

    merged["platforms"] = merged_platforms

    if "device_type" in child_config:
        merged["device_type"] = child_config["device_type"]
    return merged


async def get_device_config_for_product_key(product_key: str) -> dict:
    """Return the merged config from device_configs.json for a given product_key.
    If it references an 'inherits', merge that base config. If none found, return empty.
    """
    device_configs = await _load_device_configs()  # Now awaiting the async call
    if product_key in device_configs:
        cfg = device_configs[product_key]
        inherits_key = cfg.get("inherits")
        if inherits_key and inherits_key in device_configs:
            base_cfg = device_configs[inherits_key]
            return _merge_config(base_cfg, cfg)
        return cfg
    return {}


async def async_load_product_attrs(hass: HomeAssistant, product_key: str) -> list[dict]:
    """Load the full attribute list for a product key from its model JSON.

    Raises FileNotFoundError if no definition exists for the product key.
    """
    manager = await get_manager(hass)
    return await manager._load_device_definition(product_key)


class JebaoDevice:
    """Wraps a single Gizwits Device."""

    REDISCOVERY_INTERVAL = 60.0

    def __init__(
        self,
        hass: HomeAssistant,
        ip: str,
        product_key: str,
        uid: str | None = None,
        mac: str | None = None,
        firmware_version: str | None = None,
        name: str | None = None,
    ) -> None:
        """Initialize the JebaoDevice wrapper."""
        self.hass = hass
        self.ip = ip
        self.product_key = product_key
        self.uid = uid
        self.mac = mac
        self.firmware_version = firmware_version
        self.name = name
        # Channel number -> user-assigned name (only known via the cloud;
        # populated in cloud mode, empty for LAN-only setups).
        self.channel_names: dict[int, str] = {}
        self.device_config: dict = {}
        self.giz_device = None
        self._status_callbacks: set[Callable[[DeviceStatus], None]] = set()
        self._connection_callbacks: set[Callable[[bool], None]] = set()
        self._ip_changed_callback: Callable[[str, str], None] | None = None
        self._rediscovery_task: asyncio.Task | None = None

    def set_ip_changed_callback(self, callback: Callable[[str, str], None]) -> None:
        """Register a callback(uid, new_ip) invoked when rediscovery finds a new IP."""
        self._ip_changed_callback = callback

    async def async_connect(self) -> None:
        """Connect to the device via gizwits_lan, subscribe to updates.

        A failed initial connection is not fatal: the underlying connection
        manager keeps retrying in the background and a rediscovery loop is
        started to find the device again if its IP changed (e.g. new DHCP
        lease). Raises FileNotFoundError if there is no model definition for
        this product key - that cannot be fixed by retrying.
        """
        manager = await get_manager(self.hass)
        self.device_config = await get_device_config_for_product_key(self.product_key)

        # May raise FileNotFoundError when no definition exists - let that
        # propagate, the caller has to skip this device.
        self.giz_device = await manager.create_device(
            ip=self.ip, product_key=self.product_key, port=12416
        )
        self.giz_device.add_connection_callback(self._handle_connection_state)
        self.giz_device.add_status_callback(self._handle_status_update)

        try:
            await self.giz_device.connect()
        except (GizwitsError, TimeoutError, OSError) as err:
            # The connection manager was already started by connect() and
            # retries with backoff; the retries only target the stored IP, so
            # also start rediscovery in case the device moved.
            _LOGGER.warning(
                "Initial connection to device at %s failed (%s); retrying in "
                "the background",
                self.ip,
                err,
            )
            self._start_rediscovery()
            return

        _LOGGER.info("Jebao device connected: %s", self)

    async def async_disconnect(self) -> None:
        """Disconnect from device."""
        if self.giz_device:
            # Remove our callbacks first so the disconnect notification does
            # not restart the rediscovery loop.
            self.giz_device.remove_connection_callback(self._handle_connection_state)
            self.giz_device.remove_status_callback(self._handle_status_update)
            await self.giz_device.disconnect()
            self.giz_device = None
            _LOGGER.info("Disconnected from Jebao device at %s", self.ip)
        self._stop_rediscovery()

    def _start_rediscovery(self) -> None:
        """Start the background rediscovery loop if it isn't running."""
        if not self.uid:
            _LOGGER.debug(
                "Cannot rediscover device at %s without a UID", self.ip
            )
            return
        if self._rediscovery_task is None or self._rediscovery_task.done():
            self._rediscovery_task = self.hass.async_create_background_task(
                self._async_rediscovery_loop(),
                name=f"jebao_aqua_rediscovery_{self.uid}",
            )

    def _stop_rediscovery(self) -> None:
        """Cancel the rediscovery loop if it is running."""
        if self._rediscovery_task is not None and not self._rediscovery_task.done():
            self._rediscovery_task.cancel()
        self._rediscovery_task = None

    async def _async_rediscovery_loop(self) -> None:
        """While disconnected, periodically look for the device on the network.

        Handles the device's IP changing (DHCP lease renewal on the router):
        broadcast discovery is matched on the device UID and, if the IP moved,
        the connection manager is pointed at the new address.
        """
        try:
            while True:
                await asyncio.sleep(self.REDISCOVERY_INTERVAL)
                if self.available:
                    return
                try:
                    found = await async_discover_devices(self.hass, timeout=5.0)
                except Exception as exc:
                    _LOGGER.debug("Rediscovery attempt failed: %s", exc)
                    continue
                for dev in found:
                    if dev.get("uid") != self.uid:
                        continue
                    if dev["ip"] != self.ip:
                        _LOGGER.info(
                            "Device %s found at new IP %s (was %s); reconnecting",
                            self.uid,
                            dev["ip"],
                            self.ip,
                        )
                        self.ip = dev["ip"]
                        if self.giz_device:
                            self.giz_device.ip = dev["ip"]
                        if self._ip_changed_callback:
                            self._ip_changed_callback(self.uid, dev["ip"])
                    else:
                        _LOGGER.debug(
                            "Device %s still at %s; waiting for reconnect",
                            self.uid,
                            self.ip,
                        )
                    break
        except asyncio.CancelledError:
            raise

    def _handle_status_update(self, status: DeviceStatus) -> None:
        """Internal callback from giz_device when status changes. Notify all entity listeners."""
        _LOGGER.debug("Device status update from %s => %s", self.ip, status.data)
        for cb in self._status_callbacks:
            try:
                cb(status)
            except Exception as exc:
                _LOGGER.exception("Error in status callback: %s", exc)

    def _handle_connection_state(self, connected: bool) -> None:
        """Handle connection state changes from gizwits device."""
        if connected:
            self._stop_rediscovery()
        else:
            # Lost connection: the connection manager retries the current IP;
            # rediscovery handles the case where the IP itself changed.
            self._start_rediscovery()
        for callback in self._connection_callbacks:
            try:
                callback(connected)
            except Exception as exc:
                _LOGGER.exception("Error in connection callback: %s", exc)

    def register_status_callback(
        self, callback: Callable[[DeviceStatus], None]
    ) -> None:
        """Entity can register to be notified when device status changes."""
        self._status_callbacks.add(callback)

    def remove_status_callback(self, callback: Callable[[DeviceStatus], None]) -> None:
        """Entity unsubscribes from updates."""
        self._status_callbacks.discard(callback)

    def register_connection_callback(self, callback: Callable[[bool], None]) -> None:
        """Register a callback for connection state changes."""
        self._connection_callbacks.add(callback)
        # Immediately notify of current state
        if self.giz_device:
            callback(self.giz_device.available)

    def remove_connection_callback(self, callback: Callable[[bool], None]) -> None:
        """Remove a connection state callback."""
        self._connection_callbacks.discard(callback)

    @property
    def available(self) -> bool:
        """Return True if device is currently connected and responsive."""
        if not self.giz_device:
            return False
        return self.giz_device.available

    def get_attribute(self, attr_name: str) -> Any:
        """Retrieve current attribute value from the device's status dict."""
        if not self.giz_device:
            return None
        return self.giz_device.get_attribute(attr_name)

    async def async_set_attribute(self, attr_name: str, value: Any) -> None:
        """Set a single attribute on the device."""
        if not self.giz_device:
            _LOGGER.warning(
                "Cannot set attribute %s; device is not connected", attr_name
            )
            return
        await self.giz_device.set_device_attribute(attr_name, value)

    def __repr__(self) -> str:
        return f"<JebaoDevice ip={self.ip}, connected={bool(self.giz_device)}, product_key={self.product_key}>"
