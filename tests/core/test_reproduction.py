"""Tests for the Reproduction stage (Issue #10 / Tarefa D, RF-04, RFC-0001 §3.3)."""

from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

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
    """Validate Issue #10 acceptance criteria and safety invariants."""

    def test_satisfies_reproduction_stage_protocol(self) -> None:
        repro = Reproduction()
        self.assertIsInstance(repro, ReproductionStage)
        self.assertIs(Reproduction, ReproductionEngine)

    def test_generated_test_fails_on_buggy_demo_target_with_red_on_assertion_and_stores_evidences(self) -> None:
        """Critérios 1 e 3: O teste gerado falha na versão com defeito na asserção ligada ao relato (red_on_assertion) e grava código do teste, log e exit code como evidência."""
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
            self.assertTrue(
                "180" in result.failing_assertion or "200" in result.failing_assertion,
                f"Expected failing_assertion to mention report values, got: {result.failing_assertion!r}",
            )

            # Criterion 3: test source, log, and exit code saved as distinct evidences
            evidences = repro.last_evidence_by_case[case.case_id]
            self.assertEqual(len(evidences), 3)
            kinds = {ev.kind for ev in evidences}
            self.assertEqual(
                kinds,
                {EvidenceKind.TEST_SOURCE, EvidenceKind.TEST_LOG, EvidenceKind.EXIT_CODE},
            )
            ev_ids = {ev.evidence_id for ev in evidences}
            self.assertEqual(len(ev_ids), 3)

            case_dir = Path(tmp_runs) / case.case_id
            for ev in evidences:
                ev_file = case_dir / ev.path
                self.assertTrue(ev_file.is_file(), f"Missing evidence file: {ev_file}")
                if ev.kind == EvidenceKind.TEST_SOURCE:
                    self.assertEqual(result.test_source_ref, ev.path)
                    self.assertIn("calculate_total", ev_file.read_text(encoding="utf-8"))
                elif ev.kind == EvidenceKind.TEST_LOG:
                    self.assertEqual(result.log_ref, ev.path)
                    self.assertIn("AssertionError", ev_file.read_text(encoding="utf-8"))
                elif ev.kind == EvidenceKind.EXIT_CODE:
                    exit_payload = json.loads(ev_file.read_text(encoding="utf-8"))
                    self.assertEqual(exit_payload["exit_code"], result.exit_code)
                    self.assertEqual(exit_payload["outcome"], "red_on_assertion")

    def test_reproduction_uses_report_specific_values_300_270(self) -> None:
        """Regra do benchmark: O teste de reprodução usa os valores do relato (R$ 300,00 / R$ 270,00), nunca valores fixos de exemplo."""
        case_300 = _make_case(
            "Fiz uma compra de R$ 300,00 com cupom de 10%. O valor esperado era R$ 270,00, mas o observado foi R$ 300,00.",
            case_id="case-repro-300",
        )
        triage_300 = _make_triage(
            input_desc="compra de R$ 300,00 com cupom de 10%",
            expected="R$ 270,00",
            observed="R$ 300,00",
        )
        with tempfile.TemporaryDirectory() as tmp_runs:
            repro = Reproduction(
                llm=LLMAdapter(),
                sandbox=LocalSandbox(base_root=REPO_ROOT),
                runs_root=tmp_runs,
            )
            result = repro.run(case_300, triage_300)
            self.assertEqual(result.outcome, ReproOutcome.RED_ON_ASSERTION)
            assert result.failing_assertion is not None
            self.assertTrue("270" in result.failing_assertion or "300" in result.failing_assertion)

            source_path = Path(tmp_runs) / case_300.case_id / result.test_source_ref
            source_code = source_path.read_text(encoding="utf-8")
            self.assertIn("300", source_code)
            self.assertIn("270", source_code)
            self.assertNotIn("180", source_code)

    def test_import_error_or_environment_failure_is_classified_as_env_error(self) -> None:
        """Critério 2: Erro de importação ou ambiente é classificado como env_error."""
        bad_import_test_code = (
            "import unittest\n"
            "import non_existent_checkout_module_xyz\n\n"
            "class TestBrokenImport(unittest.TestCase):\n"
            "    def test_broken(self) -> None:\n"
            "        self.assertEqual(180, 180)\n"
        )
        case = _make_case(case_id="case-repro-enverr")
        triage = _make_triage()

        with tempfile.TemporaryDirectory() as tmp_runs:
            repro = Reproduction(
                llm=LLMAdapter(response_override=bad_import_test_code),
                sandbox=LocalSandbox(base_root=REPO_ROOT),
                runs_root=tmp_runs,
            )
            result = repro.run(case, triage)
            self.assertEqual(result.outcome, ReproOutcome.ENV_ERROR)
            self.assertIsNone(result.failing_assertion)

            # Timeout in sandbox also classifies as env_error
            class _TimeoutSandbox:
                def exec(self, workdir_ref: str, command: str, timeout_s: float = 60.0) -> ExecResult:
                    return ExecResult(
                        exit_code=124,
                        stdout_ref="",
                        stderr_ref="Command timed out after 60s",
                        timed_out=True,
                    )

            repro_timeout = Reproduction(
                llm=LLMAdapter(),
                sandbox=_TimeoutSandbox(),
                runs_root=tmp_runs,
            )
            case_to = _make_case(case_id="case-repro-timeout")
            res_to = repro_timeout.run(case_to, triage)
            self.assertEqual(res_to.outcome, ReproOutcome.ENV_ERROR)
            self.assertIsNone(res_to.failing_assertion)

    def test_passing_test_is_classified_as_green(self) -> None:
        """Se o teste gerado passar (exit_code == 0), o resultado é classificado como green."""
        passing_test_code = (
            "import unittest\n"
            "from checkout import calculate_total\n\n"
            "class TestPassing(unittest.TestCase):\n"
            "    def test_passes_with_buggy_200(self) -> None:\n"
            "        # Uses 180 in comment/var but asserts 200.0 == 200.0\n"
            "        expected_hint = 180.0\n"
            "        self.assertEqual(calculate_total(200.0, coupon_percent=0.0), 200.0)\n"
        )
        case = _make_case(case_id="case-repro-green")
        triage = _make_triage()
        with tempfile.TemporaryDirectory() as tmp_runs:
            repro = Reproduction(
                llm=LLMAdapter(response_override=passing_test_code),
                sandbox=LocalSandbox(base_root=REPO_ROOT),
                runs_root=tmp_runs,
            )
            result = repro.run(case, triage)
            self.assertEqual(result.outcome, ReproOutcome.GREEN)
            self.assertEqual(result.exit_code, 0)
            self.assertIsNone(result.failing_assertion)


if __name__ == "__main__":
    unittest.main()
