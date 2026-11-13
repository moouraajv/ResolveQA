"""Case store protocol shared by ephemeral, file, and DynamoDB backends."""

from __future__ import annotations

from typing import Optional, Protocol, runtime_checkable

from resolveqa.contracts import RunState


@runtime_checkable
class CaseStore(Protocol):
    """Durable or ephemeral map of case_id -> RunState."""

    def put(self, case: RunState) -> None:
        """Persist or replace a case snapshot."""

    def get(self, case_id: str) -> Optional[RunState]:
        """Lookup a case by id."""

    def list_cases(self) -> list[RunState]:
        """Return all known cases (newest-first preferred)."""
