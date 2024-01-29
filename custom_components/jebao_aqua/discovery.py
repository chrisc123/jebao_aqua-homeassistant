import asyncio
import socket

BROADCAST_PORT = 12414
BROADCAST_PAYLOAD = b'\x00\x00\x00\x03\x03\x00\x00\x03'
DISCOVERY_TIMEOUT = 5  # seconds

async def send_broadcast(logger, broadcast_payload, broadcast_port):
    """Send a broadcast packet."""
    loop = asyncio.get_event_loop()
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.bind(('', 0))  # Bind to a random port
        logger.debug("Sending broadcast packet")
        await loop.sock_sendto(sock, broadcast_payload, ('255.255.255.255', broadcast_port))
        logger.debug("Broadcast packet sent")

async def listen_for_responses(logger):
    """Listen for responses to the broadcast."""
    device_ips = {}
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.bind(('', BROADCAST_PORT))
        sock.settimeout(DISCOVERY_TIMEOUT)
        logger.debug("Listening for responses")

        while True:
            try:
                data, addr = sock.recvfrom(1024)
                device_id = data[10:32].decode()
                logger.debug(f"Received response from {addr[0]} with device ID {device_id}")
                device_ips[device_id] = addr[0]
            except socket.timeout:
                logger.debug("Socket timeout, stopping response listener")
                break

    return device_ips

async def discover_devices(logger, device_ids):
    """Discover devices on the local network."""
    loop = asyncio.get_event_loop()

    # Send multiple broadcast packets
    for _ in range(5):
        await send_broadcast(logger, BROADCAST_PAYLOAD, BROADCAST_PORT)

    # Collect responses
    discovered_ips = await listen_for_responses(logger)

    # Filter out devices not in our list
    logger.debug(f"Discovered devices: {discovered_ips}")
    return {did: ip for did, ip in discovered_ips.items() if did in device_ids}
