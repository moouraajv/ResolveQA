"""Tests for independent Verification stage and protected test oracle (Issue #12, RF-06, RFC-0001 §3.3)."""

from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch as mock_patch

from resolveqa.contracts import (
    CaseState,
    ChannelType,
    ExecResult,
    Patch,
    ReproOutcome,
    ReproResult,
    RunState,
    SandboxStage,
    VerdictResult,
    VerificationStage,
)
from resolveqa.sandbox import LocalSandbox
from resolveqa.verification import Verification, Verifier
from resolveqa.verification.verifier import RESIDUAL_RISK_NOTE, apply_unified_diff

REPO_ROOT = Path(__file__).resolve().parents[2]
DEMO_TARGET_DIR = REPO_ROOT / "demo-target"

COUPON_REPRO_TEST = """\
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

VALID_CHECKOUT_PATCH_DIFF = """\
--- a/checkout.py
+++ b/checkout.py
@@ -32,5 +32,5 @@
         raise ValueError("coupon_percent must be between 0 and 100")
 
     discount = round(float(subtotal) * (pct / 100.0), 2)
-    return round(float(subtotal), 2)
+    return round(float(subtotal) - discount, 2)
"""

WRONG_FIX_PATCH_DIFF = """\
--- a/checkout.py
+++ b/checkout.py
@@ -32,5 +32,5 @@
         raise ValueError("coupon_percent must be between 0 and 100")
 
     discount = round(float(subtotal) * (pct / 100.0), 2)
-    return round(float(subtotal), 2)
+    return round(float(subtotal) - (discount * 2.0), 2)
"""

SUITE_BREAKING_PATCH_DIFF = """\
--- a/checkout.py
+++ b/checkout.py
@@ -22,8 +22,6 @@
     coupon_code: str | None = None,
 ) -> float:
     \"\"\"Calculate final checkout total given subtotal and optional coupon discount.\"\"\"
-    if subtotal < 0:
-        raise ValueError("subtotal must be non-negative")
 
     pct = float(coupon_percent)
     if coupon_code is not None and pct == 0.0:
@@ -32,5 +30,5 @@
         raise ValueError("coupon_percent must be between 0 and 100")
 
     discount = round(float(subtotal) * (pct / 100.0), 2)
