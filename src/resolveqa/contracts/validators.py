"""Internal validation utilities for contracts (RFC-0001 §3)."""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional, TypeVar

from .errors import ContractValidationError

E = TypeVar("E", bound=Enum)


def parse_enum(enum_cls: type[E], value: Any, field_name: str) -> E:
    """Parse a value into an enum member or raise ContractValidationError."""
    if isinstance(value, enum_cls):
        return value
    if isinstance(value, str):
        try:
            return enum_cls(value)
        except ValueError:
            pass
    allowed = [m.value for m in enum_cls]
    raise ContractValidationError(
        f"Invalid value {value!r} for '{field_name}'. Expected one of {allowed}."
    )


def parse_optional_enum(enum_cls: type[E], value: Any, field_name: str) -> Optional[E]:
    """Parse an optional enum member or raise ContractValidationError."""
    if value is None:
        return None
    return parse_enum(enum_cls, value, field_name)


def require_non_empty_str(value: Any, field_name: str) -> str:
    """Ensure value is a non-empty string without whitespace-only."""
    if value is None or not isinstance(value, str) or not value.strip():
        raise ContractValidationError(
            f"Field '{field_name}' must be a non-empty string, got {value!r}."
        )
    return value


def require_optional_non_empty_str(value: Any, field_name: str) -> Optional[str]:
    """Ensure value is None or a non-empty string."""
    if value is None:
        return None
    return require_non_empty_str(value, field_name)


def require_bool(value: Any, field_name: str) -> bool:
    """Ensure value is strictly a boolean, rejecting string or numeric coercions."""
    if not isinstance(value, bool):
        raise ContractValidationError(
            f"Field '{field_name}' must be a boolean, got {value!r} of type {type(value).__name__}."
        )
    return value


def require_int(value: Any, field_name: str, min_value: Optional[int] = None) -> int:
    """Ensure value is strictly an integer (excluding bool) and satisfies min_value."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise ContractValidationError(
            f"Field '{field_name}' must be an integer, got {value!r} of type {type(value).__name__}."
        )
    if min_value is not None and value < min_value:
        raise ContractValidationError(
            f"Field '{field_name}' must be >= {min_value}, got {value}."
        )
    return value


def require_utc_iso8601_timestamp(value: Any, field_name: str) -> str:
    """Ensure value is a valid ISO 8601 UTC timestamp string (with Z or +00:00)."""
    if not isinstance(value, str) or not value.strip():
        raise ContractValidationError(
            f"Field '{field_name}' must be a non-empty ISO 8601 UTC timestamp string, got {value!r}."
        )
    try:
        dt = datetime.fromisoformat(value)
    except Exception as err:
        raise ContractValidationError(
            f"Field '{field_name}' has invalid ISO 8601 timestamp {value!r}: {err}."
        ) from err

    if dt.tzinfo is None:
        raise ContractValidationError(
            f"Field '{field_name}' timestamp {value!r} must include a UTC timezone offset (e.g. 'Z' or '+00:00')."
        )

    if dt.utcoffset() != timezone.utc.utcoffset(dt):
        raise ContractValidationError(
            f"Field '{field_name}' timestamp {value!r} must be in UTC (+00:00 or 'Z'), got offset {dt.utcoffset()}."
        )

    return value
