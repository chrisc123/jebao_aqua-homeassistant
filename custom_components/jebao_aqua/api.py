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
        self._sequence_number = 1  # Starting sequence number

    def _get_next_sequence(self):
        """Get next sequence number and handle rollover."""
        current = self._sequence_number
        self._sequence_number = (self._sequence_number + 1) % 0xFFFFFFFF
        if self._sequence_number == 0:
            self._sequence_number = 1
        return current.to_bytes(4, byteorder="big")

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
        attribute_model = self._attribute_models.get(product_key)
        if not attribute_model:
            LOGGER.error(
                "Invalid product key or missing attribute model: %s", product_key
            )
            raise ConnectionError("Invalid product key")

        try:
            LOGGER.debug(
                "Attempting to connect to device %s at %s", device_id, device_ip
            )
            try:
                reader, writer = await asyncio.wait_for(
                    asyncio.open_connection(device_ip, LAN_PORT), timeout=5.0
                )
            except (ConnectionRefusedError, OSError) as e:
                LOGGER.warning(
                    "Connection to device %s (%s) failed: %s",
                    device_id,
                    device_ip,
                    str(e),
                )
                raise ConnectionError(f"Connection failed: {str(e)}")
            except asyncio.TimeoutError:
                LOGGER.warning(
                    "Connection timeout for device %s (%s)", device_id, device_ip
                )
                raise ConnectionError("Connection timeout")

            try:
                # Send device passcode request and validate response
                await self._send_local_command(writer, b"\x00\x06")
                passcode = None
                try:
                    async with asyncio.timeout(5.0):
                        while True:
                            packet = await reader.read(1024)
                            if not packet:
                                break

                            # Check each packet immediately
                            if (
                                packet.startswith(b"\x00\x00\x00\x03")
                                and len(packet) >= 18
                                and packet[6:8] == b"\x00\x07"
                                and packet[8:10] == b"\x00\x0a"
                            ):
                                passcode = packet[-10:]  # Found valid passcode
                                break  # Exit loop immediately when found

                except asyncio.TimeoutError:
                    LOGGER.error(
                        "Timeout waiting for passcode response from device %s (%s)",
                        device_id,
                        device_ip,
                    )
                    return None

                if not passcode:
                    LOGGER.error(
                        "Failed to get valid passcode from device %s (%s)",
                        device_id,
                        device_ip,
                    )
                    return None

                # Send login request with received passcode
                login_command = b"\x00\x08"
                login_payload = b"\x00\x0a" + passcode
                await self._send_local_command(writer, login_command, login_payload)

                # Verify login response
                try:
                    async with asyncio.timeout(5.0):
                        while True:
                            packet = await reader.read(1024)
                            if not packet:
                                break

                            if (
                                packet.startswith(b"\x00\x00\x00\x03")
                                and len(packet) >= 9
                            ):
                                if packet[6:8] == b"\x00\x09":  # Command 09 response
                                    if (
                                        packet[-1] != 0
                                    ):  # Last byte should be 0 for success
                                        LOGGER.error(
                                            "Login failed for device %s (%s)",
                                            device_id,
                                            device_ip,
                                        )
                                        return None
                                    break
                except asyncio.TimeoutError:
                    LOGGER.error(
                        "Timeout waiting for login response from device %s (%s)",
                        device_id,
                        device_ip,
                    )
                    return None

                # Now proceed with status request
                sequence = self._get_next_sequence()
                status_request = sequence + b"\x02"
                await self._send_local_command(writer, b"\x00\x93", status_request)

                response_data = await self._get_status_response(
                    reader, sequence, device_id, device_ip
                )
                if response_data:
                    device_status_payload = self._extract_device_status_payload(
                        response_data
                    )
                    if device_status_payload:
                        parsed_data = self._parse_device_status(
                            device_status_payload, attribute_model
                        )
                        return {"did": device_id, "attr": parsed_data}

                return None

            finally:
                try:
                    writer.close()
                    await writer.wait_closed()
                except Exception as e:
                    LOGGER.debug(
                        "Error closing connection to device %s (%s): %s",
                        device_id,
                        device_ip,
                        str(e),
                    )

        except (ConnectionError, asyncio.TimeoutError) as e:
            # Re-raise these exceptions so they can be caught by the coordinator
            raise
        except Exception as e:
            LOGGER.error(
                "Unexpected error with device %s (%s): %s", device_id, device_ip, str(e)
            )
            raise ConnectionError(f"Unexpected error: {str(e)}")

    async def _get_status_response(
        self, reader, expected_sequence, device_id, device_ip, timeout=5.0
    ):
        """Wait for and validate status response, returning immediately when found."""
        try:
            async with asyncio.timeout(timeout):
                while True:
                    try:
                        packet = await reader.read(1024)
                        if not packet:
                            break

                        # Check each packet as it arrives
                        if packet.startswith(b"\x00\x00\x00\x03"):
                            vlq_start = 4
                            length, vlq_size = self._decode_vlq(packet[vlq_start:])
                            if length is not None:
                                cmd_pos = vlq_start + vlq_size + 1
                                if cmd_pos + 6 <= len(packet):
                                    if (
                                        packet[cmd_pos : cmd_pos + 2] == b"\x00\x94"
                                        and packet[cmd_pos + 2 : cmd_pos + 6]
                                        == expected_sequence
                                    ):
                                        LOGGER.debug(
                                            "Found matching status response for device %s (%s):\n"
                                            "Full packet (hex): %s\n"
                                            "Protocol marker: %s\n"
                                            "Length: %d (encoded in %d bytes)\n"
                                            "Command: %s\n"
                                            "Sequence: %s\n"
                                            "Remaining data: %s",
                                            device_id,
                                            device_ip,
                                            packet.hex(),
                                            packet[:4].hex(),
                                            length,
                                            vlq_size,
                                            packet[cmd_pos : cmd_pos + 2].hex(),
                                            packet[cmd_pos + 2 : cmd_pos + 6].hex(),
                                            packet[cmd_pos + 6 :].hex(),
                                        )
                                        return packet

                    except asyncio.IncompleteReadError:
                        continue

        except asyncio.TimeoutError:
            LOGGER.error(
                "Timeout waiting for status response from device %s (%s)",
                device_id,
                device_ip,
            )
            return None

    async def _send_local_command(self, writer, command, payload=b""):
        """Send a command to the local device.

        Gizwits Protocol Structure for 0x93 (Device Serial Control Request):
        +---------------+----------------+--------+---------+-----------------+----------------+
        | Protocol Mark | Length (1-4 B) | Flag   | Command | Sequence       | p0 Payload    |
        | 00 00 00 03  | VLQ encoded    | 00     | 00 93   | S1 S2 S3 S4    | XX ...        |
        +---------------+----------------+--------+---------+-----------------+----------------+

        The length field is VLQ encoded and represents the number of bytes after itself.
        For a status request, the p0 payload is a single byte 0x02 (read status command).
        """
        try:
            header = b"\x00\x00\x00\x03"  # Fixed protocol marker
            flag = b"\x00"  # Always 0x00 in this protocol
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
        """Extract the device status payload from the response.

        Gizwits Protocol Structure for 0x94 (Device Serial Control Response):
        +---------------+----------------+--------+---------+-----------------+----------------+
        | Protocol Mark | Length (1-4 B) | Flag   | Command | Sequence       | p0 Response   |
        | 00 00 00 03  | VLQ encoded    | 00     | 00 94   | S1 S2 S3 S4    | XX ...        |
        +---------------+----------------+--------+---------+-----------------+----------------+

        p0 Protocol Response Format:
        +-------------+------------------+
        | Action Byte | Status Payload   |
        | 0x03/0x04  | Device Data      |
        +-------------+------------------+

        Action byte values:
        - 0x03: Device status reply (response to our read request)
        - 0x04: Device status report (spontaneous update)

        The device status payload length N is calculated as:
        total_length - 8 (where 8 = 1 flag + 2 command + 4 sequence + 1 action bytes)
        """
        try:
            # Find the pattern 0x00 0x00 0x00 0x03 in the response
            pattern = b"\x00\x00\x00\x03"
            start_index = response.find(pattern)
            if start_index == -1:
                LOGGER.error(
                    "Pattern 0x00 0x00 0x00 0x03 not found in the device response"
                )
                return None

            # Start evaluating bytes after the pattern for VLQ encoded length
            vlq_bytes = response[start_index + len(pattern) :]
            length, vlq_length = self._decode_vlq(vlq_bytes)
            if length is None:
                LOGGER.error(
                    "Failed to decode VLQ encoded payload length from device response"
                )
                return None

            # Subtract 8 from the decoded length to get the device status payload length
            N = length - 8

            if N > 0 and N <= len(response):
                device_status_payload = response[-N:]
                return device_status_payload
            else:
                LOGGER.error("Invalid device status payload length: %s", N)
                return None
        except Exception as e:
            LOGGER.error(f"Error in extracting device status payload: {e}")
            return None

    def _decode_vlq(self, data):
        """Decode Variable Length Quantity (VLQ) encoded data and return the value and number of bytes read.

        VLQ Format:
        - Each byte uses 7 bits for data, 1 bit (MSB) as continuation flag
        - If MSB is 1, more bytes follow
        - If MSB is 0, this is the last byte
        - Data is accumulated by taking the 7 LSBs of each byte
        - Earlier bytes represent less significant bits

        Example:
        0x99 0x03 = 10011001 00000011
        Step 1: Take 0x99 -> data=0x19 (00011001), continue=1
        Step 2: Take 0x03 -> data=0x03 (00000011), continue=0
        Result: 0x19 | (0x03 << 7) = 25
        """
        result = 0
        shift = 0
        bytes_read = 0

        for byte in data:
            bytes_read += 1
            # Extract 7 bits of data and shift into position
            result = result | ((byte & 0x7F) << shift)
            shift += 7

            # If MSB is not set (0), this is the last byte
            if not (byte & 0x80):
                return result, bytes_read

        return None, 0

    def _swap_endian(self, hex_str):
        """Swap the endianness of the first two bytes of the hex string."""
        if len(hex_str) >= 4:
            swapped = hex_str[2:4] + hex_str[0:2] + hex_str[4:]
            return swapped
        return hex_str

    def _extract_bits_multi_byte(self, payload_bytes, byte_offset, bit_offset, length):
        """Extract bits that may span multiple bytes.

        Args:
            payload_bytes: Complete payload as bytes
            byte_offset: Starting byte position
            bit_offset: Starting bit position within the first byte
            length: Number of bits to extract

        Returns:
            int: Extracted value
        """
        result = 0
        bits_remaining = length
        current_byte = byte_offset
        current_bit = bit_offset

        while bits_remaining > 0:
            # How many bits we can get from current byte
            bits_from_this_byte = min(8 - current_bit, bits_remaining)

            # Extract value from current byte
            mask = (1 << bits_from_this_byte) - 1
            value = (payload_bytes[current_byte] >> current_bit) & mask

            # Position these bits in result
            shift = length - bits_remaining  # Shift based on remaining bits
            result |= value << shift

            # Move to next byte if needed
            bits_remaining -= bits_from_this_byte
            if bits_remaining > 0:
                current_byte += 1
                current_bit = 0

        return result

    def _parse_device_status(self, payload, attribute_model):
        """Parse the device status payload based on the attribute model."""
        status_data = {}
        try:
            # Convert bytes payload to a hexadecimal string if needed
            if isinstance(payload, bytes):
                payload = payload.hex()

            # Check if endianness swap is needed
            swap_needed = any(
                attr["position"]["byte_offset"] == 0
                and (attr["position"]["bit_offset"] + attr["position"]["len"] > 8)
                for attr in attribute_model["attrs"]
            )

            # Perform endianness swap only once if needed
            if swap_needed:
                payload = self._swap_endian(payload)

            # Convert hex payload to a byte array
            payload_bytes = bytes.fromhex(payload)

            # Process each attribute in the attribute model
            for attr in attribute_model["attrs"]:
                byte_offset = attr["position"]["byte_offset"]
                bit_offset = attr["position"]["bit_offset"]
                length = attr["position"]["len"]
                data_type = attr.get("data_type", "unknown")

                # Calculate if this attribute spans multiple bytes
                spans_bytes = (bit_offset + length) > 8

                # Extract value based on data type
                if data_type == "bool":
                    value = bool(
                        self._extract_bits(
                            payload_bytes[byte_offset], bit_offset, length
                        )
                    )
                elif data_type == "enum":
                    enum_values = attr.get("enum", [])
                    if spans_bytes:
                        enum_index = self._extract_bits_multi_byte(
                            payload_bytes, byte_offset, bit_offset, length
                        )
                    else:
                        enum_index = self._extract_bits(
                            payload_bytes[byte_offset], bit_offset, length
                        )
                    value = (
                        enum_values[enum_index]
                        if enum_index < len(enum_values)
                        else None
                    )
                elif data_type == "uint8":
                    value = payload_bytes[byte_offset]
                elif data_type == "binary":
                    value = payload_bytes[byte_offset : byte_offset + length].hex()

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