-    return round(float(subtotal), 2)
+    return round(float(subtotal) - discount, 2)
"""


def _make_case(
    repo_ref: str = "demo-target",
    base_revision: str | None = "base-rev-001",
    fix_revision: str | None = None,
) -> RunState:
    return RunState(
        case_id="case-verify-001",
        client_id="client-demo",
        repo_ref=repo_ref,
        channel=ChannelType.SIMULATED_CHAT,
        report_text="Apliquei um cupom de 10% em uma compra de R$ 200, mas o total continuou em R$ 200.",
        state=CaseState.VERIFYING,
        created_at="2026-11-08T00:00:00Z",
        updated_at="2026-11-08T00:01:00Z",
        base_revision=base_revision,
        fix_revision=fix_revision,
    )


def _make_repro(
    test_source: str = COUPON_REPRO_TEST,
    test_path: str = "tests/test_repro_coupon.py",
    exit_code: int = 1,
    outcome: ReproOutcome = ReproOutcome.RED_ON_ASSERTION,
    failing_assertion: str | None = "AssertionError: 200.0 != 180.0",
) -> ReproResult:
    return ReproResult(
        test_path=test_path,
        test_source_ref=test_source,
        exit_code=exit_code,
        outcome=outcome,
        failing_assertion=failing_assertion,
        log_ref="AssertionError: 200.0 != 180.0",
    )


class TestVerificationStage(unittest.TestCase):
    """Validate Issue #12 acceptance criteria and protected oracle invariants."""

    def test_patch_paths_through_symlinks_report_the_resolved_target(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            target_dir = Path(temp_dir)
            protected_dir = target_dir / "tests"
            protected_dir.mkdir()
            protected_file = protected_dir / "test_protected.py"
            protected_file.write_text("assert True\n", encoding="utf-8")
            alias = target_dir / "source.py"
            alias.symlink_to(protected_file)

            touched = apply_unified_diff(
                target_dir,
                """\
--- a/source.py
+++ b/source.py
@@ -1 +1 @@
-assert True
+assert False
""",
            )

            self.assertEqual(touched, ("tests/test_protected.py",))
            self.assertEqual(protected_file.read_text(encoding="utf-8"), "assert False\n")

            touched = apply_unified_diff(
                target_dir,
                """\
--- a/source.py
+++ /dev/null
@@ -1 +0,0 @@
-assert False
""",
            )

            self.assertEqual(touched, ("tests/test_protected.py",))
            self.assertFalse(protected_file.exists())

    def test_implements_verification_stage_protocol(self) -> None:
        verifier = Verification(allow_inline_test_source=True, base_root=REPO_ROOT)
        self.assertIsInstance(verifier, VerificationStage)
        self.assertIs(Verifier, Verification)

    def test_verified_on_demo_target_with_correct_patch_and_Does_not_mutate_repo(self) -> None:
        checkout_path = DEMO_TARGET_DIR / "checkout.py"
        original_sha = hashlib.sha256(checkout_path.read_bytes()).hexdigest()

        verifier = Verification(allow_inline_test_source=True, base_root=REPO_ROOT)
        case = _make_case()
        repro = _make_repro()
        patch = Patch(
            diff_ref=VALID_CHECKOUT_PATCH_DIFF,
            files_changed=("checkout.py",),
            touches_tests=False,
            touches_ci=False,
        )

        # Ensure LLM is never imported or called by Verification
        with mock_patch("resolveqa.llm.adapter.LLMAdapter.complete", side_effect=AssertionError("LLM must not be called")):
            verdict = verifier.run(case, repro, patch)

        self.assertEqual(verdict.result, VerdictResult.VERIFIED, f"Reasons: {verdict.reasons}")
        self.assertEqual(verdict.reasons, (RESIDUAL_RISK_NOTE,))
        self.assertNotEqual(verdict.before.exit_code, 0)
        self.assertIn("AssertionError", verdict.before.log_ref)
        self.assertEqual(verdict.after.exit_code, 0)
        self.assertEqual(verdict.suite.exit_code, 0)
        self.assertEqual(verdict.base_revision, "base-rev-001")
        self.assertTrue(verdict.fix_revision)
        self.assertNotEqual(verdict.base_revision, verdict.fix_revision)

        # Original demo-target must remain untouched and clean
        after_sha = hashlib.sha256(checkout_path.read_bytes()).hexdigest()
        self.assertEqual(original_sha, after_sha)
        self.assertFalse((DEMO_TARGET_DIR / "tests" / "test_repro_coupon.py").exists())

    def test_rejects_patch_that_modifies_repro_test_or_weakens_assertion(self) -> None:
        tampering_diff = (
            VALID_CHECKOUT_PATCH_DIFF
            + """\
--- a/tests/test_repro_coupon.py
+++ b/tests/test_repro_coupon.py
@@ -6,4 +6,4 @@
     def test_apply_10_percent_coupon_on_200_brl(self) -> None:
         total = calculate_total(200.0, coupon_percent=10.0)
-        self.assertEqual(total, 180.0)
-        self.assertEqual(format_brl(total), "R$ 180,00")
+        self.assertEqual(total, 200.0)
"""
        )
        verifier = Verification(allow_inline_test_source=True, base_root=REPO_ROOT)
        # Even if Patch metadata lies (touches_tests=False and omits test from files_changed),
        # Verification must catch the sha256 mismatch and test tampering.
        lying_patch = Patch(
            diff_ref=tampering_diff,
            files_changed=("checkout.py",),
            touches_tests=False,
            touches_ci=False,
        )
        verdict = verifier.run(_make_case(), _make_repro(), lying_patch)
        self.assertEqual(verdict.result, VerdictResult.REJECTED)
        reasons_text = " ".join(verdict.reasons).lower()
        self.assertTrue(
            "test_modified" in reasons_text or "touches_tests" in reasons_text or "assertion" in reasons_text,
            f"Expected test modification/weakening reason, got: {verdict.reasons}",
        )

    def test_rejects_patch_that_deletes_repro_test(self) -> None:
        deleting_diff = """\
--- a/checkout.py
+++ b/checkout.py
@@ -32,5 +32,5 @@
         raise ValueError("coupon_percent must be between 0 and 100")
 
     discount = round(float(subtotal) * (pct / 100.0), 2)
-    return round(float(subtotal), 2)
+    return round(float(subtotal) - discount, 2)
--- a/tests/test_repro_coupon.py
+++ /dev/null
@@ -1,13 +0,0 @@
-import unittest
-from checkout import calculate_total, format_brl
-
-
-class TestCouponDiscountRepro(unittest.TestCase):
-    def test_apply_10_percent_coupon_on_200_brl(self) -> None:
-        total = calculate_total(200.0, coupon_percent=10.0)
-        self.assertEqual(total, 180.0)
-        self.assertEqual(format_brl(total), "R$ 180,00")
-
-
-if __name__ == "__main__":
-    unittest.main()
"""
        verifier = Verification(allow_inline_test_source=True, base_root=REPO_ROOT)
        patch = Patch(
            diff_ref=deleting_diff,
            files_changed=("checkout.py",),
            touches_tests=False,
            touches_ci=False,
        )
        verdict = verifier.run(_make_case(), _make_repro(), patch)
        self.assertEqual(verdict.result, VerdictResult.REJECTED)
        reasons_text = " ".join(verdict.reasons).lower()
        self.assertIn("test_deleted", reasons_text)

    def test_rejects_patch_or_test_with_skip_or_xfail(self) -> None:
        skip_diff = """\
--- a/checkout.py
+++ b/checkout.py
@@ -32,5 +32,5 @@
         raise ValueError("coupon_percent must be between 0 and 100")
 
     discount = round(float(subtotal) * (pct / 100.0), 2)
-    return round(float(subtotal), 2)
+    return round(float(subtotal) - discount, 2)
--- a/tests/test_repro_coupon.py
+++ b/tests/test_repro_coupon.py
@@ -5,6 +5,7 @@
 
 class TestCouponDiscountRepro(unittest.TestCase):
+    @unittest.skip("skip failing test")
     def test_apply_10_percent_coupon_on_200_brl(self) -> None:
         total = calculate_total(200.0, coupon_percent=10.0)
         self.assertEqual(total, 180.0)
"""
        verifier = Verification(allow_inline_test_source=True, base_root=REPO_ROOT)
        patch = Patch(
            diff_ref=skip_diff,
            files_changed=("checkout.py",),
            touches_tests=False,
            touches_ci=False,
        )
        verdict = verifier.run(_make_case(), _make_repro(), patch)
        self.assertEqual(verdict.result, VerdictResult.REJECTED)
        reasons_text = " ".join(verdict.reasons).lower()
        self.assertIn("skip", reasons_text)

        # Also test when the reproduction test itself contains xfail or skip
        xfail_test = """\
import pytest
from checkout import calculate_total

@pytest.mark.xfail(reason="known bug")
def test_coupon():
    assert calculate_total(200.0, coupon_percent=10.0) == 180.0
"""
        verdict_xfail = verifier.run(
            _make_case(),
            _make_repro(test_source=xfail_test),
            Patch(diff_ref=VALID_CHECKOUT_PATCH_DIFF, files_changed=("checkout.py",)),
        )
        self.assertEqual(verdict_xfail.result, VerdictResult.REJECTED)
        self.assertIn("xfail", " ".join(verdict_xfail.reasons).lower())

    def test_rejects_test_with_removed_or_weakened_assertion(self) -> None:
        no_assert_test = """\
import unittest
from checkout import calculate_total

class TestWeak(unittest.TestCase):
    def test_no_assertion(self) -> None:
        calculate_total(200.0, coupon_percent=10.0)
"""
        tautological_test = """\
def test_trivial():
    assert True
"""
        verifier = Verification(allow_inline_test_source=True, base_root=REPO_ROOT)
        good_patch = Patch(diff_ref=VALID_CHECKOUT_PATCH_DIFF, files_changed=("checkout.py",))

        for name, bad_test in [("no_assert", no_assert_test), ("tautological", tautological_test)]:
            with self.subTest(case=name):
                verdict = verifier.run(_make_case(), _make_repro(test_source=bad_test), good_patch)
                self.assertEqual(verdict.result, VerdictResult.REJECTED)
                self.assertIn("assertion", " ".join(verdict.reasons).lower())

    def test_rejects_patch_touching_ci_or_runner_configuration(self) -> None:
        verifier = Verification(allow_inline_test_source=True, base_root=REPO_ROOT)
        # Flagged via touches_ci=True
        ci_flag_patch = Patch(
            diff_ref=VALID_CHECKOUT_PATCH_DIFF,
            files_changed=("checkout.py",),
            touches_tests=False,
            touches_ci=True,
        )
        v1 = verifier.run(_make_case(), _make_repro(), ci_flag_patch)
        self.assertEqual(v1.result, VerdictResult.REJECTED)

        # Undeclared runner config change in pyproject.toml
        runner_cfg_diff = (
            VALID_CHECKOUT_PATCH_DIFF
            + """\
--- a/pyproject.toml
+++ b/pyproject.toml
@@ -1,4 +1,4 @@
 [tool.pytest.ini_options]
 pythonpath = ["."]
 testpaths = ["tests"]
-addopts = "-q -p no:cacheprovider"
+addopts = "-q -p no:cacheprovider -k not_coupon"
"""
        )
        runner_patch = Patch(
            diff_ref=runner_cfg_diff,
            files_changed=("checkout.py",),
            touches_tests=False,
            touches_ci=False,
        )
        v2 = verifier.run(_make_case(), _make_repro(), runner_patch)
        self.assertEqual(v2.result, VerdictResult.REJECTED)
        self.assertIn("runner_config_modified", " ".join(v2.reasons).lower())

    def test_rejects_patch_exceeding_max_files_changed(self) -> None:
        verifier = Verification(allow_inline_test_source=True, base_root=REPO_ROOT, max_files_changed=3)
        patch = Patch(
            diff_ref=VALID_CHECKOUT_PATCH_DIFF,
            files_changed=("checkout.py", "a.py", "b.py", "c.py"),
            touches_tests=False,
            touches_ci=False,
        )
        verdict = verifier.run(_make_case(), _make_repro(), patch)
        self.assertEqual(verdict.result, VerdictResult.REJECTED)
        self.assertIn("max_files_changed", " ".join(verdict.reasons).lower())

    def test_rejects_wrong_fix_and_suite_breaking_fix(self) -> None:
        verifier = Verification(allow_inline_test_source=True, base_root=REPO_ROOT)
        # Wrong fix: reproduction test still fails after patch
        wrong_patch = Patch(
            diff_ref=WRONG_FIX_PATCH_DIFF,
            files_changed=("checkout.py",),
        )
        v_wrong = verifier.run(_make_case(), _make_repro(), wrong_patch)
        self.assertEqual(v_wrong.result, VerdictResult.REJECTED)
        self.assertNotEqual(v_wrong.after.exit_code, 0)

        # Suite-breaking fix: reproduction test passes, but existing suite fails
        breaking_patch = Patch(
            diff_ref=SUITE_BREAKING_PATCH_DIFF,
            files_changed=("checkout.py",),
        )
        v_suite = verifier.run(_make_case(), _make_repro(), breaking_patch)
        self.assertEqual(v_suite.result, VerdictResult.REJECTED)
        self.assertEqual(v_suite.after.exit_code, 0)
        self.assertNotEqual(v_suite.suite.exit_code, 0)

    def test_import_collection_and_setup_errors_do_not_count_as_valid_red(self) -> None:
        verifier = Verification(allow_inline_test_source=True, base_root=REPO_ROOT)
        good_patch = Patch(diff_ref=VALID_CHECKOUT_PATCH_DIFF, files_changed=("checkout.py",))

        import_error_test = """\
import nonexistent_dependency_xyz
from checkout import calculate_total

def test_coupon():
    assert calculate_total(200.0, coupon_percent=10.0) == 180.0
"""
        syntax_error_test = """\
def test_broken(
    assert 1 == 2
"""
        setup_error_test = """\
import unittest
from checkout import calculate_total

class TestSetupError(unittest.TestCase):
    def setUp(self) -> None:
        raise RuntimeError("preparation failed before assertion")

    def test_coupon(self) -> None:
        self.assertEqual(calculate_total(200.0, coupon_percent=10.0), 180.0)
"""
        non_assertion_error_test = """\
from checkout import calculate_total

def test_coupon():
    raise ValueError("unexpected crash instead of AssertionError")
    assert calculate_total(200.0, coupon_percent=10.0) == 180.0
"""

        for label, bad_source in [
            ("import_error", import_error_test),
            ("syntax_error", syntax_error_test),
            ("setup_error", setup_error_test),
            ("non_assertion_error", non_assertion_error_test),
        ]:
            with self.subTest(error_kind=label):
                verdict = verifier.run(
                    _make_case(),
                    _make_repro(test_source=bad_source),
                    good_patch,
                )
                self.assertNotEqual(
                    verdict.result,
                    VerdictResult.VERIFIED,
                    f"{label} must never count as valid RED / VERIFIED",
                )
                self.assertIn(
                    verdict.result,
                    (VerdictResult.REJECTED, VerdictResult.ENV_ERROR),
                )
                self.assertTrue(len(verdict.reasons) > 0)

    def test_env_error_cases_with_fixture_patches(self) -> None:
        # 1. Timeout induced by fixture patch inside sandbox -> ENV_ERROR
        timeout_patch_diff = """\
--- a/checkout.py
+++ b/checkout.py
@@ -1,4 +1,5 @@
 \"\"\"Checkout pricing module for order totals and promotional coupons.\"\"\"
 
 from __future__ import annotations
+import time
 
@@ -32,5 +33,6 @@
         raise ValueError("coupon_percent must be between 0 and 100")
 
+    time.sleep(5.0)
     discount = round(float(subtotal) * (pct / 100.0), 2)
-    return round(float(subtotal), 2)
+    return round(float(subtotal) - discount, 2)
"""
        verifier = Verification(allow_inline_test_source=True, base_root=REPO_ROOT, test_timeout_s=0.3)
        timeout_patch = Patch(
            diff_ref=timeout_patch_diff,
            files_changed=("checkout.py",),
        )
        v_timeout = verifier.run(_make_case(), _make_repro(), timeout_patch)
        self.assertEqual(v_timeout.result, VerdictResult.ENV_ERROR)
        self.assertTrue(any("infra_error" in r.lower() or "timeout" in r.lower() for r in v_timeout.reasons))

        # 2. Non-existent target repository -> ENV_ERROR
        v_missing_repo = verifier.run(
            _make_case(repo_ref="nonexistent-repo-fixture"),
            _make_repro(),
            Patch(diff_ref=VALID_CHECKOUT_PATCH_DIFF, files_changed=("checkout.py",)),
        )
        self.assertEqual(v_missing_repo.result, VerdictResult.ENV_ERROR)

        # 3. Reproduction stage outcome already ENV_ERROR -> ENV_ERROR
        v_repro_env = verifier.run(
            _make_case(),
            _make_repro(outcome=ReproOutcome.ENV_ERROR, exit_code=2),
            Patch(diff_ref=VALID_CHECKOUT_PATCH_DIFF, files_changed=("checkout.py",)),
        )
        self.assertEqual(v_repro_env.result, VerdictResult.ENV_ERROR)


def _new_file_diff(path: str, body: str) -> str:
    lines = body.splitlines()
    return (
        f"--- /dev/null\n+++ b/{path}\n@@ -0,0 +1,{len(lines)} @@\n"
        + "".join(f"+{line}\n" for line in lines)
    )


QA_HOOKS_SOURCE = """\
mod = __import__('pyt' + 'est')


def pytest_runtest_makereport(item, call):
    return None
"""


class TestVerifierHardening(unittest.TestCase):
    """Regression tests for QA findings V7/V8 (X1), X2, X3, X4/X5 on PR #53."""

    def setUp(self) -> None:
        self.verifier = Verification(allow_inline_test_source=True, base_root=REPO_ROOT)

    def _run(self, diff: str, files: tuple[str, ...], repro: ReproResult | None = None):
        return self.verifier.run(
            _make_case(), repro or _make_repro(), Patch(diff_ref=diff, files_changed=files)
        )

    def _assert_rejected(self, verdict, *needles: str) -> None:
        self.assertEqual(verdict.result, VerdictResult.REJECTED, verdict.reasons)
        text = " ".join(verdict.reasons)
        for needle in needles:
            self.assertIn(needle, text)

    def test_v7_v8_pytest_config_files_are_protected_at_any_level(self) -> None:
        for name in ("pytest.toml", ".pytest.toml", ".pytest.ini", "sub/pytest.toml", "unittest.cfg", "sitecustomize.py"):
            with self.subTest(config=name):
                diff = VALID_CHECKOUT_PATCH_DIFF + _new_file_diff(name, "[pytest]\naddopts = -p qa_hooks")
                verdict = self._run(diff, ("checkout.py", name))
                self._assert_rejected(verdict, "runner_config_modified")

    def test_v7_v8_full_qa_exploit_is_rejected_and_never_verified(self) -> None:
        # QA proof: pytest.toml/.pytest.ini with addopts '-p qa_hooks' + hook module + unfixed checkout.py.
        unfixed = (
            "--- a/checkout.py\n+++ b/checkout.py\n@@ -1,3 +1,3 @@\n"
            ' """Checkout pricing module for order totals and promotional coupons."""\n'
            " \n"
            "-from __future__ import annotations\n"
            "+from __future__ import annotations  # touched, bug NOT fixed\n"
        )
        diff = (
            unfixed
            + _new_file_diff("pytest.toml", "[pytest]\naddopts = '-p qa_hooks'")
            + _new_file_diff(".pytest.ini", "[pytest]\naddopts = -p qa_hooks")
            + _new_file_diff("qa_hooks.py", QA_HOOKS_SOURCE)
        )
        verdict = self._run(diff, ("checkout.py", "pytest.toml", ".pytest.ini"))
        self.assertNotEqual(verdict.result, VerdictResult.VERIFIED)
        self._assert_rejected(verdict, "runner_config_modified")

    def test_new_python_files_and_pytest_hooks_are_rejected_in_patch(self) -> None:
        diff = VALID_CHECKOUT_PATCH_DIFF + _new_file_diff("qa_hooks.py", QA_HOOKS_SOURCE)
        verdict = self._run(diff, ("checkout.py", "qa_hooks.py"))
        self._assert_rejected(verdict, "new file 'qa_hooks.py'", "pytest_")

        hook_diff = (
            VALID_CHECKOUT_PATCH_DIFF.replace(
                "+    return round(float(subtotal) - discount, 2)",
                "+    import pytest\n+    hookimpl = pytest_runtest_call = None\n+    return round(float(subtotal) - discount, 2)",
            )
        )
        verdict = self._run(hook_diff, ("checkout.py",))
        self._assert_rejected(verdict, "forbidden pytest hook")

    def test_dynamic_import_in_patch_is_rejected(self) -> None:
        diff = VALID_CHECKOUT_PATCH_DIFF.replace(
            "+    return round(float(subtotal) - discount, 2)",
            "+    __import__('pyt' + 'est')\n+    return round(float(subtotal) - discount, 2)",
        )
        self._assert_rejected(self._run(diff, ("checkout.py",)), "dynamic import")

    def test_runner_uses_fixed_configuration_command(self) -> None:
        verdict = self._run(VALID_CHECKOUT_PATCH_DIFF, ("checkout.py",))
        self.assertEqual(verdict.result, VerdictResult.VERIFIED, verdict.reasons)
        for run in (verdict.before, verdict.after, verdict.suite):
            self.assertIn("PYTEST_DISABLE_PLUGIN_AUTOLOAD=1", run.command)
            self.assertIn("-c .rqa_verifier_pytest.ini", run.command)
            self.assertIn("addopts=", run.command)
            self.assertIn("no:cacheprovider", run.command)
        self.assertIn(RESIDUAL_RISK_NOTE, verdict.reasons)

    def test_workspace_pytest_config_cannot_influence_runs(self) -> None:
        with tempfile.TemporaryDirectory(dir=REPO_ROOT) as tmp:
            repo = Path(tmp) / "target"
            (repo / "tests").mkdir(parents=True)
            (repo / "checkout.py").write_text((DEMO_TARGET_DIR / "checkout.py").read_text(), encoding="utf-8")
            (repo / "tests" / "__init__.py").write_text("", encoding="utf-8")
            # Hostile config already present in the workspace: would deselect everything.
            (repo / "pytest.toml").write_text("[pytest]\naddopts = '-k nothing_matches'\n", encoding="utf-8")
            verifier = Verification(allow_inline_test_source=True, base_root=Path(tmp))
            repo_ref = "target"
            case = _make_case(repo_ref=repo_ref)
            verdict = verifier.run(
                case, _make_repro(), Patch(diff_ref=VALID_CHECKOUT_PATCH_DIFF, files_changed=("checkout.py",))
            )
            self.assertEqual(verdict.result, VerdictResult.VERIFIED, verdict.reasons)

    def test_x2_red_must_use_the_value_reported(self) -> None:
        other_value_test = """\
import unittest
from checkout import calculate_total


class TestOther(unittest.TestCase):
    def test_fifty_percent_on_100(self) -> None:
        self.assertEqual(calculate_total(100.0, coupon_percent=50.0), 50.0)
"""
        verdict = self._run(
            VALID_CHECKOUT_PATCH_DIFF,
            ("checkout.py",),
            _make_repro(test_source=other_value_test),
        )
        self._assert_rejected(verdict, "does not match the report")

    def test_x2_requires_failing_assertion_and_failure_from_test_function(self) -> None:
        verdict = self._run(
            VALID_CHECKOUT_PATCH_DIFF, ("checkout.py",), _make_repro(failing_assertion=None)
        )
        self._assert_rejected(verdict, "failing_assertion")

    def test_x3_rejects_eq_hash_and_value_subclasses(self) -> None:
        eq_diff = VALID_CHECKOUT_PATCH_DIFF.replace(
            "+    return round(float(subtotal) - discount, 2)",
            "+    class _Any(float):\n+        def __eq__(self, other):\n+            return True\n"
            "+    return _Any(200.0)",
        )
        self._assert_rejected(self._run(eq_diff, ("checkout.py",)), "value_type_spoofing")

    def test_x3_after_requires_exact_returned_type(self) -> None:
        str_diff = VALID_CHECKOUT_PATCH_DIFF.replace(
            "+    return round(float(subtotal) - discount, 2)",
            "+    return str(round(float(subtotal) - discount, 2))",
        )
        verdict = self._run(str_diff, ("checkout.py",))
        self.assertNotEqual(verdict.result, VerdictResult.VERIFIED)
        self.assertIn("RQA_TYPE_MISMATCH", verdict.after.log_ref)

    def test_x4_inline_source_and_foreign_absolute_paths_are_refused_by_default(self) -> None:
        strict = Verification(base_root=REPO_ROOT)
        verdict = strict.run(
            _make_case(), _make_repro(), Patch(diff_ref=VALID_CHECKOUT_PATCH_DIFF, files_changed=("checkout.py",))
        )
        self._assert_rejected(verdict, "inline test_source_ref")
        with tempfile.TemporaryDirectory() as tmp:
            outside = Path(tmp) / "test_repro.py"
            outside.write_text(COUPON_REPRO_TEST, encoding="utf-8")
            verdict = strict.run(
                _make_case(),
                _make_repro(test_source=str(outside)),
                Patch(diff_ref=VALID_CHECKOUT_PATCH_DIFF, files_changed=("checkout.py",)),
            )
            self._assert_rejected(verdict, "outside the case folder")

    def test_x5_staging_dir_is_private_and_removed(self) -> None:
        with self.verifier._staging_root() as staging:
            self.assertEqual(staging.stat().st_mode & 0o777, 0o700)
            created = staging
        self.assertFalse(created.exists())


QA_EXPLOIT_SNIPPET = (
    "_b = __builtins__ if isinstance(__builtins__, dict) else vars(__builtins__)\n"
    "_imp = _b['__imp'+'ort__']\n"
    "setattr(getattr(_imp('_pyt'+'est.python', fromlist=['_']), 'Func'+'tion'), 'run'+'test', lambda self: None)\n"
    "setattr(getattr(_imp('_pyt'+'est.unit'+'test', fromlist=['_']), 'TestCaseFunc'+'tion'), 'run'+'test', lambda self: None)\n"
)

PYTEST_STYLE_REPRO = """\
from checkout import calculate_total


def test_coupon():
    total = calculate_total(200.0, coupon_percent=10.0)
    assert total == 180.0
"""

INT_EXPECTED_REPRO = COUPON_REPRO_TEST.replace("180.0", "180").replace('self.assertEqual(format_brl(total), "R$ 180,00")\n', "")

INT_VALID_PATCH = VALID_CHECKOUT_PATCH_DIFF  # returns float 180.0, compared with the int 180 in the test


class TestVerifierBlackBoxOracle(unittest.TestCase):
    """PR #53 round 3: black-box oracle outside pytest, regressions (a)/(b), X2."""

    def setUp(self) -> None:
        self.verifier = Verification(allow_inline_test_source=True, base_root=REPO_ROOT)

    def _run(self, diff: str, files: tuple[str, ...] = ("checkout.py",), repro: ReproResult | None = None):
        return self.verifier.run(_make_case(), repro or _make_repro(), Patch(diff_ref=diff, files_changed=files))

    def test_v0_valid_coupon_fix_is_verified_with_blackbox_values(self) -> None:
        verdict = self._run(VALID_CHECKOUT_PATCH_DIFF)
        self.assertEqual(verdict.result, VerdictResult.VERIFIED, verdict.reasons)
        self.assertIn("oracle checkout.calculate_total -> float:200.0", verdict.before.log_ref)
        self.assertIn("oracle checkout.calculate_total -> float:180.0", verdict.after.log_ref)

    def test_exploit_patching_pytest_internals_is_not_verified(self) -> None:
        exploit = (
            "--- a/checkout.py\n+++ b/checkout.py\n@@ -1,3 +1,8 @@\n"
            ' """Checkout pricing module for order totals and promotional coupons."""\n'
            " \n"
            " from __future__ import annotations\n"
            + "".join(f"+{line}\n" for line in QA_EXPLOIT_SNIPPET.splitlines())
        )
        verdict = self._run(exploit)
        self.assertNotEqual(verdict.result, VerdictResult.VERIFIED)
        self.assertEqual(verdict.result, VerdictResult.REJECTED)
        self.assertIn("target code violation", " ".join(verdict.reasons))

    def test_blackbox_oracle_alone_catches_exploit_when_static_checks_miss_it(self) -> None:
        # Bypass the AST gate to prove the oracle is an independent line of defence: the unfixed code still
        # returns 200.0 in a clean interpreter, so the patched revision can never be VERIFIED.
        from resolveqa.verification import verifier as verifier_module

        harmless = (
            "--- a/checkout.py\n+++ b/checkout.py\n@@ -1,3 +1,4 @@\n"
            ' """Checkout pricing module for order totals and promotional coupons."""\n'
            " \n"
            " from __future__ import annotations\n"
            "+# no behavioural change\n"
        )
        with mock_patch.object(verifier_module, "_ast_target_code_violations", return_value=[]):
            verdict = self._run(harmless)
        self.assertEqual(verdict.result, VerdictResult.REJECTED)
        self.assertTrue(any("oracle_failed" in r or "after_not_green" in r for r in verdict.reasons), verdict.reasons)

    def test_ast_bans_builtins_dynamic_getattr_and_framework_access(self) -> None:
        snippets = {
            "builtins": "x = __builtins__\n",
            "getattr": "def f(n):\n    return getattr(object, n)\n",
            "importlib": "import importlib\n",
            "framework": "import _pytest\n",
            "folded": "name = '_pyt' + 'est'\n",
        }
        for label, snippet in snippets.items():
            with self.subTest(label=label):
                diff = VALID_CHECKOUT_PATCH_DIFF.replace(
                    "+    return round(float(subtotal) - discount, 2)",
                    "+    return round(float(subtotal) - discount, 2)",
                ) + "--- a/checkout.py\n+++ b/checkout.py\n"
                diff = (
                    "--- a/checkout.py\n+++ b/checkout.py\n@@ -1,3 +1,"
                    + str(3 + len(snippet.splitlines()))
                    + " @@\n"
                    ' """Checkout pricing module for order totals and promotional coupons."""\n'
                    " \n"
                    " from __future__ import annotations\n"
                    + "".join(f"+{line}\n" for line in snippet.splitlines())
                )
                verdict = self._run(diff)
                self.assertEqual(verdict.result, VerdictResult.REJECTED, verdict.reasons)

    def test_regression_a_int_expected_matches_float_result_by_value(self) -> None:
        verdict = self._run(VALID_CHECKOUT_PATCH_DIFF, repro=_make_repro(test_source=INT_EXPECTED_REPRO))
        self.assertEqual(verdict.result, VerdictResult.VERIFIED, verdict.reasons)

    def test_regression_a_forged_subclasses_and_non_numeric_types_still_refused(self) -> None:
        forged = VALID_CHECKOUT_PATCH_DIFF.replace(
            "+    return round(float(subtotal) - discount, 2)",
            "+    return str(round(float(subtotal) - discount, 2))",
        )
        verdict = self._run(forged)
        self.assertNotEqual(verdict.result, VerdictResult.VERIFIED)

    def test_regression_b_pytest_style_plain_assert_is_verified(self) -> None:
        repro = _make_repro(
            test_source=PYTEST_STYLE_REPRO, failing_assertion="assert 200.0 == 180.0"
        )
        verdict = self._run(VALID_CHECKOUT_PATCH_DIFF, repro=repro)
        self.assertEqual(verdict.result, VerdictResult.VERIFIED, verdict.reasons)

    def test_x2_self_consistent_100_50_red_is_rejected_against_the_report(self) -> None:
        coherent_but_unrelated = """\
from checkout import calculate_total


def test_half_price():
    total = calculate_total(100.0, coupon_percent=50.0)
    assert total == 50.0
"""
        repro = _make_repro(test_source=coherent_but_unrelated, failing_assertion="assert 100.0 == 50.0")
        verdict = self._run(VALID_CHECKOUT_PATCH_DIFF, repro=repro)
        self.assertEqual(verdict.result, VerdictResult.REJECTED)
        self.assertIn("does not match the report", " ".join(verdict.reasons))


if __name__ == "__main__":
    unittest.main()
