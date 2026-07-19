"""Cloud (Gizwits API) polling and control support for Jebao Aqua.

This is the "fully cloud" connection mode: device state is polled from the
Gizwits cloud and commands are sent through it, for installs where LAN access
to the pumps is not possible. Based on the original cloud implementation with
the fixes from PR #62 (no shared closed session, 30s poll interval).
"""

from __future__ import annotations

import asyncio
import binascii
import json
import logging
import time
from collections.abc import Callable
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    CLOUD_TIMEOUT,
    CLOUD_UPDATE_INTERVAL,
    GIZWITS_API_URLS,
    GIZWITS_APP_ID,
)
from .gizwits_lan.device_status import DeviceStatus
from .hub import async_load_product_attrs, get_device_config_for_product_key

_LOGGER = logging.getLogger(__name__)

GIZWITS_ERROR_CODES = {
    "1000000": "user_not_exist",
    "1000033": "invalid_password",
}

# How long to wait before re-trying a login after a failed poll.
REAUTH_COOLDOWN = 300.0
# Consecutive failed polls before entities are marked unavailable.
MAX_FAILED_POLLS = 2
# Delay between sending a control command and the confirmation poll.
CONTROL_CONFIRM_DELAY = 2.0


def uid_to_did(uid: str) -> str:
    """Convert the stored hex uid back to the Gizwits cloud device id."""
    return binascii.unhexlify(uid).decode("ascii")


def parse_channel_names(remark: str | None) -> dict[int, str]:
    """Parse user-assigned doser channel names from a binding's remark field.

    The Jebao app stores them as JSON, e.g.
    {"names": {"CHANNEL_1": "Ca", "CHANNEL_2": "KH"}}. (From PR #49.)
    """
    if not remark:
        return {}
    try:
        names = json.loads(remark).get("names", {})
        return {
            int(key.split("_")[1]): value
            for key, value in names.items()
            if key.startswith("CHANNEL_")
        }
    except (json.JSONDecodeError, ValueError, KeyError, AttributeError, IndexError):
        return {}


def did_to_uid(did: str) -> str:
    """Convert a Gizwits cloud device id to the stored hex uid."""
    return did.encode("ascii", "ignore").hex()


