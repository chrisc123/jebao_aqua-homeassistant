"""Credential-free LAN protocol for the verified MCP150 product."""

from contextlib import contextmanager
from dataclasses import dataclass
import math
import socket
import time
from typing import Generator, Mapping


PRODUCT_KEY = "54114ccdac1e41c0bb17e222887c07ba"
PORT = 12416
HEADER = b"\x00\x00\x00\x03"
TIMEOUT = 5.0
MAX_FRAME_SIZE = 4096
STATUS_SIZE = 401
WRITABLE_SIZE = 400
FLOW_OFFSET = 2
FLOW_MASK = (1 << 8).to_bytes(8, "big")
CONTROL_NAMES = frozenset({
    "SwitchON", "PulseTide", "FeedSwitch", "TimerON",
    "Mode", "Linkage", "Flow", "Frequency", "FeedTime",
})
ControlValue = bool | int | float | str


class ProbeError(Exception):
    """An unsupported response or failed verification."""


class RestorationError(ProbeError):
    """The original settings could not be confirmed after a test."""


class InvalidCommand(ProbeError, ValueError):
    """An invalid command must not be retried through the cloud."""


@dataclass(frozen=True)
class Frame:
    flag: int
    command: int
    payload: bytes


@dataclass(frozen=True)
class Status:
    device_id: str
    raw: bytes

    def __post_init__(self) -> None:
        if not self.device_id or len(self.raw) != STATUS_SIZE:
            raise ProbeError("Expected a device ID and exactly 401 status bytes")

    @property
    def flow(self) -> int:
        return self.raw[FLOW_OFFSET]

    def summary(self) -> dict[str, int | bool]:
        bits = int.from_bytes(self.raw[:2], "big")
        return {
            "SwitchON": bool(bits & 1),
            "PulseTide": bool(bits & 2),
            "FeedSwitch": bool(bits & 4),
            "TimerON": bool(bits & 8),
            "Mode": (bits >> 5) & 3,
            "Linkage": (bits >> 7) & 3,
            "Flow": self.flow,
            "Frequency": self.raw[3],
            "FeedTime": self.raw[4],
            "fault_bits": self.raw[400],
        }


def encode_frame(command: int, payload: bytes = b"") -> bytes:
    body = b"\x00" + command.to_bytes(2, "big") + payload
    length = len(body)
    if length > MAX_FRAME_SIZE:
        raise ProbeError("Outgoing frame is too large")
    encoded_length = bytearray()
    while True:
        byte = length & 0x7F
        length >>= 7
        encoded_length.append(byte | (0x80 if length else 0))
        if not length:
            return HEADER + encoded_length + body


def parse_product_key(payload: bytes) -> str:
    if len(payload) < 52:
        raise ProbeError("Truncated device-info response")
    firmware_length = int.from_bytes(payload[48:50], "big")
    offset = 50 + firmware_length
    if offset + 2 > len(payload):
        raise ProbeError("Invalid firmware length in device-info response")
    key_length = int.from_bytes(payload[offset:offset + 2], "big")
    key = payload[offset + 2:offset + 2 + key_length]
    if key_length != 32 or len(key) != key_length:
        raise ProbeError("Invalid product key in device-info response")
    if key != PRODUCT_KEY.encode("ascii"):
        raise ProbeError("Refusing this device: product key is not the MCP150 test model")
    return PRODUCT_KEY


def flow_control(status: Status, value: int) -> bytes:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 100:
        raise ProbeError("Flow must be an integer from 1 to 100; zero is not tested")
    writable = bytearray(status.raw[:WRITABLE_SIZE])
    writable[FLOW_OFFSET] = value
    # Standard P0 control: action, big-endian attribute flags, fixed values block.
    return b"\x01" + FLOW_MASK + writable


def supports_local_control(product_key: str, attributes: Mapping[str, ControlValue]) -> bool:
    return product_key == PRODUCT_KEY and bool(attributes) and attributes.keys() <= CONTROL_NAMES


def normalize_attributes(
    attributes: Mapping[str, ControlValue], model: dict,
) -> dict[str, bool | int | str]:
    if not supports_local_control(model.get("product_key"), attributes):
        raise InvalidCommand("Unsupported model or local control attribute")
    specs = {attr["name"]: attr for attr in model["attrs"] if attr["type"] == "status_writable"}
    result = {}
    for name, value in attributes.items():
        if name not in specs:
            raise InvalidCommand(f"Missing model definition for {name}")
        attr = specs[name]
        if attr["data_type"] == "bool":
            if not isinstance(value, bool):
                raise InvalidCommand(f"{name} must be a boolean")
            result[name] = value
        elif attr["data_type"] == "enum":
            if not isinstance(value, str) or value not in attr["enum"]:
                raise InvalidCommand(f"Invalid option for {name}")
            result[name] = value
        elif attr["data_type"] == "uint8":
            limits = attr["uint_spec"]
            if (
                isinstance(value, bool) or not isinstance(value, (int, float))
                or not limits["min"] <= value <= limits["max"]
                or not math.isfinite(value) or int(value) != value
            ):
                raise InvalidCommand(f"{name} must be a whole number in {limits['min']}..{limits['max']}")
            result[name] = int(value)
        else:
            raise InvalidCommand(f"Unsupported local data type for {name}")
    return result


