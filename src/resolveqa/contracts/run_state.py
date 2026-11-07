"""RunState contract and related sub-models (RFC-0001 §3.1)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Optional

from .enums import CaseState, ChannelType, TERMINAL_STATES
from .errors import ContractValidationError
from .validators import (
    parse_enum,
    require_int,
    require_non_empty_str,
    require_optional_non_empty_str,
    require_utc_iso8601_timestamp,
)


@dataclass
class Attempts:
    """Execution attempts counters (RNF-03)."""
    fix: int = 0
    llm_calls: int = 0

    def __post_init__(self) -> None:
        self.fix = require_int(self.fix, "fix", min_value=0)
        self.llm_calls = require_int(self.llm_calls, "llm_calls", min_value=0)

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


@dataclass
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
    terminal_reason: Optional[str] = None
    attempts: Attempts = field(default_factory=Attempts)
    base_revision: Optional[str] = None
    fix_revision: Optional[str] = None
    evidence_ids: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.case_id = require_non_empty_str(self.case_id, "case_id")
        self.client_id = require_non_empty_str(self.client_id, "client_id")
        self.repo_ref = require_non_empty_str(self.repo_ref, "repo_ref")
        self.channel = parse_enum(ChannelType, self.channel, "channel")
        self.report_text = require_non_empty_str(self.report_text, "report_text")
        self.state = parse_enum(CaseState, self.state, "state")
        self.created_at = require_utc_iso8601_timestamp(self.created_at, "created_at")
        self.updated_at = require_utc_iso8601_timestamp(self.updated_at, "updated_at")
        self.terminal_reason = require_optional_non_empty_str(
            self.terminal_reason, "terminal_reason"
        )
        self.base_revision = require_optional_non_empty_str(
            self.base_revision, "base_revision"
        )
        self.fix_revision = require_optional_non_empty_str(
            self.fix_revision, "fix_revision"
        )

        if isinstance(self.attempts, dict):
            self.attempts = Attempts.from_dict(self.attempts)
        elif not isinstance(self.attempts, Attempts):
            raise ContractValidationError(
                f"'attempts' must be an Attempts instance or dict, got {type(self.attempts).__name__}."
            )

        if not isinstance(self.evidence_ids, list):
            raise ContractValidationError(
                f"'evidence_ids' must be a list, got {type(self.evidence_ids).__name__}."
            )
        self.evidence_ids = [
            require_non_empty_str(eid, f"evidence_ids[{i}]")
            for i, eid in enumerate(self.evidence_ids)
        ]

        self.validate()

    def validate(self) -> None:
        """Validate RunState invariants."""
        if self.state in TERMINAL_STATES and self.state != CaseState.VERIFIED:
            if self.terminal_reason is None:
                raise ContractValidationError(
                    f"Terminal state '{self.state.value}' different from verified requires terminal_reason."
                )

    def transition_to(
        self,
        new_state: CaseState | str,
        updated_at: str,
        terminal_reason: Optional[str] = None,
    ) -> RunState:
        """Return an updated RunState in a new state with invariants validated."""
        parsed_new_state = parse_enum(CaseState, new_state, "state")
        reason_to_use = terminal_reason if terminal_reason is not None else self.terminal_reason
        return RunState(
            case_id=self.case_id,
            client_id=self.client_id,
            repo_ref=self.repo_ref,
            channel=self.channel,
            report_text=self.report_text,
            state=parsed_new_state,
            created_at=self.created_at,
            updated_at=updated_at,
            terminal_reason=reason_to_use,
            attempts=Attempts(fix=self.attempts.fix, llm_calls=self.attempts.llm_calls),
            base_revision=self.base_revision,
            fix_revision=self.fix_revision,
            evidence_ids=list(self.evidence_ids),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "client_id": self.client_id,
            "repo_ref": self.repo_ref,
            "channel": self.channel.value,
            "report_text": self.report_text,
            "state": self.state.value,
            "terminal_reason": self.terminal_reason,
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
            evidence_ids=data.get("evidence_ids", []),
        )

    @classmethod
    def from_json(cls, json_str: str) -> RunState:
        try:
            parsed = json.loads(json_str)
        except Exception as err:
            raise ContractValidationError(f"Invalid JSON string: {err}") from err
        return cls.from_dict(parsed)
