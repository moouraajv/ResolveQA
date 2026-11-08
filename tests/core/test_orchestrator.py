"""Orchestrator state machine tests with labeled stage doubles (issue #6)."""

from __future__ import annotations

import tempfile
import unittest
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
from typing import Any, Callable

from resolveqa.contracts import (
    Attempts,
    BlockedReason,
    CaseState,
    ChannelType,
    EventType,
    NeedsInfo,
    Patch,
    ReproOutcome,
    ReproResult,
    RunState,
    TriageRecord,
    Verdict,
    VerdictResult,
)
from resolveqa.contracts import TestRun as ContractTestRun
from resolveqa.orchestrator import Orchestrator, OrchestratorError, OrchestratorLimits
from resolveqa.store import EventStore


def _case(
    *,
    case_id: str = "case-orch-001",
    llm_calls: int = 0,
    fix_attempts: int = 0,
) -> RunState:
    return RunState(
        case_id=case_id,
        client_id="client-demo",
        repo_ref="demo-target",
        channel=ChannelType.API,
        report_text="Expected R$ 180,00 after 10% coupon on R$ 200,00; observed R$ 200,00",
        state=CaseState.CREATED,
        created_at="2026-11-07T21:00:00Z",
        updated_at="2026-11-07T21:00:00Z",
        attempts=Attempts(fix=fix_attempts, llm_calls=llm_calls),
    )


def _triage_ok() -> TriageRecord:
    return TriageRecord(
        input="checkout with 10% coupon",
        expected="R$ 180,00",
        observed="R$ 200,00",
        suspect_files=("checkout.py",),
        confidence=0.9,
    )


def _repro_red() -> ReproResult:
    return ReproResult(
        test_path="tests/test_coupon_repro.py",
        test_source_ref="evidence/test_coupon_repro.py",
        exit_code=1,
        outcome=ReproOutcome.RED_ON_ASSERTION,
        failing_assertion="assert total == 180.0",
        log_ref="evidence/repro.log",
    )


def _patch() -> Patch:
    return Patch(diff_ref="evidence/fix.diff", files_changed=("checkout.py",))


def _test_run(exit_code: int, name: str) -> ContractTestRun:
    return ContractTestRun(
        command=f"pytest {name}",
        exit_code=exit_code,
        duration_s=0.1,
        log_ref=f"evidence/{name}.log",
    )


def _verdict_verified() -> Verdict:
    return Verdict(
        before=_test_run(1, "before"),
        after=_test_run(0, "after"),
        suite=_test_run(0, "suite"),
        base_revision="base-sha",
        fix_revision="fix-sha",
        result=VerdictResult.VERIFIED,
    )


def _verdict_rejected(reason: str = "assertion still failing") -> Verdict:
    return Verdict(
        before=_test_run(1, "before"),
        after=_test_run(1, "after"),
        suite=_test_run(0, "suite"),
        base_revision="base-sha",
        fix_revision="fix-sha-bad",
        result=VerdictResult.REJECTED,
        reasons=(reason,),
    )


def _verdict_env_error() -> Verdict:
    return Verdict(
        before=_test_run(1, "before"),
        after=_test_run(0, "after"),
        suite=_test_run(0, "suite"),
        base_revision="base-sha",
        fix_revision="fix-sha",
        result=VerdictResult.ENV_ERROR,
        reasons=("sandbox unavailable",),
    )


class _LabeledTriage:
    """Test double: triage stage (labeled mock)."""

    def __init__(
        self,
        result: Any = None,
        *,
        error: BaseException | None = None,
        on_run: Callable[[RunState], None] | None = None,
        return_verified_case: bool = False,
    ) -> None:
        self.result: Any = _triage_ok() if result is None else result
        self.error = error
        self.on_run = on_run
        self.return_verified_case = return_verified_case
        self.calls = 0

    def run(self, case: RunState) -> Any:
        self.calls += 1
        if self.on_run is not None:
            self.on_run(case)
        if self.error is not None:
            raise self.error
        if self.return_verified_case:
            return replace(case, state=CaseState.VERIFIED)
        return self.result


class _LabeledReproduction:
    """Test double: reproduction stage (labeled mock)."""

    def __init__(
        self,
        result: Any = None,
        *,
        return_verified_case: bool = False,
    ) -> None:
        self.result: Any = _repro_red() if result is None else result
        self.return_verified_case = return_verified_case
        self.calls = 0

    def run(self, case: RunState, triage: TriageRecord) -> Any:
        self.calls += 1
        if self.return_verified_case:
            return replace(case, state=CaseState.VERIFIED)
        return self.result


