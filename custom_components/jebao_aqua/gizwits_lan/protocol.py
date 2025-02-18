# gizwits_lan/protocol.py

import logging
from .errors import ProtocolError
from typing import Tuple


logger = logging.getLogger(__name__)

def encode_varlen(n: int) -> bytes:
    """
    Encode integer 'n' into Gizwits' variable-length format.
    If n < 128 => single byte, else multiple 7-bit chunks with top bit=1 for continuation.
    """
    if n < 128:
        return bytes([n])
    out = []
    while True:
        b7 = n & 0x7F
        n >>= 7
        if n > 0:
            out.append(0x80 | b7)
        else:
            out.append(b7)
            break
    return bytes(out)

def build_prefix_and_command(cmd: bytes, payload: bytes = b"") -> bytes:
    """
    Build a Gizwits packet:
      [00 00 00 03] + [varlen length] + [0x00 flag] + [cmd(2 bytes)] + [payload].
    length = 1(flag) + 2(cmd) + len(payload).
    """
    version = b"\x00\x00\x00\x03"
    body_len = 1 + 2 + len(payload)  # flag + cmd + payload
    length_bytes = encode_varlen(body_len)
    flag = b"\x00"  # we set 0, the device might respond with 0x01 or something
    return version + length_bytes + flag + cmd + payload


def parse_response_prefix(data: bytes) -> Tuple[bytes, bytes]:
    """
    Parse the Gizwits response prefix, returning (cmd, payload).
    data format:
      00 00 00 03 <varlen> <flag> <cmd(2 bytes)> <payload...>
    """
    if not data.startswith(b"\x00\x00\x00\x03"):
        raise ProtocolError("Response missing 00 00 00 03 prefix.")
    idx = 4

    # decode varlen
    length_val = 0
    shift = 0
    while True:
        if idx >= len(data):
            raise ProtocolError("Incomplete varlen in parse_response_prefix.")
        b_i = data[idx]
        idx += 1
        length_val |= (b_i & 0x7F) << shift
        shift += 7
        if (b_i & 0x80) == 0:
            break

    # read flag
    if idx + 1 + 2 > len(data):
        raise ProtocolError("Not enough bytes for flag+cmd.")
    flag = data[idx] # Flag is usually 0 but seems to be set to 1 for unsolicited status updates
    idx += 1

    # read cmd
    cmd = data[idx:idx+2]
    idx += 2

    payload = data[idx:]
    return cmd, payload

##########################################################################
# Functions for partial-update "set bits"
##########################################################################
def set_swapped_bits(av: bytearray, bit_offset: int, length_bits: int, value: int):
    """
    "Swapped" approach for the first 2 bytes => av[0]=[15..8], av[1]=[7..0].
    """
    av16 = (av[0] << 8) | av[1]
    mask = (1 << length_bits) - 1
    av16 &= ~(mask << bit_offset)
    av16 |= ((value & mask) << bit_offset)
    av[0] = (av16 >> 8) & 0xFF
    av[1] = av16 & 0xFF

def set_normal_bits_in_first_16(av: bytearray, bit_offset: int, length_bits: int, value: int):
    """
    Normal approach => av[0]=[7..0], av[1]=[15..8].
    """
    av16 = av[0] | (av[1] << 8)
    mask = (1 << length_bits) - 1
    av16 &= ~(mask << bit_offset)
    av16 |= ((value & mask) << bit_offset)
    av[0] = av16 & 0xFF
    av[1] = (av16 >> 8) & 0xFF

def set_bits_in_byte(av: bytearray, byte_index: int, bit_offset: int, bit_length: int, value: int):
    mask = (1 << bit_length) - 1
    av[byte_index] &= ~(mask << bit_offset)
    av[byte_index] |= ((value & mask) << bit_offset)
