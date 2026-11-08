"""Orchestrator state machine, limits enforcement, and terminal state transitions (RFC-0001 §2.2, §4, §5)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import resolveqa.contracts as contracts
from resolveqa.contracts import (
    Attempts,
    CaseState,
    Event,
    EventSource,
    EventType,
    NeedsInfo,
    Patch,
    ReproOutcome,
    ReproResult,
    RunState,
    TERMINAL_STATES,
    TriageRecord,
    VerdictResult,
)
from resolveqa.llm import LLMLimitExceededError, LLMOutputError
from resolveqa.store import EvidenceStore

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_LIMITS_PATH = REPO_ROOT / "config" / "limits.json"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def extract_terminal_reason_code(terminal_reason: Any) -> str:
    """Extract comparable reason string/code from either str or structured TerminalReason."""
    if terminal_reason is None:
        return ""
    if isinstance(terminal_reason, str):
        return terminal_reason
    if hasattr(terminal_reason, "code"):
        code = getattr(terminal_reason, "code")
        return code.value if hasattr(code, "value") else str(code)
    if hasattr(terminal_reason, "question_to_support"):
        return str(getattr(terminal_reason, "question_to_support"))
    if hasattr(terminal_reason, "detail"):
        return str(getattr(terminal_reason, "detail"))
    return str(terminal_reason)


def _make_terminal_reason(
    state: CaseState,
    code_or_text: str,
    detail: Optional[str] = None,
) -> Any:
    if state not in TERMINAL_STATES or state == CaseState.VERIFIED:
        return None
    if hasattr(contracts, "BlockedTerminalReason"):
        if state == CaseState.BLOCKED:
            code = (
                code_or_text
                if code_or_text in {"limit_exceeded", "not_reproduced", "patch_rejected"}
                else "not_reproduced"
            )
            return contracts.BlockedTerminalReason(code=code, detail=detail)
        if state == CaseState.NEEDS_INFO:
            return contracts.NeedsInfoTerminalReason(question_to_support=detail or code_or_text)
        if state == CaseState.INFRA_ERROR:
            return contracts.InfraErrorTerminalReason(detail=detail or code_or_text)
    return code_or_text


@dataclass(frozen=True)
class PipelineLimits:
    """Configured pipeline limits per RNF-03 and RFC-0001 §5."""

    max_fix_attempts: int = 2
    max_llm_calls: int = 12
    test_timeout_s: int = 600
    max_files_changed: int = 3

    @classmethod
    def from_config_file(cls, path: Path | None = None) -> PipelineLimits:
        target = path if path is not None else DEFAULT_LIMITS_PATH
        if not target.is_file():
            raise FileNotFoundError(f"Limits config file not found: {target}")
        data = json.loads(target.read_text(encoding="utf-8"))
        return cls(
            max_fix_attempts=int(data["max_fix_attempts"]),
            max_llm_calls=int(data["max_llm_calls"]),
            test_timeout_s=int(data["test_timeout_s"]),
            max_files_changed=int(data["max_files_changed"]),
        )


def _clone_run_state(
    case: RunState,
    *,
    state: Optional[CaseState] = None,
    updated_at: Optional[str] = None,
    terminal_reason: Any = ...,
    fix_attempts: Optional[int] = None,
    llm_calls: Optional[int] = None,
    base_revision: Optional[str] = ...,
    fix_revision: Optional[str] = ...,
    extra_evidence_ids: Optional[list[str]] = None,
) -> RunState:
    """Construct a brand new `RunState` without mutating `case`."""
    next_state = state if state is not None else case.state
    next_reason = case.terminal_reason if terminal_reason is ... else terminal_reason
    next_fix = fix_attempts if fix_attempts is not None else case.attempts.fix
    next_llm = llm_calls if llm_calls is not None else case.attempts.llm_calls
    next_base = case.base_revision if base_revision is ... else base_revision
    next_fix_rev = case.fix_revision if fix_revision is ... else fix_revision

    ev_list = list(case.evidence_ids)
    for eid in extra_evidence_ids or []:
        if eid and eid not in ev_list:
            ev_list.append(eid)
    ev_collection: Any = tuple(ev_list) if isinstance(case.evidence_ids, tuple) else ev_list

    return RunState(
        case_id=case.case_id,
        client_id=case.client_id,
        repo_ref=case.repo_ref,
        channel=case.channel,
        report_text=case.report_text,
        state=next_state,
        created_at=case.created_at,
        updated_at=updated_at or _utc_now_iso(),
        terminal_reason=next_reason,
        attempts=Attempts(fix=next_fix, llm_calls=next_llm),
        base_revision=next_base,
        fix_revision=next_fix_rev,
        evidence_ids=ev_collection,
    )


def _sync_llm_calls(stage_obj: Any, case: RunState) -> int:
    """Read updated LLM call count from a stage or its underlying LLM adapter without mutating `case`."""
    if hasattr(stage_obj, "get_llm_calls") and callable(stage_obj.get_llm_calls):
        return max(case.attempts.llm_calls, int(stage_obj.get_llm_calls(case)))
    llm_attr = getattr(stage_obj, "llm", None)
    if llm_attr is not None and hasattr(llm_attr, "get_llm_calls") and callable(llm_attr.get_llm_calls):
        return max(case.attempts.llm_calls, int(llm_attr.get_llm_calls(case)))
    return case.attempts.llm_calls


class Orchestrator:
    """Deterministic state machine coordinating Track A stages and recording append-only audit events."""

    def __init__(
        self,
        triage: Any,
        reproduction: Any,
        fix: Any,
        verification: Any,
        store: Optional[EvidenceStore] = None,
        limits: Optional[PipelineLimits] = None,
    ) -> None:
        self.triage = triage
        self.reproduction = reproduction
        self.fix = fix
        self.verification = verification
        self.store = store if store is not None else EvidenceStore()
        self.limits = limits if limits is not None else PipelineLimits.from_config_file()

    def _next_seq(self, case_id: str) -> int:
        existing = self.store.read_events(case_id)
        return (existing[-1].seq + 1) if existing else 1

    def _emit_event(
        self,
        case_id: str,
        source: EventSource,
        event_type: EventType,
        from_state: Optional[CaseState] = None,
        to_state: Optional[CaseState] = None,
        reason: Optional[str] = None,
        evidence_refs: Optional[list[str]] = None,
    ) -> Event:
        seq = self._next_seq(case_id)
        refs_list = [r for r in (evidence_refs or []) if r]
        ev = Event(
            event_id=f"{case_id}-ev-{seq:04d}",
            case_id=case_id,
            seq=seq,
            ts=_utc_now_iso(),
            source=source,
            type=event_type,
            from_state=from_state,
            to_state=to_state,
            reason=reason,
            evidence_refs=refs_list,
        )
        return self.store.append_event(ev)

    def _transition(
        self,
        case: RunState,
        to_state: CaseState,
        source: EventSource,
        *,
        event_reason: Optional[str] = None,
        terminal_reason: Any = None,
        fix_attempts: Optional[int] = None,
        llm_calls: Optional[int] = None,
        base_revision: Optional[str] = ...,
        fix_revision: Optional[str] = ...,
        evidence_refs: Optional[list[str]] = None,
    ) -> RunState:
        ev = self._emit_event(
            case_id=case.case_id,
            source=source,
            event_type=EventType.STATE_CHANGED,
            from_state=case.state,
            to_state=to_state,
            reason=event_reason,
            evidence_refs=evidence_refs,
        )
        return _clone_run_state(
            case,
            state=to_state,
            updated_at=ev.ts,
            terminal_reason=terminal_reason,
            fix_attempts=fix_attempts,
            llm_calls=llm_calls,
            base_revision=base_revision,
            fix_revision=fix_revision,
            extra_evidence_ids=evidence_refs,
        )

    def _transition_limit_exceeded(self, case: RunState, detail: str) -> RunState:
        self._emit_event(
            case_id=case.case_id,
            source=EventSource.ORCHESTRATOR,
            event_type=EventType.LIMIT_REACHED,
            reason="limit_exceeded",
        )
        term_reason = _make_terminal_reason(CaseState.BLOCKED, "limit_exceeded", detail=detail)
        return self._transition(
            case,
            CaseState.BLOCKED,
            EventSource.ORCHESTRATOR,
            event_reason="limit_exceeded",
            terminal_reason=term_reason,
        )

    def run(self, initial_case: RunState) -> RunState:
        """Execute the ResolveQA Track A pipeline deterministically without mutating `initial_case`."""
        case = _clone_run_state(initial_case)

        if not self.store.read_events(case.case_id):
            self._emit_event(
                case_id=case.case_id,
                source=EventSource.INTAKE,
                event_type=EventType.CASE_CREATED,
                to_state=CaseState.CREATED,
            )

        # 1. Triage
        case = self._transition(case, CaseState.TRIAGING, EventSource.ORCHESTRATOR)
        if case.attempts.llm_calls >= self.limits.max_llm_calls:
            return self._transition_limit_exceeded(case, "max_llm_calls reached before triage")

        try:
            triage_out = self.triage.run(case)
            updated_llm = _sync_llm_calls(self.triage, case)
            case = _clone_run_state(case, llm_calls=updated_llm)
        except LLMLimitExceededError as err:
            return self._transition_limit_exceeded(case, str(err))
        except LLMOutputError as err:
            term = _make_terminal_reason(CaseState.BLOCKED, "not_reproduced", detail=str(err))
            return self._transition(
                case,
                CaseState.BLOCKED,
                EventSource.TRIAGE,
                event_reason="not_reproduced",
                terminal_reason=term,
            )

        if isinstance(triage_out, NeedsInfo):
            term = _make_terminal_reason(
                CaseState.NEEDS_INFO,
                triage_out.question_to_support,
                detail=triage_out.question_to_support,
            )
            return self._transition(
                case,
                CaseState.NEEDS_INFO,
                EventSource.TRIAGE,
                event_reason=triage_out.question_to_support,
                terminal_reason=term,
            )

        case = self._transition(case, CaseState.TRIAGED, EventSource.TRIAGE)

        # 2. Reproduction
        case = self._transition(case, CaseState.REPRODUCING, EventSource.ORCHESTRATOR)
        if case.attempts.llm_calls >= self.limits.max_llm_calls:
            return self._transition_limit_exceeded(case, "max_llm_calls reached before reproduction")

        try:
            repro_out: ReproResult = self.reproduction.run(case, triage_out)
            updated_llm = _sync_llm_calls(self.reproduction, case)
            case = _clone_run_state(case, llm_calls=updated_llm)
        except LLMLimitExceededError as err:
            return self._transition_limit_exceeded(case, str(err))
        except LLMOutputError as err:
            term = _make_terminal_reason(CaseState.BLOCKED, "not_reproduced", detail=str(err))
            return self._transition(
                case,
                CaseState.BLOCKED,
                EventSource.REPRODUCTION,
                event_reason="not_reproduced",
                terminal_reason=term,
            )

        repro_refs = [r for r in [repro_out.test_source_ref, repro_out.log_ref] if r]
        if repro_out.outcome == ReproOutcome.ENV_ERROR:
            term = _make_terminal_reason(
                CaseState.INFRA_ERROR,
                "env_error",
                detail=repro_out.log_ref or "Environment error during reproduction",
            )
            return self._transition(
                case,
                CaseState.INFRA_ERROR,
                EventSource.REPRODUCTION,
                event_reason="env_error",
                terminal_reason=term,
                evidence_refs=repro_refs,
            )

        if repro_out.outcome != ReproOutcome.RED_ON_ASSERTION:
            term = _make_terminal_reason(
                CaseState.BLOCKED,
                "not_reproduced",
                detail="Generated test did not fail on assertion",
            )
            return self._transition(
                case,
                CaseState.BLOCKED,
                EventSource.REPRODUCTION,
                event_reason="not_reproduced",
                terminal_reason=term,
                evidence_refs=repro_refs,
            )

        case = self._transition(
            case,
            CaseState.REPRODUCED,
            EventSource.REPRODUCTION,
            evidence_refs=repro_refs,
        )

        # 3. Fix & Independent Verification loop (bounded by limits.max_fix_attempts)
        while case.attempts.fix < self.limits.max_fix_attempts:
            if case.attempts.llm_calls >= self.limits.max_llm_calls:
                return self._transition_limit_exceeded(case, "max_llm_calls reached before fix")

            next_fix_count = case.attempts.fix + 1
            case = self._transition(
                case,
                CaseState.FIXING,
                EventSource.ORCHESTRATOR,
                fix_attempts=next_fix_count,
            )

            try:
                patch_out: Patch = self.fix.run(case, triage_out, repro_out)
                updated_llm = _sync_llm_calls(self.fix, case)
                case = _clone_run_state(case, llm_calls=updated_llm)
            except LLMLimitExceededError as err:
                return self._transition_limit_exceeded(case, str(err))
            except LLMOutputError as err:
                term = _make_terminal_reason(CaseState.BLOCKED, "patch_rejected", detail=str(err))
                return self._transition(
                    case,
                    CaseState.BLOCKED,
                    EventSource.FIX,
                    event_reason="patch_rejected",
                    terminal_reason=term,
                )

            case = self._transition(
                case,
                CaseState.FIXED,
                EventSource.FIX,
                evidence_refs=[patch_out.diff_ref] if patch_out.diff_ref else None,
            )

            case = self._transition(case, CaseState.VERIFYING, EventSource.ORCHESTRATOR)
            verdict = self.verification.run(case, repro_out, patch_out)
            verdict_refs = [
                r
                for r in [verdict.before.log_ref, verdict.after.log_ref, verdict.suite.log_ref]
                if r
            ]

            if verdict.result == VerdictResult.ENV_ERROR:
                term = _make_terminal_reason(
                    CaseState.INFRA_ERROR,
                    "env_error",
                    detail="; ".join(verdict.reasons) or "Environment error during verification",
                )
                return self._transition(
                    case,
                    CaseState.INFRA_ERROR,
                    EventSource.VERIFICATION,
                    event_reason="env_error",
                    terminal_reason=term,
                    evidence_refs=verdict_refs,
                )

            if verdict.result == VerdictResult.VERIFIED:
                return self._transition(
                    case,
                    CaseState.VERIFIED,
                    EventSource.VERIFICATION,
                    base_revision=verdict.base_revision,
                    fix_revision=verdict.fix_revision,
                    evidence_refs=verdict_refs,
                )

            # VerdictResult.REJECTED
            if (
                patch_out.touches_tests
                or patch_out.touches_ci
                or len(patch_out.files_changed) > self.limits.max_files_changed
                or "patch_rejected" in verdict.reasons
            ):
                term = _make_terminal_reason(
                    CaseState.BLOCKED,
                    "patch_rejected",
                    detail="; ".join(verdict.reasons) or "Patch violated safety constraints",
                )
                return self._transition(
                    case,
                    CaseState.BLOCKED,
                    EventSource.VERIFICATION,
                    event_reason="patch_rejected",
                    terminal_reason=term,
                    evidence_refs=verdict_refs,
                )

            if case.attempts.fix >= self.limits.max_fix_attempts:
                return self._transition_limit_exceeded(
                    case,
                    f"Maximum fix attempts ({self.limits.max_fix_attempts}) exhausted",
                )

        return self._transition_limit_exceeded(
            case,
            f"Maximum fix attempts ({self.limits.max_fix_attempts}) exhausted",
        )
