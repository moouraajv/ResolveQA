"""Deterministic orchestrator state machine (RFC-0001 §2.2, §4, §5; issue #6)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from resolveqa.contracts import (
    Attempts,
    BlockedReason,
    BlockedTerminalReason,
    CaseState,
    Event,
    EventSource,
    EventType,
    FixStage,
    InfraErrorTerminalReason,
    NeedsInfo,
    NeedsInfoTerminalReason,
    Patch,
    ReproductionStage,
    ReproOutcome,
    ReproResult,
    RunState,
    TERMINAL_STATES,
    TerminalReason,
    TriageRecord,
    TriageStage,
    Verdict,
    VerdictResult,
    VerificationStage,
)
from resolveqa.orchestrator.limits import OrchestratorLimits, load_orchestrator_limits
from resolveqa.store.events import EventStore, reason_for_terminal

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_LIMITS_PATH = REPO_ROOT / "config" / "limits.json"

# Operational failures become infra_error. Programming bugs stay explicit.
_OPERATIONAL_ERRORS = (OSError, TimeoutError)


@dataclass(frozen=True)
class _StageFailure:
    """Private marker: operational/limit failure already recorded as a terminal RunState."""

    case: RunState


def utc_now_iso() -> str:
    """Return current UTC time as ISO 8601 with explicit Z suffix."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _is_llm_limit_exceeded(exc: BaseException) -> bool:
    """Duck-type LLM limit failures without importing the LLM adapter."""
    if type(exc).__name__ == "LLMLimitExceededError":
        return True
    return getattr(exc, "reason", None) == BlockedReason.LIMIT_EXCEEDED.value


class OrchestratorError(RuntimeError):
    """Raised when the orchestrator cannot progress a case safely."""


