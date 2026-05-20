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
        """Create and return a new aiohttp ClientSession."""
        return aiohttp.ClientSession()

    async def async_login(self, email: str, password: str) -> Tuple[str, str]:
        """Login to Gizwits and return the token and any error code.

        Returns:
            Tuple[str, str]: (token, error_code). If successful, error_code will be None.
        """
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
                LOGGER.debug("Login response status: %s", response.status)
                LOGGER.debug("Login response headers: %s", response.headers)
                LOGGER.debug("Login response body: %s", response_text)

                try:
                    json_response = json.loads(response_text)
                    LOGGER.debug("Parsed JSON response: %s", json_response)

                    # Check for error codes first
                    if json_response.get("error", False):
                        error_code = json_response.get("code")
                        if error_code in GIZWITS_ERROR_CODES:
                            return None, GIZWITS_ERROR_CODES[error_code]
                        return None, "unknown_error"

                    # If no error, process the token
                    if json_response and isinstance(json_response, dict):
                        data = json_response.get("data", {})
                        LOGGER.debug("Data field content: %s", data)

                        if isinstance(data, dict):
                            token = data.get("userToken")
                            if token:
                                return token, None
                            else:
                                LOGGER.error("No userToken in data: %s", data)
                        else:
                            LOGGER.error(
                                "Data is not a dictionary: %s, type: %s",
                                data,
                                type(data),
                            )

                    return None, "invalid_response"

                except json.JSONDecodeError as e:
                    LOGGER.error(
                        "Failed to decode JSON response: %s\nResponse text: %s",
                        e,
                        response_text,
                    )
                    return None, "invalid_json"

        except Exception as e:
            LOGGER.error("Exception during login to Gizwits API: %s", e)
            return None, "connection_error"

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
            "Accept": "application/json",
        }
        LOGGER.debug("Trying to get devices - Headers are: %s", headers)
        try:
            async with self._session.get(
                self.devices_url, headers=headers, timeout=TIMEOUT
            ) as response:
                result = await response.text()
                LOGGER.debug("Response from Gizwits API: %s", result)
                if response.status == 200:
                    return json.loads(result)
                else:
                    LOGGER.error(
                        "Failed to fetch devices from Gizwits API: %s", response.status
                    )
                    return None
        except Exception as e:
            LOGGER.error("Exception while fetching devices from Gizwits API: %s", e)
            return None

    async def get_device_data(self, device_id: str):
        """Get the latest attribute status values from a device."""
        url = self.device_data_url.format(device_id=device_id)
        LOGGER.debug("Trying to get device data from URL: %s", url)
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
                LOGGER.debug("Response from Gizwits API - Device Data: %s", result)
                if response.status == 200:
                    return json.loads(result)
                else:
                    LOGGER.error(
                        "Failed to fetch device data from Gizwits API: %s",
                        response.status,
                    )
                    return None
        except Exception as e:
            LOGGER.error("Exception while fetching device data from Gizwits API: %s", e)
            return None

    async def control_device(self, device_id: str, attributes: dict):
        """Send a command to change an attribute value on a device."""
        url = self.control_url.format(device_id=device_id)
        headers = {
            "X-Gizwits-User-token": self._token,
            "X-Gizwits-Application-Id": GIZWITS_APP_ID,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        data = {"attrs": attributes}
        LOGGER.debug(
            "Sending control command to Gizwits API - URL: %s, Data: %s, Headers: %s",
            url,
            data,
            headers,
        )

        # Create a new session for the control command
        async with aiohttp.ClientSession() as session:
            try:
                async with session.post(
                    url, json=data, headers=headers, timeout=TIMEOUT
                ) as response:
                    result = await response.text()
                    LOGGER.debug(
                        "Response from Gizwits API to Control Command - Device Data: %s",
                        result,
                    )
                    if response.status == 200:
                        return json.loads(result)
                    else:
                        LOGGER.error(
                            "Failed to send control command to Gizwits API: %s",
                            response.status,
                        )
                        return None
            except Exception as e:
                LOGGER.error(
                    "Exception while sending control command to Gizwits API: %s", e
                )
                return None

    async def get_local_device_data(self, device_ip, product_key, device_id):
        """Poll the local device for its status."""
        # Load attribute model for the product
        attribute_model = self._attribute_models.get(product_key)
        if not attribute_model:
            LOGGER.error(
                "Invalid product key or missing attribute model for product key: %s",
                product_key,
            )
            return None
        LOGGER.debug(
            "Attempting to get local device data - IP: %s, Device ID: %s",
            device_ip,
            device_id,
        )

        try:
            # Establish a connection with the local device (5s timeout to avoid blocking startup)
            try:
                reader, writer = await asyncio.wait_for(
                    asyncio.open_connection(device_ip, LAN_PORT),
                    timeout=5.0,
                )
            except asyncio.TimeoutError:
                LOGGER.warning(
                    "TCP connection to local device %s timed out after 5s", device_ip
                )
                return None

            try:
                # Perform necessary commands to retrieve device data
                await self._send_local_command(writer, b"\x00\x06")
                response = await reader.read(1024)
                binding_key = response[-12:]
                await self._send_local_command(writer, b"\x00\x08", binding_key)
                await reader.read(1024)
                await self._send_local_command(
                    writer, b"\x00\x93", b"\x00\x00\x00\x02\x02"
                )
                response = await reader.read(1024)

                # Debug log the response in hex format
                LOGGER.debug("Response after sending command 0x93: %s", response.hex())

                # Process the response
                device_status_payload = self._extract_device_status_payload(response)
                if device_status_payload:
                    parsed_data = self._parse_device_status(
                        device_status_payload, attribute_model
                    )
                    LOGGER.debug(
                        "Successfully parsed local device data: %s", parsed_data
                    )
                    return {"did": device_id, "attr": parsed_data}
                else:
                    LOGGER.error(
                        "Failed to retrieve or parse device status from local device: %s",
                        device_id,
                    )
                    return None
            finally:
                # Ensure the writer is closed properly
                writer.close()
                await writer.wait_closed()

        except asyncio.TimeoutError:
            LOGGER.error(
                "Timeout error while communicating with local device: %s", device_ip
            )
            return None
        except ConnectionError as e:
            LOGGER.error("Connection error with local device %s: %s", device_ip, e)
            return None
        except Exception as e:
            LOGGER.error(
                "Unexpected error while communicating with local device %s: %s",
                device_ip,
                e,
            )
            return None

    async def _send_local_command(self, writer, command, payload=b""):
        """Send a command to the local device."""
        try:
            header = b"\x00\x00\x00\x03"
            flag = b"\x00"
            length = len(flag + command + payload).to_bytes(1, byteorder="big")
            packet = header + length + flag + command + payload

            LOGGER.debug(
                "Sending local command: %s, Payload: %s", command.hex(), payload.hex()
            )
            writer.write(packet)
            await writer.drain()
            LOGGER.debug("Command sent successfully")
        except Exception as e:
            LOGGER.error("Error sending command to local device: %s", e)
            raise

    def _extract_device_status_payload(self, response):
        """Extract the device status payload from the response."""
        try:
            # Find the last occurrence of the pattern 0x00 0x00 0x00 0x03 in the response
            # This is the marker for the start of the device status message
            pattern = b"\x00\x00\x00\x03"
            start_index = response.rfind(pattern)
            if start_index == -1:
                LOGGER.error(
                    "Pattern 0x00 0x00 0x00 0x03 not found in the device response"
                )
                return None

            # Start evaluating bytes after the pattern for LEB128 encoded length
            leb128_start = start_index + len(pattern)
            leb128_bytes = response[leb128_start:]
            length, leb128_length = self._decode_leb128(leb128_bytes)
            if length is None:
                LOGGER.error(
                    "Failed to decode LEB128 encoded payload length from device response"
                )
                return None

            # Calculate the start of the payload (after header, length, flag, and command)
            # Header (4 bytes) + LEB128 length + flag (1 byte) + command (2 bytes) = 7 + leb128_length
            payload_start = start_index + 4 + leb128_length + 1 + 2
            
            # The length includes flag + command + payload, so subtract 3 (flag=1, command=2)
            payload_length = length - 3
            
            if payload_length > 0 and payload_start + payload_length <= len(response):
                # Extract the payload bytes
                device_status_payload = response[payload_start:payload_start + payload_length]
                LOGGER.debug("Extracted device status payload (length=%d): %s", payload_length, device_status_payload.hex())
                return device_status_payload
            else:
                LOGGER.error("Invalid device status payload length: %s (total response length: %s, payload_start: %s)", 
                            payload_length, len(response), payload_start)
                return None
        except Exception as e:
            LOGGER.error(f"Error in extracting device status payload: {e}")
            return None

    def _decode_leb128(self, data):
        """Decode LEB128 encoded data and return the value and number of bytes read."""
        result = 0
        shift = 0
        for i, byte in enumerate(data):
            result |= (byte & 0x7F) << shift
            if (byte & 0x80) == 0:
                return result, i + 1
            shift += 7
        return None, 0

    def _parse_device_status(self, payload, attribute_model):
        """Parse the device status payload based on the attribute model."""
        status_data = {}
        try:
            # Check if model has position data (required for local parsing)
            if not any("position" in attr for attr in attribute_model["attrs"]):
                LOGGER.debug("Model does not have position data for local parsing, skipping")
                return status_data

            # Ensure we have a bytes object to index into
            if isinstance(payload, str):
                payload_bytes = bytes.fromhex(payload)
            else:
                payload_bytes = payload

            # Process each attribute in the attribute model
            for attr in attribute_model["attrs"]:
                # Skip attributes without position data
                if "position" not in attr:
                    continue

                byte_offset = attr["position"]["byte_offset"]
                bit_offset = attr["position"]["bit_offset"]
                length = attr["position"]["len"]
                data_type = attr.get("data_type", "unknown")

                # For bit-addressed types (bool/enum), bit_offset may be >= 8 when the
                # model encodes all flags as a flat bit-stream from byte 0.  Resolve the
                # real byte and the in-byte bit position before reading.
                if data_type in ("bool", "enum"):
                    actual_byte = byte_offset + bit_offset // 8
                    actual_bit = bit_offset % 8
                else:
                    actual_byte = byte_offset
                    actual_bit = bit_offset

                # Bounds check
                if actual_byte >= len(payload_bytes):
                    LOGGER.debug(
                        "Skipping attribute '%s': byte %d exceeds payload length %d",
                        attr.get("name", "?"), actual_byte, len(payload_bytes)
                    )
                    continue

                value = None

                # Extract value based on data type
                if data_type == "bool":
                    value = bool(
                        self._extract_bits(payload_bytes[actual_byte], actual_bit, length)
                    )
                elif data_type == "enum":
                    enum_values = attr.get("enum", [])
                    enum_index = self._extract_bits(
                        payload_bytes[actual_byte], actual_bit, length
                    )
                    value = (
                        enum_values[enum_index]
                        if enum_index < len(enum_values)
                        else None
                    )
                elif data_type == "uint8":
                    value = payload_bytes[actual_byte]
                elif data_type == "uint16":
                    if actual_byte + 1 < len(payload_bytes):
                        value = (payload_bytes[actual_byte] << 8) | payload_bytes[actual_byte + 1]
                    else:
                        LOGGER.debug(
                            "Skipping uint16 attribute '%s': not enough bytes at offset %d",
                            attr.get("name", "?"), actual_byte
                        )
                        continue
                elif data_type == "binary":
                    value = payload_bytes[actual_byte : actual_byte + length].hex()
                else:
                    LOGGER.debug(
                        "Skipping attribute '%s': unhandled data_type '%s'",
                        attr.get("name", "?"), data_type
                    )
                    continue

                status_data[attr["name"]] = value
        except Exception as e:
            LOGGER.error(f"Error parsing device status payload: {e}")

        return status_data

    def _extract_bits(self, byte_val, bit_offset, length):
        """Extract specific bits from a byte value."""
        mask = (1 << length) - 1
        return (byte_val >> bit_offset) & mask

    async def close(self):
        """Close the session."""
        if self._session:
            await self._session.close()
