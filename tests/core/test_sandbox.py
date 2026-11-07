"""Tests for isolated local Sandbox execution (Issue #7, RNF-01, D2)."""

from __future__ import annotations

import errno
import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from resolveqa.contracts import SandboxStage
from resolveqa.sandbox import LocalSandbox, Sandbox, redact_secrets

REPO_ROOT = Path(__file__).resolve().parents[2]
DEMO_TARGET_DIR = REPO_ROOT / "demo-target"


class TestLocalSandbox(unittest.TestCase):
    """Validate Issue #7 acceptance criteria and QA security hardening for Sandbox.exec."""

    def test_implements_sandbox_stage_protocol(self) -> None:
        sandbox = Sandbox(base_root=REPO_ROOT)
        self.assertIsInstance(sandbox, SandboxStage)
        self.assertIsInstance(sandbox, LocalSandbox)

    def test_environment_strips_git_tokens_llm_keys_and_aws_keys(self) -> None:
        sandbox = Sandbox(base_root=REPO_ROOT)
        injected_secrets = {
            "GITHUB_TOKEN": "ghp_super_secret_token_12345",
            "GH_TOKEN": "gho_another_secret_67890",
            "GIT_ASKPASS": "/tmp/secret-askpass",
            "OPENAI_API_KEY": "sk-proj-secret-openai-key",
            "ANTHROPIC_API_KEY": "sk-ant-secret-key",
            "GEMINI_API_KEY": "AIzaSySecretGeminiKey",
            "GOOGLE_API_KEY": "AIzaSySecretGoogleKey",
            "LLM_API_KEY": "llm-secret-value",
            "AWS_ACCESS_KEY_ID": "AKIAIOSFODNN7EXAMPLE",
            "AWS_SECRET_ACCESS_KEY": "aws-super-secret",
        }
        with patch.dict(os.environ, injected_secrets, clear=False):
            res = sandbox.exec(
                "demo-target",
                'python3 -c "import json, os; print(json.dumps(dict(os.environ)))"',
                timeout_s=10.0,
            )

        self.assertEqual(res.exit_code, 0, f"stderr: {res.stderr_ref}")
        self.assertFalse(res.timed_out)
        sandbox_env = json.loads(res.stdout_ref.strip())
        for key, secret_val in injected_secrets.items():
            self.assertNotIn(key, sandbox_env, f"Secret env key {key} leaked into sandbox")
            self.assertNotIn(secret_val, res.stdout_ref, f"Secret value for {key} leaked")

        self.assertEqual(redact_secrets("Key AKIAIOSFODNN7EXAMPLE here"), "Key [REDACTED_SECRET] here")

    def test_rejects_absolute_paths_traversal_and_external_symlinks(self) -> None:
        sandbox = Sandbox(base_root=REPO_ROOT)
        for forbidden_ref in ["/", "/home", "../..", "a/../../x", str(DEMO_TARGET_DIR)]:
            with self.subTest(workdir_ref=forbidden_ref):
                with self.assertRaises(ValueError):
                    sandbox.resolve_workdir(forbidden_ref)
                res = sandbox.exec(forbidden_ref, 'python3 -c "print(1)"', timeout_s=5.0)
                self.assertNotEqual(res.exit_code, 0)

        with tempfile.TemporaryDirectory() as tmp_base_str, tempfile.TemporaryDirectory() as outside_str:
            tmp_base = Path(tmp_base_str)
            outside_dir = Path(outside_str)
            (outside_dir / "secret.txt").write_text("TOP_SECRET", encoding="utf-8")

            # Case A: workdir_ref itself is a symlink pointing outside base_root
            ext_link = tmp_base / "linked-repo"
            ext_link.symlink_to(outside_dir)
            scoped_sandbox = Sandbox(base_root=tmp_base)
            with self.assertRaises(ValueError):
                scoped_sandbox.resolve_workdir("linked-repo")
            res_ext = scoped_sandbox.exec("linked-repo", 'python3 -c "print(1)"', timeout_s=5.0)
            self.assertNotEqual(res_ext.exit_code, 0)

            # Case B: a valid workdir inside base_root contains a symlink pointing outside workdir
            valid_repo = tmp_base / "valid-repo"
            valid_repo.mkdir()
            (valid_repo / "app.py").write_text("x = 1\n", encoding="utf-8")
            (valid_repo / "escape_link.txt").symlink_to(outside_dir / "secret.txt")
            with self.assertRaises(ValueError):
                with scoped_sandbox.isolated_copy("valid-repo"):
                    pass
            res_inner = scoped_sandbox.exec("valid-repo", 'python3 -c "print(1)"', timeout_s=5.0)
            self.assertNotEqual(res_inner.exit_code, 0)

    def test_timeout_kills_entire_process_group_including_grandchildren(self) -> None:
        sandbox = Sandbox(base_root=REPO_ROOT)
        with tempfile.NamedTemporaryFile(prefix="resolveqa_pgid_", delete=False) as pid_file:
            pid_path = Path(pid_file.name)

        try:
            cmd = (
                "python3 -c \""
                "import subprocess, time; "
                "child = subprocess.Popen(['python3', '-c', 'import time; time.sleep(30)']); "
                f"open({str(pid_path)!r}, 'w').write(str(child.pid)); "
                "time.sleep(30)"
                "\""
            )
            res = sandbox.exec("demo-target", cmd, timeout_s=0.25)
            self.assertTrue(res.timed_out)
            self.assertEqual(res.exit_code, 124)

            grandchild_pid_text = pid_path.read_text(encoding="utf-8").strip()
            self.assertTrue(grandchild_pid_text.isdigit(), "Grandchild PID must have been recorded")
            grandchild_pid = int(grandchild_pid_text)

            with self.assertRaises(ProcessLookupError) as ctx:
                os.kill(grandchild_pid, 0)
            self.assertEqual(ctx.exception.errno, errno.ESRCH)
        finally:
            pid_path.unlink(missing_ok=True)

    def test_output_exceeding_max_output_bytes_is_truncated_and_marked(self) -> None:
        sandbox = Sandbox(base_root=REPO_ROOT, max_output_bytes=256)
        res = sandbox.exec(
            "demo-target",
            'python3 -c "print(\'X\' * 2048)"',
            timeout_s=10.0,
        )
        self.assertEqual(res.exit_code, 0)
        self.assertTrue(getattr(res, "truncated", False))
        self.assertTrue(sandbox.last_output_truncated)
        self.assertIn("...[truncated: output exceeded max_output_bytes]", res.stdout_ref)
        self.assertLess(len(res.stdout_ref), 400)

    def test_modifications_inside_sandbox_do_not_affect_original_demo_target(self) -> None:
        checkout_file = DEMO_TARGET_DIR / "checkout.py"
        before_sha = hashlib.sha256(checkout_file.read_bytes()).hexdigest()

        sandbox = Sandbox(base_root=REPO_ROOT)
        res = sandbox.exec(
            "demo-target",
            'python3 -c "from pathlib import Path; Path(\'checkout.py\').write_text(\'CORRUPTED\'); Path(\'extra.txt\').write_text(\'NEW\')"',
            timeout_s=10.0,
        )
        self.assertEqual(res.exit_code, 0, f"stderr: {res.stderr_ref}")

        after_sha = hashlib.sha256(checkout_file.read_bytes()).hexdigest()
        self.assertEqual(before_sha, after_sha)
        self.assertFalse((DEMO_TARGET_DIR / "extra.txt").exists())

    def test_no_shell_injection_execution(self) -> None:
        sandbox = Sandbox(base_root=REPO_ROOT)
        marker = DEMO_TARGET_DIR / "injected_marker.txt"
        res = sandbox.exec(
            "demo-target",
            f'python3 -c "print(123)" ; touch {marker}',
            timeout_s=10.0,
        )
        self.assertEqual(res.exit_code, 0)
        self.assertFalse(marker.exists())


if __name__ == "__main__":
    unittest.main()
