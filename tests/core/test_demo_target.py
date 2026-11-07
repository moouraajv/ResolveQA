"""Tests for demo-target repository fixture with coupon defect (Issue #5, D1/D4).

IMPORTANT FIXTURE GUARD NOTE:
This test module intentionally pins the unpatched D1-a coupon defect inside `demo-target/`
(where applying a 10% coupon to R$ 200.00 returns 200.0 instead of 180.0).
It serves as an invariant guard guaranteeing that the baseline `demo-target/` fixture inside
the repository remains unpatched and contains no spoilers or pre-existing oracle tests.
If the fix is applied directly to `demo-target/checkout.py` in the repository working tree
(instead of inside an isolated Sandbox copy as required by RF-05/RF-06),
`test_separate_manual_repro_test_expecting_180_fails_on_buggy_version` will intentionally turn RED.
"""

from __future__ import annotations

import ast
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEMO_TARGET_DIR = REPO_ROOT / "demo-target"
KNOWN_COUPON_CODES = {"DESC10", "CUPOM10", "10OFF"}
FORBIDDEN_HINT_TOKENS = ("defect", "defeito", "d1-a", "intentional", "intencional")


def _extract_valid_coupon_calls(source_code: str) -> list[str]:
    """Return descriptions of any calls in `source_code` that invoke checkout calculation with a valid coupon."""
    tree = ast.parse(source_code)
    violations: list[str] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func_name = None
        if isinstance(node.func, ast.Name):
            func_name = node.func.id
        elif isinstance(node.func, ast.Attribute):
            func_name = node.func.attr

        if func_name not in {"calculate_total", "calcular_total"}:
            continue

        # Positional 2nd arg: coupon_percent / cupom_percentual
        if len(node.args) >= 2:
            arg2 = node.args[1]
            if isinstance(arg2, ast.Constant) and isinstance(arg2.value, (int, float)):
                if 0 < float(arg2.value) <= 100:
                    violations.append(f"{func_name} positional coupon_percent={arg2.value}")

        # Positional 3rd arg: coupon_code / codigo_cupom
        if len(node.args) >= 3:
            arg3 = node.args[2]
            if isinstance(arg3, ast.Constant) and isinstance(arg3.value, str):
                if arg3.value.strip().upper() in KNOWN_COUPON_CODES:
                    violations.append(f"{func_name} positional coupon_code={arg3.value!r}")

        # Keyword args
        for kw in node.keywords:
            if kw.arg in {"coupon_percent", "cupom_percentual"}:
                if isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, (int, float)):
                    if 0 < float(kw.value.value) <= 100:
                        violations.append(f"{func_name} keyword {kw.arg}={kw.value.value}")
            elif kw.arg in {"coupon_code", "codigo_cupom"}:
                if isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                    if kw.value.value.strip().upper() in KNOWN_COUPON_CODES:
                        violations.append(f"{func_name} keyword {kw.arg}={kw.value.value!r}")

    return violations


class TestDemoTargetFixture(unittest.TestCase):
    """Verify demo-target acceptance criteria and fixture guards from Issue #5."""

    def test_demo_target_files_exist_and_contain_no_defect_hints(self) -> None:
        checkout_py = DEMO_TARGET_DIR / "checkout.py"
        test_checkout_py = DEMO_TARGET_DIR / "tests" / "test_checkout.py"
        self.assertTrue(checkout_py.is_file())
        self.assertTrue(test_checkout_py.is_file())

        for py_file in [checkout_py, test_checkout_py]:
            lower_text = py_file.read_text(encoding="utf-8").lower()
            for token in FORBIDDEN_HINT_TOKENS:
                self.assertNotIn(
                    token,
                    lower_text,
                    f"Target file {py_file.name} must not reveal defect hint {token!r}",
                )

    def test_demo_target_own_suite_passes_on_buggy_version(self) -> None:
        env = {
            "PATH": os.environ.get("PATH", ""),
            "PYTHONPATH": str(DEMO_TARGET_DIR),
            "PYTHONDONTWRITEBYTECODE": "1",
        }
        proc = subprocess.run(
            [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
            cwd=str(DEMO_TARGET_DIR),
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(
            proc.returncode,
            0,
            f"Expected demo-target own suite to pass (exit 0), got {proc.returncode}:\n{proc.stderr}",
        )

    def test_no_prior_defect_test_or_valid_coupon_call_exists_in_demo_target(self) -> None:
        tests_dir = DEMO_TARGET_DIR / "tests"
        self.assertTrue(tests_dir.is_dir())
        for test_file in tests_dir.glob("test_*.py"):
            content = test_file.read_text(encoding="utf-8")
            self.assertNotIn(
                "180",
                content,
                f"Found prior coupon defect expectation (180) in {test_file.name}",
            )
            violations = _extract_valid_coupon_calls(content)
            self.assertEqual(
                violations,
                [],
                f"Found prior test calling checkout with valid coupon in {test_file.name}: {violations}",
            )

        # Self-check the AST guard against synthetic test snippets
        self.assertTrue(_extract_valid_coupon_calls("calculate_total(200.0, 10.0)"))
        self.assertTrue(_extract_valid_coupon_calls("calculate_total(200.0, coupon_percent=10)"))
        self.assertTrue(_extract_valid_coupon_calls("calculate_total(200.0, coupon_code='DESC10')"))
        self.assertTrue(_extract_valid_coupon_calls("calcular_total(200.0, codigo_cupom='CUPOM10')"))

    def test_separate_manual_repro_test_expecting_180_fails_on_buggy_version(self) -> None:
        """Intentional fixture guard: turns RED if demo-target/checkout.py is patched in-place."""
        repro_test_code = (
            "import unittest\n"
            "from checkout import calculate_total, format_brl\n\n"
            "class TestCouponRepro(unittest.TestCase):\n"
            "    def test_10_percent_coupon_on_200_brl(self):\n"
            "        total = calculate_total(200.0, coupon_percent=10.0)\n"
            "        self.assertEqual(total, 180.0)\n"
            "        self.assertEqual(format_brl(total), 'R$ 180,00')\n\n"
            "if __name__ == '__main__':\n"
            "    unittest.main()\n"
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            test_path = Path(tmpdir) / "test_repro_coupon.py"
            test_path.write_text(repro_test_code, encoding="utf-8")
            env = {
                "PATH": os.environ.get("PATH", ""),
                "PYTHONPATH": str(DEMO_TARGET_DIR),
                "PYTHONDONTWRITEBYTECODE": "1",
            }
            proc = subprocess.run(
                [sys.executable, str(test_path)],
                cwd=tmpdir,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(proc.returncode, 0, "Repro test must fail on buggy demo-target")
            self.assertIn("AssertionError", proc.stderr)
            self.assertIn("200.0 != 180.0", proc.stderr)


if __name__ == "__main__":
    unittest.main()
