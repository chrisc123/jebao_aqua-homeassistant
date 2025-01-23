import aiohttp
import asyncio
import json
import logging

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

    async def __aenter__(self):
        self._session = await aiohttp.ClientSession().__aenter__()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self._session.__aexit__(exc_type, exc_val, exc_tb)

    async def get_session(self):
        """Create and return a new aiohttp ClientSession."""
        return aiohttp.ClientSession()

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
        try:
            async with self._session.post(GIZWITS_LOGIN_URL, json=data, headers=headers, timeout=TIMEOUT) as response:
                if response.status == 200:
                    json_response = await response.json()
                    return json_response.get("data", {}).get("userToken")
                else:
                    LOGGER.error("Failed to login to Gizwits API: %s", response.status)
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
        LOGGER.debug("Trying to get devices - Headers are: %s", headers)
        try:
            async with self._session.get(GIZWITS_DEVICES_URL, headers=headers, timeout=TIMEOUT) as response:
                result = await response.text()
                LOGGER.debug("Response from Gizwits API: %s", result)
                if response.status == 200:
                    return json.loads(result)
                else:
                    LOGGER.error("Failed to fetch devices from Gizwits API: %s", response.status)
                    return None
        except Exception as e:
            LOGGER.error("Exception while fetching devices from Gizwits API: %s", e)
            return None

    async def get_device_data(self, device_id: str):
        """Get the latest attribute status values from a device."""
        url = GIZWITS_DEVICE_DATA_URL.format(device_id=device_id)
        LOGGER.debug("Trying to get device data from URL: %s", url)
        headers = {
            "X-Gizwits-User-token": self._token,
            "X-Gizwits-Application-Id": GIZWITS_APP_ID,
            "Accept": "application/json"
        }
        try:
            async with self._session.get(url, headers=headers, timeout=TIMEOUT) as response:
                result = await response.text()
                LOGGER.debug("Response from Gizwits API - Device Data: %s", result)
                if response.status == 200:
                    return json.loads(result)
                else:
                    LOGGER.error("Failed to fetch device data from Gizwits API: %s", response.status)
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
        LOGGER.debug("Sending control command to Gizwits API - URL: %s, Data: %s, Headers: %s", url, data, headers)

        # Create a new session for the control command
        async with aiohttp.ClientSession() as session:
            try:
                async with session.post(url, json=data, headers=headers, timeout=TIMEOUT) as response:
                    result = await response.text()
                    LOGGER.debug("Response from Gizwits API to Control Command - Device Data: %s", result)
                    if response.status == 200:
                        return json.loads(result)
                    else:
                        LOGGER.error("Failed to send control command to Gizwits API: %s", response.status)
                        return None
            except Exception as e:
                LOGGER.error("Exception while sending control command to Gizwits API: %s", e)
                return None


    async def get_local_device_data(self, device_ip, product_key, device_id):
        """Poll the local device for its status."""
        # Load attribute model for the product
        attribute_model = self._attribute_models.get(product_key)
        if not attribute_model:
            LOGGER.error("Invalid product key or missing attribute model for product key: %s", product_key)
            return None
        LOGGER.debug("Attempting to get local device data - IP: %s, Device ID: %s", device_ip, device_id)
        
        try:
            # Establish a connection with the local device
            reader, writer = await asyncio.open_connection(device_ip, LAN_PORT)

            try:
                # Perform necessary commands to retrieve device data
                await self._send_local_command(writer, b'\x00\x06')
                response = await reader.read(1024)
                binding_key = response[-12:]
                await self._send_local_command(writer, b'\x00\x08', binding_key)
                await reader.read(1024)
                await self._send_local_command(writer, b'\x00\x93', b'\x00\x00\x00\x02\x02')
                response = await reader.read(1024)

                # Debug log the response in hex format
                LOGGER.debug("Response after sending command 0x93: %s", response.hex())

                # Process the response
                device_status_payload = self._extract_device_status_payload(response)
                if device_status_payload:
                    parsed_data = self._parse_device_status(device_status_payload, attribute_model)
                    LOGGER.debug("Successfully parsed local device data: %s", parsed_data)
                    return {'did': device_id, 'attr': parsed_data}
                else:
                    LOGGER.error("Failed to retrieve or parse device status from local device: %s", device_id)
                    return None
            finally:
                # Ensure the writer is closed properly
                writer.close()
                await writer.wait_closed()

        except asyncio.TimeoutError:
            LOGGER.error("Timeout error while communicating with local device: %s", device_ip)
            return None
        except ConnectionError as e:
            LOGGER.error("Connection error with local device %s: %s", device_ip, e)
            return None
        except Exception as e:
            LOGGER.error("Unexpected error while communicating with local device %s: %s", device_ip, e)
            return None



    async def _send_local_command(self, writer, command, payload=b''):
        """Send a command to the local device."""
        try:
            header = b'\x00\x00\x00\x03'
            flag = b'\x00'
            length = len(flag + command + payload).to_bytes(1, byteorder='big')
            packet = header + length + flag + command + payload

            LOGGER.debug("Sending local command: %s, Payload: %s", command.hex(), payload.hex())
            writer.write(packet)
            await writer.drain()
            LOGGER.debug("Command sent successfully")
        except Exception as e:
            LOGGER.error("Error sending command to local device: %s", e)
            raise

    def _extract_device_status_payload(self, response):
        """Extract the device status payload from the response."""
        try:
            # Find the pattern 0x00 0x00 0x00 0x03 in the response, this is marker for start of gizwits message
            pattern = b'\x00\x00\x00\x03'
            start_index = response.find(pattern)
            if start_index == -1:
                LOGGER.error("Pattern 0x00 0x00 0x00 0x03 not found in the device response")
                return None

            # Start evaluating bytes after the pattern for LEB128 encoded length
            leb128_bytes = response[start_index + len(pattern):]
            length, leb128_length = self._decode_leb128(leb128_bytes)
            if length is None:
                LOGGER.error("Failed to decode LEB128 encoded payload length from device response")
                return None

            # Subtract 8 from the decoded length to get the device status payload length
            N = length - 8

            if N > 0 and N <= len(response):
                # Extract the last N bytes as the device status payload
                device_status_payload = response[-N:]
                return device_status_payload
            else:
                LOGGER.error("Invalid device status payload length: %s", N)
                return None
        except Exception as e:
            LOGGER.error(f"Error in extracting device status payload: {e}")
            return None

    def _decode_leb128(self, data):
        """Decode LEB128 encoded data and return the value and number of bytes read."""
        result = 0
        shift = 0
        for i, byte in enumerate(data):
            result |= ((byte & 0x7F) << shift)
            if (byte & 0x80) == 0:
                return result, i + 1
            shift += 7
        return None, 0


    def _swap_endian(self, hex_str):
        """ Swap the endianness of the first two bytes of the hex string. """
        if len(hex_str) >= 4:
            swapped = hex_str[2:4] + hex_str[0:2] + hex_str[4:]
            return swapped
        return hex_str

    def _parse_device_status(self, payload, attribute_model):
        """Parse the device status payload based on the attribute model."""
        status_data = {}
        try:
            # Convert bytes payload to a hexadecimal string if needed
            if isinstance(payload, bytes):
                payload = payload.hex()

            # Check if endianness swap is needed
            swap_needed = any(
                attr['position']['byte_offset'] == 0 and (attr['position']['bit_offset'] + attr['position']['len'] > 8)
                for attr in attribute_model['attrs']
            )

            # Perform endianness swap only once if needed
            if swap_needed:
                payload = self._swap_endian(payload)

            # Convert hex payload to a byte array
            payload_bytes = bytes.fromhex(payload)

            # Process each attribute in the attribute model
            for attr in attribute_model['attrs']:
                byte_offset = attr['position']['byte_offset']
                bit_offset = attr['position']['bit_offset']
                length = attr['position']['len']
                data_type = attr.get('data_type', 'unknown')

                # Extract value based on data type
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
        except Exception as e:
            LOGGER.error(f"Error parsing device status payload: {e}")

        return status_data

    def _extract_bits(self, byte_val, bit_offset, length):
        """ Extract specific bits from a byte value. """
        mask = (1 << length) - 1
        return (byte_val >> bit_offset) & mask

    async def close(self):
        """Close the session."""
        if self._session:
            await self._session.close()

