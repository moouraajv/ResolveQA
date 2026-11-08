"""Edge tests for local unpublished evidence package (issue #16, RF-08)."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from resolveqa.contracts import (
    CaseState,
    ChannelType,
    DeliveryKind,
    RunState,
    Verdict,
    VerdictResult,
)
from resolveqa.contracts.stages import TestRun as ContractTestRun
from resolveqa.delivery import DeliveryBuilder, DeliveryError


def _verified_case(case_id: str = "case-delivery-1") -> RunState:
    return RunState(
        case_id=case_id,
        client_id="client-demo",
        repo_ref="demo-target",
        channel=ChannelType.API,
        report_text="Cupom 10% em R$ 200 retornou R$ 200 em vez de R$ 180.",
        state=CaseState.VERIFIED,
        created_at="2026-11-07T12:00:00Z",
        updated_at="2026-11-07T12:10:00Z",
        base_revision="base-sha",
        fix_revision="fix-sha",
    )


def _verified_verdict() -> Verdict:
    return Verdict(
        before=ContractTestRun(
            command="pytest -q",
            exit_code=1,
            duration_s=0.2,
            log_ref="evidence/before.log",
        ),
        after=ContractTestRun(
            command="pytest -q",
            exit_code=0,
            duration_s=0.2,
            log_ref="evidence/after.log",
        ),
        suite=ContractTestRun(
            command="pytest -q",
            exit_code=0,
            duration_s=0.4,
            log_ref="evidence/suite.log",
        ),
        base_revision="base-sha",
        fix_revision="fix-sha",
        result=VerdictResult.VERIFIED,
        reasons=("red_before_green_after",),
    )


def _seed_evidence(runs: Path, case_id: str) -> None:
    evidence = runs / case_id / "evidence"
    evidence.mkdir(parents=True)
    (evidence / "cause.txt").write_text(
        "Cupom percentual não era aplicado no total.\n",
        encoding="utf-8",
    )
    (evidence / "diff.patch").write_text(
        "--- a/checkout.py\n+++ b/checkout.py\n@@\n-return total\n+return total * 0.9\n",
        encoding="utf-8",
    )
    (evidence / "before.log").write_text("FAILED test_checkout\n", encoding="utf-8")
    (evidence / "after.log").write_text("PASSED test_checkout\n", encoding="utf-8")
    (evidence / "suite.log").write_text("2 passed\n", encoding="utf-8")


class TestDeliveryLocalPackage(unittest.TestCase):
    def test_package_contains_report_cause_diff_tests_and_limits(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runs = Path(tmp) / "runs"
            repo_root = Path(__file__).resolve().parents[2]
            case = _verified_case()
            _seed_evidence(runs, case.case_id)
            builder = DeliveryBuilder(
                runs_root=runs,
                limits_path=repo_root / "config" / "limits.json",
            )
            result = builder.build(case, _verified_verdict())
            self.assertEqual(result.kind, DeliveryKind.LOCAL_PACKAGE)
            self.assertEqual(result.label, "PR não publicado")
            package = Path(result.url_or_path)
            self.assertTrue(package.is_dir())
            for name in [
                "README.md",
                "report.md",
                "cause.md",
                "diff.patch",
                "before.log",
                "after.log",
                "suite.log",
                "limits.json",
                "verdict.json",
                "MANIFEST.json",
            ]:
                self.assertTrue((package / name).is_file(), name)
                self.assertGreater((package / name).stat().st_size, 0)

            report = (package / "report.md").read_text(encoding="utf-8")
            self.assertIn("R$ 180", report)
            cause = (package / "cause.md").read_text(encoding="utf-8")
            self.assertIn("Cupom", cause)
            limits = json.loads((package / "limits.json").read_text(encoding="utf-8"))
            self.assertEqual(limits["max_fix_attempts"], 2)
            manifest = json.loads((package / "MANIFEST.json").read_text(encoding="utf-8"))
            self.assertIs(manifest["auto_merge"], False)
            for rel in result.evidence_refs:
                self.assertTrue((runs / case.case_id / rel).is_file(), rel)

    def test_every_link_exists_and_no_auto_merge(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runs = Path(tmp) / "runs"
            case = _verified_case("case-delivery-2")
            _seed_evidence(runs, case.case_id)
            builder = DeliveryBuilder(runs_root=runs)
            result = builder.build(case, _verified_verdict())
            readme = Path(result.url_or_path).joinpath("README.md").read_text(encoding="utf-8")
            self.assertIn("não", readme.lower())
            self.assertIn("merge", readme.lower())
            self.assertFalse(any("merge" == part for part in result.to_dict()))

    def test_rejects_unverified_or_missing_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runs = Path(tmp) / "runs"
            builder = DeliveryBuilder(runs_root=runs)
            case = _verified_case()
            with self.assertRaises(DeliveryError):
                builder.build(case, _verified_verdict())
            _seed_evidence(runs, case.case_id)
            bad = RunState(
                case_id=case.case_id,
                client_id=case.client_id,
                repo_ref=case.repo_ref,
                channel=case.channel,
                report_text=case.report_text,
                state=CaseState.FIXED,
                created_at=case.created_at,
                updated_at=case.updated_at,
            )
            with self.assertRaises(DeliveryError):
                builder.build(bad, _verified_verdict())


if __name__ == "__main__":
    unittest.main()
