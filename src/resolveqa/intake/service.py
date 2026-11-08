"""Intake stage: ReportInput -> frozen RunState in state created (RFC-0001 §3.3, RF-01)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from resolveqa.contracts import (
    CaseState,
    ContractValidationError,
    IntakeStage,
    ReportInput,
    RunState,
)

from .store import EphemeralCaseStore


def utc_now_iso() -> str:
    """Return current UTC time as ISO 8601 with explicit Z suffix."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def new_case_id() -> str:
    """Generate a unique opaque case identifier."""
    return f"case-{uuid.uuid4().hex}"


class Intake:
    """Creates immutable RunState cases and records them in an ephemeral store."""

    def __init__(self, store: EphemeralCaseStore | None = None) -> None:
        self.store = store if store is not None else EphemeralCaseStore()

    def create(self, report: ReportInput) -> RunState:
        """Create a new case in `created` with a unique case_id (IntakeStage)."""
        if not isinstance(report, ReportInput):
            raise ContractValidationError(
                f"Intake.create expects ReportInput, got {type(report).__name__}."
            )

        timestamp = utc_now_iso()
        case = RunState(
            case_id=new_case_id(),
            client_id=report.client_id,
            repo_ref=report.repo_ref,
            channel=report.channel,
            report_text=report.report_text,
            state=CaseState.CREATED,
            created_at=timestamp,
            updated_at=timestamp,
        )
        self.store.put(case)
        return case

    def get(self, case_id: str) -> RunState | None:
        """Lookup a previously created case by id (ephemeral store)."""
        if not isinstance(case_id, str) or not case_id.strip():
            return None
        return self.store.get(case_id.strip())


# Structural check against the frozen contracts protocol.
_: type[IntakeStage] = Intake
