"""Structured terminal reasons for ResolveQA contracts (RFC-0001 §3, §4)."""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Optional, Union

from .enums import BlockedReason, CaseState, TERMINAL_STATES
from .errors import ContractValidationError
from .validators import decode_json_dict, parse_enum, require_non_empty_str


@dataclass(frozen=True)
class BlockedTerminalReason:
    """Structured terminal reason for CaseState.BLOCKED."""
    code: BlockedReason
    detail: Optional[str] = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "code", parse_enum(BlockedReason, self.code, "code"))
        if self.detail is not None:
            if not isinstance(self.detail, str) or not self.detail.strip():
                raise ContractValidationError(
                    f"BlockedTerminalReason detail must be a non-empty string if provided, got {self.detail!r}."
                )

    def to_dict(self) -> dict[str, Any]:
        res: dict[str, Any] = {"code": self.code.value}
        if self.detail is not None:
            res["detail"] = self.detail
        return res

    def to_json(self, **kwargs: Any) -> str:
        return json.dumps(self.to_dict(), **kwargs)

    @classmethod
    def from_dict(cls, data: Any) -> BlockedTerminalReason:
        if not isinstance(data, dict):
            raise ContractValidationError(
                f"BlockedTerminalReason payload must be a dict, got {type(data).__name__}."
            )
        allowed_keys = {"code", "detail"}
        extra_keys = set(data.keys()) - allowed_keys
        if extra_keys:
            raise ContractValidationError(
                f"BlockedTerminalReason payload contains unexpected keys: {sorted(extra_keys)}."
            )
        if "code" not in data:
            raise ContractValidationError("Missing required field 'code' in BlockedTerminalReason.")
        return cls(code=data["code"], detail=data.get("detail"))

    @classmethod
    def from_json(cls, json_str: str) -> BlockedTerminalReason:
        data = decode_json_dict(json_str)
        return cls.from_dict(data)


@dataclass(frozen=True)
class NeedsInfoTerminalReason:
    """Structured terminal reason for CaseState.NEEDS_INFO."""
    question_to_support: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "question_to_support",
            require_non_empty_str(self.question_to_support, "question_to_support"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {"question_to_support": self.question_to_support}

    def to_json(self, **kwargs: Any) -> str:
        return json.dumps(self.to_dict(), **kwargs)

    @classmethod
    def from_dict(cls, data: Any) -> NeedsInfoTerminalReason:
        if not isinstance(data, dict):
            raise ContractValidationError(
                f"NeedsInfoTerminalReason payload must be a dict, got {type(data).__name__}."
            )
        allowed_keys = {"question_to_support"}
        extra_keys = set(data.keys()) - allowed_keys
        if extra_keys:
            raise ContractValidationError(
                f"NeedsInfoTerminalReason payload contains unexpected keys: {sorted(extra_keys)}."
            )
        if "question_to_support" not in data:
            raise ContractValidationError(
                "Missing required field 'question_to_support' in NeedsInfoTerminalReason."
            )
        return cls(question_to_support=data["question_to_support"])

    @classmethod
    def from_json(cls, json_str: str) -> NeedsInfoTerminalReason:
        data = decode_json_dict(json_str)
        return cls.from_dict(data)


@dataclass(frozen=True)
class InfraErrorTerminalReason:
    """Structured terminal reason for CaseState.INFRA_ERROR."""
    detail: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "detail", require_non_empty_str(self.detail, "detail"))

    def to_dict(self) -> dict[str, Any]:
        return {"detail": self.detail}

    def to_json(self, **kwargs: Any) -> str:
        return json.dumps(self.to_dict(), **kwargs)

    @classmethod
    def from_dict(cls, data: Any) -> InfraErrorTerminalReason:
        if not isinstance(data, dict):
            raise ContractValidationError(
                f"InfraErrorTerminalReason payload must be a dict, got {type(data).__name__}."
            )
        allowed_keys = {"detail"}
        extra_keys = set(data.keys()) - allowed_keys
        if extra_keys:
            raise ContractValidationError(
                f"InfraErrorTerminalReason payload contains unexpected keys: {sorted(extra_keys)}."
            )
        if "detail" not in data:
            raise ContractValidationError(
                "Missing required field 'detail' in InfraErrorTerminalReason."
            )
        return cls(detail=data["detail"])

    @classmethod
    def from_json(cls, json_str: str) -> InfraErrorTerminalReason:
        data = decode_json_dict(json_str)
        return cls.from_dict(data)


TerminalReason = Union[BlockedTerminalReason, NeedsInfoTerminalReason, InfraErrorTerminalReason]


def validate_terminal_reason(state: CaseState, terminal_reason: Any) -> Optional[TerminalReason]:
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

    if terminal_reason is None:
        raise ContractValidationError(
            f"Terminal state '{state.value}' requires a structured terminal_reason."
        )

    if isinstance(terminal_reason, str):
        raise ContractValidationError(
            f"terminal_reason for state '{state.value}' must be a structured object, not a string: {terminal_reason!r}."
        )

    if state == CaseState.BLOCKED:
        if isinstance(terminal_reason, BlockedTerminalReason):
            return terminal_reason
        if isinstance(terminal_reason, dict):
            return BlockedTerminalReason.from_dict(terminal_reason)
        raise ContractValidationError(
            f"Terminal state 'blocked' requires BlockedTerminalReason, got {type(terminal_reason).__name__}."
        )

    if state == CaseState.NEEDS_INFO:
        if isinstance(terminal_reason, NeedsInfoTerminalReason):
            return terminal_reason
        if isinstance(terminal_reason, dict):
            return NeedsInfoTerminalReason.from_dict(terminal_reason)
        raise ContractValidationError(
            f"Terminal state 'needs_info' requires NeedsInfoTerminalReason, got {type(terminal_reason).__name__}."
        )

    if state == CaseState.INFRA_ERROR:
        if isinstance(terminal_reason, InfraErrorTerminalReason):
            return terminal_reason
        if isinstance(terminal_reason, dict):
            return InfraErrorTerminalReason.from_dict(terminal_reason)
        raise ContractValidationError(
            f"Terminal state 'infra_error' requires InfraErrorTerminalReason, got {type(terminal_reason).__name__}."
        )

    raise ContractValidationError(f"Unhandled terminal state: {state}")
