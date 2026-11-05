"""Tests for LAN login and reconnects, against a fake device."""

from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path
import socket
import struct
import sys
import unittest

PACKAGE = Path(__file__).parents[1] / "custom_components" / "jebao_aqua" / "gizwits_lan"
SPEC = importlib.util.spec_from_file_location(
    "gizwits_lan", PACKAGE / "__init__.py", submodule_search_locations=[str(PACKAGE)]
)
assert SPEC and SPEC.loader
gizwits_lan = importlib.util.module_from_spec(SPEC)
sys.modules["gizwits_lan"] = gizwits_lan
SPEC.loader.exec_module(gizwits_lan)

from gizwits_lan.device import Device  # noqa: E402
from gizwits_lan.protocol import build_prefix_and_command  # noqa: E402

PASSCODE = b"JJRSBSOEEL"
ATTRS = [
    {
        "id": 0,
        "name": "SwitchON",
        "type": "status_writable",
        "data_type": "bool",
        "position": {"byte_offset": 0, "unit": "bit", "len": 1, "bit_offset": 0},
    },
    {
        "id": 1,
        "name": "Motor_Speed",
        "type": "status_writable",
        "data_type": "uint8",
        "position": {"byte_offset": 1, "unit": "byte", "len": 1, "bit_offset": 0},
    },
]


class FakeDevice:
    """A GAgent TCP server. binding: whether it gives out its passcode."""

    def __init__(self, binding: bool = True, passcode: bytes = PASSCODE) -> None:
        self.binding = binding
        self.passcode = passcode
        self.commands: list[int] = []
        self.ports: list[int] = []

    async def handle(self, reader, writer) -> None:
        self.ports.append(writer.get_extra_info("peername")[1])
        try:
            while True:
                head = await reader.readexactly(5)
                body = await reader.readexactly(head[4])
                cmd = body[2]
                self.commands.append(cmd)
                if cmd == 0x06:
                    if not self.binding:
                        writer.write(build_prefix_and_command(b"\x00\x07", b"\x00\x00"))
                        await writer.drain()
                        break
                    reply = struct.pack(">H", len(self.passcode)) + self.passcode
                    writer.write(build_prefix_and_command(b"\x00\x07", reply))
                elif cmd == 0x08:
                    good = body[5:] == self.passcode
                    writer.write(build_prefix_and_command(b"\x00\x09", b"\x00" if good else b"\x01"))
                    await writer.drain()
                    if not good:
                        break
                    # Pumps follow up with a second login-OK and a 0x62
                    writer.write(build_prefix_and_command(b"\x00\x09", b"\x00"))
                    writer.write(build_prefix_and_command(b"\x00\x62", b""))
                elif cmd == 0x15:
                    writer.write(build_prefix_and_command(b"\x00\x16", b""))
                elif cmd == 0x90:
                    writer.write(build_prefix_and_command(b"\x00\x91", b"\x03\x01\x32"))
                await writer.drain()
        except (asyncio.IncompleteReadError, ConnectionError):
            pass
        finally:
            writer.close()


