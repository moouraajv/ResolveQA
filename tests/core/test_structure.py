"""Tests for repository structure, configuration and test runner setup (Issue #4)."""

from __future__ import annotations

import json
import tomllib
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


class TestRepositoryStructure(unittest.TestCase):
    """Validate RFC-0001 §8 Track A layout, .gitignore, limits config and pyproject.toml."""

    def test_track_a_directories_exist(self) -> None:
        expected_dirs = [
            "src/resolveqa",
            "src/resolveqa/orchestrator",
            "src/resolveqa/triage",
            "src/resolveqa/reproduction",
            "src/resolveqa/fix",
            "src/resolveqa/verification",
            "src/resolveqa/sandbox",
            "src/resolveqa/llm",
            "src/resolveqa/store",
            "demo-target",
            "config",
            "tests/core",
        ]
        for rel_path in expected_dirs:
            full_path = REPO_ROOT / rel_path
            self.assertTrue(full_path.is_dir(), f"Missing directory: {rel_path}")

    def test_gitignore_excludes_runs_and_venv(self) -> None:
        gitignore_path = REPO_ROOT / ".gitignore"
        self.assertTrue(gitignore_path.is_file(), ".gitignore must exist")
        lines = [
            line.strip()
            for line in gitignore_path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
        self.assertIn("runs/", lines)
        self.assertIn(".venv/", lines)

    def test_pyproject_toml_configures_pytest_runner(self) -> None:
        pyproject_path = REPO_ROOT / "pyproject.toml"
        self.assertTrue(pyproject_path.is_file(), "pyproject.toml must exist")
        data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
        self.assertEqual(data["project"]["name"], "resolveqa")
        pytest_opts = data["tool"]["pytest"]["ini_options"]
        self.assertIn("src", pytest_opts["pythonpath"])
        self.assertIn("tests", pytest_opts["testpaths"])

    def test_limits_config_matches_rfc_section_5(self) -> None:
        limits_path = REPO_ROOT / "config" / "limits.json"
        self.assertTrue(limits_path.is_file(), "config/limits.json must exist")
        limits = json.loads(limits_path.read_text(encoding="utf-8"))
        self.assertEqual(limits["max_fix_attempts"], 2)
        self.assertEqual(limits["max_llm_calls"], 12)
        self.assertEqual(limits["test_timeout_s"], 600)
        self.assertEqual(limits["max_files_changed"], 3)


if __name__ == "__main__":
    unittest.main()
