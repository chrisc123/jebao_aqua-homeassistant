# gizwits_lan/device_manager.py

import asyncio
import binascii
import json
import logging
import socket
import struct
import time

from pathlib import Path
from typing import Optional, Dict, List
from .device import Device
from .errors import GizwitsError, ProtocolError
from .protocol import parse_response_prefix, build_prefix_and_command

logger = logging.getLogger(__name__)

DISCOVERY_REQUEST = b"\x00\x00\x00\x03\x03\x00\x00\x03"  # 8 bytes

def _hex_to_ascii_uid(hex_uid: str) -> str:
    """Convert hex UID (44 chars representing 22 bytes) to ASCII (22 chars)"""
    try:
        return binascii.unhexlify(hex_uid).decode('ascii')
    except (binascii.Error, UnicodeDecodeError):
        return hex_uid

def parse_varlen_field(data: bytes, offset: int) -> tuple[bytes, int]:
    """Parse a variable length field from data."""
    if offset + 2 > len(data):
        return None, offset
    
    field_len = int.from_bytes(data[offset:offset+2], 'big')
    offset += 2
    
    if offset + field_len > len(data):
        return None, offset
        
    return data[offset:offset+field_len], offset + field_len

def parse_cstring(data: bytes, offset: int) -> tuple[str, int]:
    """Parse a null-terminated string."""
    end = offset
    while end < len(data) and data[end] != 0:
        end += 1
    
    if end >= len(data):
        return "", end
        
    return data[offset:end].decode('ascii', errors='ignore'), end + 1

