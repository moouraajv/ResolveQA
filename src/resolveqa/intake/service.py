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
    TERMINAL_STATES,
)

from .store import EphemeralCaseStore

# Happy-path demo progression for operator "advance" controls (pitch / Quadro).
HAPPY_PATH_NEXT: dict[CaseState, CaseState] = {
    CaseState.CREATED: CaseState.TRIAGING,
    CaseState.TRIAGING: CaseState.TRIAGED,
    CaseState.TRIAGED: CaseState.REPRODUCING,
    CaseState.REPRODUCING: CaseState.REPRODUCED,
    CaseState.REPRODUCED: CaseState.FIXING,
    CaseState.FIXING: CaseState.FIXED,
    CaseState.FIXED: CaseState.VERIFYING,
    CaseState.VERIFYING: CaseState.VERIFIED,
}


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

    def advance(
        self,
        case_id: str,
        *,
        to_state: CaseState | str | None = None,
    ) -> tuple[RunState, CaseState]:
        """Advance a case along the happy path (or to an explicit state) and persist it.

        Returns ``(updated_case, previous_state)``. This is an operator/demo control:
        it updates the ephemeral store so the Quadro stays synchronized with the API.
        It does not run triage/fix/verification stages.
        """
        case = self.get(case_id)
        if case is None:
            raise ContractValidationError(f"case_id not found: {case_id}")
        previous = case.state
        if previous in TERMINAL_STATES:
            raise ContractValidationError(
                f"case {case_id} is already terminal ({previous.value})"
            )
        if to_state is None:
            nxt = HAPPY_PATH_NEXT.get(previous)
            if nxt is None:
                raise ContractValidationError(
                    f"no happy-path advance from state {previous.value}"
                )
            target = nxt
        else:
            if isinstance(to_state, str):
                try:
                    target = CaseState(to_state.strip())
                except ValueError as err:
                    raise ContractValidationError(str(err)) from err
            else:
                target = to_state
            if target == previous:
                raise ContractValidationError("to_state must differ from current state")
        updated = case.transition_to(target, updated_at=utc_now_iso())
        self.store.put(updated)
        return updated, previous


# Structural check against the frozen contracts protocol.
_: type[IntakeStage] = Intake
