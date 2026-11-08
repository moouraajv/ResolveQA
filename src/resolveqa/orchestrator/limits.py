"""Read-only loader for RNF-03 limits from config/limits.json (RFC-0001 §5)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class OrchestratorLimits:
    """Immutable limit values consumed by the orchestrator."""

    max_fix_attempts: int
    max_llm_calls: int

    def __post_init__(self) -> None:
        if (
            not isinstance(self.max_fix_attempts, int)
            or isinstance(self.max_fix_attempts, bool)
            or self.max_fix_attempts <= 0
        ):
            raise ValueError(
                f"max_fix_attempts must be a positive int, got {self.max_fix_attempts!r}"
            )
        if (
            not isinstance(self.max_llm_calls, int)
            or isinstance(self.max_llm_calls, bool)
            or self.max_llm_calls <= 0
        ):
            raise ValueError(
                f"max_llm_calls must be a positive int, got {self.max_llm_calls!r}"
            )


def load_orchestrator_limits(limits_path: Path | str) -> OrchestratorLimits:
    """Load max_fix_attempts and max_llm_calls without mutating the config file."""
    path = Path(limits_path)
    if not path.is_file():
        raise FileNotFoundError(f"Limits configuration file not found: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Limits configuration must be a JSON object: {path}")
    if "max_fix_attempts" not in data or "max_llm_calls" not in data:
        raise ValueError(
            f"Limits configuration missing max_fix_attempts/max_llm_calls: {path}"
        )
    return OrchestratorLimits(
        max_fix_attempts=data["max_fix_attempts"],
        max_llm_calls=data["max_llm_calls"],
    )