class GizwitsCloudApi:
    """Minimal Gizwits cloud API client (login, bindings, poll, control).

    Uses Home Assistant's shared aiohttp session, which is never closed for
    the lifetime of HA - this fixes the "Session is closed" failures the old
    implementation worked around by creating a session per request.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        region: str,
        token: str | None = None,
        email: str | None = None,
        password: str | None = None,
    ) -> None:
        """Initialize the API client for a region."""
        self._session = async_get_clientsession(hass)
        self._urls = GIZWITS_API_URLS[region]
        self._token = token
        self._email = email
        self._password = password
        self._last_reauth = 0.0

    @property
    def token(self) -> str | None:
        """Return the current user token."""
        return self._token

    def set_token(self, token: str) -> None:
        """Set the user token for subsequent requests."""
        self._token = token

    def _auth_headers(self) -> dict[str, str]:
        return {
            "X-Gizwits-User-token": self._token or "",
            "X-Gizwits-Application-Id": GIZWITS_APP_ID,
            "Accept": "application/json",
        }

    async def async_login(
        self, email: str | None = None, password: str | None = None
    ) -> tuple[str | None, str | None]:
        """Login and return (token, error_code); error_code is None on success."""
        email = email or self._email
        password = password or self._password
        if not email or not password:
            return None, "auth"
        payload = {
            "appKey": GIZWITS_APP_ID,
            "data": {
                "account": email,
                "password": password,
                "lang": "en",
                "refreshToken": True,
            },
            "version": "1.0",
        }
        headers = {
            "X-Gizwits-Application-Id": GIZWITS_APP_ID,
            "Content-Type": "application/json",
        }
        try:
            async with self._session.post(
                self._urls["LOGIN_URL"],
                json=payload,
                headers=headers,
                timeout=CLOUD_TIMEOUT,
            ) as response:
                body = await response.text()
        except Exception as exc:
            _LOGGER.error("Error logging in to Gizwits API: %s", exc)
            return None, "connection_error"

        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            _LOGGER.error("Non-JSON login response from Gizwits API: %s", body[:200])
            return None, "invalid_json"

        if data.get("error"):
            code = str(data.get("code"))
            return None, GIZWITS_ERROR_CODES.get(code, "unknown_error")

        token = data.get("data", {}).get("userToken") if isinstance(
            data.get("data"), dict
        ) else None
        if not token:
            _LOGGER.error("No userToken in Gizwits login response: %s", body[:200])
            return None, "invalid_response"

        self._token = token
        return token, None

    async def async_maybe_reauth(self) -> bool:
        """Attempt a cooldown-limited re-login with stored credentials."""
        if not self._email or not self._password:
            return False
        now = time.monotonic()
        if now - self._last_reauth < REAUTH_COOLDOWN:
            return False
        self._last_reauth = now
        token, err = await self.async_login()
        if token:
            _LOGGER.info("Refreshed Gizwits cloud token")
            return True
        _LOGGER.warning("Gizwits cloud re-login failed: %s", err)
        return False

    async def _get_json(self, url: str) -> dict | None:
        try:
            async with self._session.get(
                url, headers=self._auth_headers(), timeout=CLOUD_TIMEOUT
            ) as response:
                body = await response.text()
                if response.status != 200:
                    _LOGGER.debug(
                        "Gizwits API GET %s failed: %s %s",
                        url,
                        response.status,
                        body[:200],
                    )
                    return None
                return json.loads(body)
        except Exception as exc:
            _LOGGER.debug("Gizwits API GET %s error: %s", url, exc)
            return None

    async def async_get_devices(self) -> dict | None:
        """Return the account's device bindings."""
        return await self._get_json(self._urls["DEVICES_URL"])

    async def async_get_device_data(self, did: str) -> dict | None:
        """Return the latest attribute values for a device."""
        return await self._get_json(
            self._urls["DEVICE_DATA_URL"].format(device_id=did)
        )

    async def async_control_device(self, did: str, attributes: dict) -> bool:
        """Send a control command to a device; return True on success."""
        url = self._urls["CONTROL_URL"].format(device_id=did)
        headers = self._auth_headers() | {"Content-Type": "application/json"}
        try:
            async with self._session.post(
                url,
                json={"attrs": attributes},
                headers=headers,
                timeout=CLOUD_TIMEOUT,
            ) as response:
                body = await response.text()
                if response.status != 200:
                    _LOGGER.error(
                        "Gizwits control command for %s failed: %s %s",
                        did,
                        response.status,
                        body[:200],
                    )
                    return False
                return True
        except Exception as exc:
            _LOGGER.error("Error sending Gizwits control command for %s: %s", did, exc)
            return False


