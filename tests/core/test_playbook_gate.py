"""Unit tests for Playbook Gate in Verification stage (Issue #23).

Validates:
- Hunks in paths.forbidden[] are rejected before being applied.
- Hunks outside paths.allowed[] are rejected.
- Modifications to tests.protected[] or .resolveqa/playbook.toml lead to rejected verdict.
- Playbook limits are enforced when stricter than defaults.
- Verdict records policy rules and sha256 of the playbook.
- Missing playbook falls back to default RFC policy.
- Invalid playbook is refused with clear error.
- Purely deterministic decision without LLM calls.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch as mock_patch

from resolveqa.contracts import (
    CaseState,
    ChannelType,
    Patch,
    ReproOutcome,
    ReproResult,
    RunState,
    VerdictResult,
)
from resolveqa.contracts.run_state import Attempts
from resolveqa.playbook import Playbook, PlaybookLimits
from resolveqa.verification import (
    PlaybookGate,
    PlaybookGateResult,
    PolicyRuleResult,
    Verification,
    evaluate_playbook_gate,
    extract_diff_target_paths,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
DEMO_TARGET_DIR = REPO_ROOT / "demo-target"

VALID_COUPON_PATCH_DIFF = """\
--- a/checkout.py
+++ b/checkout.py
@@ -32,5 +32,5 @@
         raise ValueError("coupon_percent must be between 0 and 100")

     discount = round(float(subtotal) * (pct / 100.0), 2)
-    return round(float(subtotal), 2)
+    return round(float(subtotal) - discount, 2)
"""

COUPON_REPRO_SOURCE = """\
import unittest
from checkout import calculate_total, format_brl


class TestCouponDiscountRepro(unittest.TestCase):
    def test_apply_10_percent_coupon_on_200_brl(self) -> None:
        total = calculate_total(200.0, coupon_percent=10.0)
        self.assertEqual(total, 180.0)
        self.assertEqual(format_brl(total), "R$ 180,00")


if __name__ == "__main__":
    unittest.main()
