"""Internal validation utilities for contracts (RFC-0001 §3)."""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional, TypeVar

from .enums import BlockedReason, CaseState, TERMINAL_STATES
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


def require_tuple_of_strings(items: Any, field_name: str) -> tuple[str, ...]:
    """Validate and convert a sequence into an immutable tuple of non-empty strings."""
    if not isinstance(items, (list, tuple)):
        raise ContractValidationError(
            f"Field '{field_name}' must be a sequence of strings, got {type(items).__name__}."
        )
    return tuple(require_non_empty_str(item, f"{field_name}[{i}]") for i, item in enumerate(items))


def validate_terminal_reason(state: CaseState, terminal_reason: Optional[str]) -> Optional[str]:
    """Validate terminal_reason structured invariants by state (RFC-0001 §4)."""
    if state == CaseState.VERIFIED:
        if terminal_reason is not None:
            raise ContractValidationError("Verified terminal state must not have a terminal_reason.")
        return None

    if state not in TERMINAL_STATES:
        if terminal_reason is not None:
            raise ContractValidationError(
                f"Non-terminal state '{state.value}' must not have a terminal_reason."
            )
        return None

    if state == CaseState.NEEDS_INFO:
        if terminal_reason is None or not isinstance(terminal_reason, str) or not terminal_reason.strip():
            raise ContractValidationError(
                "Terminal state 'needs_info' requires a non-empty question as terminal_reason."
            )
        return terminal_reason

    if state == CaseState.INFRA_ERROR:
        if terminal_reason is None or not isinstance(terminal_reason, str) or not terminal_reason.strip():
            raise ContractValidationError(
                "Terminal state 'infra_error' requires a non-empty detail as terminal_reason."
            )
        return terminal_reason

    if state == CaseState.BLOCKED:
        if terminal_reason is None or not isinstance(terminal_reason, str) or not terminal_reason.strip():
            raise ContractValidationError(
                "Terminal state 'blocked' requires a non-empty terminal_reason."
            )
        parts = terminal_reason.split(":", 1)
        code = parts[0].strip()
        valid_codes = {r.value for r in BlockedReason}
        if code not in valid_codes:
            raise ContractValidationError(
                f"Blocked terminal_reason must specify one of {sorted(valid_codes)}, got {code!r}."
            )
        if len(parts) > 1:
            detail = parts[1].strip()
            if not detail:
                raise ContractValidationError(
                    "Optional detail following ':' in blocked terminal_reason must not be empty."
                )
        return terminal_reason

    return terminal_reason


