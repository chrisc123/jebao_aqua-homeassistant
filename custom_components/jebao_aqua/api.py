import aiohttp
import asyncio
import json
from .const import (
    GIZWITS_LOGIN_URL,
    GIZWITS_DEVICES_URL,
    GIZWITS_DEVICE_DATA_URL,
    GIZWITS_CONTROL_URL,
    GIZWITS_APP_ID,
    TIMEOUT,
    LOGGER,
    LAN_PORT
)

class GizwitsApi:
    """Class to handle communication with the Gizwits API."""

    def __init__(self, token: str = None):
        self._token = token
        self._attribute_models = None
        # Create a persistent session upon instantiation.
        self._session = aiohttp.ClientSession()
        LOGGER.debug("Created new HTTP session for GizwitsApi.")

    async def async_login(self, email: str, password: str) -> str:
        """Login to Gizwits and return the token."""
        data = {
            "appKey": GIZWITS_APP_ID,
            "data": {
                "account": email,
                "password": password,
                "lang": "en",
                "refreshToken": True
            },
            "version": "1.0"
        }
        headers = {
            "X-Gizwits-Application-Id": GIZWITS_APP_ID,
            "Content-Type": "application/json"
        }
        LOGGER.debug("Logging in with payload: %s", data)
        try:
            async with self._session.post(GIZWITS_LOGIN_URL, json=data, headers=headers, timeout=TIMEOUT) as response:
                text = await response.text()
                LOGGER.debug("Login response: %s", text)
                if response.status == 200:
                    json_response = await response.json()
                    token = json_response.get("data", {}).get("userToken")
                    LOGGER.debug("Received token: %s", token)
                    return token
                else:
                    LOGGER.error("Failed to login to Gizwits API, status: %s, response: %s", response.status, text)
                    return None
        except Exception as e:
            LOGGER.error("Exception during login to Gizwits API: %s", e)
            return None

    def set_token(self, token: str):
        """Set the user token for the API."""
        self._token = token

    def add_attribute_models(self, attribute_models):
        """Add attribute models to the API instance."""
        self._attribute_models = attribute_models

    async def get_devices(self):
        """Get a list of bound devices."""
        headers = {
            "X-Gizwits-User-token": self._token,
            "X-Gizwits-Application-Id": GIZWITS_APP_ID,
            "Accept": "application/json"
        }
        LOGGER.debug("Attempting to get devices with headers: %s", headers)
        try:
            async with self._session.get(GIZWITS_DEVICES_URL, headers=headers, timeout=TIMEOUT) as response:
                result = await response.text()
                LOGGER.debug("Get devices response (status %s): %s", response.status, result)
                if response.status == 200:
                    return json.loads(result)
                else:
                    LOGGER.error("Failed to fetch devices from Gizwits API, status: %s", response.status)
                    return None
        except Exception as e:
            LOGGER.error("Exception while fetching devices from Gizwits API: %s", e)
            return None

    async def get_device_data(self, device_id: str):
        """Get the latest attribute status values from a device."""
        url = GIZWITS_DEVICE_DATA_URL.format(device_id=device_id)
        LOGGER.debug("Attempting to get device data from URL: %s", url)
        headers = {
            "X-Gizwits-User-token": self._token,
            "X-Gizwits-Application-Id": GIZWITS_APP_ID,
            "Accept": "application/json"
        }
        try:
            async with self._session.get(url, headers=headers, timeout=TIMEOUT) as response:
                result = await response.text()
                LOGGER.debug("Get device data response (status %s): %s", response.status, result)
                if response.status == 200:
                    return json.loads(result)
                else:
                    LOGGER.error("Failed to fetch device data from Gizwits API, status: %s", response.status)
                    return None
        except Exception as e:
            LOGGER.error("Exception while fetching device data from Gizwits API: %s", e)
            return None

    async def control_device(self, device_id: str, attributes: dict):
        """Send a command to change an attribute value on a device."""
        url = GIZWITS_CONTROL_URL.format(device_id=device_id)
        headers = {
            "X-Gizwits-User-token": self._token,
            "X-Gizwits-Application-Id": GIZWITS_APP_ID,
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
        data = {"attrs": attributes}
        LOGGER.debug("Sending control command to %s with payload: %s", url, data)
        try:
            async with self._session.post(url, json=data, headers=headers, timeout=TIMEOUT) as response:
                result = await response.text()
                LOGGER.debug("Control device response (status %s): %s", response.status, result)
                if response.status == 200:
                    return json.loads(result)
                else:
                    LOGGER.error("Failed to send control command (status %s)", response.status)
                    return None
        except Exception as e:
            LOGGER.error("Exception while sending control command: %s", e)
            return None

    async def get_local_device_data(self, device_ip, product_key, device_id):
        """Poll the local device for its status."""
        attribute_model = self._attribute_models.get(product_key)
        if not attribute_model:
            LOGGER.error("Invalid product key or missing attribute model: %s", product_key)
            return None
        LOGGER.debug("Attempting to poll local device at IP %s for device %s", device_ip, device_id)
        try:
            reader, writer = await asyncio.open_connection(device_ip, LAN_PORT)
            try:
                await self._send_local_command(writer, b'\x00\x06')
                response = await reader.read(1024)
                binding_key = response[-12:]
                await self._send_local_command(writer, b'\x00\x08', binding_key)
                _ = await reader.read(1024)
                await self._send_local_command(writer, b'\x00\x93', b'\x00\x00\x00\x02\x02')
                response = await reader.read(1024)
                LOGGER.debug("Local device response after 0x93 command: %s", response.hex())
                device_status_payload = self._extract_device_status_payload(response)
                if device_status_payload:
                    parsed_data = self._parse_device_status(device_status_payload, attribute_model)
                    LOGGER.debug("Parsed local device data: %s", parsed_data)
                    return {'did': device_id, 'attr': parsed_data}
                else:
                    LOGGER.error("Failed to extract or parse local device status for %s", device_id)
                    return None
            finally:
                writer.close()
                await writer.wait_closed()
        except asyncio.TimeoutError:
            LOGGER.error("Timeout while connecting to local device at %s", device_ip)
            return None
        except ConnectionError as e:
            LOGGER.error("Connection error with local device at %s: %s", device_ip, e)
            return None
        except Exception as e:
            LOGGER.error("Unexpected error while connecting to local device at %s: %s", device_ip, e)
            return None

    async def _send_local_command(self, writer, command, payload=b''):
        """Send a command to the local device."""
        try:
            header = b'\x00\x00\x00\x03'
            flag = b'\x00'
            length = len(flag + command + payload).to_bytes(1, byteorder='big')
            packet = header + length + flag + command + payload
            LOGGER.debug("Sending local command with packet: %s", packet.hex())
            writer.write(packet)
            await writer.drain()
            LOGGER.debug("Local command sent successfully.")
        except Exception as e:
            LOGGER.error("Error sending local command: %s", e)
            raise

    def _extract_device_status_payload(self, response):
        """Extract the device status payload from the response."""
        try:
            pattern = b'\x00\x00\x00\x03'
            start_index = response.find(pattern)
            if start_index == -1:
                LOGGER.error("Pattern not found in device response: %s", response.hex())
                return None
            leb128_bytes = response[start_index + len(pattern):]
            length, leb128_length = self._decode_leb128(leb128_bytes)
            if length is None:
                LOGGER.error("Failed to decode LEB128 from response: %s", response.hex())
                return None
            N = length - 8
            if N > 0 and N <= len(response):
                payload = response[-N:]
                LOGGER.debug("Extracted device status payload: %s", payload.hex())
                return payload
            else:
                LOGGER.error("Invalid device status payload length: %s", N)
                return None
        except Exception as e:
            LOGGER.error("Error extracting device status payload: %s", e)
            return None

    def _decode_leb128(self, data):
        """Decode LEB128 encoded data."""
        result = 0
        shift = 0
        for i, byte in enumerate(data):
            result |= ((byte & 0x7F) << shift)
            if (byte & 0x80) == 0:
                return result, i + 1
            shift += 7
        return None, 0

    def _swap_endian(self, hex_str):
        """Swap the endianness of the hex string (first two bytes)."""
        if len(hex_str) >= 4:
            swapped = hex_str[2:4] + hex_str[0:2] + hex_str[4:]
            LOGGER.debug("Swapped endian: %s", swapped)
            return swapped
        return hex_str

    def _parse_device_status(self, payload, attribute_model):
        """Parse the device status payload using the attribute model."""
        status_data = {}
        try:
            if isinstance(payload, bytes):
                payload = payload.hex()
            swap_needed = any(
                attr['position']['byte_offset'] == 0 and (attr['position']['bit_offset'] + attr['position']['len'] > 8)
                for attr in attribute_model['attrs']
            )
            if swap_needed:
                payload = self._swap_endian(payload)
            payload_bytes = bytes.fromhex(payload)
            for attr in attribute_model['attrs']:
                byte_offset = attr['position']['byte_offset']
                bit_offset = attr['position']['bit_offset']
                length = attr['position']['len']
                data_type = attr.get('data_type', 'unknown')
                if data_type == 'bool':
                    value = bool(self._extract_bits(payload_bytes[byte_offset], bit_offset, length))
                elif data_type == 'enum':
                    enum_values = attr.get('enum', [])
                    enum_index = self._extract_bits(payload_bytes[byte_offset], bit_offset, length)
                    value = enum_values[enum_index] if enum_index < len(enum_values) else None
                elif data_type == 'uint8':
                    value = payload_bytes[byte_offset]
                elif data_type == 'binary':
                    value = payload_bytes[byte_offset:byte_offset + length].hex()
                status_data[attr['name']] = value
            LOGGER.debug("Final parsed status data: %s", status_data)
        except Exception as e:
            LOGGER.error("Error parsing device status payload: %s", e)
        return status_data

    def _extract_bits(self, byte_val, bit_offset, length):
        """Extract bits from a single byte."""
        mask = (1 << length) - 1
        return (byte_val >> bit_offset) & mask

    async def close(self):
        """Close the HTTP session."""
        if self._session and not self._session.closed:
            LOGGER.debug("Closing HTTP session for GizwitsApi.")
            await self._session.close()
