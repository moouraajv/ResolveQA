"""Orchestrator state machine tests with labeled stage doubles (issue #6)."""

from __future__ import annotations

import tempfile
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path

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
from resolveqa.orchestrator import Orchestrator, OrchestratorLimits
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

    def __init__(self, result: TriageRecord | NeedsInfo) -> None:
        self.result = result
        self.calls = 0

    def run(self, case: RunState) -> TriageRecord | NeedsInfo:
        self.calls += 1
        return self.result


class _LabeledReproduction:
    """Test double: reproduction stage (labeled mock)."""

    def __init__(self, result: ReproResult) -> None:
        self.result = result
        self.calls = 0

    def run(self, case: RunState, triage: TriageRecord) -> ReproResult:
        self.calls += 1
        return self.result


class _LabeledFix:
    """Test double: fix stage (labeled mock)."""

    def __init__(self, result: Patch | None = None) -> None:
        self.result = result if result is not None else _patch()
        self.calls = 0

    def run(self, case: RunState, triage: TriageRecord, repro: ReproResult) -> Patch:
        self.calls += 1
        return self.result


class _LabeledVerification:
    """Test double: verification stage with scripted verdicts (labeled mock)."""

    def __init__(self, results: list[Verdict]) -> None:
        self.results = list(results)
        self.calls = 0

    def run(self, case: RunState, repro: ReproResult, patch: Patch) -> Verdict:
        if self.calls >= len(self.results):
            raise AssertionError("Verification double exhausted scripted verdicts")
        verdict = self.results[self.calls]
        self.calls += 1
        return verdict


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
        repro: ReproResult | None = None,
        verdicts: list[Verdict] | None = None,
        limits: OrchestratorLimits | None = None,
    ) -> tuple[Orchestrator, _LabeledTriage, _LabeledReproduction, _LabeledFix, _LabeledVerification]:
        triage_double = _LabeledTriage(triage if triage is not None else _triage_ok())
        repro_double = _LabeledReproduction(repro if repro is not None else _repro_red())
        fix_double = _LabeledFix()
        verification_double = _LabeledVerification(
            verdicts if verdicts is not None else [_verdict_verified()]
        )
        orch = Orchestrator(
            triage=triage_double,
            reproduction=repro_double,
            fix=fix_double,
            verification=verification_double,
            store=self.store,
            limits=limits
            if limits is not None
            else OrchestratorLimits(max_fix_attempts=2, max_llm_calls=12),
            clock=self._clock,
        )
        return orch, triage_double, repro_double, fix_double, verification_double

    def test_success_reaches_verified_with_continuous_seq(self) -> None:
        orch, triage_d, repro_d, fix_d, ver_d = self._build()
        initial = _case()
        final = orch.run(initial)

        self.assertEqual(final.state, CaseState.VERIFIED)
        self.assertIsNone(final.terminal_reason)
        self.assertEqual(final.base_revision, "base-sha")
        self.assertEqual(final.fix_revision, "fix-sha")
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

        # Original case immutable.
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
        self.assertEqual(final.attempts.fix, 1)
        self.assertIsNot(final.attempts, original_attempts)
        with self.assertRaises(FrozenInstanceError):
            original_attempts.fix = 9  # type: ignore[misc]


if __name__ == "__main__":
    unittest.main()
