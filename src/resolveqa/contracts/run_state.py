"""RunState contract and related sub-models (RFC-0001 §3.1)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Optional

from .enums import CaseState, ChannelType
from .errors import ContractValidationError
from .terminal_reason import (
    BlockedTerminalReason,
    InfraErrorTerminalReason,
    NeedsInfoTerminalReason,
    TerminalReason,
    validate_terminal_reason,
)
from .validators import (
    decode_json_dict,
    parse_enum,
    require_int,
    require_non_empty_str,
    require_optional_non_empty_str,
    require_tuple_of_strings,
    require_utc_iso8601_timestamp,
)


@dataclass(frozen=True)
class Attempts:
    """Execution attempts counters (RNF-03)."""
    fix: int = 0
    llm_calls: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "fix", require_int(self.fix, "fix", min_value=0))
        object.__setattr__(
            self, "llm_calls", require_int(self.llm_calls, "llm_calls", min_value=0)
        )

    def to_dict(self) -> dict[str, int]:
        return {
            "fix": self.fix,
            "llm_calls": self.llm_calls,
        }

    @classmethod
    def from_dict(cls, data: Any) -> Attempts:
        if not isinstance(data, dict):
            raise ContractValidationError(
                f"'attempts' must be a dictionary, got {type(data).__name__}."
            )
        return cls(
            fix=require_int(data.get("fix", 0), "attempts.fix", min_value=0),
            llm_calls=require_int(data.get("llm_calls", 0), "attempts.llm_calls", min_value=0),
        )


@dataclass(frozen=True)
class RunState:
    """Core state machine entity tracking a case run (RFC-0001 §3.1)."""
    case_id: str
    client_id: str
    repo_ref: str
    channel: ChannelType
    report_text: str
    state: CaseState
    created_at: str
    updated_at: str
    terminal_reason: Optional[TerminalReason] = None
    attempts: Attempts = field(default_factory=Attempts)
    base_revision: Optional[str] = None
    fix_revision: Optional[str] = None
    evidence_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "case_id", require_non_empty_str(self.case_id, "case_id"))
        object.__setattr__(self, "client_id", require_non_empty_str(self.client_id, "client_id"))
        object.__setattr__(self, "repo_ref", require_non_empty_str(self.repo_ref, "repo_ref"))
        object.__setattr__(self, "channel", parse_enum(ChannelType, self.channel, "channel"))
        object.__setattr__(self, "report_text", require_non_empty_str(self.report_text, "report_text"))
        parsed_state = parse_enum(CaseState, self.state, "state")
        object.__setattr__(self, "state", parsed_state)
        object.__setattr__(
            self, "created_at", require_utc_iso8601_timestamp(self.created_at, "created_at")
        )
        object.__setattr__(
            self, "updated_at", require_utc_iso8601_timestamp(self.updated_at, "updated_at")
        )
        validated_reason = validate_terminal_reason(parsed_state, self.terminal_reason)
        object.__setattr__(self, "terminal_reason", validated_reason)

        object.__setattr__(
            self, "base_revision", require_optional_non_empty_str(self.base_revision, "base_revision")
        )
        object.__setattr__(
            self, "fix_revision", require_optional_non_empty_str(self.fix_revision, "fix_revision")
        )

        if isinstance(self.attempts, dict):
            object.__setattr__(self, "attempts", Attempts.from_dict(self.attempts))
        elif not isinstance(self.attempts, Attempts):
            raise ContractValidationError(
                f"'attempts' must be an Attempts instance or dict, got {type(self.attempts).__name__}."
            )

        object.__setattr__(
            self, "evidence_ids", require_tuple_of_strings(self.evidence_ids, "evidence_ids")
        )

    def transition_to(
        self,
        new_state: CaseState | str,
        updated_at: str,
        terminal_reason: Optional[TerminalReason | dict[str, Any]] = None,
    ) -> RunState:
        """Return a brand new RunState instance in the new state without mutating self."""
        parsed_new_state = parse_enum(CaseState, new_state, "state")
        return RunState(
            case_id=self.case_id,
            client_id=self.client_id,
            repo_ref=self.repo_ref,
            channel=self.channel,
            report_text=self.report_text,
            state=parsed_new_state,
            created_at=self.created_at,
            updated_at=updated_at,
            terminal_reason=terminal_reason,
            attempts=self.attempts,
            base_revision=self.base_revision,
            fix_revision=self.fix_revision,
            evidence_ids=self.evidence_ids,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "client_id": self.client_id,
            "repo_ref": self.repo_ref,
            "channel": self.channel.value,
            "report_text": self.report_text,
            "state": self.state.value,
            "terminal_reason": (
                self.terminal_reason.to_dict()
                if self.terminal_reason is not None
                else None
            ),
            "attempts": self.attempts.to_dict(),
            "base_revision": self.base_revision,
            "fix_revision": self.fix_revision,
            "evidence_ids": list(self.evidence_ids),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    def to_json(self, **kwargs: Any) -> str:
        return json.dumps(self.to_dict(), **kwargs)

    @classmethod
    def from_dict(cls, data: Any) -> RunState:
        if not isinstance(data, dict):
            raise ContractValidationError(
                f"Payload must be a dictionary, got {type(data).__name__}."
            )

        required_fields = [
            "case_id",
            "client_id",
            "repo_ref",
            "channel",
            "report_text",
            "state",
            "created_at",
            "updated_at",
        ]
        for field_name in required_fields:
            if field_name not in data:
                raise ContractValidationError(
                    f"Missing required field '{field_name}' in RunState payload."
                )

        attempts_data = data.get("attempts", {})
        attempts = Attempts.from_dict(attempts_data) if isinstance(attempts_data, dict) else attempts_data

        return cls(
            case_id=data["case_id"],
            client_id=data["client_id"],
            repo_ref=data["repo_ref"],
            channel=data["channel"],
            report_text=data["report_text"],
            state=data["state"],
            created_at=data["created_at"],
            updated_at=data["updated_at"],
            terminal_reason=data.get("terminal_reason"),
            attempts=attempts,
            base_revision=data.get("base_revision"),
            fix_revision=data.get("fix_revision"),
            evidence_ids=data["evidence_ids"] if "evidence_ids" in data else (),
        )

    @classmethod
    def from_json(cls, json_str: str) -> RunState:
        data = decode_json_dict(json_str)
        return cls.from_dict(data)
