import asyncio
import socket
import logging
from contextlib import asynccontextmanager
from .const import DISCOVERY_TIMEOUT

_LOGGER = logging.getLogger(__name__)

BROADCAST_PORT = 12414
BROADCAST_PAYLOAD = b"\x00\x00\x00\x03\x03\x00\x00\x03"


@asynccontextmanager
async def create_broadcast_socket():
    """Create and configure a broadcast socket."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.setblocking(False)
        yield sock
    finally:
        sock.close()


async def send_broadcast():
    """Send a single broadcast packet and return the source port used."""
    async with create_broadcast_socket() as sock:
        sock.bind(("", 0))
        source_port = sock.getsockname()[1]
        _LOGGER.debug(f"Sending broadcast packet from port {source_port}")

        try:
            loop = asyncio.get_event_loop()
            await loop.sock_sendto(
                sock, BROADCAST_PAYLOAD, ("255.255.255.255", BROADCAST_PORT)
            )
            _LOGGER.debug("Broadcast packet sent successfully")
            return source_port
        except Exception as e:
            _LOGGER.error(f"Error sending broadcast: {e}")
            return None


async def listen_for_responses(source_port):
    """Listen for responses to the broadcast from the same port."""
    if not source_port:
        return {}

    device_ips = {}
    async with create_broadcast_socket() as sock:
        try:
            sock.bind(("", source_port))
            loop = asyncio.get_event_loop()

            end_time = loop.time() + DISCOVERY_TIMEOUT
            while loop.time() < end_time:
                try:
                    # Use wait_for to implement timeout for each receive operation
                    data, addr = await asyncio.wait_for(
                        loop.sock_recvfrom(sock, 1024),
                        timeout=0.5,  # 500ms timeout for each receive attempt
                    )

                    if len(data) < 32:  # Minimum expected packet size
                        continue

                    # Extract device ID from response
                    device_id_start = 10
                    device_id_length = 22
                    device_id_bytes = data[
                        device_id_start : device_id_start + device_id_length
                    ]
                    device_id = device_id_bytes.decode(errors="ignore").strip()

                    if device_id:
                        device_ips[device_id] = addr[0]
                        _LOGGER.debug(f"Found device {device_id} at {addr[0]}")

                except asyncio.TimeoutError:
                    continue
                except Exception as e:
                    _LOGGER.debug(f"Error receiving response: {e}")
                    continue

        except Exception as e:
            _LOGGER.error(f"Error in discovery listener: {e}")

    return device_ips


async def discover_devices():
    """Discover devices on the local network."""
    try:
        _LOGGER.debug("Starting device discovery")
        # Use wait_for to implement overall timeout
        source_port = await asyncio.wait_for(send_broadcast(), timeout=2.0)
        discovered_ips = await asyncio.wait_for(
            listen_for_responses(source_port), timeout=DISCOVERY_TIMEOUT
        )
        _LOGGER.debug(f"Discovery complete. Found devices: {discovered_ips}")
        return discovered_ips
    except asyncio.TimeoutError:
        _LOGGER.warning("Device discovery timed out")
        return {}
    except Exception as e:
        _LOGGER.error(f"Error during device discovery: {e}")
        return {}