"""


def _make_case(repo_ref: str = "demo-target", base_revision: str = "base-rev-001") -> RunState:
    return RunState(
        case_id="case-playbook-gate-001",
        client_id="client-demo",
        repo_ref=repo_ref,
        channel=ChannelType.SIMULATED_CHAT,
        report_text="Cupom de 10% em R$ 200 não aplicou desconto.",
        state=CaseState.VERIFYING,
        created_at="2026-11-08T00:00:00Z",
        updated_at="2026-11-08T00:01:00Z",
        base_revision=base_revision,
        attempts=Attempts(fix=0, llm_calls=0),
    )


def _make_repro(
    test_path: str = "tests/test_repro_coupon.py",
    test_source: str = COUPON_REPRO_SOURCE,
    exit_code: int = 1,
) -> ReproResult:
    return ReproResult(
        test_path=test_path,
        test_source_ref=test_source,
        exit_code=exit_code,
        outcome=ReproOutcome.RED_ON_ASSERTION,
        failing_assertion="AssertionError: 200.0 != 180.0",
        log_ref="AssertionError: 200.0 != 180.0",
    )


class TestPlaybookGate(unittest.TestCase):
    """Test suite for PlaybookGate and playbook application in Verification (Issue #23)."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.temp_root = Path(self.temp_dir.name).resolve()

        # Create isolated workspace mirror of demo-target
        self.repo_dir = self.temp_root / "repo"
        shutil.copytree(
            DEMO_TARGET_DIR,
            self.repo_dir,
            symlinks=True,
            ignore=shutil.ignore_patterns(".git", "__pycache__", ".pytest_cache", ".venv"),
        )

    def _write_playbook(self, content: str) -> Path:
        pb_path = self.repo_dir / ".resolveqa" / "playbook.toml"
        pb_path.parent.mkdir(parents=True, exist_ok=True)
        pb_path.write_text(content, encoding="utf-8")
        return pb_path

    def test_playbook_forbidding_patch_file_leads_to_rejected(self) -> None:
        """Hunk in paths.forbidden[] is rejected before being applied."""
        self._write_playbook("""\
version = 1
[paths]
allowed = ["**"]
forbidden = [".resolveqa/**", "checkout.py"]
""")
        verifier = Verification(allow_inline_test_source=True, base_root=self.temp_root)
        patch = Patch(
            diff_ref=VALID_COUPON_PATCH_DIFF,
            files_changed=("checkout.py",),
        )
        case = _make_case(repo_ref="repo")
        repro = _make_repro()

        verdict = verifier.run(case, repro, patch)
        self.assertEqual(verdict.result, VerdictResult.REJECTED)
        reasons_text = " ".join(verdict.reasons)
        self.assertIn("diff touches forbidden path 'checkout.py' (playbook)", reasons_text)
        self.assertIn("patch_rejected", reasons_text)

    def test_playbook_allowed_paths_refuses_patch_outside_allowed(self) -> None:
        """Hunk outside paths.allowed[] is rejected."""
        self._write_playbook("""\
version = 1
[paths]
allowed = ["src/**"]
forbidden = [".resolveqa/**"]
""")
        verifier = Verification(allow_inline_test_source=True, base_root=self.temp_root)
        patch = Patch(
            diff_ref=VALID_COUPON_PATCH_DIFF,
            files_changed=("checkout.py",),
        )
        case = _make_case(repo_ref="repo")
        repro = _make_repro()

        verdict = verifier.run(case, repro, patch)
        self.assertEqual(verdict.result, VerdictResult.REJECTED)
        reasons_text = " ".join(verdict.reasons)
        self.assertIn("not in allowed paths (playbook)", reasons_text)

    def test_missing_playbook_uses_default_rfc_policy(self) -> None:
        """Playbook ausente usa o padrão da RFC e permite patch válido."""
        pb_file = self.repo_dir / ".resolveqa" / "playbook.toml"
        if pb_file.exists():
            pb_file.unlink()

        verifier = Verification(allow_inline_test_source=True, base_root=self.temp_root)
        patch = Patch(
            diff_ref=VALID_COUPON_PATCH_DIFF,
            files_changed=("checkout.py",),
        )
        case = _make_case(repo_ref="repo")
        repro = _make_repro()

        verdict = verifier.run(case, repro, patch)
        self.assertEqual(verdict.result, VerdictResult.VERIFIED, f"Reasons: {verdict.reasons}")
        self.assertIsNone(verdict.playbook_sha256)
        self.assertIsNotNone(verdict.policy_rule)
        self.assertTrue(verdict.policy_rule.passed)
        self.assertTrue(verdict.playbook.is_default)

    def test_invalid_playbook_syntax_refused_with_clear_error(self) -> None:
        """Playbook com erro de sintaxe TOML é recusado com erro claro."""
        self._write_playbook("""\
version = 1
[paths
allowed = ["checkout.py"]
""")
        verifier = Verification(allow_inline_test_source=True, base_root=self.temp_root)
        patch = Patch(
            diff_ref=VALID_COUPON_PATCH_DIFF,
            files_changed=("checkout.py",),
        )
        case = _make_case(repo_ref="repo")
        repro = _make_repro()

        verdict = verifier.run(case, repro, patch)
        self.assertEqual(verdict.result, VerdictResult.REJECTED)
        reasons_text = " ".join(verdict.reasons)
        self.assertIn("playbook_invalid", reasons_text)
        self.assertIn("line 2", reasons_text)

    def test_invalid_playbook_schema_refused_with_clear_error(self) -> None:
        """Playbook com campos desconhecidos ou inválidos é recusado com erro claro."""
        self._write_playbook("""\
version = 1
[invalid_section]
forbidden_key = "abc"
""")
        verifier = Verification(allow_inline_test_source=True, base_root=self.temp_root)
        patch = Patch(
            diff_ref=VALID_COUPON_PATCH_DIFF,
            files_changed=("checkout.py",),
        )
        case = _make_case(repo_ref="repo")
        repro = _make_repro()

        verdict = verifier.run(case, repro, patch)
        self.assertEqual(verdict.result, VerdictResult.REJECTED)
        reasons_text = " ".join(verdict.reasons)
        self.assertIn("playbook_invalid", reasons_text)
        self.assertIn("invalid_section", reasons_text)

    def test_patch_modifying_playbook_itself_is_rejected(self) -> None:
        """Alteração no próprio playbook leva o veredito a rejected."""
        self._write_playbook("""\
version = 1
[paths]
allowed = ["**"]
""")
        playbook_tamper_diff = """\
--- a/.resolveqa/playbook.toml
+++ b/.resolveqa/playbook.toml
@@ -1,2 +1,3 @@
 version = 1
+# modified
"""
        verifier = Verification(allow_inline_test_source=True, base_root=self.temp_root)
        patch = Patch(
            diff_ref=playbook_tamper_diff,
            files_changed=(".resolveqa/playbook.toml",),
        )
        case = _make_case(repo_ref="repo")
        repro = _make_repro()

        verdict = verifier.run(case, repro, patch)
        self.assertEqual(verdict.result, VerdictResult.REJECTED)
        reasons_text = " ".join(verdict.reasons)
        self.assertIn("diff touches protected playbook '.resolveqa/playbook.toml'", reasons_text)

    def test_patch_modifying_custom_protected_tests_is_rejected(self) -> None:
        """Alteração em caminho de tests.protected[] leva o veredito a rejected."""
        self._write_playbook("""\
version = 1
[paths]
allowed = ["**"]
[tests]
protected = ["custom_tests/**"]
""")
        patch_diff = """\
--- a/custom_tests/test_audit.py
+++ b/custom_tests/test_audit.py
@@ -1,2 +1,3 @@
 assert True
+# modified
"""
        verifier = Verification(allow_inline_test_source=True, base_root=self.temp_root)
        patch = Patch(
            diff_ref=patch_diff,
            files_changed=("custom_tests/test_audit.py",),
        )
        case = _make_case(repo_ref="repo")
        repro = _make_repro()

        verdict = verifier.run(case, repro, patch)
        self.assertEqual(verdict.result, VerdictResult.REJECTED)
        reasons_text = " ".join(verdict.reasons)
        self.assertIn("diff touches protected test 'custom_tests/test_audit.py' (playbook)", reasons_text)

    def test_stricter_limits_in_playbook_are_applied(self) -> None:
        """Os limites do playbook são aplicados no lugar dos padrões quando forem mais restritos."""
        self._write_playbook("""\
version = 1
[paths]
allowed = ["**"]
[limits]
max_files_changed = 1
""")
        # Verifier allows 3 by default, but playbook restricts to 1
        two_file_diff = """\
--- a/checkout.py
+++ b/checkout.py
@@ -32,5 +32,5 @@
         raise ValueError("coupon_percent must be between 0 and 100")

     discount = round(float(subtotal) * (pct / 100.0), 2)
-    return round(float(subtotal), 2)
+    return round(float(subtotal) - discount, 2)
--- a/helper.py
+++ b/helper.py
@@ -1,1 +1,2 @@
 x = 1
+y = 2
"""
        verifier = Verification(allow_inline_test_source=True, base_root=self.temp_root)
        patch = Patch(
            diff_ref=two_file_diff,
            files_changed=("checkout.py", "helper.py"),
        )
        case = _make_case(repo_ref="repo")
        repro = _make_repro()

        verdict = verifier.run(case, repro, patch)
        self.assertEqual(verdict.result, VerdictResult.REJECTED)
        reasons_text = " ".join(verdict.reasons)
        self.assertIn("exceeds playbook max_files_changed (1)", reasons_text)

    def test_verdict_records_policy_rule_and_playbook_sha256(self) -> None:
        """O Verdict registra uma regra de política com resultado e o sha256 do playbook usado."""
        pb_content = """\
version = 1
[paths]
allowed = ["checkout.py"]
forbidden = [".resolveqa/**", "tests/**"]
"""
        pb_path = self._write_playbook(pb_content)
        expected_sha = hashlib.sha256(pb_path.read_bytes()).hexdigest()

        verifier = Verification(allow_inline_test_source=True, base_root=self.temp_root)
        patch = Patch(
            diff_ref=VALID_COUPON_PATCH_DIFF,
            files_changed=("checkout.py",),
        )
        case = _make_case(repo_ref="repo")
        repro = _make_repro()

        verdict = verifier.run(case, repro, patch)
        self.assertEqual(verdict.result, VerdictResult.VERIFIED, f"Reasons: {verdict.reasons}")
        self.assertEqual(verdict.playbook_sha256, expected_sha)
        self.assertIsNotNone(verdict.policy_rule)
        self.assertTrue(verdict.policy_rule.passed)
        self.assertEqual(verdict.policy_rule.playbook_sha256, expected_sha)

        rule_names = [r.rule_name for r in verdict.policy_rules]
        self.assertIn("playbook_policy", rule_names)
        self.assertIn("paths_forbidden", rule_names)
        self.assertIn("paths_allowed", rule_names)
        self.assertIn("tests_protected", rule_names)
        self.assertIn("limits_max_files", rule_names)

    def test_deterministic_decision_without_llm(self) -> None:
        """A decisão não usa o LLM; reexecutar a verificação sobre as mesmas evidências dá o mesmo resultado."""
        self._write_playbook("""\
version = 1
[paths]
allowed = ["checkout.py"]
forbidden = [".resolveqa/**", "tests/**"]
""")
        verifier = Verification(allow_inline_test_source=True, base_root=self.temp_root)
        patch = Patch(
            diff_ref=VALID_COUPON_PATCH_DIFF,
            files_changed=("checkout.py",),
        )
        case = _make_case(repo_ref="repo")
        repro = _make_repro()

        with mock_patch(
            "resolveqa.llm.adapter.LLMAdapter.complete",
            side_effect=AssertionError("LLM must not be called during verification"),
        ):
            v1 = verifier.run(case, repro, patch)
            v2 = verifier.run(case, repro, patch)

        self.assertEqual(v1.result, v2.result)
        self.assertEqual(v1.reasons, v2.reasons)
        self.assertEqual(v1.playbook_sha256, v2.playbook_sha256)
        self.assertEqual(v1.base_revision, v2.base_revision)
        self.assertEqual(v1.fix_revision, v2.fix_revision)

    def test_extract_diff_target_paths_helper(self) -> None:
        """Unit test for diff path extraction utility."""
        unified_diff = """\
--- a/src/module.py
+++ b/src/module.py
@@ -1,2 +1,2 @@
--- /dev/null
+++ b/created.txt
@@ -0,0 +1,1 @@
--- a/deleted.txt
+++ /dev/null
@@ -1,1 +0,0 @@
"""
        paths = extract_diff_target_paths(unified_diff)
        self.assertEqual(paths, ["src/module.py", "created.txt", "deleted.txt"])

        json_patch = '{"app/main.py": "x = 1", "tests/test_x.py": "y = 2"}'
        json_paths = extract_diff_target_paths(json_patch)
        self.assertEqual(json_paths, ["app/main.py", "tests/test_x.py"])


if __name__ == "__main__":
    unittest.main()
