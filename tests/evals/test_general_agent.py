"""Evals for general agent mode: positive fix, needs_info, forbidden path."""

from __future__ import annotations

import unittest
from dataclasses import replace
from pathlib import Path

from resolveqa.contracts import (
    CaseState,
    ChannelType,
    NeedsInfo,
    ReproOutcome,
    ReproResult,
    ReportInput,
    TriageRecord,
)
from resolveqa.demo.llm import create_demo_llm
from resolveqa.fix.engine import PatchRejected
from resolveqa.intake import Intake
from resolveqa.pipeline import run_pipeline
from resolveqa.pipeline.gates import PlaybookGatedFix, PlaybookGatedTriage
from resolveqa.playbook import load_playbook

ROOT = Path(__file__).resolve().parents[2]
COUPON = (
    "Comprei R$ 200,00 no site, apliquei o cupom DESC10 de 10% "
    "e o total continuou R$ 200,00. Deveria ser R$ 180,00."
)
VAGUE = "O checkout está estranho, o valor não bate."


class GeneralAgentEvals(unittest.TestCase):
    def test_positive_coupon_verified_with_llm_fix(self) -> None:
        case = Intake().create(
            ReportInput(
                client_id="resolveqa",
                repo_ref="targets/resolveqa-checkout",
                channel=ChannelType.API,
                report_text=COUPON,
            )
        )
        result = run_pipeline(
            case,
            root=ROOT,
            llm=create_demo_llm(real=False),
            real=False,
            mode="general",
        )
        self.assertEqual(result.case.state, CaseState.VERIFIED)

    def test_vague_report_needs_info(self) -> None:
        case = Intake().create(
            ReportInput(
                client_id="resolveqa",
                repo_ref="targets/resolveqa-checkout",
                channel=ChannelType.API,
                report_text=VAGUE,
            )
        )
        result = run_pipeline(
            case,
            root=ROOT,
            llm=create_demo_llm(real=False),
            real=False,
            mode="general",
        )
        self.assertEqual(result.case.state, CaseState.NEEDS_INFO)

    def test_forbidden_path_rejected_by_playbook_gate(self) -> None:
        playbook = load_playbook(ROOT / "targets" / "resolveqa-checkout")
        triage = TriageRecord(
            input="x",
            expected="y",
            observed="z",
            suspect_files=["tests/test_checkout.py"],
            confidence=0.9,
        )
        gated = PlaybookGatedTriage(
            inner=type("T", (), {"run": staticmethod(lambda _c: triage)})(),
            playbook=playbook,
        )
        out = gated.run(
            Intake().create(
                ReportInput(
                    client_id="resolveqa",
                    repo_ref="targets/resolveqa-checkout",
                    channel=ChannelType.API,
                    report_text=COUPON,
                )
            )
        )
        self.assertIsInstance(out, NeedsInfo)

    def test_fix_gate_rejects_protected_suspect(self) -> None:
        playbook = load_playbook(ROOT / "targets" / "resolveqa-checkout")

        class _Boom:
            def run(self, case, triage, repro):  # noqa: ANN001
                raise AssertionError("inner fix must not run for protected suspects")

        gated = PlaybookGatedFix(_Boom(), playbook)
        case = Intake().create(
            ReportInput(
                client_id="resolveqa",
                repo_ref="targets/resolveqa-checkout",
                channel=ChannelType.API,
                report_text=COUPON,
            )
        )
        triage = TriageRecord(
            input="x",
            expected="y",
            observed="z",
            suspect_files=["tests/test_checkout.py"],
            confidence=0.9,
        )
        repro = ReproResult(
            outcome=ReproOutcome.RED_ON_ASSERTION,
            test_path="tests/generated_repro.py",
            test_source_ref="evidence/repro.py",
            log_ref="evidence/repro.log",
            exit_code=1,
            failing_assertion="assert equal",
        )
        with self.assertRaises(PatchRejected):
            gated.run(case, triage, repro)

    def test_playbook_allows_checkout_only(self) -> None:
        playbook = load_playbook(ROOT / "targets" / "resolveqa-checkout")
        self.assertTrue(playbook.is_path_allowed("checkout.py"))
        self.assertFalse(playbook.is_path_allowed("tests/test_checkout.py"))
        self.assertTrue(playbook.is_path_forbidden(".resolveqa/playbook.toml"))


if __name__ == "__main__":
    unittest.main()
