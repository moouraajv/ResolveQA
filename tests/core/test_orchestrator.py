"""Tests for Orchestrator state machine, terminal states, limits, and EvidenceStore (Issue #6)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from resolveqa.contracts import (
    Attempts,
    CaseState,
    ChannelType,
    EventType,
    EvidenceKind,
    NeedsInfo,
    Patch,
    ReproOutcome,
    ReproResult,
    RunState,
    TestRun as ContractTestRun,
    TriageRecord,
    Verdict,
    VerdictResult,
)
from resolveqa.llm import LLMLimitExceededError, LLMOutputError
from resolveqa.orchestrator import Orchestrator, PipelineLimits, extract_terminal_reason_code
from resolveqa.store import EvidenceStore


def _make_initial_case(case_id: str = "case-orch-001") -> RunState:
    return RunState(
        case_id=case_id,
        client_id="client-demo",
        repo_ref="demo-target",
        channel=ChannelType.SIMULATED_CHAT,
        report_text="Apliquei um cupom de 10% em uma compra de R$ 200, mas o total continuou em R$ 200.",
        state=CaseState.CREATED,
        created_at="2026-11-07T17:00:00Z",
        updated_at="2026-11-07T17:00:00Z",
    )


class _StubTriage:
    def __init__(
        self,
        result: TriageRecord | NeedsInfo,
        raise_limit: bool = False,
        raise_output_err: bool = False,
        llm_calls_used: int = 1,
    ) -> None:
        self.result = result
        self.raise_limit = raise_limit
        self.raise_output_err = raise_output_err
        self.llm_calls_used = llm_calls_used
        self._calls_by_case: dict[str, int] = {}

    def get_llm_calls(self, case: RunState) -> int:
        return self._calls_by_case.get(case.case_id, case.attempts.llm_calls)

    def run(self, case: RunState) -> TriageRecord | NeedsInfo:
        if self.raise_limit:
            raise LLMLimitExceededError(12)
        if self.raise_output_err:
            raise LLMOutputError("Malformed triage JSON", purpose="triage")
        self._calls_by_case[case.case_id] = case.attempts.llm_calls + self.llm_calls_used
        return self.result


class _StubReproduction:
    def __init__(self, result: ReproResult, llm_calls_used: int = 1) -> None:
        self.result = result
        self.llm_calls_used = llm_calls_used
        self._calls_by_case: dict[str, int] = {}

    def get_llm_calls(self, case: RunState) -> int:
        return self._calls_by_case.get(case.case_id, case.attempts.llm_calls)

    def run(self, case: RunState, triage: TriageRecord) -> ReproResult:
        self._calls_by_case[case.case_id] = case.attempts.llm_calls + self.llm_calls_used
        return self.result


class _StubFix:
    def __init__(self, patch_obj: Patch, llm_calls_used: int = 1) -> None:
        self.patch_obj = patch_obj
        self.llm_calls_used = llm_calls_used
        self.calls = 0
        self._calls_by_case: dict[str, int] = {}

    def get_llm_calls(self, case: RunState) -> int:
        return self._calls_by_case.get(case.case_id, case.attempts.llm_calls)

    def run(self, case: RunState, triage: TriageRecord, repro: ReproResult) -> Patch:
        self.calls += 1
        self._calls_by_case[case.case_id] = case.attempts.llm_calls + self.llm_calls_used
        return self.patch_obj


class _StubVerification:
    def __init__(self, verdicts: list[Verdict]) -> None:
        self.verdicts = list(verdicts)
        self.calls = 0

    def run(self, case: RunState, repro: ReproResult, patch: Patch) -> Verdict:
        idx = min(self.calls, len(self.verdicts) - 1)
        self.calls += 1
        return self.verdicts[idx]


class TestOrchestratorAndStore(unittest.TestCase):
    """Validate Issue #6 acceptance criteria without mutating input RunState."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.runs_dir = Path(self._tmp.name) / "runs"
        self.store = EvidenceStore(runs_root=self.runs_dir)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_happy_path_verified_does_not_mutate_input_and_reconstructs_from_events_jsonl(self) -> None:
        initial = _make_initial_case("case-happy")
        triage = _StubTriage(
            TriageRecord(
                input="subtotal=200.0, coupon_percent=10.0",
                expected="R$ 180,00",
                observed="R$ 200,00",
                suspect_files=["checkout.py"],
                confidence=0.95,
            )
        )
        repro = _StubReproduction(
            ReproResult(
                test_path="tests/test_repro_coupon.py",
                test_source_ref="evidence/repro_test.py",
                exit_code=1,
                outcome=ReproOutcome.RED_ON_ASSERTION,
                failing_assertion="AssertionError: 200.0 != 180.0",
                log_ref="evidence/repro.log",
            )
        )
        fix = _StubFix(
            Patch(
                diff_ref="evidence/fix.diff",
                files_changed=["checkout.py"],
                touches_tests=False,
                touches_ci=False,
            )
        )
        verdict = Verdict(
            before=ContractTestRun("pytest", 1, 0.1, "evidence/before.log"),
            after=ContractTestRun("pytest", 0, 0.1, "evidence/after.log"),
            suite=ContractTestRun("pytest", 0, 0.2, "evidence/suite.log"),
            base_revision="rev-base-111",
            fix_revision="rev-fix-222",
            result=VerdictResult.VERIFIED,
        )
        verification = _StubVerification([verdict])

        orch = Orchestrator(
            triage=triage,
            reproduction=repro,
            fix=fix,
            verification=verification,
            store=self.store,
        )
        final_case = orch.run(initial)

        # Input RunState must remain untouched
        self.assertEqual(initial.state, CaseState.CREATED)
        self.assertEqual(initial.attempts.fix, 0)
        self.assertEqual(initial.attempts.llm_calls, 0)

        self.assertEqual(final_case.state, CaseState.VERIFIED)
        self.assertEqual(final_case.base_revision, "rev-base-111")
        self.assertEqual(final_case.fix_revision, "rev-fix-222")
        self.assertEqual(final_case.attempts.fix, 1)
        self.assertEqual(final_case.attempts.llm_calls, 3)

        events = self.store.read_events("case-happy")
        self.assertGreaterEqual(len(events), 8)
        for idx, ev in enumerate(events, start=1):
            self.assertEqual(ev.seq, idx, "Event sequence must be strictly contiguous starting at 1")

        state_changes = [e for e in events if e.type == EventType.STATE_CHANGED]
        transitions = [(e.from_state, e.to_state) for e in state_changes]
        self.assertEqual(
            transitions,
            [
                (CaseState.CREATED, CaseState.TRIAGING),
                (CaseState.TRIAGING, CaseState.TRIAGED),
                (CaseState.TRIAGED, CaseState.REPRODUCING),
                (CaseState.REPRODUCING, CaseState.REPRODUCED),
                (CaseState.REPRODUCED, CaseState.FIXING),
                (CaseState.FIXING, CaseState.FIXED),
                (CaseState.FIXED, CaseState.VERIFYING),
                (CaseState.VERIFYING, CaseState.VERIFIED),
            ],
        )

        reconstructed = self.store.reconstruct_state("case-happy", _make_initial_case("case-happy"))
        self.assertEqual(reconstructed.state, final_case.state)
        self.assertEqual(reconstructed.terminal_reason, final_case.terminal_reason)

    def test_exceeding_two_fix_attempts_leads_to_blocked_limit_exceeded(self) -> None:
        triage = _StubTriage(
            TriageRecord(
                input="200 com 10%",
                expected="R$ 180,00",
                observed="R$ 200,00",
                suspect_files=["checkout.py"],
                confidence=0.9,
            )
        )
        repro = _StubReproduction(
            ReproResult(
                test_path="tests/test_repro.py",
                test_source_ref="evidence/repro.py",
                exit_code=1,
                outcome=ReproOutcome.RED_ON_ASSERTION,
                failing_assertion="AssertionError",
            )
        )
        fix = _StubFix(
            Patch(
                diff_ref="evidence/bad.diff",
                files_changed=["checkout.py"],
                touches_tests=False,
                touches_ci=False,
            )
        )
        rejected_verdict = Verdict(
            before=ContractTestRun("pytest", 1, 0.1, "before.log"),
            after=ContractTestRun("pytest", 1, 0.1, "after.log"),
            suite=ContractTestRun("pytest", 0, 0.1, "suite.log"),
            base_revision="rev-base",
            fix_revision="rev-bad",
            result=VerdictResult.REJECTED,
            reasons=["after test still failing"],
        )
        verification = _StubVerification([rejected_verdict, rejected_verdict])

        orch = Orchestrator(
            triage=triage,
            reproduction=repro,
            fix=fix,
            verification=verification,
            store=self.store,
        )
        final_case = orch.run(_make_initial_case("case-fix-limit"))

        self.assertEqual(final_case.state, CaseState.BLOCKED)
        self.assertEqual(extract_terminal_reason_code(final_case.terminal_reason), "limit_exceeded")
        self.assertEqual(final_case.attempts.fix, 2)
        self.assertEqual(fix.calls, 2)

        reconstructed = self.store.reconstruct_state("case-fix-limit", _make_initial_case("case-fix-limit"))
        self.assertEqual(reconstructed.state, CaseState.BLOCKED)
        self.assertEqual(extract_terminal_reason_code(reconstructed.terminal_reason), "limit_exceeded")

    def test_exceeding_12_llm_calls_leads_to_blocked_limit_exceeded(self) -> None:
        base = _make_initial_case("case-llm-limit")
        case = RunState(
            case_id=base.case_id,
            client_id=base.client_id,
            repo_ref=base.repo_ref,
            channel=base.channel,
            report_text=base.report_text,
            state=base.state,
            created_at=base.created_at,
            updated_at=base.updated_at,
            attempts=Attempts(fix=0, llm_calls=12),
        )

        triage = _StubTriage(
            TriageRecord(
                input="200",
                expected="180",
                observed="200",
                suspect_files=["checkout.py"],
            ),
            raise_limit=True,
        )
        repro = _StubReproduction(
            ReproResult("t.py", "ref", 1, ReproOutcome.RED_ON_ASSERTION)
        )
        fix = _StubFix(Patch("d.diff", ["checkout.py"]))
        verification = _StubVerification([])

        orch = Orchestrator(
            triage=triage,
            reproduction=repro,
            fix=fix,
            verification=verification,
            store=self.store,
        )
        final_case = orch.run(case)

        self.assertEqual(final_case.state, CaseState.BLOCKED)
        self.assertEqual(extract_terminal_reason_code(final_case.terminal_reason), "limit_exceeded")

    def test_environment_error_in_reproduction_leads_to_infra_error_never_reproduced(self) -> None:
        triage = _StubTriage(
            TriageRecord(
                input="200",
                expected="180",
                observed="200",
                suspect_files=["checkout.py"],
            )
        )
        repro = _StubReproduction(
            ReproResult(
                test_path="tests/test_repro.py",
                test_source_ref="evidence/repro.py",
                exit_code=2,
                outcome=ReproOutcome.ENV_ERROR,
                log_ref="evidence/env_err.log",
            )
        )
        fix = _StubFix(Patch("d.diff", ["checkout.py"]))
        verification = _StubVerification([])

        orch = Orchestrator(
            triage=triage,
            reproduction=repro,
            fix=fix,
            verification=verification,
            store=self.store,
        )
        final_case = orch.run(_make_initial_case("case-env-err"))

        self.assertEqual(final_case.state, CaseState.INFRA_ERROR)
        self.assertIsNotNone(final_case.terminal_reason)
        self.assertEqual(fix.calls, 0)

        events = self.store.read_events("case-env-err")
        reached_states = [e.to_state for e in events if e.to_state is not None]
        self.assertNotIn(CaseState.REPRODUCED, reached_states)
        self.assertEqual(reached_states[-1], CaseState.INFRA_ERROR)

    def test_needs_info_terminates_cleanly_without_calling_reproduction_or_fix(self) -> None:
        triage = _StubTriage(
            NeedsInfo(
                missing_fields=["expected", "observed"],
                question_to_support="Qual era o valor esperado e o valor observado?",
            )
        )
        repro = _StubReproduction(
            ReproResult("t.py", "ref", 1, ReproOutcome.RED_ON_ASSERTION)
        )
        fix = _StubFix(Patch("d.diff", ["checkout.py"]))
        verification = _StubVerification([])

        orch = Orchestrator(
            triage=triage,
            reproduction=repro,
            fix=fix,
            verification=verification,
            store=self.store,
        )
        final_case = orch.run(_make_initial_case("case-needs-info"))

        self.assertEqual(final_case.state, CaseState.NEEDS_INFO)
        self.assertIn("valor esperado", extract_terminal_reason_code(final_case.terminal_reason))
        self.assertEqual(fix.calls, 0)

    def test_evidence_store_saves_artifact_with_sha256_and_rejects_traversal(self) -> None:
        ev = self.store.save_evidence(
            case_id="case-ev-1",
            evidence_id="ev-001",
            kind=EvidenceKind.DIFF,
            content="--- a/checkout.py\n+++ b/checkout.py\n",
            extension="diff",
            revision="abc1234",
        )
        self.assertEqual(ev.path, "evidence/ev-001.diff")
        self.assertEqual(len(ev.sha256), 64)
        self.assertTrue((self.runs_dir / "case-ev-1" / ev.path).is_file())

        with self.assertRaises(ValueError):
            self.store.save_evidence(
                case_id="../escape",
                evidence_id="ev-001",
                kind=EvidenceKind.DIFF,
                content="x",
                extension="diff",
            )


if __name__ == "__main__":
    unittest.main()