class _LabeledFix:
    """Test double: fix stage (labeled mock)."""

    def __init__(
        self,
        result: Any = None,
        *,
        return_verified_case: bool = False,
    ) -> None:
        self.result: Any = _patch() if result is None else result
        self.return_verified_case = return_verified_case
        self.calls = 0

    def run(self, case: RunState, triage: TriageRecord, repro: ReproResult) -> Any:
        self.calls += 1
        if self.return_verified_case:
            return replace(case, state=CaseState.VERIFIED)
        return self.result


class _LabeledVerification:
    """Test double: verification stage with scripted verdicts (labeled mock)."""

    def __init__(
        self,
        results: list[Any] | None = None,
        *,
        return_verified_case: bool = False,
    ) -> None:
        self.results = list(results) if results is not None else [_verdict_verified()]
        self.return_verified_case = return_verified_case
        self.calls = 0

    def run(self, case: RunState, repro: ReproResult, patch: Patch) -> Any:
        self.calls += 1
        if self.return_verified_case:
            return replace(case, state=CaseState.VERIFIED)
        if self.calls > len(self.results):
            raise AssertionError("Verification double exhausted scripted verdicts")
        return self.results[self.calls - 1]


class _SharedLlmBudget:
    """Labeled shared LLM call counter for live budget sync during a run."""

    def __init__(self, initial: int = 0) -> None:
        self.calls = initial

    def getter(self, case: RunState) -> int:
        return max(int(case.attempts.llm_calls), self.calls)

    def consume(self, n: int = 1) -> None:
        self.calls += n


class LLMLimitExceededError(RuntimeError):
    """Local stand-in matching adapter duck-type (reason=limit_exceeded)."""

    def __init__(self) -> None:
        super().__init__("limit_exceeded: maximum LLM calls reached")
        self.reason = "limit_exceeded"