class DeviceManager:
    """
    DeviceManager handles device discovery and creation using JSON device definitions.

    Args:
        definitions_dir: Path to directory containing <product_key>.json device definition files

    The manager can:
    - Discover devices on the network via broadcast or directed discovery
    - Load device definitions from JSON files
    - Create and configure Device instances
    """

    def __init__(self, definitions_dir: Optional[str] = None):
        self.definitions_dir = Path(definitions_dir) if definitions_dir else None
        self._definition_cache: Dict[str, List[dict]] = {}

    async def discover_devices(self, ip: str = "255.255.255.255",
                             port: int = 12414, timeout: float = 2.0,
                             retry_count: int = 3, retry_delay: float = 0.3) -> list:
        """
        Send multiple discovery packets to improve reliability.
        
        Args:
            ip: Target IP (255.255.255.255 for broadcast)
            port: UDP port for discovery
            timeout: Total time to wait for responses
            retry_count: Number of discovery packets to send
            retry_delay: Delay between packets in seconds

        Returns:
            List of discovered devices
        """
        loop = asyncio.get_running_loop()
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        if ip == "255.255.255.255":
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        
        sock.bind(("0.0.0.0", 0))
        sock.setblocking(False)

        # Track unique devices by IP to avoid duplicates
        devices = {}
        start_time = time.time()

        try:
            # Send multiple discovery packets with delays
            for i in range(retry_count):
                if i > 0:
                    await asyncio.sleep(retry_delay)
                
                logger.debug("Sending discovery packet %d/%d to %s:%d", 
                            i + 1, retry_count, ip, port)
                sock.sendto(DISCOVERY_REQUEST, (ip, port))

                # Process responses until next packet or timeout
                while True:
                    elapsed = time.time() - start_time
                    if elapsed > timeout:
                        break
                    
                    # Calculate time until next packet or final timeout
                    if i < retry_count - 1:
                        wait_until = start_time + (i + 1) * retry_delay
                        remaining = wait_until - time.time()
                        if remaining <= 0:
                            break
                    else:
                        remaining = timeout - elapsed

                    try:
                        data, (src_ip, src_port) = sock.recvfrom(2048)
                    except BlockingIOError:
                        await asyncio.sleep(min(0.05, remaining))
                        continue
                    except socket.timeout:
                        break

                    try:
                        cmd, payload = parse_response_prefix(data)
                        if cmd != b"\x00\x04":
                            logger.debug("Ignoring non-04 response from %s", src_ip)
                            continue

                        # Parse all fields
                        offset = 0
                        device_info = {'ip': src_ip}

                        # Essential fields (logged at INFO)
                        uid, offset = parse_varlen_field(payload, offset)
                        if uid:
                            device_info['uid'] = uid.hex()
                            device_info['uid_ascii'] = _hex_to_ascii_uid(device_info['uid'])
                            
                        mac, offset = parse_varlen_field(payload, offset)
                        if mac:
                            device_info['mac'] = mac.hex(':')
                            
                        fw_ver, offset = parse_varlen_field(payload, offset)
                        if fw_ver:
                            device_info['firmware_version'] = fw_ver.decode('ascii', errors='ignore')
                            
                        prod_key, offset = parse_varlen_field(payload, offset)
                        if prod_key:
                            device_info['product_key'] = prod_key.decode('ascii', errors='ignore')

                        # Additional fields (logged at DEBUG)
                        if offset + 8 <= len(payload):
                            mcu_attrs = payload[offset:offset+8]
                            logger.debug("Device %s MCU attrs: %s", src_ip, mcu_attrs.hex())
                            offset += 8
                            
                        api_server, offset = parse_cstring(payload, offset)
                        if api_server:
                            logger.debug("Device %s API server: %s", src_ip, api_server)
                            
                        gizwits_ver, offset = parse_cstring(payload, offset)
                        if gizwits_ver:
                            logger.debug("Device %s Gizwits version: %s", src_ip, gizwits_ver)

                        # Store device if we have the minimum required info
                        if 'product_key' in device_info:
                            devices[src_ip] = device_info
                            logger.info(
                                "Found device: ip=%s mac=%s uid=%s product_key=%s fw=%s", 
                                src_ip,
                                device_info.get('mac', '?'),
                                device_info.get('uid', '?'),
                                device_info['product_key'],
                                device_info.get('firmware_version', '?')
                            )

                    except ProtocolError as e:
                        logger.warning("Invalid response from %s: %s", src_ip, e)
                        continue
                    except Exception as e:
                        logger.error("Error processing response from %s: %s", src_ip, e)
                        continue

        finally:
            sock.close()

        logger.info("Discovery completed, found %d device(s)", len(devices))
        return list(devices.values())

    async def create_device(self, ip: str, product_key: str, port: int = 12416) -> Device:
        """
        Create a Device instance.

        Args:
            ip: IP address of the device
            product_key: Product key identifying the device model
            port: Port to connect to (default 12416)

        Returns:
            Device instance (not connected)

        Raises:
            FileNotFoundError: If device definition not found
        """
        all_attrs = await self._load_device_definition(product_key)
        return Device(ip=ip, port=port, product_key=product_key,
                     attributes=all_attrs)

    async def _load_device_definition(self, product_key: str) -> List[dict]:
        """
        Load the <product_key>.json from definitions_dir.
        We do NOT filter by 'type'. The Device code will handle partial updates
        for 'status_writable' only, but we parse all attributes for status.

        Args:
            product_key: Product key identifying the device model

        Returns:
            List of attribute dictionaries
        """
        if product_key in self._definition_cache:
            return self._definition_cache[product_key]

        if not self.definitions_dir:
            raise FileNotFoundError("No definitions_dir specified for loading product definitions")

        json_file = self.definitions_dir / f"{product_key}.json"
        if not json_file.is_file():
            raise FileNotFoundError(f"Device definition not found: {json_file}")

        logger.debug("Loading definition for %s from %s", product_key, json_file)
        loop = asyncio.get_running_loop()
        content = await loop.run_in_executor(None, json_file.read_text, "utf-8-sig")
        data = json.loads(content)

        all_attrs = []
        for ent in data.get("entities", []):
            for at in ent.get("attrs", []):
                all_attrs.append(at)

        self._definition_cache[product_key] = all_attrs
        return all_attrs