def control_payload(
    status: Status, attributes: Mapping[str, ControlValue], model: dict,
) -> bytes:
    normalized = normalize_attributes(attributes, model)
    specs = {attr["name"]: attr for attr in model["attrs"]}
    writable = bytearray(status.raw[:WRITABLE_SIZE])
    flags = 0
    for name, value in normalized.items():
        attr = specs[name]
        attr_id = attr["id"]
        if not isinstance(attr_id, int) or not 0 <= attr_id < 64:
            raise InvalidCommand(f"Invalid attribute flag for {name}")
        flags |= 1 << attr_id
        position = attr["position"]
        offset = position["byte_offset"]
        if attr["data_type"] == "uint8":
            writable[offset] = int(value)
        else:
            if offset != 0:
                raise InvalidCommand(f"Unsupported bit-field location for {name}")
            encoded = attr["enum"].index(value) if attr["data_type"] == "enum" else int(value)
            shift = position["bit_offset"]
            mask = ((1 << position["len"]) - 1) << shift
            bits = int.from_bytes(writable[:2], "big")
            writable[:2] = ((bits & ~mask) | (encoded << shift)).to_bytes(2, "big")
    return b"\x01" + flags.to_bytes(8, "big") + writable


def decode_status(status: Status, model: dict) -> dict[str, bool | int | str]:
    result = {}
    for attr in model["attrs"]:
        position = attr["position"]
        offset = position["byte_offset"]
        data_type = attr["data_type"]
        if data_type in ("bool", "enum"):
            bits = int.from_bytes(status.raw[:2], "big") if offset == 0 else status.raw[offset]
            value = (bits >> position["bit_offset"]) & ((1 << position["len"]) - 1)
            if data_type == "bool":
                result[attr["name"]] = bool(value)
            elif value < len(attr["enum"]):
                result[attr["name"]] = attr["enum"][value]
            else:
                raise ProbeError(f"Invalid enum value for {attr['name']}")
        elif data_type == "uint8":
            result[attr["name"]] = status.raw[offset]
        else:
            raise ProbeError(f"Unsupported status data type for {attr['name']}")
    return result


def control_values(status: Status, model: dict) -> dict[str, bool | int | str]:
    return {name: value for name, value in decode_status(status, model).items() if name in CONTROL_NAMES}


def verify_unchanged(before: Status, after: Status) -> None:
    if before.device_id != after.device_id:
        raise ProbeError("Device ID changed; refusing to continue")
    # YMDData/HMSData occupy bytes 392..399 and can tick during the test.
    changed = [
        index for index in range(STATUS_SIZE)
        if index != FLOW_OFFSET and not 392 <= index < 400
        and before.raw[index] != after.raw[index]
    ]
    if changed:
        raise ProbeError(f"Non-Flow status changed at byte offsets {changed}")


