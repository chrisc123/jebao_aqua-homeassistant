from dataclasses import dataclass
from typing import Literal, TypedDict


@dataclass
class AttributePosition:
    byte_offset: int
    bit_offset: int
    len: int
    unit: Literal["bit", "byte"]


@dataclass
class UnitSpec:
    """Specs for numeric attribute types"""

    min: int
    max: int
    ratio: int
    addition: int


class AttributeDefinition(TypedDict):
    """Full attribute definition matching JSON schema"""

    id: int
    name: str
    display_name: str
    type: Literal["status", "status_writable", "alert", "fault"]
    data_type: Literal["bool", "enum", "uint8", "binary"]
    position: AttributePosition
    desc: str
    enum: list[str] | None  # Only present for enum types
    uint_spec: UnitSpec | None  # Only present for uint8 types


class DeviceDefinition(TypedDict):
    """Top level device definition matching JSON schema"""

    name: str
    product_key: str
    packetVersion: str
    protocolType: str
    entities: list[dict[str, str | list[AttributeDefinition]]]
