"""Evidence contract format (RFC-0001 §3.4)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Optional

from .enums import EvidenceKind
from .errors import ContractValidationError
from .validators import (
    parse_enum,
    require_bool,
    require_non_empty_str,
    require_optional_non_empty_str,
    require_utc_iso8601_timestamp,
)


@dataclass(frozen=True)
class Evidence:
    """Stored artifact descriptor linked to a case run (RFC-0001 §3.4, RNF-04)."""
    evidence_id: str
    case_id: str
    kind: EvidenceKind
    path: str
    sha256: str
    created_at: str
    revision: Optional[str] = None
    simulated: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "evidence_id", require_non_empty_str(self.evidence_id, "evidence_id")
        )
        object.__setattr__(self, "case_id", require_non_empty_str(self.case_id, "case_id"))
        object.__setattr__(self, "kind", parse_enum(EvidenceKind, self.kind, "kind"))
        object.__setattr__(self, "path", require_non_empty_str(self.path, "path"))
        object.__setattr__(self, "sha256", require_non_empty_str(self.sha256, "sha256"))
        object.__setattr__(
            self, "created_at", require_utc_iso8601_timestamp(self.created_at, "created_at")
        )
        object.__setattr__(
            self, "revision", require_optional_non_empty_str(self.revision, "revision")
        )
        object.__setattr__(self, "simulated", require_bool(self.simulated, "simulated"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "case_id": self.case_id,
            "kind": self.kind.value,
            "path": self.path,
            "sha256": self.sha256,
            "revision": self.revision,
            "created_at": self.created_at,
            "simulated": self.simulated,
        }

    def to_json(self, **kwargs: Any) -> str:
        return json.dumps(self.to_dict(), **kwargs)

    @classmethod
    def from_dict(cls, data: Any) -> Evidence:
        if not isinstance(data, dict):
            raise ContractValidationError(
                f"Payload must be a dictionary, got {type(data).__name__}."
            )

        required_fields = ["evidence_id", "case_id", "kind", "path", "sha256", "created_at"]
        for field_name in required_fields:
            if field_name not in data:
                raise ContractValidationError(
                    f"Missing required field '{field_name}' in Evidence payload."
                )

        return cls(
            evidence_id=data["evidence_id"],
            case_id=data["case_id"],
            kind=data["kind"],
            path=data["path"],
            sha256=data["sha256"],
            created_at=data["created_at"],
            revision=data.get("revision"),
            simulated=data.get("simulated", False),
        )

    @classmethod
    def from_json(cls, json_str: str) -> Evidence:
        try:
            parsed = json.loads(json_str)
        except Exception as err:
            raise ContractValidationError(f"Invalid JSON string: {err}") from err
        return cls.from_dict(parsed)
