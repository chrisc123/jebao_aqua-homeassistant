# gizwits_lan/device.py

import asyncio
import logging
import struct
import time
from typing import Any

from .connection import Connection
from .device_status import DeviceStatus
from .errors import LoginError, PasscodeError, ProtocolError
from .protocol import (
    build_prefix_and_command,
    parse_response_prefix,
    set_bits_in_byte,
    set_normal_bits_in_first_16,
    set_swapped_bits,
)

logger = logging.getLogger(__name__)


def need_swapped_16bits(all_attrs) -> bool:
    for a in all_attrs:
        pos = a["position"]
        if pos["byte_offset"] == 0 and pos["unit"] == "bit":
            if pos["bit_offset"] + pos["len"] > 7:
                return True
    return False


class Device:
    """Represents a Gizwits device accessible via LAN protocol.

    Handles:
    - Connection and login
    - Status updates (solicited and unsolicited)
    - Writing attributes
    - Connection monitoring via ping/pong
    - Status change callbacks

    Args:
        ip: Device IP address
        port: TCP port (default 12416)
        product_key: Device model identifier
        attributes: List of attribute definitions from product JSON

    """

    def __init__(
        self, ip: str, port: int = 12416, product_key: str = "", attributes=None
    ):
        self.ip = ip
        self.port = port
        self.product_key = product_key

        self.all_attrs = attributes or []
        self.writable_attrs = [
            a for a in self.all_attrs if a.get("type") == "status_writable"
        ]

        self.reader: asyncio.StreamReader = None
        self.writer: asyncio.StreamWriter = None
        self._read_task: asyncio.Task = None

        self._pending_requests = {}
        self.current_status = None

        self.max_status_len = self._compute_status_len_from_all()
        self.swapped_16 = need_swapped_16bits(self.all_attrs)

        self.last_pong = 0.0  # We want to try and keep our connection alive with Ping/Pongs so that we recieve status updates.
        self.ping_interval = 4  # 10 Seconds seems to be the maximum interval - anything longer and the device will close the connection.
        self.pong_timeout = 10  # If we've not seen a Pong in this long then we'll definitely need to reconnect anyway.

        self._status_callbacks = set()
        self._connection_callbacks = set()

        self._connected = False  # Keep this for connection sequence

        self._connection = Connection(
            connect_func=self._do_connect,
            disconnect_func=self._do_disconnect,
            ping_func=self._do_ping,
            ready_check=lambda: self.available,  # Change from property to lambda
            device_id=f"{ip}:{port}",  # Pass device identifier
            retry_interval=2.0,
            min_retry_interval=2.0,
            max_retry_interval=128.0,
            ping_interval=self.ping_interval,
            ping_timeout=self.pong_timeout,
        )

    def add_status_callback(self, callback):
        """Register a callback to be called when device status updates."""
        self._status_callbacks.add(callback)

    def remove_status_callback(self, callback):
        """Remove a previously registered status callback."""
        self._status_callbacks.discard(callback)

    def add_connection_callback(self, callback):
        """Register a callback for connection state changes."""
        self._connection.add_callback(callback)

    def remove_connection_callback(self, callback):
        """Remove a previously registered connection callback."""
        self._connection.remove_callback(callback)

    def _compute_status_len_from_all(self) -> int:
        max_len = 0
        for a in self.all_attrs:
            pos = a["position"]
            bo = pos["byte_offset"]
            length_bits = pos["len"]
            if pos["unit"] == "byte":
                end = bo + length_bits
            else:
                end = bo + 1
            max_len = max(end, max_len)
        return max_len

    async def connect(self, timeout: float = 5.0):
        """Connect to the device and start connection management.

        This method:
        1. Starts the connection manager
        2. Waits for initial connection
        3. Ensures login sequence completes
        4. Sets up status monitoring
        5. Enables auto-reconnection

        Args:
            timeout: How long to wait for initial connection in seconds

        Raises:
            TimeoutError: If initial connection fails
            PasscodeError: If device not in binding mode
            LoginError: If login handshake fails
            ProtocolError: If initial status fails

        """
        await self._connection.start()
        # Wait for initial connection
        start = time.time()
        while time.time() - start < timeout:
            if self._connection.ready:
                return
            await asyncio.sleep(0.1)
        if not self._connection.ready:
            raise TimeoutError("Initial connection failed")

    async def disconnect(self):
        """Stop connection management and disconnect."""
        await self._connection.stop()

    async def _do_connect(self) -> bool:
        """Full connection sequence including login."""
        try:
            # Open TCP connection with timeout
            try:
                self.reader, self.writer = await asyncio.wait_for(
                    asyncio.open_connection(self.ip, self.port),
                    timeout=3.0,  # 3 second timeout for initial connection
                )
            except (TimeoutError, ConnectionRefusedError, OSError) as e:
                logger.info("Device %s not reachable: %s", self.ip, str(e))
                return False

            # Start read loop
            if self._read_task is None or self._read_task.done():
                self._read_task = asyncio.create_task(
                    self._read_loop(), name=f"read_loop_{self.ip}"
                )

            # Allow read loop to start
            await asyncio.sleep(0.1)

            # Login sequence
            passcode = await self._send_command_no_seq(0x06, 0x07, b"", 5.0)
            if len(passcode) < 2:
                raise PasscodeError("No passcode length in cmd=07 payload")
            length_reported = struct.unpack(">H", passcode[:2])[0]
            if length_reported == 0:
                raise PasscodeError("Device not in binding mode or passcode=0")
            passcode_bytes = passcode[2 : 2 + length_reported]

            payload = struct.pack(">H", len(passcode_bytes)) + passcode_bytes
            login_resp = await self._send_command_no_seq(0x08, 0x09, payload, 5.0)
            if not login_resp or (login_resp[0] != 0):
                raise LoginError("User login failed (cmd=09 first byte != 0)")

            # Mark as connected and set initial pong time
            self._connected = True  # Set TCP connection state
            self.last_pong = time.time()

            # Get initial status
            if not await self.request_status_update():
                return False

            logger.info("Successfully connected to device %s", self.ip)
            return True

        except Exception as e:
            logger.error("Connection failed to %s: %s", self.ip, str(e))
            await self._do_disconnect()
            return False

    async def _do_disconnect(self):
        """Clean up connection."""
        self._connected = False  # Clear TCP connection state
        if self._read_task:
            self._read_task.cancel()
            try:
                await self._read_task
            except asyncio.CancelledError:
                pass
        if self.writer:
            self.writer.close()
            try:
                await self.writer.wait_closed()
            except Exception:
                pass
        # Reset the streams to None
        self.reader = None
        self.writer = None

    async def _do_ping(self) -> bool:
        """Perform a single ping and wait for pong."""
        try:
            cmd_15 = build_prefix_and_command(b"\x00\x15", b"")
            last_pong = self.last_pong

            self.writer.write(cmd_15)
            await self.writer.drain()

            # Wait up to pong_timeout for response
            for _ in range(3):  # Try up to 3 times
                await asyncio.sleep(0.1)
                if self.last_pong > last_pong:
                    return True
            return False

        except Exception as e:
            logger.error("Ping failed: %s", e)
            return False

    ###########################################################################
    # Partial Updates (93->94) for Writable Attributes
    ###########################################################################
    async def set_device_attribute(self, attr_name: str, value, timeout=3.0):
        """Set a single device attribute.

        Args:
            attr_name: Name of attribute to set
            value: New value (type must match attribute definition)
            timeout: Command timeout in seconds

        Returns:
            Response payload or None if failed

        Raises:
            RuntimeError: If device not connected

        """
        return await self.set_multiple_attributes({attr_name: value}, timeout)

    async def set_multiple_attributes(self, updates: dict, timeout=3.0):
        if not self._connected:  # Check TCP connection state
            raise RuntimeError("Device not connected")

        if not self.writable_attrs:
            logger.warning("No writable attributes in this device definition.")
            return None

        max_id = max(a["id"] for a in self.writable_attrs)
        flags_count = (max_id // 8) + 1
        attr_flags = bytearray(flags_count)

        max_offset = 0
        for a in self.writable_attrs:
            pos = a["position"]
            bo = pos["byte_offset"]
            end = bo + pos["len"] if pos["unit"] == "byte" else bo + 1
            max_offset = max(end, max_offset)
        if max_offset < 2 and any(
            a["position"]["byte_offset"] == 0 for a in self.writable_attrs
        ):
            max_offset = 2
        attr_values = bytearray(max_offset)

        name_map = {a["name"]: a for a in self.writable_attrs}
        for k, v in updates.items():
            if k not in name_map:
                logger.warning("Ignoring attribute '%s' (not status_writable?).", k)
                continue
            self._set_one_writable_attribute(name_map[k], v, attr_flags, attr_values)

        seq = struct.pack(">I", int(time.time()) & 0xFFFF)
        action_byte = b"\x01"
        payload = seq + action_byte + attr_flags + attr_values

        ack_payload = await self._send_command_with_seq(
            0x93, 0x94, seq, payload, timeout
        )
        logger.debug(
            "Partial update ack, seq=%s, ack_payload=%s",
            seq.hex(),
            ack_payload.hex() if ack_payload else "<none>",
        )
        return ack_payload

    def _set_one_writable_attribute(self, attr, user_value, attr_flags, attr_values):
        a_id = attr["id"]
        byte_index = a_id // 8
        bit_index = a_id % 8
        flags_byte = len(attr_flags) - 1 - byte_index
        attr_flags[flags_byte] |= 1 << bit_index

        pos = attr["position"]
        bo = pos["byte_offset"]
        bit_off = pos["bit_offset"]
        length_bits = pos["len"]
        dtype = attr["data_type"]
        unit = pos["unit"]

        if dtype in ("bool", "enum"):
            if dtype == "bool":
                val_int = 1 if str(user_value).lower() in ("1", "true") else 0
            else:
                val_int = int(user_value)
            if unit == "bit":
                if bo == 0 and self.swapped_16:
                    set_swapped_bits(attr_values, bit_off, length_bits, val_int)
                elif bo == 0:
                    set_normal_bits_in_first_16(
                        attr_values, bit_off, length_bits, val_int
                    )
                else:
                    set_bits_in_byte(attr_values, bo, bit_off, length_bits, val_int)
            else:
                attr_values[bo] = val_int & 0xFF
        elif dtype == "uint8":
            val = int(user_value)
            attr_values[bo] = val & 0xFF
        elif dtype == "binary":
            length_bytes = pos["len"] if unit == "byte" else (length_bits + 7) // 8
            val_bytes = (
                bytes.fromhex(user_value) if isinstance(user_value, str) else user_value
            )
            for i in range(min(length_bytes, len(val_bytes))):
                attr_values[bo + i] = val_bytes[i]
        else:
            logger.warning("Unsupported data_type=%s for '%s'", dtype, attr["name"])

    ###########################################################################
    # Read Loop (Updated to Catch OSErrors)
    ###########################################################################
    async def _read_loop(self):
        logger.debug("read_loop started for %s", self.ip)
        buf = bytearray()
        try:
            while True:
                try:
                    chunk = await self.reader.read(1024)
                except OSError as e:
                    logger.error("OSError in read_loop for %s: %s", self.ip, e)
                    break
                if not chunk:
                    logger.warning("EOF from device %s", self.ip)
                    break
                buf += chunk
                while True:
                    packet = self._try_extract_one_packet(buf)
                    if not packet:
                        break
                    cmd, payload = parse_response_prefix(packet)
                    await self._handle_incoming_packet(cmd, payload)
        except asyncio.CancelledError:
            logger.debug("read_loop cancelled for %s", self.ip)
        except Exception as e:
            logger.exception("Unexpected error in read_loop on %s: %s", self.ip, e)
        finally:
            logger.debug("read_loop exiting for %s", self.ip)
            self._connected = False  # Clear connection state when read loop exits

    def _try_extract_one_packet(self, buffer: bytearray):
        if len(buffer) < 4:
            return None
        if not buffer.startswith(b"\x00\x00\x00\x03"):
            raise ProtocolError("Bad packet prefix in read_loop")
        idx = 4
        length_val = 0
        shift = 0
        while True:
            if idx >= len(buffer):
                return None
            b_i = buffer[idx]
            idx += 1
            length_val |= (b_i & 0x7F) << shift
            shift += 7
            if (b_i & 0x80) == 0:
                break
        total_len = idx + length_val
        if len(buffer) < total_len:
            return None
        packet = bytes(buffer[:total_len])
        del buffer[:total_len]
        return packet

    async def _handle_incoming_packet(self, cmd: bytes, payload: bytes):
        cmd_int = int.from_bytes(cmd, "big")
        if cmd_int == 0x16:
            logger.debug("Pong (cmd=16) from %s", self.ip)
            self.last_pong = time.time()
            if isinstance(self.current_status, DeviceStatus):
                self.current_status.last_pong = self.last_pong
        elif cmd_int == 0x91:
            logger.info(
                "Unsolicited cmd=0x91 from %s, payload=%s", self.ip, payload.hex()
            )
        elif cmd_int == 0x93:
            logger.info(
                "Unsolicited cmd=0x93 from %s, payload=%s", self.ip, payload.hex()
            )
            needed = self.max_status_len
            if len(payload) < needed:
                logger.warning(
                    "cmd=0x93 but payload len=%d < %d, ignoring", len(payload), needed
                )
                return
            status_data = payload[-self.max_status_len :]
            parsed_dict = self._unpack_status_data(status_data)
            self.current_status = DeviceStatus(parsed_dict)
            logger.info("Device status updated => %s", self.current_status)
            for callback in self._status_callbacks:
                try:
                    callback(self.current_status)
                except Exception as e:
                    logger.error("Error in status callback: %s", e)
        elif cmd_int in (0x07, 0x09):
            fut = self._pending_requests.pop((cmd_int, None), None)
            if fut:
                fut.set_result(payload)
            else:
                logger.info("Unsolicited cmd=0x%02x with no matching request", cmd_int)
        elif cmd_int == 0x94:
            if len(payload) < 4:
                logger.warning("cmd=0x94 but payload < 4 bytes.")
                return
            seq_echo = payload[:4]
            fut = self._pending_requests.pop((0x94, seq_echo), None)
            if fut:
                fut.set_result(payload[4:])
            else:
                logger.info(
                    "Unsolicited cmd=0x94 with seq=%s not found in pending",
                    seq_echo.hex(),
                )
        else:
            logger.info(
                "Unsolicited cmd=0x%02x from %s, len=%d, payload=%s",
                cmd_int,
                self.ip,
                len(payload),
                payload.hex(),
            )

    async def _send_command_no_seq(
        self, cmd_send: int, cmd_recv: int, payload: bytes, timeout: float
    ) -> bytes:
        cmd_send_bytes = cmd_send.to_bytes(2, "big")
        packet = build_prefix_and_command(cmd_send_bytes, payload)
        logger.debug(
            "Sending cmd=0x%02x => expect cmd=0x%02x, payload=%s",
            cmd_send,
            cmd_recv,
            payload.hex(),
        )
        fut = asyncio.get_event_loop().create_future()
        self._pending_requests[(cmd_recv, None)] = fut
        self.writer.write(packet)
        await self.writer.drain()
        try:
            resp = await asyncio.wait_for(fut, timeout=timeout)
            return resp
        except TimeoutError:
            self._pending_requests.pop((cmd_recv, None), None)
            raise ProtocolError(
                f"No response for cmd=0x{cmd_recv:02x} within {timeout}s"
            )

    async def _send_command_with_seq(
        self, cmd_send: int, cmd_recv: int, seq: bytes, payload: bytes, timeout: float
    ) -> bytes:
        cmd_send_bytes = cmd_send.to_bytes(2, "big")
        packet = build_prefix_and_command(cmd_send_bytes, payload)
        logger.debug(
            "Sending cmd=0x%02x, seq=%s => expecting cmd=0x%02x",
            cmd_send,
            seq.hex(),
            cmd_recv,
        )
        fut = asyncio.get_event_loop().create_future()
        self._pending_requests[(cmd_recv, seq)] = fut
        self.writer.write(packet)
        await self.writer.drain()
        try:
            resp = await asyncio.wait_for(fut, timeout=timeout)
            return resp
        except TimeoutError:
            self._pending_requests.pop((cmd_recv, seq), None)
            raise ProtocolError(
                f"No ack for cmd=0x{cmd_recv:02x}, seq={seq.hex()} within {timeout}s"
            )

    def _unpack_status_data(self, data: bytes) -> dict:
        result = {}
        for attr in self.all_attrs:
            name = attr["name"]
            pos = attr["position"]
            bo = pos["byte_offset"]
            bit_off = pos["bit_offset"]
            length_bits = pos["len"]
            dtype = attr["data_type"]
            unit = pos["unit"]
            if bo >= len(data):
                continue
            val = None
            if dtype in ("bool", "enum"):
                val_int = self._decode_bits(data, bo, bit_off, length_bits, unit)
                val = bool(val_int) if dtype == "bool" else val_int
            elif dtype == "uint8":
                if bo < len(data):
                    val = data[bo]
            elif dtype == "binary":
                length_bytes = (
                    pos["len"] if unit == "byte" else ((length_bits + 7) // 8)
                )
                end = bo + length_bytes
                val = data[bo:end] if end <= len(data) else data[bo:]
            result[name] = val
        return result

    def _decode_bits(
        self, data: bytes, bo: int, bit_off: int, length_bits: int, unit: str
    ) -> int:
        if unit == "bit":
            if bo == 0 and self.swapped_16:
                return self._get_swapped_bits(data, bit_off, length_bits)
            if bo == 0:
                return self._get_normal_bits_16(data, bit_off, length_bits)
            return self._get_bits_in_byte(data, bo, bit_off, length_bits)
        return data[bo]

    def _get_swapped_bits(self, data: bytes, bit_off: int, length_bits: int) -> int:
        if len(data) < 2:
            return 0
        av16 = (data[0] << 8) | data[1]
        mask = (1 << length_bits) - 1
        return (av16 >> bit_off) & mask

    def _get_normal_bits_16(self, data: bytes, bit_off: int, length_bits: int) -> int:
        if len(data) < 2:
            return 0
        av16 = data[0] | (data[1] << 8)
        mask = (1 << length_bits) - 1
        return (av16 >> bit_off) & mask

    def _get_bits_in_byte(
        self, data: bytes, bo: int, bit_off: int, bit_length: int
    ) -> int:
        val = data[bo]
        mask = (1 << bit_length) - 1
        return (val >> bit_off) & mask

    async def request_status_update(self, timeout: float = 5.0) -> bool:
        """Request an immediate status update from the device.
        Returns True if status was updated successfully.
        """
        if not self._connected:  # Check TCP connection state
            raise RuntimeError("Device not connected")

        seq = struct.pack(">I", int(time.time()) & 0xFFFF)
        payload = seq + b"\x02"  # 0x02 = Request status update

        try:
            resp = await self._send_command_with_seq(0x93, 0x94, seq, payload, timeout)
            if (
                not resp or resp[0] != 0x03
            ):  # First byte (p0 action byte) should be 0x03 for status response
                logger.warning("Status request: unexpected response format")
                return False

            parsed_dict = self._unpack_status_data(resp[1:])  # Skip the p0 action byte
            self.current_status = DeviceStatus(parsed_dict)
            logger.debug("Device status updated => %s", self.current_status)

            # Notify callbacks about status update
            for callback in self._status_callbacks:
                try:
                    callback(self.current_status)
                except Exception as e:
                    logger.error("Error in status callback: %s", e)

            return True

        except Exception as e:
            logger.error("Failed to request status update: %s", e)
            return False

    @property
    def available(self) -> bool:
        """Whether the device is connected and responding to pings.

        A device is considered available if:
        1. TCP connection is established
        2. We have valid status data
        3. Last pong was recent
        """
        return (
            self._connected
            and isinstance(self.current_status, DeviceStatus)
            and self.current_status.pong_age() < self.pong_timeout
        )

    @property
    def attributes(self) -> dict:
        """Return the current values of all attributes."""
        return self.current_status.data if self.current_status else {}

    def get_attribute(self, attr_name: str) -> Any:
        """Get current value of a specific attribute."""
        return self.attributes.get(attr_name)

    def get_attribute_metadata(self, attr_name: str) -> dict | None:
        """Get metadata for a specific attribute (type, position, etc)."""
        for attr in self.all_attrs:
            if attr["name"] == attr_name:
                return attr
        return None

    def __repr__(self):
        return f"<Device {self.ip}:{self.port}, connected={self._connected}, status={self.current_status}>"
