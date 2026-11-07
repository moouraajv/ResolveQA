"""Event contract and replay references (RFC-0001 §3.2)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Optional

from .enums import CaseState, EventSource, EventType
from .errors import ContractValidationError
from .validators import (
    parse_enum,
    parse_optional_enum,
    require_int,
    require_non_empty_str,
    require_optional_non_empty_str,
    require_tuple_of_strings,
    require_utc_iso8601_timestamp,
)


@dataclass(frozen=True)
class ReplayRef:
    """Reference to the original case in a replay run (RFC-0001 §3.2, RNF-07)."""
    case_id: str
    original_ts: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "case_id", require_non_empty_str(self.case_id, "replay_of.case_id")
        )
        object.__setattr__(
            self,
            "original_ts",
            require_utc_iso8601_timestamp(self.original_ts, "replay_of.original_ts"),
        )

    def to_dict(self) -> dict[str, str]:
        return {
            "case_id": self.case_id,
            "original_ts": self.original_ts,
        }

    @classmethod
    def from_dict(cls, data: Any) -> ReplayRef:
        if not isinstance(data, dict):
            raise ContractValidationError(
                f"'replay_of' must be a dictionary, got {type(data).__name__}."
            )
        if "case_id" not in data or "original_ts" not in data:
            raise ContractValidationError(
                "Missing 'case_id' or 'original_ts' in 'replay_of'."
            )
        return cls(
            case_id=data["case_id"],
            original_ts=data["original_ts"],
        )


@dataclass(frozen=True)
class Event:
    """Append-only audit event for case progression (RFC-0001 §3.2, RNF-04)."""
    event_id: str
    case_id: str
    seq: int
    ts: str
    source: EventSource
    type: EventType
    from_state: Optional[CaseState] = None
    to_state: Optional[CaseState] = None
    reason: Optional[str] = None
    evidence_refs: tuple[str, ...] = ()
    replay_of: Optional[ReplayRef] = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "event_id", require_non_empty_str(self.event_id, "event_id"))
        object.__setattr__(self, "case_id", require_non_empty_str(self.case_id, "case_id"))
        object.__setattr__(self, "seq", require_int(self.seq, "seq", min_value=0))
        object.__setattr__(self, "ts", require_utc_iso8601_timestamp(self.ts, "ts"))
        object.__setattr__(self, "source", parse_enum(EventSource, self.source, "source"))
        object.__setattr__(self, "type", parse_enum(EventType, self.type, "type"))
        object.__setattr__(
            self, "from_state", parse_optional_enum(CaseState, self.from_state, "from_state")
        )
        object.__setattr__(
            self, "to_state", parse_optional_enum(CaseState, self.to_state, "to_state")
        )
        object.__setattr__(self, "reason", require_optional_non_empty_str(self.reason, "reason"))

        if isinstance(self.replay_of, dict):
            object.__setattr__(self, "replay_of", ReplayRef.from_dict(self.replay_of))
        elif self.replay_of is not None and not isinstance(self.replay_of, ReplayRef):
            raise ContractValidationError(
                f"'replay_of' must be a ReplayRef or dict, got {type(self.replay_of).__name__}."
            )

        object.__setattr__(
            self, "evidence_refs", require_tuple_of_strings(self.evidence_refs, "evidence_refs")
        )

        self.validate()

    def validate(self) -> None:
        """Validate Event invariants (RFC-0001 §3.2)."""
        if self.type == EventType.STATE_CHANGED:
            if self.from_state is None:
                raise ContractValidationError(
                    "StateChanged event requires a valid 'from_state'."
                )
            if self.to_state is None:
                raise ContractValidationError(
                    "StateChanged event requires a valid 'to_state'."
                )
            if self.from_state == self.to_state:
                raise ContractValidationError(
                    f"StateChanged event requires 'from_state' and 'to_state' to be different, got {self.from_state.value} for both."
                )
        else:
            if self.from_state is not None or self.to_state is not None:
                raise ContractValidationError(
                    f"Event of type '{self.type.value}' must not have 'from_state' or 'to_state'."
                )

        if self.type == EventType.REPLAY_STARTED and self.replay_of is None:
            raise ContractValidationError(
                "replay_of is required when event type is ReplayStarted."
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "case_id": self.case_id,
            "seq": self.seq,
            "ts": self.ts,
            "source": self.source.value,
            "type": self.type.value,
            "from_state": self.from_state.value if self.from_state is not None else None,
            "to_state": self.to_state.value if self.to_state is not None else None,
            "reason": self.reason,
            "evidence_refs": list(self.evidence_refs),
            "replay_of": self.replay_of.to_dict() if self.replay_of is not None else None,
        }

    def to_json(self, **kwargs: Any) -> str:
        return json.dumps(self.to_dict(), **kwargs)

    @classmethod
    def from_dict(cls, data: Any) -> Event:
        if not isinstance(data, dict):
            raise ContractValidationError(
                f"Payload must be a dictionary, got {type(data).__name__}."
            )

        required_fields = ["event_id", "case_id", "seq", "ts", "source", "type"]
        for field_name in required_fields:
            if field_name not in data:
                raise ContractValidationError(
                    f"Missing required field '{field_name}' in Event payload."
                )

        replay_data = data.get("replay_of")
        replay_of = ReplayRef.from_dict(replay_data) if isinstance(replay_data, dict) else replay_data

        return cls(
            event_id=data["event_id"],
            case_id=data["case_id"],
            seq=data["seq"],
            ts=data["ts"],
            source=data["source"],
            type=data["type"],
            from_state=data.get("from_state"),
            to_state=data.get("to_state"),
            reason=data.get("reason"),
            evidence_refs=tuple(data.get("evidence_refs", ())),
            replay_of=replay_of,
        )

    @classmethod
    def from_json(cls, json_str: str) -> Event:
        try:
            parsed = json.loads(json_str)
        except Exception as err:
            raise ContractValidationError(f"Invalid JSON string: {err}") from err
        return cls.from_dict(parsed)
