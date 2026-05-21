import aiohttp
import asyncio
import json
import logging
from typing import Tuple

from .const import (
    GIZWITS_APP_ID,
    TIMEOUT,
    LOGGER,
    LAN_PORT,
    GIZWITS_API_URLS,
    DEFAULT_REGION,
)

GIZWITS_ERROR_CODES = {
    "1000000": "user_not_exist",
    "1000033": "invalid_password",
}

class GizwitsApi:
    """Class to handle communication with the Gizwits API."""

    def __init__(
        self,
        login_url,
        devices_url,
        device_data_url,
        control_url,
        token: str = None,
    ):
        self._token = token
        self._attribute_models = None
        self.login_url = login_url
        self.devices_url = devices_url
        self.device_data_url = device_data_url
        self.control_url = control_url

    async def __aenter__(self):
        self._session = await aiohttp.ClientSession().__aenter__()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self._session.__aexit__(exc_type, exc_val, exc_tb)

    async def get_session(self):
        return aiohttp.ClientSession()

    async def async_login(self, email: str, password: str) -> Tuple[str, str]:
        data = {
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
                self.login_url, json=data, headers=headers, timeout=TIMEOUT
            ) as response:
                response_text = await response.text()
                try:
                    json_response = json.loads(response_text)
                    if json_response.get("error", False):
                        error_code = json_response.get("code")
                        if error_code in GIZWITS_ERROR_CODES:
                            return None, GIZWITS_ERROR_CODES[error_code]
                        return None, "unknown_error"

                    if json_response and isinstance(json_response, dict):
                        data = json_response.get("data", {})
                        if isinstance(data, dict):
                            token = data.get("userToken")
                            if token:
                                return token, None
                    return None, "invalid_response"
                except json.JSONDecodeError:
                    return None, "invalid_json"
        except Exception:
            return None, "connection_error"

    def set_token(self, token: str):
        self._token = token

    def add_attribute_models(self, attribute_models):
        self._attribute_models = attribute_models

    async def get_devices(self):
        headers = {
            "X-Gizwits-User-token": self._token,
            "X-Gizwits-Application-Id": GIZWITS_APP_ID,
            "Accept": "application/json",
        }
        try:
            async with self._session.get(
                self.devices_url, headers=headers, timeout=TIMEOUT
            ) as response:
                result = await response.text()
                if response.status == 200:
                    return json.loads(result)
                return None
        except Exception:
            return None

    async def get_device_data(self, device_id: str):
        url = self.device_data_url.format(device_id=device_id)
        headers = {
            "X-Gizwits-User-token": self._token,
            "X-Gizwits-Application-Id": GIZWITS_APP_ID,
            "Accept": "application/json",
        }
        try:
            async with self._session.get(
                url, headers=headers, timeout=TIMEOUT
            ) as response:
                result = await response.text()
                if response.status == 200:
                    return json.loads(result)
                return None
        except Exception:
            return None

    async def control_device(self, device_id: str, attributes: dict):
        url = self.control_url.format(device_id=device_id)
        headers = {
            "X-Gizwits-User-token": self._token,
            "X-Gizwits-Application-Id": GIZWITS_APP_ID,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        data = {"attrs": attributes}
        async with aiohttp.ClientSession() as session:
            try:
                async with session.post(
                    url, json=data, headers=headers, timeout=TIMEOUT
                ) as response:
                    result = await response.text()
                    if response.status == 200:
                        return json.loads(result)
                    return None
            except Exception:
                return None

    async def get_local_device_data(self, device_ip, product_key, device_id):
        attribute_model = self._attribute_models.get(product_key)
        if not attribute_model:
            return None

        try:
            reader, writer = await asyncio.open_connection(device_ip, LAN_PORT)
            try:
                await self._send_local_command(writer, b"\x00\x06")
                response = await reader.read(1024)
                binding_key = response[-12:]
                await self._send_local_command(writer, b"\x00\x08", binding_key)
                await reader.read(1024)
                await self._send_local_command(
                    writer, b"\x00\x93", b"\x00\x00\x00\x02\x02"
                )
                response = await reader.read(1024)

                # 🔧 修復長度 -4 問題：如果抓到的只有 ACK (長度太短)，再讀取一次真實的長封包
                if len(response) < 20:
                    try:
                        extra_data = await asyncio.wait_for(reader.read(1024), timeout=1.5)
                        response += extra_data
                    except Exception:
                        pass

                device_status_payload = self._extract_device_status_payload(response)
                if device_status_payload:
                    parsed_data = self._parse_device_status(
                        device_status_payload, attribute_model
                    )
                    return {"did": device_id, "attr": parsed_data}
                return None
            finally:
                writer.close()
                await writer.wait_closed()
        except Exception:
            return None

    async def _send_local_command(self, writer, command, payload=b""):
        try:
            header = b"\x00\x00\x00\x03"
            flag = b"\x00"
            length = len(flag + command + payload).to_bytes(1, byteorder="big")
            packet = header + length + flag + command + payload
            writer.write(packet)
            await writer.drain()
        except Exception as e:
            raise

    def _extract_device_status_payload(self, response):
        try:
            pattern = b"\x00\x00\x00\x03"
            # 🔧 修復：使用 rfind 從封包尾端尋找，避開開頭的 ACK 封包干擾
            start_index = response.rfind(pattern)
            if start_index == -1:
                return None

            leb128_bytes = response[start_index + len(pattern) :]
            length, leb128_length = self._decode_leb128(leb128_bytes)
            if length is None:
                return None

            N = length - 8
            if N > 0 and N <= len(response):
                device_status_payload = response[-N:]
                return device_status_payload
            else:
                LOGGER.error("Invalid device status payload length: %s", N)
                return None
        except Exception:
            return None

    def _decode_leb128(self, data):
        result = 0
        shift = 0
        for i, byte in enumerate(data):
            result |= (byte & 0x7F) << shift
            if (byte & 0x80) == 0:
                return result, i + 1
            shift += 7
        return None, 0

    def _swap_endian(self, hex_str):
        if len(hex_str) >= 4:
            swapped = hex_str[2:4] + hex_str[0:2] + hex_str[4:]
            return swapped
        return hex_str

    def _parse_device_status(self, payload, attribute_model):
        status_data = {}
        try:
            if isinstance(payload, bytes):
                payload = payload.hex()

            swap_needed = any(
                attr["position"]["byte_offset"] == 0
                and (attr["position"]["bit_offset"] + attr["position"]["len"] > 8)
                for attr in attribute_model["attrs"]
            )

            if swap_needed:
                payload = self._swap_endian(payload)

            payload_bytes = bytes.fromhex(payload)

            for attr in attribute_model["attrs"]:
                byte_offset = attr["position"]["byte_offset"]
                bit_offset = attr["position"]["bit_offset"]
                length = attr["position"]["len"]
                data_type = attr.get("data_type", "unknown")

                if data_type == "bool":
                    value = bool(self._extract_bits(payload_bytes[byte_offset], bit_offset, length))
                elif data_type == "enum":
                    enum_values = attr.get("enum", [])
                    enum_index = self._extract_bits(payload_bytes[byte_offset], bit_offset, length)
                    value = enum_values[enum_index] if enum_index < len(enum_values) else None
                elif data_type == "uint8":
                    value = payload_bytes[byte_offset]
                elif data_type == "binary":
                    value = payload_bytes[byte_offset : byte_offset + length].hex()

                status_data[attr["name"]] = value
        except Exception:
            pass

        return status_data

    def _extract_bits(self, byte_val, bit_offset, length):
        mask = (1 << length) - 1
        return (byte_val >> bit_offset) & mask

    async def close(self):
        if self._session:
            await self._session.close()