class Orchestrator:
    """Calls injectable stage protocols, applies limits, and appends events."""

    def __init__(
        self,
        triage: TriageStage,
        reproduction: ReproductionStage,
        fix: FixStage,
        verification: VerificationStage,
        store: EventStore,
        limits: OrchestratorLimits | None = None,
        limits_path: Path | str | None = None,
        clock: Callable[[], str] | None = None,
        llm_calls_getter: Callable[[RunState], int] | None = None,
    ) -> None:
        self.triage = triage
        self.reproduction = reproduction
        self.fix = fix
        self.verification = verification
        self.store = store
        if limits is not None:
            self.limits = limits
        else:
            path = Path(limits_path) if limits_path is not None else DEFAULT_LIMITS_PATH
            self.limits = load_orchestrator_limits(path)
        self.clock = clock if clock is not None else utc_now_iso
        self.llm_calls_getter = llm_calls_getter

    def run(self, case: RunState) -> RunState:
        """Drive a case from `created` to a terminal state with append-only events."""
        if not isinstance(case, RunState):
            raise OrchestratorError(
                f"Orchestrator.run expects RunState, got {type(case).__name__}"
            )
        if case.state in TERMINAL_STATES:
            return case
        if case.state != CaseState.CREATED:
            raise OrchestratorError(
                f"Orchestrator.run expects state 'created', got {case.state.value}"
            )

        self._assert_history_compatible(case)

        current = case
        self._ensure_case_created(current)

        current = self._ensure_llm_budget(current)
        if current.state in TERMINAL_STATES:
            return current

        current = self._transition(current, CaseState.TRIAGING, source=EventSource.ORCHESTRATOR)
        triage_raw = self._call_stage(
            current,
            source=EventSource.TRIAGE,
            call=lambda: self.triage.run(current),
        )
        triage_result = self._require_stage_result(
            triage_raw,
            TriageRecord,
            NeedsInfo,
            stage="TriageStage.run",
        )
        if isinstance(triage_result, _StageFailure):
            return triage_result.case
        if isinstance(triage_result, NeedsInfo):
            return self._transition(
                current,
                CaseState.NEEDS_INFO,
                source=EventSource.TRIAGE,
                terminal_reason=NeedsInfoTerminalReason(
                    question_to_support=triage_result.question_to_support
                ),
            )

        current = self._transition(
            current,
            CaseState.TRIAGED,
            source=EventSource.TRIAGE,
        )
        current = self._ensure_llm_budget(current)
        if current.state in TERMINAL_STATES:
            return current

        current = self._transition(
            current,
            CaseState.REPRODUCING,
            source=EventSource.ORCHESTRATOR,
        )
        repro_raw = self._call_stage(
            current,
            source=EventSource.REPRODUCTION,
            call=lambda: self.reproduction.run(current, triage_result),
        )
        repro = self._require_stage_result(
            repro_raw,
            ReproResult,
            stage="ReproductionStage.run",
        )
        if isinstance(repro, _StageFailure):
            return repro.case

        if repro.outcome == ReproOutcome.ENV_ERROR:
            return self._transition(
                current,
                CaseState.INFRA_ERROR,
                source=EventSource.REPRODUCTION,
                terminal_reason=InfraErrorTerminalReason(
                    detail=repro.failing_assertion or repro.log_ref or "environment error"
                ),
            )
        if repro.outcome != ReproOutcome.RED_ON_ASSERTION:
            return self._transition(
                current,
                CaseState.BLOCKED,
                source=EventSource.REPRODUCTION,
                terminal_reason=BlockedTerminalReason(code=BlockedReason.NOT_REPRODUCED),
            )

        current = self._transition(
            current,
            CaseState.REPRODUCED,
            source=EventSource.REPRODUCTION,
        )

        while True:
            current = self._ensure_llm_budget(current)
            if current.state in TERMINAL_STATES:
                return current

            current = self._ensure_fix_budget(current)
            if current.state in TERMINAL_STATES:
                return current

            current = self._transition(
                current,
                CaseState.FIXING,
                source=EventSource.ORCHESTRATOR,
            )
            # Count every attempted Fix execution (success or rejection) via new Attempts.
            current = self._with_attempts(
                current,
                Attempts(
                    fix=current.attempts.fix + 1,
                    llm_calls=current.attempts.llm_calls,
                ),
            )

            patch_raw = self._call_stage(
                current,
                source=EventSource.FIX,
                call=lambda: self.fix.run(current, triage_result, repro),
            )
            patch = self._require_stage_result(
                patch_raw,
                Patch,
                stage="FixStage.run",
            )
            if isinstance(patch, _StageFailure):
                return patch.case

            current = self._ensure_llm_budget(current)
            if current.state in TERMINAL_STATES:
                return current

            current = self._transition(
                current,
                CaseState.FIXED,
                source=EventSource.FIX,
            )
            current = self._transition(
                current,
                CaseState.VERIFYING,
                source=EventSource.ORCHESTRATOR,
            )
            verdict_raw = self._call_stage(
                current,
                source=EventSource.VERIFICATION,
                call=lambda: self.verification.run(current, repro, patch),
            )
            verdict = self._require_stage_result(
                verdict_raw,
                Verdict,
                stage="VerificationStage.run",
            )
            if isinstance(verdict, _StageFailure):
                return verdict.case

            if verdict.result == VerdictResult.ENV_ERROR:
                detail = (
                    verdict.reasons[0]
                    if verdict.reasons
                    else "verification environment error"
                )
                return self._transition(
                    current,
                    CaseState.INFRA_ERROR,
                    source=EventSource.VERIFICATION,
                    terminal_reason=InfraErrorTerminalReason(detail=detail),
                )

            if verdict.result == VerdictResult.VERIFIED:
                return self._complete_verified(current, verdict)

            if verdict.result != VerdictResult.REJECTED:
                raise OrchestratorError(
                    f"Unsupported verdict result: {verdict.result!r}"
                )

            # RFC §2.2: rejected with remaining budget returns to Fix (VERIFYING → FIXING).
            # Budget is re-checked at the top of the loop before the next Fix.

    def _assert_history_compatible(self, case: RunState) -> None:
        """Refuse stale CREATED inputs against an advanced event history before appending."""
        existing = self.store.list_events(case.case_id)
        if not existing:
            return
        rebuilt = self.store.reconstruct_state(case)
        if rebuilt.state != case.state:
            raise OrchestratorError(
                "Stale or incompatible event history for case "
                f"{case.case_id}: input_state={case.state.value}, "
                f"history_state={rebuilt.state.value}"
            )

    def _ensure_case_created(self, case: RunState) -> None:
        existing = self.store.list_events(case.case_id)
        if existing:
            return
        self.store.append(
            Event(
                event_id=self._new_event_id(),
                case_id=case.case_id,
                seq=0,
                ts=case.created_at,
                source=EventSource.INTAKE,
                type=EventType.CASE_CREATED,
            )
        )

    def _sync_llm_calls(self, case: RunState) -> RunState:
        reported = case.attempts.llm_calls
        if self.llm_calls_getter is not None:
            getter_value = int(self.llm_calls_getter(case))
            if getter_value < 0:
                raise OrchestratorError(
                    f"llm_calls_getter returned negative value: {getter_value}"
                )
            reported = max(reported, getter_value)
        if reported == case.attempts.llm_calls:
            return case
        return self._with_attempts(
            case,
            Attempts(fix=case.attempts.fix, llm_calls=reported),
        )

    def _ensure_llm_budget(self, case: RunState) -> RunState:
        synced = self._sync_llm_calls(case)
        if synced.attempts.llm_calls < self.limits.max_llm_calls:
            return synced
        return self._block_limit_exceeded(
            synced,
            detail=(
                f"max_llm_calls={self.limits.max_llm_calls} already reached "
                f"(attempts.llm_calls={synced.attempts.llm_calls})"
            ),
        )

    def _ensure_fix_budget(self, case: RunState) -> RunState:
        if case.attempts.fix < self.limits.max_fix_attempts:
            return case
        return self._block_limit_exceeded(
            case,
            detail=(
                f"max_fix_attempts={self.limits.max_fix_attempts} already reached "
                f"(attempts.fix={case.attempts.fix})"
            ),
        )

    def _call_stage(
        self,
        case: RunState,
        *,
        source: EventSource,
        call: Callable[[], object],
    ) -> object | _StageFailure:
        """Invoke a stage; wrap operational/limit terminals, re-raise programming errors."""
        try:
            return call()
        except _OPERATIONAL_ERRORS as err:
            return _StageFailure(
                self._transition(
                    case,
                    CaseState.INFRA_ERROR,
                    source=source,
                    terminal_reason=InfraErrorTerminalReason(
                        detail=str(err) or type(err).__name__
                    ),
                )
            )
        except Exception as err:
            if _is_llm_limit_exceeded(err):
                synced = self._sync_llm_calls(case)
                return _StageFailure(
                    self._block_limit_exceeded(
                        synced,
                        detail=str(err) or "limit_exceeded",
                    )
                )
            raise

    @staticmethod
    def _require_stage_result(
        value: object | _StageFailure,
        *allowed: type,
        stage: str,
    ) -> object | _StageFailure:
        """Accept only an internal failure wrapper or the exact external stage types."""
        if isinstance(value, _StageFailure):
            return value
        if isinstance(value, allowed):
            return value
        raise OrchestratorError(
            f"{stage} returned unsupported type {type(value).__name__}; "
            f"expected one of {[cls.__name__ for cls in allowed]}"
        )

    def _block_limit_exceeded(self, case: RunState, detail: str) -> RunState:
        ts = self.clock()
        seq = self.store.next_seq(case.case_id)
        self.store.append(
            Event(
                event_id=self._new_event_id(),
                case_id=case.case_id,
                seq=seq,
                ts=ts,
                source=EventSource.ORCHESTRATOR,
                type=EventType.LIMIT_REACHED,
                reason=BlockedReason.LIMIT_EXCEEDED.value,
            )
        )
        return self._transition(
            case,
            CaseState.BLOCKED,
            source=EventSource.ORCHESTRATOR,
            terminal_reason=BlockedTerminalReason(
                code=BlockedReason.LIMIT_EXCEEDED,
                detail=detail,
            ),
        )

    def _complete_verified(self, case: RunState, verdict: Verdict) -> RunState:
        ts = self.clock()
        from_state = case.state
        verified = RunState(
            case_id=case.case_id,
            client_id=case.client_id,
            repo_ref=case.repo_ref,
            channel=case.channel,
            report_text=case.report_text,
            state=CaseState.VERIFIED,
            created_at=case.created_at,
            updated_at=ts,
            terminal_reason=None,
            attempts=case.attempts,
            base_revision=verdict.base_revision,
            fix_revision=verdict.fix_revision,
            evidence_ids=case.evidence_ids,
        )
        self.store.append(
            Event(
                event_id=self._new_event_id(),
                case_id=case.case_id,
                seq=self.store.next_seq(case.case_id),
                ts=ts,
                source=EventSource.VERIFICATION,
                type=EventType.STATE_CHANGED,
                from_state=from_state,
                to_state=CaseState.VERIFIED,
            )
        )
        return verified

    def _transition(
        self,
        case: RunState,
        new_state: CaseState,
        *,
        source: EventSource,
        terminal_reason: TerminalReason | None = None,
        reason: str | None = None,
    ) -> RunState:
        if case.state == new_state:
            raise OrchestratorError(
                f"Refusing no-op transition from {case.state.value} to {new_state.value}"
            )
        ts = self.clock()
        next_case = case.transition_to(
            new_state,
            updated_at=ts,
            terminal_reason=terminal_reason,
        )
        event_reason = reason
        if terminal_reason is not None:
            event_reason = reason_for_terminal(terminal_reason)
        self.store.append(
            Event(
                event_id=self._new_event_id(),
                case_id=case.case_id,
                seq=self.store.next_seq(case.case_id),
                ts=ts,
                source=source,
                type=EventType.STATE_CHANGED,
                from_state=case.state,
                to_state=new_state,
                reason=event_reason,
            )
        )
        return next_case

    def _with_attempts(self, case: RunState, attempts: Attempts) -> RunState:
        """Return a new RunState with replaced attempts; never mutates the input."""
        return RunState(
            case_id=case.case_id,
            client_id=case.client_id,
            repo_ref=case.repo_ref,
            channel=case.channel,
            report_text=case.report_text,
            state=case.state,
            created_at=case.created_at,
            updated_at=self.clock(),
            terminal_reason=case.terminal_reason,
            attempts=attempts,
            base_revision=case.base_revision,
            fix_revision=case.fix_revision,
            evidence_ids=case.evidence_ids,
        )

    @staticmethod
    def _new_event_id() -> str:
        return f"evt-{uuid.uuid4().hex}"