class TestOrchestrator(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.runs_root = Path(self._tmp.name) / "runs"
        self.store = EventStore(self.runs_root)
        self._tick = 0

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _clock(self) -> str:
        self._tick += 1
        return f"2026-11-07T21:{self._tick:02d}:00Z"

    def _build(
        self,
        *,
        triage: TriageRecord | NeedsInfo | None = None,
        triage_double: _LabeledTriage | None = None,
        repro: ReproResult | None = None,
        repro_double: _LabeledReproduction | None = None,
        fix_double: _LabeledFix | None = None,
        verdicts: list[Verdict] | None = None,
        verification_double: _LabeledVerification | None = None,
        limits: OrchestratorLimits | None = None,
        llm_calls_getter: Callable[[RunState], int] | None = None,
    ) -> tuple[Orchestrator, _LabeledTriage, _LabeledReproduction, _LabeledFix, _LabeledVerification]:
        triage_obj = triage_double or _LabeledTriage(triage if triage is not None else _triage_ok())
        repro_obj = repro_double or _LabeledReproduction(
            repro if repro is not None else _repro_red()
        )
        fix_obj = fix_double or _LabeledFix()
        verification_obj = verification_double or _LabeledVerification(
            verdicts if verdicts is not None else [_verdict_verified()]
        )
        orch = Orchestrator(
            triage=triage_obj,
            reproduction=repro_obj,
            fix=fix_obj,
            verification=verification_obj,
            store=self.store,
            limits=limits
            if limits is not None
            else OrchestratorLimits(max_fix_attempts=2, max_llm_calls=12),
            clock=self._clock,
            llm_calls_getter=llm_calls_getter,
        )
        return orch, triage_obj, repro_obj, fix_obj, verification_obj

    def test_success_reaches_verified_with_continuous_seq(self) -> None:
        orch, triage_d, repro_d, fix_d, ver_d = self._build()
        initial = _case()
        final = orch.run(initial)

        self.assertEqual(final.state, CaseState.VERIFIED)
        self.assertIsNone(final.terminal_reason)
        self.assertEqual(final.base_revision, "base-sha")
        self.assertEqual(final.fix_revision, "fix-sha")
        self.assertEqual(final.attempts.fix, 1)  # successful Fix counts as an attempt
        self.assertEqual(triage_d.calls, 1)
        self.assertEqual(repro_d.calls, 1)
        self.assertEqual(fix_d.calls, 1)
        self.assertEqual(ver_d.calls, 1)

        events = self.store.list_events(initial.case_id)
        self.assertEqual(events[0].type, EventType.CASE_CREATED)
        self.assertEqual(events[0].seq, 0)
        state_events = [e for e in events if e.type == EventType.STATE_CHANGED]
        self.assertGreaterEqual(len(state_events), 1)
        seqs = [e.seq for e in events]
        self.assertEqual(seqs, list(range(len(events))))
        for left, right in zip(events, events[1:]):
            self.assertLess(left.seq, right.seq)
            self.assertTrue(left.ts.endswith("Z"))
            self.assertTrue(right.ts.endswith("Z"))
        self.assertEqual(state_events[-1].to_state, CaseState.VERIFIED)
        self.assertEqual(state_events[-1].source.value, "verification")

        self.assertEqual(initial.state, CaseState.CREATED)
        with self.assertRaises(FrozenInstanceError):
            initial.state = CaseState.VERIFIED  # type: ignore[misc]

    def test_needs_info_terminal(self) -> None:
        orch, _, _, fix_d, ver_d = self._build(
            triage=NeedsInfo(
                missing_fields=("expected",),
                question_to_support="Qual valor esperado após o cupom?",
            )
        )
        final = orch.run(_case(case_id="case-needs-info"))
        self.assertEqual(final.state, CaseState.NEEDS_INFO)
        self.assertEqual(
            final.terminal_reason.question_to_support,  # type: ignore[union-attr]
            "Qual valor esperado após o cupom?",
        )
        self.assertEqual(fix_d.calls, 0)
        self.assertEqual(ver_d.calls, 0)

    def test_fix_budget_checked_before_fix_when_already_exhausted(self) -> None:
        orch, _, _, fix_d, ver_d = self._build()
        final = orch.run(_case(case_id="case-fix-preexhausted", fix_attempts=2))
        self.assertEqual(final.state, CaseState.BLOCKED)
        self.assertEqual(final.terminal_reason.code, BlockedReason.LIMIT_EXCEEDED)  # type: ignore[union-attr]
        self.assertEqual(fix_d.calls, 0)
        self.assertEqual(ver_d.calls, 0)
        events = self.store.list_events("case-fix-preexhausted")
        self.assertTrue(any(e.type == EventType.LIMIT_REACHED for e in events))

    def test_patch_rejection_retries_then_blocks_at_fix_limit(self) -> None:
        orch, _, _, fix_d, ver_d = self._build(
            verdicts=[
                _verdict_rejected("patch insufficient"),
                _verdict_rejected("patch still insufficient"),
            ],
            limits=OrchestratorLimits(max_fix_attempts=2, max_llm_calls=12),
        )
        final = orch.run(_case(case_id="case-retry-2"))
        self.assertEqual(final.state, CaseState.BLOCKED)
        self.assertEqual(final.terminal_reason.code, BlockedReason.LIMIT_EXCEEDED)  # type: ignore[union-attr]
        self.assertEqual(final.attempts.fix, 2)
        self.assertEqual(fix_d.calls, 2)
        self.assertEqual(ver_d.calls, 2)

        events = self.store.list_events("case-retry-2")
        self.assertTrue(any(e.type == EventType.LIMIT_REACHED for e in events))
        blocked = [e for e in events if e.to_state == CaseState.BLOCKED]
        self.assertEqual(len(blocked), 1)
        self.assertEqual(blocked[0].reason, BlockedReason.LIMIT_EXCEEDED.value)

    def test_llm_limit_blocks_without_calling_stages(self) -> None:
        orch, triage_d, repro_d, fix_d, ver_d = self._build(
            limits=OrchestratorLimits(max_fix_attempts=2, max_llm_calls=12),
        )
        final = orch.run(_case(case_id="case-llm-12", llm_calls=12))
        self.assertEqual(final.state, CaseState.BLOCKED)
        self.assertEqual(final.terminal_reason.code, BlockedReason.LIMIT_EXCEEDED)  # type: ignore[union-attr]
        self.assertEqual(triage_d.calls, 0)
        self.assertEqual(repro_d.calls, 0)
        self.assertEqual(fix_d.calls, 0)
        self.assertEqual(ver_d.calls, 0)
        events = self.store.list_events("case-llm-12")
        self.assertTrue(any(e.type == EventType.LIMIT_REACHED for e in events))

    def test_llm_budget_syncs_incremental_calls_during_run(self) -> None:
        budget = _SharedLlmBudget(initial=11)
        triage = _LabeledTriage(on_run=lambda _case: budget.consume(1))
        orch, triage_d, repro_d, fix_d, ver_d = self._build(
            triage_double=triage,
            llm_calls_getter=budget.getter,
            limits=OrchestratorLimits(max_fix_attempts=2, max_llm_calls=12),
        )
        final = orch.run(_case(case_id="case-llm-live", llm_calls=11))
        self.assertEqual(final.state, CaseState.BLOCKED)
        self.assertEqual(final.terminal_reason.code, BlockedReason.LIMIT_EXCEEDED)  # type: ignore[union-attr]
        self.assertEqual(final.attempts.llm_calls, 12)
        self.assertEqual(triage_d.calls, 1)
        self.assertEqual(repro_d.calls, 0)
        self.assertEqual(fix_d.calls, 0)
        self.assertEqual(ver_d.calls, 0)

    def test_llm_limit_exceeded_error_from_stage_becomes_blocked(self) -> None:
        triage = _LabeledTriage(error=LLMLimitExceededError())
        orch, triage_d, repro_d, fix_d, _ = self._build(triage_double=triage)
        final = orch.run(_case(case_id="case-llm-exc"))
        self.assertEqual(final.state, CaseState.BLOCKED)
        self.assertEqual(final.terminal_reason.code, BlockedReason.LIMIT_EXCEEDED)  # type: ignore[union-attr]
        self.assertEqual(triage_d.calls, 1)
        self.assertEqual(repro_d.calls, 0)
        self.assertEqual(fix_d.calls, 0)

    def test_stage_oserror_becomes_infra_error_with_event(self) -> None:
        triage = _LabeledTriage(error=OSError("disk unavailable"))
        orch, triage_d, repro_d, fix_d, _ = self._build(triage_double=triage)
        final = orch.run(_case(case_id="case-oserror-triage"))
        self.assertEqual(final.state, CaseState.INFRA_ERROR)
        self.assertEqual(final.terminal_reason.detail, "disk unavailable")  # type: ignore[union-attr]
        self.assertEqual(triage_d.calls, 1)
        self.assertEqual(repro_d.calls, 0)
        self.assertEqual(fix_d.calls, 0)
        events = self.store.list_events("case-oserror-triage")
        self.assertEqual(events[-1].to_state, CaseState.INFRA_ERROR)
        self.assertEqual(events[-1].from_state, CaseState.TRIAGING)
        self.assertEqual(events[-1].reason, "disk unavailable")

    def test_stage_timeout_becomes_infra_error(self) -> None:
        triage = _LabeledTriage(error=TimeoutError("stage timed out"))
        orch, _, _, _, _ = self._build(triage_double=triage)
        final = orch.run(_case(case_id="case-timeout-triage"))
        self.assertEqual(final.state, CaseState.INFRA_ERROR)
        self.assertEqual(final.terminal_reason.detail, "stage timed out")  # type: ignore[union-attr]

    def test_programming_error_from_stage_propagates(self) -> None:
        triage = _LabeledTriage(error=TypeError("bug in triage double"))
        orch, _, _, _, _ = self._build(triage_double=triage)
        with self.assertRaises(TypeError):
            orch.run(_case(case_id="case-type-error"))
        events = self.store.list_events("case-type-error")
        self.assertEqual(events[-1].to_state, CaseState.TRIAGING)

    def _assert_no_verified_outcome(self, case_id: str) -> None:
        events = self.store.list_events(case_id)
        self.assertFalse(any(e.to_state == CaseState.VERIFIED for e in events))
        self.assertFalse(
            any(e.type == EventType.STATE_CHANGED and e.to_state == CaseState.VERIFIED for e in events)
        )

    def test_triage_returning_runstate_verified_is_rejected(self) -> None:
        orch, triage_d, repro_d, fix_d, ver_d = self._build(
            triage_double=_LabeledTriage(return_verified_case=True),
        )
        with self.assertRaises(OrchestratorError) as ctx:
            orch.run(_case(case_id="case-fake-verified-triage"))
        self.assertIn("TriageStage.run", str(ctx.exception))
        self.assertIn("RunState", str(ctx.exception))
        self.assertEqual(triage_d.calls, 1)
        self.assertEqual(repro_d.calls, 0)
        self.assertEqual(fix_d.calls, 0)
        self.assertEqual(ver_d.calls, 0)
        self._assert_no_verified_outcome("case-fake-verified-triage")
        events = self.store.list_events("case-fake-verified-triage")
        self.assertEqual(events[-1].to_state, CaseState.TRIAGING)

    def test_reproduction_returning_runstate_verified_is_rejected(self) -> None:
        orch, _, repro_d, fix_d, ver_d = self._build(
            repro_double=_LabeledReproduction(return_verified_case=True),
        )
        with self.assertRaises(OrchestratorError) as ctx:
            orch.run(_case(case_id="case-fake-verified-repro"))
        self.assertIn("ReproductionStage.run", str(ctx.exception))
        self.assertEqual(repro_d.calls, 1)
        self.assertEqual(fix_d.calls, 0)
        self.assertEqual(ver_d.calls, 0)
        self._assert_no_verified_outcome("case-fake-verified-repro")

    def test_fix_returning_runstate_verified_is_rejected(self) -> None:
        orch, _, _, fix_d, ver_d = self._build(
            fix_double=_LabeledFix(return_verified_case=True),
        )
        with self.assertRaises(OrchestratorError) as ctx:
            orch.run(_case(case_id="case-fake-verified-fix"))
        self.assertIn("FixStage.run", str(ctx.exception))
        self.assertEqual(fix_d.calls, 1)
        self.assertEqual(ver_d.calls, 0)
        self._assert_no_verified_outcome("case-fake-verified-fix")

    def test_verification_returning_runstate_verified_is_rejected(self) -> None:
        orch, _, _, fix_d, ver_d = self._build(
            verification_double=_LabeledVerification(return_verified_case=True),
        )
        with self.assertRaises(OrchestratorError) as ctx:
            orch.run(_case(case_id="case-fake-verified-verdict"))
        self.assertIn("VerificationStage.run", str(ctx.exception))
        self.assertEqual(fix_d.calls, 1)
        self.assertEqual(ver_d.calls, 1)
        self._assert_no_verified_outcome("case-fake-verified-verdict")

    def test_reproduction_env_error_is_infra_error_not_bug(self) -> None:
        orch, _, _, fix_d, _ = self._build(
            repro=ReproResult(
                test_path="tests/test_coupon_repro.py",
                test_source_ref="evidence/test_coupon_repro.py",
                exit_code=2,
                outcome=ReproOutcome.ENV_ERROR,
                failing_assertion="interpreter missing",
                log_ref="evidence/env.log",
            )
        )
        final = orch.run(_case(case_id="case-infra-repro"))
        self.assertEqual(final.state, CaseState.INFRA_ERROR)
        self.assertNotEqual(final.state, CaseState.BLOCKED)
        self.assertEqual(final.terminal_reason.detail, "interpreter missing")  # type: ignore[union-attr]
        self.assertEqual(fix_d.calls, 0)

    def test_verification_env_error_is_infra_error(self) -> None:
        orch, _, _, _, ver_d = self._build(verdicts=[_verdict_env_error()])
        final = orch.run(_case(case_id="case-infra-verify"))
        self.assertEqual(final.state, CaseState.INFRA_ERROR)
        self.assertEqual(final.terminal_reason.detail, "sandbox unavailable")  # type: ignore[union-attr]
        self.assertEqual(ver_d.calls, 1)

    def test_final_state_reconstructible_from_events(self) -> None:
        orch, _, _, _, _ = self._build()
        initial = _case(case_id="case-reconstruct")
        final = orch.run(initial)
        rebuilt = self.store.reconstruct_state(initial)
        self.assertEqual(rebuilt.state, final.state)
        self.assertEqual(rebuilt.state, CaseState.VERIFIED)
        self.assertEqual(rebuilt.updated_at, final.updated_at)

    def test_stale_created_input_rejected_before_append(self) -> None:
        orch, _, _, fix_d, _ = self._build()
        stale = _case(case_id="case-stale-rerun")
        first = orch.run(stale)
        self.assertEqual(first.state, CaseState.VERIFIED)
        before = list(self.store.list_events("case-stale-rerun"))
        with self.assertRaises(OrchestratorError) as ctx:
            orch.run(stale)
        self.assertIn("incompatible", str(ctx.exception).lower())
        after = self.store.list_events("case-stale-rerun")
        self.assertEqual(len(before), len(after))
        self.assertEqual([e.event_id for e in before], [e.event_id for e in after])
        rebuilt = self.store.reconstruct_state(stale)
        self.assertEqual(rebuilt.state, CaseState.VERIFIED)
        self.assertEqual(fix_d.calls, 1)

    def test_attempts_use_new_instances_never_setattr(self) -> None:
        orch, _, _, _, _ = self._build(
            verdicts=[
                _verdict_rejected("first"),
                _verdict_verified(),
            ]
        )
        initial = _case(case_id="case-attempts-immut")
        original_attempts = initial.attempts
        final = orch.run(initial)
        self.assertEqual(original_attempts.fix, 0)
        # First Fix attempt + second Fix attempt (verified) => 2
        self.assertEqual(final.attempts.fix, 2)
        self.assertIsNot(final.attempts, original_attempts)
        with self.assertRaises(FrozenInstanceError):
            original_attempts.fix = 9  # type: ignore[misc]


if __name__ == "__main__":
    unittest.main()
