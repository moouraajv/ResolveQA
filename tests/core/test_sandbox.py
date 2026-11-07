"""Tests for isolated local Sandbox execution (Issue #7, RNF-01, D2)."""

from __future__ import annotations

import hashlib
import json
import os
import unittest
from pathlib import Path
from unittest.mock import patch

from resolveqa.contracts import SandboxStage
from resolveqa.sandbox import LocalSandbox, Sandbox

REPO_ROOT = Path(__file__).resolve().parents[2]
DEMO_TARGET_DIR = REPO_ROOT / "demo-target"


class TestLocalSandbox(unittest.TestCase):
    """Validate Issue #7 acceptance criteria for Sandbox.exec."""

    def test_implements_sandbox_stage_protocol(self) -> None:
        sandbox = Sandbox()
        self.assertIsInstance(sandbox, SandboxStage)
        self.assertIsInstance(sandbox, LocalSandbox)

    def test_environment_strips_git_tokens_and_llm_keys(self) -> None:
        sandbox = Sandbox()
        injected_secrets = {
            "GITHUB_TOKEN": "ghp_super_secret_token_12345",
            "GH_TOKEN": "gho_another_secret_67890",
            "GIT_ASKPASS": "/tmp/secret-askpass",
            "OPENAI_API_KEY": "sk-proj-secret-openai-key",
            "ANTHROPIC_API_KEY": "sk-ant-secret-key",
            "GEMINI_API_KEY": "AIzaSySecretGeminiKey",
            "GOOGLE_API_KEY": "AIzaSySecretGoogleKey",
            "LLM_API_KEY": "llm-secret-value",
            "AWS_SECRET_ACCESS_KEY": "aws-super-secret",
        }
        with patch.dict(os.environ, injected_secrets, clear=False):
            res = sandbox.exec(
                str(DEMO_TARGET_DIR),
                'python3 -c "import json, os; print(json.dumps(dict(os.environ)))"',
                timeout_s=10.0,
            )

        self.assertEqual(res.exit_code, 0, f"stderr: {res.stderr_ref}")
        self.assertFalse(res.timed_out)
        sandbox_env = json.loads(res.stdout_ref.strip())
        for key, secret_val in injected_secrets.items():
            self.assertNotIn(key, sandbox_env, f"Secret env key {key} leaked into sandbox")
            self.assertNotIn(secret_val, res.stdout_ref, f"Secret value for {key} leaked")

    def test_command_exceeding_timeout_returns_timed_out_true(self) -> None:
        sandbox = Sandbox()
        res = sandbox.exec(
            str(DEMO_TARGET_DIR),
            'python3 -c "import time; time.sleep(5)"',
            timeout_s=0.15,
        )
        self.assertTrue(res.timed_out)
        self.assertNotEqual(res.exit_code, 0)

    def test_modifications_inside_sandbox_do_not_affect_original_demo_target(self) -> None:
        checkout_file = DEMO_TARGET_DIR / "checkout.py"
        before_sha = hashlib.sha256(checkout_file.read_bytes()).hexdigest()

        sandbox = Sandbox()
        res = sandbox.exec(
            str(DEMO_TARGET_DIR),
            'python3 -c "from pathlib import Path; Path(\'checkout.py\').write_text(\'CORRUPTED\'); Path(\'extra.txt\').write_text(\'NEW\')"',
            timeout_s=10.0,
        )
        self.assertEqual(res.exit_code, 0, f"stderr: {res.stderr_ref}")

        after_sha = hashlib.sha256(checkout_file.read_bytes()).hexdigest()
        self.assertEqual(before_sha, after_sha)
        self.assertFalse((DEMO_TARGET_DIR / "extra.txt").exists())

    def test_no_shell_injection_execution(self) -> None:
        sandbox = Sandbox()
        marker = DEMO_TARGET_DIR / "injected_marker.txt"
        res = sandbox.exec(
            str(DEMO_TARGET_DIR),
            f'python3 -c "print(123)" ; touch {marker}',
            timeout_s=10.0,
        )
        # Because python3 -c receives only "print(123)" as argv[2] and extra args in sys.argv,
        # `;` and `touch` are never interpreted by a shell.
        self.assertEqual(res.exit_code, 0)
        self.assertFalse(marker.exists())


if __name__ == "__main__":
    unittest.main()
