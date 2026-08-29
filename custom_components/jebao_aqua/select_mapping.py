"""Value mapping helpers for Jebao select entities."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any


OPTION_SLUG_PATTERN = re.compile(r"[a-z0-9_-]+")


class SelectValueMap:
    """Translate between Gizwits values and Home Assistant select options."""

    def __init__(
        self, value_to_option: dict[int, str], device_options: Sequence[str] = ()
    ) -> None:
        """Initialize an already validated value map."""
        self._value_to_option = value_to_option
        self._option_to_value = {
            option: value for value, option in value_to_option.items()
        }
        self._device_options = tuple(device_options)

    @classmethod
    def from_enum(
        cls, device_options: Sequence[str], option_slugs: Mapping[str, str]
    ) -> SelectValueMap:
        """Build a value map for a native Gizwits enum."""
        return cls(
            {
                index: option_slugs.get(device_option, device_option)
                for index, device_option in enumerate(device_options)
            },
            device_options,
        )

    @classmethod
    def from_config(cls, raw_value_map: Any) -> SelectValueMap:
        """Build and validate a configured uint8-to-option mapping."""
        if not isinstance(raw_value_map, Mapping) or not raw_value_map:
            raise ValueError("value map must be a non-empty object")

        value_to_option: dict[int, str] = {}
        used_options: set[str] = set()
        for raw_value, option in raw_value_map.items():
            if isinstance(raw_value, bool):
                raise ValueError("boolean value keys are not supported")
            try:
                value = int(raw_value)
            except (TypeError, ValueError) as err:
                raise ValueError(f"invalid integer value key: {raw_value!r}") from err

            if not 0 <= value <= 255:
                raise ValueError(f"value key is outside the uint8 range: {value}")
            if value in value_to_option:
                raise ValueError(f"duplicate integer value key: {value}")
            if not isinstance(option, str) or not option:
                raise ValueError(f"option for value {value} must be a non-empty string")
            if OPTION_SLUG_PATTERN.fullmatch(option) is None:
                raise ValueError(f"option is not a valid translation slug: {option!r}")
            if option in used_options:
                raise ValueError(f"duplicate option: {option!r}")

            value_to_option[value] = option
            used_options.add(option)

        return cls(dict(sorted(value_to_option.items())))

    @property
    def options(self) -> list[str]:
        """Return options in device-value order."""
        return list(self._value_to_option.values())

    def value_for_option(self, option: str) -> int | None:
        """Return the device value for a Home Assistant option."""
        return self._option_to_value.get(option)

    def option_for_value(self, raw_value: Any) -> str | None:
        """Return the option represented by a LAN or cloud status value."""
        value: int | None = None

        if isinstance(raw_value, bool):
            return None
        if isinstance(raw_value, (int, float)):
            value = int(raw_value)
        elif isinstance(raw_value, str):
            if raw_value in self._device_options:
                value = self._device_options.index(raw_value)
            elif raw_value in self._option_to_value:
                return raw_value
            else:
                try:
                    value = int(raw_value)
                except ValueError:
                    return None

        return self._value_to_option.get(value) if value is not None else None