class MCP150Client:
    def __init__(self, connection: socket.socket) -> None:
        self.connection = connection
        self.sequence = 0
        self.wifi_firmware = ""

    def _read_exact(self, count: int, deadline: float) -> bytes:
        result = bytearray()
        while len(result) < count:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("Timed out waiting for a complete LAN response")
            self.connection.settimeout(remaining)
            chunk = self.connection.recv(count - len(result))
            if not chunk:
                raise ProbeError("Pump closed the TCP connection")
            result.extend(chunk)
        return bytes(result)

    def _read_frame(self, deadline: float) -> Frame:
        if self._read_exact(4, deadline) != HEADER:
            raise ProbeError("Invalid LAN frame header")
        length = 0
        for shift in range(0, 28, 7):
            byte = self._read_exact(1, deadline)[0]
            length |= (byte & 0x7F) << shift
            if not byte & 0x80:
                break
        else:
            raise ProbeError("Invalid LAN frame length encoding")
        if not 3 <= length <= MAX_FRAME_SIZE:
            raise ProbeError(f"Invalid LAN frame size: {length}")
        body = self._read_exact(length, deadline)
        return Frame(body[0], int.from_bytes(body[1:3], "big"), body[3:])

    def _response(
        self, command: int, sequence: int | None = None, deadline: float | None = None,
    ) -> Frame:
        if deadline is None:
            deadline = time.monotonic() + TIMEOUT
        for _ in range(32):
            frame = self._read_frame(deadline)
            if frame.command != command:
                continue
            if sequence is not None:
                if len(frame.payload) < 4:
                    raise ProbeError("Missing serial number in LAN response")
                if int.from_bytes(frame.payload[:4], "big") != sequence:
                    continue
            return frame
        raise ProbeError("Too many unrelated frames without the requested response")

    def _send(self, command: int, payload: bytes = b"") -> None:
        self.connection.settimeout(TIMEOUT)
        self.connection.sendall(encode_frame(command, payload))

    def login(self) -> None:
        self._send(0x0013)
        info = self._response(0x0014)
        parse_product_key(info.payload)
        self.wifi_firmware = info.payload[8:16].decode("ascii", errors="replace")
        self._send(0x0006)
        binding = self._response(0x0007).payload
        if len(binding) < 2 or int.from_bytes(binding[:2], "big") != len(binding) - 2:
            raise ProbeError("Invalid binding response")
        self._send(0x0008, binding)
        if self._response(0x0009).payload != b"\x00":
            raise ProbeError("Pump rejected the local login")

    def _send_data(self, payload: bytes) -> int:
        self.sequence += 1
        self._send(0x0093, self.sequence.to_bytes(4, "big") + payload)
        return self.sequence

    def read_status(self, deadline: float | None = None) -> Status:
        sequence = self._send_data(b"\x02")
        frame = self._response(0x0094, sequence, deadline)
        if frame.flag != 1 or len(frame.payload) < 7:
            raise ProbeError("Expected an identified status response")
        did_length = int.from_bytes(frame.payload[4:6], "big")
        offset = 6 + did_length
        if not did_length or offset >= len(frame.payload):
            raise ProbeError("Invalid device ID length in status response")
        try:
            device_id = frame.payload[6:offset].decode("ascii")
        except UnicodeDecodeError as error:
            raise ProbeError("Invalid device ID in status response") from error
        if frame.payload[offset] != 3:
            raise ProbeError("Expected a status-read response (P0 action 0x03)")
        return Status(device_id, frame.payload[offset + 1:])

    def write_flow(self, status: Status, value: int) -> None:
        self._send_data(flow_control(status, value))

    def write_attributes(
        self, status: Status, attributes: Mapping[str, ControlValue], model: dict,
    ) -> None:
        self._send_data(control_payload(status, attributes, model))

    def wait_for_attributes(
        self, attributes: Mapping[str, ControlValue], device_id: str, model: dict,
    ) -> Status:
        expected = normalize_attributes(attributes, model)
        deadline = time.monotonic() + TIMEOUT
        while True:
            status = self.read_status(deadline)
            if status.device_id != device_id:
                raise ProbeError("Device ID changed while verifying commands")
            current = control_values(status, model)
            if all(current[name] == value for name, value in expected.items()):
                return status
            if time.monotonic() + 0.2 >= deadline:
                actual = {name: current[name] for name in expected}
                raise ProbeError(f"Command read-back is {actual}, expected {expected}")
            time.sleep(0.2)

    def wait_for_flow(self, value: int, device_id: str) -> Status:
        deadline = time.monotonic() + TIMEOUT
        while True:
            status = self.read_status(deadline)
            if status.device_id != device_id:
                raise ProbeError("Device ID changed while verifying Flow")
            if status.flow == value:
                return status
            if time.monotonic() + 0.2 >= deadline:
                raise ProbeError(f"Flow read-back is {status.flow}, expected {value}")
            time.sleep(0.2)


@contextmanager
def connect(host: str) -> Generator[MCP150Client, None, None]:
    with socket.create_connection((host, PORT), timeout=TIMEOUT) as connection:
        client = MCP150Client(connection)
        client.login()
        yield client


def read_device(host: str, device_id: str) -> Status:
    with connect(host) as client:
        status = client.read_status()
        if status.device_id != device_id:
            raise ProbeError("Device ID does not match the configured pump")
        return status


def confirm_device(
    host: str, device_id: str, attributes: Mapping[str, ControlValue], model: dict,
) -> Status:
    with connect(host) as client:
        return client.wait_for_attributes(attributes, device_id, model)


def control_device(
    host: str, device_id: str, attributes: Mapping[str, ControlValue], model: dict,
) -> Status:
    normalized = normalize_attributes(attributes, model)
    with connect(host) as client:
        status = client.read_status()
        if status.device_id != device_id:
            raise ProbeError("Device ID does not match the configured pump; no command sent")
        client.write_attributes(status, normalized, model)
        client.wait_for_attributes(normalized, device_id, model)
    return confirm_device(host, device_id, normalized, model)
