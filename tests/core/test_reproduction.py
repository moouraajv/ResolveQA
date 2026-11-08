"""Tests for the Reproduction stage (Issue #10 / Tarefa D, RF-04, RFC-0001 §3.3)."""

from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any, Optional

from resolveqa.contracts import (
    Attempts,
    CaseState,
    ChannelType,
    EvidenceKind,
    ExecResult,
    ReproOutcome,
    ReproResult,
    ReproductionStage,
    RunState,
    SandboxStage,
    TriageRecord,
)
from resolveqa.llm import LLMAdapter, LLMOutputError
from resolveqa.reproduction import Reproduction, ReproductionEngine
from resolveqa.sandbox import LocalSandbox

REPO_ROOT = Path(__file__).resolve().parents[2]
DEMO_TARGET_CHECKOUT = REPO_ROOT / "demo-target" / "checkout.py"


def _make_case(
    report_text: str = (
        "Fiz uma compra de R$ 200,00 e apliquei um cupom de 10% (DESC10). "
        "O valor esperado era R$ 180,00, mas o valor observado foi R$ 200,00."
    ),
    *,
    case_id: str = "case-repro-001",
    repo_ref: str = "demo-target",
    base_revision: Optional[str] = "rev-base-12345",
) -> RunState:
    return RunState(
        case_id=case_id,
        client_id="client-demo",
        repo_ref=repo_ref,
        channel=ChannelType.SIMULATED_CHAT,
        report_text=report_text,
        state=CaseState.REPRODUCING,
        created_at="2026-11-08T00:00:00Z",
        updated_at="2026-11-08T00:00:00Z",
        attempts=Attempts(),
        base_revision=base_revision,
    )


def _make_triage(
    *,
    input_desc: str = "compra de R$ 200,00 com cupom de 10%",
    expected: str = "R$ 180,00",
    observed: str = "R$ 200,00",
) -> TriageRecord:
    return TriageRecord(
        input=input_desc,
        expected=expected,
        observed=observed,
        suspect_files=["checkout.py"],
        confidence=0.95,
    )


