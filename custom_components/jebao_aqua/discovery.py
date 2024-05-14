import asyncio
import socket
import logging

_LOGGER = logging.getLogger(__name__)

BROADCAST_PORT = 12414
BROADCAST_PAYLOAD = b'\x00\x00\x00\x03\x03\x00\x00\x03'
DISCOVERY_TIMEOUT = 5  # seconds

async def send_broadcast():
    """Send a single broadcast packet and return the source port used."""
    loop = asyncio.get_event_loop()
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.bind(('', 0))  # Bind to a random port
        source_port = sock.getsockname()[1]
        _LOGGER.debug(f"Sending broadcast packet from port {source_port}")
        await loop.sock_sendto(sock, BROADCAST_PAYLOAD, ('255.255.255.255', BROADCAST_PORT))
        _LOGGER.debug("Broadcast packet sent")
    return source_port

async def listen_for_responses(source_port):
    """Listen for responses to the broadcast from the same port."""
    device_ips = {}
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(('', source_port))  # Bind to the same port used for sending the broadcast
        _LOGGER.debug(f"Socket bound to port {source_port}")
        sock.settimeout(DISCOVERY_TIMEOUT)
        _LOGGER.debug("Listening for responses")

        while True:
            try:
                data, addr = sock.recvfrom(1024)
                _LOGGER.debug(f"Raw data received from {addr}: {data.hex()}")
                _LOGGER.debug(f"Raw data length: {len(data)}")
                
                # Determine payload start position
                payload_start = 0
                payload = data[payload_start:]
                
                _LOGGER.debug(f"Payload data: {payload.hex()}")
                _LOGGER.debug(f"Payload length: {len(payload)}")

                # Adjusting device ID extraction based on observed payload structure
                device_id_start = 10
                device_id_length = 22
                device_id_bytes = payload[device_id_start:device_id_start + device_id_length]
                _LOGGER.debug(f"Device ID bytes: {device_id_bytes.hex()}")
                device_id = device_id_bytes.decode(errors='ignore').strip()
                
                _LOGGER.debug(f"Extracted device ID: {device_id} from {addr[0]}")
                device_ips[device_id] = addr[0]
            except socket.timeout:
                _LOGGER.debug("Socket timeout, stopping response listener")
                break
            except Exception as e:
                _LOGGER.error(f"Error receiving data: {e}")
                break

    return device_ips

async def discover_devices():
    """Discover devices on the local network."""
    _LOGGER.debug("Starting device discovery")
    source_port = await send_broadcast()
    discovered_ips = await listen_for_responses(source_port)
    _LOGGER.debug(f"Discovered devices: {discovered_ips}")
    return discovered_ips
