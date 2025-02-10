import asyncio
import socket
import logging
from .const import DISCOVERY_TIMEOUT

_LOGGER = logging.getLogger(__name__)

BROADCAST_PORT = 12414
BROADCAST_PAYLOAD = b"\x00\x00\x00\x03\x03\x00\x00\x03"


class DiscoveryProtocol(asyncio.DatagramProtocol):
    def __init__(self):
        self.transport = None
        self.results = {}
        self._waiter = None

    def connection_made(self, transport):
        self.transport = transport

    def datagram_received(self, data, addr):
        if len(data) >= 32:
            device_id_start = 10
            device_id_length = 22
            device_id = (
                data[device_id_start : device_id_start + device_id_length]
                .decode(errors="ignore")
                .strip()
            )

            if device_id:
                self.results[device_id] = addr[0]
                _LOGGER.debug(f"Found device {device_id} at {addr[0]}")


async def discover_devices():
    """Discover devices on the local network."""
    try:
        _LOGGER.debug("Starting device discovery")
        loop = asyncio.get_event_loop()

        # Create the broadcast socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("", 0))
        source_port = sock.getsockname()[1]
        sock.close()  # Close the temporary socket

        # Create the protocol
        protocol = DiscoveryProtocol()

        # Create transport with the specific local port
        transport, _ = await loop.create_datagram_endpoint(
            lambda: protocol,
            local_addr=("0.0.0.0", source_port),
            allow_broadcast=True,
            reuse_port=True,
        )

        try:
            # Send broadcast
            transport.sendto(BROADCAST_PAYLOAD, ("255.255.255.255", BROADCAST_PORT))

            # Wait for responses
            await asyncio.sleep(DISCOVERY_TIMEOUT)

            _LOGGER.debug(f"Discovery complete. Found devices: {protocol.results}")
            return protocol.results

        finally:
            transport.close()

    except Exception as e:
        _LOGGER.error(f"Error during device discovery: {e}")
        return {}
