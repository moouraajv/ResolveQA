"""Tests for demo-target repository fixture with coupon defect (Issue #5, D1/D4)."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEMO_TARGET_DIR = REPO_ROOT / "demo-target"


class TestDemoTargetFixture(unittest.TestCase):
    """Verify demo-target acceptance criteria from Issue #5."""

    def test_demo_target_files_exist(self) -> None:
        self.assertTrue((DEMO_TARGET_DIR / "checkout.py").is_file())
        self.assertTrue((DEMO_TARGET_DIR / "tests" / "test_checkout.py").is_file())

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

    def test_no_prior_defect_test_exists_in_demo_target(self) -> None:
        tests_dir = DEMO_TARGET_DIR / "tests"
        self.assertTrue(tests_dir.is_dir())
        for test_file in tests_dir.glob("test_*.py"):
            content = test_file.read_text(encoding="utf-8")
            self.assertNotIn(
                "180",
                content,
                f"Found prior coupon defect expectation (180) in {test_file.name}",
            )

    def test_separate_manual_repro_test_expecting_180_fails_on_buggy_version(self) -> None:
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