class TestReproductionStage(unittest.TestCase):
    """Validate Issue #10 acceptance criteria, QA regressions, and team decisions."""

    def test_satisfies_reproduction_stage_protocol(self) -> None:
        repro = Reproduction()
        self.assertIsInstance(repro, ReproductionStage)
        self.assertIs(Reproduction, ReproductionEngine)

    def test_generated_test_fails_on_buggy_demo_target_with_red_on_assertion_and_stores_evidences(self) -> None:
        """Critérios 1, 3 e B4: Teste gerado falha com red_on_assertion, grava evidências com EvidenceStore, base_revision e simulated=True."""
        checkout_before = DEMO_TARGET_CHECKOUT.read_text(encoding="utf-8")
        case = _make_case()
        case_snapshot = copy.deepcopy(case.to_dict())
        triage = _make_triage()

        with tempfile.TemporaryDirectory() as tmp_runs:
            repro = Reproduction(
                llm=LLMAdapter(),
                sandbox=LocalSandbox(base_root=REPO_ROOT),
                runs_root=tmp_runs,
            )
            result = repro.run(case, triage)

            # Immutability of RunState and demo-target/
            self.assertEqual(case.to_dict(), case_snapshot)
            self.assertEqual(DEMO_TARGET_CHECKOUT.read_text(encoding="utf-8"), checkout_before)
            self.assertEqual(repro.get_llm_calls(case), 1)

            self.assertIsInstance(result, ReproResult)
            self.assertEqual(result.outcome, ReproOutcome.RED_ON_ASSERTION)
            self.assertNotEqual(result.exit_code, 0)
            self.assertIsNotNone(result.failing_assertion)
            assert result.failing_assertion is not None
            self.assertIn("180", result.failing_assertion)

            # B4: EvidenceStore with base_revision and simulated=True
            evidences = repro.last_evidence_by_case[case.case_id]
            self.assertEqual(len(evidences), 3)
            for ev in evidences:
                self.assertEqual(ev.revision, "rev-base-12345")
                self.assertTrue(ev.simulated)

            case_dir = Path(tmp_runs) / case.case_id
            for ev in evidences:
                ev_file = case_dir / ev.path
                self.assertTrue(ev_file.is_file(), f"Missing evidence file: {ev_file}")

    def test_b1_three_false_red_cases_proven_by_qa_are_rejected(self) -> None:
        """B1 regression: assert no nível do módulo, AssertionError no setUp e assertEqual(len('abc'), 200) NUNCA são classificados como RED_ON_ASSERTION."""
        triage = _make_triage(expected="R$ 180,00", observed="R$ 200,00")

        # 1. Assert no nível do módulo
        module_level_assert_code = (
            "import unittest\n"
            "assert 180 == 200\n\n"
            "class TestModAssert(unittest.TestCase):\n"
            "    def test_dummy(self) -> None:\n"
            "        self.assertEqual(180, 180)\n"
        )
        case1 = _make_case(case_id="case-b1-mod")
        with tempfile.TemporaryDirectory() as tmp_runs:
            repro = Reproduction(
                llm=LLMAdapter(response_override=module_level_assert_code),
                sandbox=LocalSandbox(base_root=REPO_ROOT),
                runs_root=tmp_runs,
            )
            res1 = repro.run(case1, triage)
            self.assertNotEqual(res1.outcome, ReproOutcome.RED_ON_ASSERTION)

        # 2. AssertionError no setUp
        setup_assert_code = (
            "import unittest\n\n"
            "class TestSetupAssert(unittest.TestCase):\n"
            "    def setUp(self) -> None:\n"
            "        self.assertEqual(180, 200)\n\n"
            "    def test_dummy(self) -> None:\n"
            "        self.assertEqual(180, 180)\n"
        )
        case2 = _make_case(case_id="case-b1-setup")
        with tempfile.TemporaryDirectory() as tmp_runs:
            repro = Reproduction(
                llm=LLMAdapter(response_override=setup_assert_code),
                sandbox=LocalSandbox(base_root=REPO_ROOT),
                runs_root=tmp_runs,
            )
            res2 = repro.run(case2, triage)
            self.assertNotEqual(res2.outcome, ReproOutcome.RED_ON_ASSERTION)

        # 3. assertEqual(len('abc'), 200) — sem o valor esperado 180 na comparação que falhou
        unrelated_assert_code = (
            "import unittest\n\n"
            "class TestUnrelatedAssert(unittest.TestCase):\n"
            "    def test_len_mismatch(self) -> None:\n"
            "        # Uses 180 in dummy comment\n"
            "        self.assertEqual(len('abc'), 200)\n"
        )
        case3 = _make_case(case_id="case-b1-len")
        with tempfile.TemporaryDirectory() as tmp_runs:
            repro = Reproduction(
                llm=LLMAdapter(response_override=unrelated_assert_code),
                sandbox=LocalSandbox(base_root=REPO_ROOT),
                runs_root=tmp_runs,
            )
            # B7 check rejects assertion not comparing expected, or if forced, classifies as GREEN (not RED)
            try:
                res3 = repro.run(case3, triage)
                self.assertNotEqual(res3.outcome, ReproOutcome.RED_ON_ASSERTION)
                self.assertEqual(res3.outcome, ReproOutcome.GREEN)
            except LLMOutputError:
                pass  # B7 guard successfully caught unasserted expected value

    def test_b2_delegating_sandbox_and_missing_repo_ref(self) -> None:
        """B2 & B5: Sandbox delegada roda no diretório preparado com o teste, e repo_ref inexistente falha explicitamente."""
        triage = _make_triage()

        class DelegatingSandbox(SandboxStage):
            def __init__(self, inner: SandboxStage) -> None:
                self.inner = inner
                self.recorded_calls: list[tuple[str, str]] = []

            def exec(
                self,
                repo_ref: str,
                command: str,
                env: Optional[dict[str, str]] = None,
                timeout_s: Optional[float] = None,
            ) -> ExecResult:
                self.recorded_calls.append((repo_ref, command))
                return self.inner.exec(repo_ref, command, timeout_s=timeout_s)

        inner_sandbox = LocalSandbox(base_root=REPO_ROOT)
        delegating_sandbox = DelegatingSandbox(inner_sandbox)

        case = _make_case(case_id="case-b2-delegating")
        with tempfile.TemporaryDirectory() as tmp_runs:
            repro = Reproduction(
                llm=LLMAdapter(),
                sandbox=delegating_sandbox,
                runs_root=tmp_runs,
            )
            res = repro.run(case, triage)
            self.assertEqual(res.outcome, ReproOutcome.RED_ON_ASSERTION)
            self.assertGreaterEqual(len(delegating_sandbox.recorded_calls), 1)

            # Target demo-target original was never modified
            self.assertFalse((REPO_ROOT / "demo-target" / "tests" / "test_repro_generated.py").exists())

        # Inexistent repo_ref fails explicitly with ENV_ERROR
        case_missing = _make_case(repo_ref="non_existent_target_repo_xyz", case_id="case-b2-missing")
        with tempfile.TemporaryDirectory() as tmp_runs:
            repro = Reproduction(llm=LLMAdapter(), sandbox=inner_sandbox, runs_root=tmp_runs)
            res_missing = repro.run(case_missing, triage)
            self.assertEqual(res_missing.outcome, ReproOutcome.ENV_ERROR)

    def test_b3_target_exceptions_and_unrelated_assertions_are_green_not_env_error(self) -> None:
        """B3 DECISÃO DA EQUIPE: TypeError, AttributeError, NameError do código-alvo devolvem resultado não reproduzido (GREEN) para o orquestrador bloquear como not_reproduced, NUNCA env_error."""
        triage = _make_triage()

        type_error_code = (
            "import unittest\n"
            "from checkout import calculate_total\n\n"
            "class TestTypeError(unittest.TestCase):\n"
            "    def test_calls_with_invalid_type(self) -> None:\n"
            "        self.assertEqual(180, 180)  # satisfy B7\n"
            "        calculate_total(None)  # raises TypeError\n"
        )
        case_te = _make_case(case_id="case-b3-te")
        with tempfile.TemporaryDirectory() as tmp_runs:
            repro = Reproduction(
                llm=LLMAdapter(response_override=type_error_code),
                sandbox=LocalSandbox(base_root=REPO_ROOT),
                runs_root=tmp_runs,
            )
            res_te = repro.run(case_te, triage)
            self.assertEqual(res_te.outcome, ReproOutcome.GREEN)
            self.assertIsNone(res_te.failing_assertion)

        attribute_error_code = (
            "import unittest\n"
            "from checkout import calculate_total\n\n"
            "class TestAttrError(unittest.TestCase):\n"
            "    def test_calls_attr(self) -> None:\n"
            "        self.assertEqual(180, 180)  # satisfy B7\n"
            "        calculate_total.non_existent_attr()\n"
        )
        case_ae = _make_case(case_id="case-b3-ae")
        with tempfile.TemporaryDirectory() as tmp_runs:
            repro = Reproduction(
                llm=LLMAdapter(response_override=attribute_error_code),
                sandbox=LocalSandbox(base_root=REPO_ROOT),
                runs_root=tmp_runs,
            )
            res_ae = repro.run(case_ae, triage)
            self.assertEqual(res_ae.outcome, ReproOutcome.GREEN)
            self.assertIsNone(res_ae.failing_assertion)

    def test_b6_and_b7_override_restoration_and_assertion_guard(self) -> None:
        """B6/B7: llm.response_override é restaurado com segurança e o guard exige que o valor esperado esteja na asserção."""
        llm = LLMAdapter()
        triage = _make_triage(expected="R$ 180,00")
        case = _make_case(case_id="case-b6")

        repro = Reproduction(llm=llm, sandbox=LocalSandbox(base_root=REPO_ROOT))
        self.assertIsNone(llm.response_override)
        res = repro.run(case, triage)
        self.assertIsNone(llm.response_override)

        # B7: Test code having the expected number only in a comment while the assertion does not compare it -> LLMOutputError
        comment_only_code = (
            "import unittest\n\n"
            "# The expected value was 180.0\n"
            "class TestCommentOnly(unittest.TestCase):\n"
            "    def test_unrelated(self) -> None:\n"
            "        self.assertEqual(1, 1)\n"
        )
        with self.assertRaises(LLMOutputError):
            llm_comment = LLMAdapter(response_override=comment_only_code)
            repro_b7 = Reproduction(llm=llm_comment, sandbox=LocalSandbox(base_root=REPO_ROOT))
            repro_b7.run(case, triage)


if __name__ == "__main__":
    unittest.main()