def run_session(pump: FakeDevice, count: int = 1, **kwargs) -> tuple[bool, Device]:
    """Connect count times to a fake device; return the last result and the Device."""

    async def run():
        server = await asyncio.start_server(pump.handle, "127.0.0.1", 0)
        device = Device(
            ip="127.0.0.1",
            port=server.sockets[0].getsockname()[1],
            attributes=ATTRS,
            **kwargs,
        )
        learned.clear()
        device.passcode_callback = learned.append
        result = False
        for _ in range(count):
            result = await device._do_connect()
            await device._do_disconnect()
        server.close()
        return result, device

    learned: list[str] = []
    result = asyncio.run(run())
    run_session.learned = learned
    return result


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class LoginTest(unittest.TestCase):
    def test_first_login_asks_and_reports_the_passcode(self) -> None:
        pump = FakeDevice()
        ok, device = run_session(pump)
        self.assertTrue(ok)
        self.assertEqual(PASSCODE.decode(), device.passcode)
        self.assertEqual([PASSCODE.decode()], run_session.learned)
        self.assertEqual([0x06, 0x08, 0x90], pump.commands)

    def test_known_passcode_logs_in_after_the_binding_window(self) -> None:
        pump = FakeDevice(binding=False)
        ok, _ = run_session(pump, passcode=PASSCODE.decode())
        self.assertTrue(ok)
        self.assertNotIn(0x06, pump.commands)
        self.assertEqual([], run_session.learned)

    def test_binding_window_shut_without_a_passcode_fails(self) -> None:
        pump = FakeDevice(binding=False)
        ok, device = run_session(pump)
        self.assertFalse(ok)
        self.assertIsNone(device.passcode)

    def test_wrong_passcode_falls_back_on_a_new_session(self) -> None:
        pump = FakeDevice()
        ok, device = run_session(pump, passcode="WRONGCODE0")
        self.assertTrue(ok)
        self.assertEqual(PASSCODE.decode(), device.passcode)
        self.assertEqual([PASSCODE.decode()], run_session.learned)
        self.assertEqual(2, len(pump.ports))

    def test_failed_status_read_leaves_no_session_open(self) -> None:
        async def run():
            server = await asyncio.start_server(FakeDevice().handle, "127.0.0.1", 0)
            device = Device(
                ip="127.0.0.1", port=server.sockets[0].getsockname()[1], attributes=ATTRS
            )

            async def no_status(timeout: float = 5.0) -> bool:
                return False

            device.request_status_update = no_status
            result = await device._do_connect()
            writer = device.writer
            server.close()
            return result, writer

        self.assertEqual((False, None), asyncio.run(run()))


@unittest.skipIf(sys.platform == "win32", "Windows won't rebind the port straight away")
class LocalPortTest(unittest.TestCase):
    def test_reconnects_come_from_the_same_port(self) -> None:
        pump = FakeDevice()
        port = free_port()
        ok, _ = run_session(pump, count=3, local_port=port)
        self.assertTrue(ok)
        self.assertEqual([port] * 3, pump.ports)

    def test_port_in_use_falls_back_to_a_random_one(self) -> None:
        pump = FakeDevice()
        with socket.socket() as taken:
            taken.bind(("", 0))
            taken.listen()
            port = taken.getsockname()[1]
            ok, _ = run_session(pump, local_port=port)
        self.assertTrue(ok)
        self.assertNotEqual([port], pump.ports)


class DiscoveryTest(unittest.TestCase):
    def test_mac_in_either_form(self) -> None:
        async def run(mac: bytes) -> list[dict]:
            from gizwits_lan.device_manager import DeviceManager

            def field(value: bytes) -> bytes:
                return struct.pack(">H", len(value)) + value

            reply = build_prefix_and_command(
                b"\x00\x04",
                field(b"Y33TGYeoTLsF2rAwNgL1gF")
                + field(mac)
                + field(b"04D30Q37")
                + field(b"6a5c47b3ea364ecb841b47f5997a1775"),
            )

            class Responder(asyncio.DatagramProtocol):
                def connection_made(self, transport):
                    self.transport = transport

                def datagram_received(self, data, addr):
                    self.transport.sendto(reply, addr)

            loop = asyncio.get_running_loop()
            transport, _ = await loop.create_datagram_endpoint(
                Responder, local_addr=("127.0.0.1", 0)
            )
            try:
                return await DeviceManager().discover_devices(
                    ip="127.0.0.1",
                    port=transport.get_extra_info("sockname")[1],
                    timeout=0.5,
                    retry_count=1,
                )
            finally:
                transport.close()

        for mac in (bytes.fromhex("8856a6fbb99c"), b"8856A6FBB99C"):
            found = asyncio.run(run(mac))
            self.assertEqual("88:56:a6:fb:b9:9c", found[0]["mac"])


if __name__ == "__main__":
    unittest.main()