class JebaoCloudDevice:
    """Cloud-polled device with the same interface as JebaoDevice.

    Entities and platforms are agnostic of the connection mode: this class
    mirrors JebaoDevice's surface (uid/mac/product_key/name, giz_device,
    get_attribute, async_set_attribute, status/connection callbacks).
    """

    def __init__(
        self,
        hass: HomeAssistant,
        api: GizwitsCloudApi,
        uid: str,
        product_key: str,
        name: str | None = None,
    ) -> None:
        """Initialize the cloud device wrapper."""
        self.hass = hass
        self.api = api
        self.uid = uid
        self.did = uid_to_did(uid)
        self.product_key = product_key
        self.name = name
        self.ip: str | None = None
        self.mac: str | None = None
        self.firmware_version: str | None = None
        self.device_config: dict = {}
        self.all_attrs: list[dict] = []
        self.channel_names: dict[int, str] = {}
        self._data: dict[str, Any] = {}
        self._available = False
        self._failed_polls = 0
        self._poll_task: asyncio.Task | None = None
        self._status_callbacks: set[Callable[[DeviceStatus], None]] = set()
        self._connection_callbacks: set[Callable[[bool], None]] = set()

    @property
    def giz_device(self) -> JebaoCloudDevice:
        """Platforms enumerate device.giz_device.all_attrs; serve them here."""
        return self

    @property
    def available(self) -> bool:
        """Return True if the last cloud polls succeeded."""
        return self._available

    async def async_connect(self) -> None:
        """Load definitions and start the polling loop.

        Raises FileNotFoundError if there is no model definition for this
        product key.
        """
        self.device_config = await get_device_config_for_product_key(self.product_key)
        self.all_attrs = await async_load_product_attrs(self.hass, self.product_key)
        self._poll_task = self.hass.async_create_background_task(
            self._async_poll_loop(),
            name=f"jebao_aqua_cloud_poll_{self.uid}",
        )

    async def async_disconnect(self) -> None:
        """Stop polling."""
        if self._poll_task is not None and not self._poll_task.done():
            self._poll_task.cancel()
        self._poll_task = None

    async def request_status_update(self) -> None:
        """Poll the cloud for fresh data now."""
        await self._async_poll_once()

    def get_attribute(self, attr_name: str) -> Any:
        """Return the last polled value for an attribute."""
        return self._data.get(attr_name)

    async def async_set_attribute(self, attr_name: str, value: Any) -> None:
        """Set an attribute via the cloud, optimistically update, then confirm."""
        if not await self.api.async_control_device(self.did, {attr_name: value}):
            return
        # Optimistic update so the UI doesn't wait up to a full poll interval.
        self._data[attr_name] = value
        self._notify_status()

        async def _confirm() -> None:
            await asyncio.sleep(CONTROL_CONFIRM_DELAY)
            await self._async_poll_once()

        self.hass.async_create_background_task(
            _confirm(), name=f"jebao_aqua_cloud_confirm_{self.uid}"
        )

    def register_status_callback(
        self, callback: Callable[[DeviceStatus], None]
    ) -> None:
        """Entity subscribes to status updates; replay the last known state.

        Entities may register after the initial poll completed (entity
        addition is scheduled as a task), so without a replay they would
        show no state until the next poll interval.
        """
        self._status_callbacks.add(callback)
        if self._data:
            try:
                callback(DeviceStatus(data=dict(self._data)))
            except Exception:
                _LOGGER.exception("Error replaying status to new callback")

    def remove_status_callback(self, callback: Callable[[DeviceStatus], None]) -> None:
        """Entity unsubscribes from status updates."""
        self._status_callbacks.discard(callback)

    def register_connection_callback(self, callback: Callable[[bool], None]) -> None:
        """Register a callback for availability changes; notify current state."""
        self._connection_callbacks.add(callback)
        callback(self._available)

    def remove_connection_callback(self, callback: Callable[[bool], None]) -> None:
        """Remove an availability callback."""
        self._connection_callbacks.discard(callback)

    def _set_available(self, available: bool) -> None:
        if available == self._available:
            return
        self._available = available
        for callback in self._connection_callbacks:
            try:
                callback(available)
            except Exception:
                _LOGGER.exception("Error in connection callback")

    def _notify_status(self) -> None:
        status = DeviceStatus(data=dict(self._data))
        for callback in self._status_callbacks:
            try:
                callback(status)
            except Exception:
                _LOGGER.exception("Error in status callback")

    async def _async_poll_once(self) -> None:
        """Poll the cloud once and update state/availability."""
        result = await self.api.async_get_device_data(self.did)
        attrs = result.get("attr") if isinstance(result, dict) else None
        if isinstance(attrs, dict) and attrs:
            self._failed_polls = 0
            self._data = attrs
            self._set_available(True)
            self._notify_status()
            return

        self._failed_polls += 1
        _LOGGER.debug(
            "Cloud poll failed for %s (%d consecutive)", self.did, self._failed_polls
        )
        if self._failed_polls >= MAX_FAILED_POLLS:
            self._set_available(False)
            # The token may have expired; try to refresh it (cooldown-limited).
            await self.api.async_maybe_reauth()

    async def _async_poll_loop(self) -> None:
        """Poll on a fixed interval until cancelled."""
        while True:
            try:
                await self._async_poll_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                _LOGGER.exception("Unexpected error polling %s", self.did)
            await asyncio.sleep(CLOUD_UPDATE_INTERVAL)

    def __repr__(self) -> str:
        return (
            f"<JebaoCloudDevice did={self.did}, available={self._available}, "
            f"product_key={self.product_key}>"
        )
