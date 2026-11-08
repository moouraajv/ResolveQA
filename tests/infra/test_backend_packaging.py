"""Automated tests for ResolveQA AWS packaging, Dockerfile, CloudFormation template, and origin security."""

from __future__ import annotations

import os
import re
import stat
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import unittest
from pathlib import Path

# Paths
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DOCKERFILE_PATH = REPO_ROOT / "Dockerfile"
DOCKERIGNORE_PATH = REPO_ROOT / ".dockerignore"
TEMPLATE_PATH = REPO_ROOT / "infra" / "aws" / "template.yaml"
DEPLOY_DOC_PATH = REPO_ROOT / "docs" / "deploy-backend.md"
RUN_SERVER_SCRIPT = REPO_ROOT / "scripts" / "run_server.py"
SMOKE_TEST_SCRIPT = REPO_ROOT / "scripts" / "smoke_test.py"
PACKAGE_BUNDLE_SCRIPT = REPO_ROOT / "scripts" / "package_bundle.py"
DEPLOY_DRY_RUN_SCRIPT = REPO_ROOT / "scripts" / "deploy_dry_run.sh"

SCRIPTS_DIR = str(REPO_ROOT / "scripts")
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)


class BackendPackagingValidationTest(unittest.TestCase):
    """Verifies packaging artifacts, Dockerfile security, and CloudFormation template."""

    def test_dockerfile_security_and_directives(self) -> None:
        self.assertTrue(DOCKERFILE_PATH.is_file(), "Dockerfile must exist")
        content = DOCKERFILE_PATH.read_text(encoding="utf-8")

        self.assertIn("FROM python:3.11-slim", content)
        self.assertRegex(content, r"useradd .*resolveqa", "Must create non-root user resolveqa")
        self.assertIn("USER resolveqa", content, "Must switch to non-root USER resolveqa")
        self.assertIn("EXPOSE 8080", content)
        self.assertIn("PYTHONDONTWRITEBYTECODE=1", content)
        self.assertIn("PYTHONUNBUFFERED=1", content)
        self.assertIn("PYTHONPATH=/app/src", content)
        self.assertIn("HEALTHCHECK", content)
        self.assertIn("RESOLVEQA_ORIGIN_SECRET", content, "Healthcheck must handle origin secret")
        self.assertIn("/health", content)
        self.assertIn('ENTRYPOINT ["python", "scripts/run_server.py"]', content)

    def test_dockerignore_entries(self) -> None:
        self.assertTrue(DOCKERIGNORE_PATH.is_file(), ".dockerignore must exist")
        lines = set(DOCKERIGNORE_PATH.read_text(encoding="utf-8").splitlines())

        self.assertIn(".git", lines)
        self.assertIn("__pycache__", lines)
        self.assertIn("*.pyc", lines)
        self.assertIn("docs/", lines)
        self.assertIn("infra/", lines)
        self.assertIn("tests/", lines)

    def test_cloudformation_template_structure_and_security(self) -> None:
        self.assertTrue(TEMPLATE_PATH.is_file(), "infra/aws/template.yaml must exist")
        content = TEMPLATE_PATH.read_text(encoding="utf-8")

        self.assertIn("AWSTemplateFormatVersion: '2010-09-09'", content)

        # Origin secret validation: NoEcho, AllowedPattern, no hardcoded default
        self.assertIn("OriginSecretHeader:", content)
        self.assertIn("NoEcho: true", content)
        self.assertIn("AllowedPattern: ^[a-fA-F0-9]{32,128}$", content)
        self.assertNotIn(
            "Default: ResolveQA-Origin-Verify-Secret-Token-2026",
            content,
            "OriginSecretHeader must not have a hardcoded default token",
        )

        # CloudFront Prefix List configuration for port 8080 ingress
        self.assertIn("CloudFrontPrefixListId:", content)
        self.assertIn("pl-3b927c52", content)
        self.assertIn("SourcePrefixListId: !Ref CloudFrontPrefixListId", content)

        # Instance architecture restricted to ARM64 Graviton
        self.assertIn("InstanceType:", content)
        self.assertIn("t4g.nano", content)
        self.assertIn("t4g.micro", content)
        self.assertNotIn("t3.micro", content, "Must not allow x86 t3 with ARM64 AMI")

        # IAM role and profile for S3 artifact retrieval
        self.assertIn("BackendInstanceRole:", content)
        self.assertIn("BackendInstanceProfile:", content)
        self.assertIn("s3:GetObject", content)
        self.assertIn("ArtifactBucket", content)
        self.assertIn("ArtifactKey", content)
        self.assertIn("ArtifactSha256", content)

        # CreationPolicy and cfn-signal
        self.assertIn("CreationPolicy:", content)
        self.assertIn("ResourceSignal:", content)
        self.assertIn("cfn-signal", content)
        self.assertIn("sha256sum -c", content)

        # Token must NOT be passed in ExecStart command line (use EnvironmentFile)
        self.assertIn("EnvironmentFile=/etc/resolveqa/backend.env", content)
        self.assertNotIn("ExecStart=/usr/bin/python3.11 scripts/run_server.py --host 0.0.0.0 --port 8080 --origin-secret", content)
        self.assertIn("chmod 600 /etc/resolveqa/backend.env", content)

        # CloudFront HTTPS enforcement and CacheDisabled policy
        self.assertIn("ViewerProtocolPolicy: redirect-to-https", content)
        self.assertIn("4135ea2d-6df8-44a3-9df3-4b5a84be39ad", content)

    def test_deploy_docs_clarifications_and_cost_breakdown(self) -> None:
        self.assertTrue(DEPLOY_DOC_PATH.is_file(), "docs/deploy-backend.md must exist")
        doc = DEPLOY_DOC_PATH.read_text(encoding="utf-8")

        self.assertIn("EphemeralCaseStore", doc)
        self.assertIn("jornada completa e real de resolução de bugs", doc)
        self.assertIn("SubscriptionRequiredException", doc)
        self.assertNotIn("usuário proibiu assinaturas", doc)
        self.assertIn("IPv4 Público", doc)
        self.assertIn("pl-3b927c52", doc)
        self.assertIn("<AWS_ACCOUNT_ID>", doc)

    def test_security_hygiene_no_account_ids_or_local_paths(self) -> None:
        checked_files = [
            DOCKERFILE_PATH,
            DOCKERIGNORE_PATH,
            TEMPLATE_PATH,
            DEPLOY_DOC_PATH,
            RUN_SERVER_SCRIPT,
            SMOKE_TEST_SCRIPT,
            PACKAGE_BUNDLE_SCRIPT,
            DEPLOY_DRY_RUN_SCRIPT,
            REPO_ROOT / "scripts" / "validate_template.sh",
            Path(__file__).resolve(),
        ]
        for path in checked_files:
            with self.subTest(file=path.name):
                text = path.read_text(encoding="utf-8")
                self.assertIsNone(
                    re.search(r"\b\d{12}\b", text),
                    f"{path.name} must not contain a 12-digit AWS account ID",
                )
                self.assertIsNone(
                    re.search(r"arn:aws:[a-z0-9-]+:[a-z0-9-]*:\d{12}:", text),
                    f"{path.name} must not contain an AWS ARN with an account ID",
                )
                self.assertIsNone(
                    re.search(r"--profile\s+[A-Za-z0-9_-]+", text),
                    f"{path.name} must not hardcode a named AWS CLI profile",
                )
                self.assertIsNone(
                    re.search(r"/(?:home|Users)/[A-Za-z0-9_.-]+", text),
                    f"{path.name} must not contain local user home paths",
                )
                self.assertIsNone(
                    re.search(r"~/\.local", text),
                    f"{path.name} must not contain local user tool paths",
                )
                self.assertIsNone(
                    re.search(r"file:/{3}", text),
                    f"{path.name} must not contain absolute file URI links",
                )

        # deploy_dry_run.sh must use clean build by default (no --allow-dirty)
        dry_run_text = DEPLOY_DRY_RUN_SCRIPT.read_text(encoding="utf-8")
        self.assertNotIn(
            "--allow-dirty",
            dry_run_text,
            "deploy_dry_run.sh must enforce clean bundle build by default",
        )


class LocalServerRuntimeAndOriginSecurityTest(unittest.TestCase):
    """Spawns an ephemeral server locally and tests origin security, smoke tests, and Docker healthcheck."""

    def test_origin_security_enforcement(self) -> None:
        import run_server
        import smoke_test

        secret = "test-secret-token-abcdef1234567890"
        server = run_server._create_server("127.0.0.1", 0, origin_secret=secret)
        host, port = server.server_address
        base_url = f"http://{host}:{port}"

        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        try:
            time.sleep(0.1)

            # Direct request without header -> 403 Forbidden
            st, data = smoke_test._request(base_url, "GET", "/health", headers={})
            self.assertEqual(st, 403)
            self.assertIn("forbidden", str(data).lower())

            # Request with wrong header -> 403 Forbidden
            st, data = smoke_test._request(
                base_url,
                "GET",
                "/health",
                headers={"X-ResolveQA-Origin-Verify": "wrong-secret-token"},
            )
            self.assertEqual(st, 403)
            self.assertIn("forbidden", str(data).lower())

            # Request with correct header -> 200 OK
            st, data = smoke_test._request(
                base_url,
                "GET",
                "/health",
                headers={"X-ResolveQA-Origin-Verify": secret},
            )
            self.assertEqual(st, 200)
            self.assertTrue(isinstance(data, dict) and data.get("ok") is True)

            # Full smoke test suite with origin secret passed
            result = smoke_test.run_smoke_tests(base_url, origin_secret=secret)
            self.assertTrue(result, "Smoke test suite must pass with valid origin secret")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_dockerfile_healthcheck_logic(self) -> None:
        import run_server

        secret = "docker-healthcheck-token-1234567890"
        server = run_server._create_server("127.0.0.1", 0, origin_secret=secret)
        host, port = server.server_address

        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        try:
            time.sleep(0.1)
            # Command from Dockerfile HEALTHCHECK
            cmd = (
                f"import os, sys, urllib.request; "
                f"req = urllib.request.Request('http://{host}:{port}/health'); "
                f"secret = os.environ.get('RESOLVEQA_ORIGIN_SECRET'); "
                f"(req.add_header('X-ResolveQA-Origin-Verify', secret.strip()) if secret and secret.strip() else None); "
                f"sys.exit(0 if urllib.request.urlopen(req).getcode() == 200 else 1)"
            )

            # 1. With correct RESOLVEQA_ORIGIN_SECRET env var -> exit code 0
            env_with_secret = os.environ.copy()
            env_with_secret["RESOLVEQA_ORIGIN_SECRET"] = secret
            proc_ok = subprocess.run([sys.executable, "-c", cmd], env=env_with_secret)
            self.assertEqual(proc_ok.returncode, 0, "Healthcheck must succeed when origin secret env is configured")

            # 2. Without env var -> fails with HTTP 403 (unhealthy when server expects token)
            env_empty = os.environ.copy()
            env_empty.pop("RESOLVEQA_ORIGIN_SECRET", None)
            proc_fail = subprocess.run([sys.executable, "-c", cmd], env=env_empty)
            self.assertNotEqual(proc_fail.returncode, 0, "Healthcheck must fail when server requires token but none provided")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_reproducible_package_bundle_determinism(self) -> None:
        import package_bundle

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            p1 = tmp / "bundle1.tar.gz"
            p2 = tmp / "bundle2.tar.gz"

            _, d1, s1 = package_bundle.build_bundle(p1, reject_dirty=False)
            time.sleep(1.1)
            _, d2, s2 = package_bundle.build_bundle(p2, reject_dirty=False)

            self.assertEqual(d1, d2, "Hashes of bundles built at different times must be bit-for-bit identical")
            self.assertEqual(s1, s2, "File sizes must be identical")
            self.assertEqual(p1.read_bytes(), p2.read_bytes(), "Bundle bytes must be identical")

            # Inspect manifest inside archive
            with tarfile.open(p1, "r:gz") as tar:
                names = tar.getnames()
                self.assertIn("resolveqa-manifest.json", names)
                manifest_file = tar.extractfile("resolveqa-manifest.json")
                self.assertIsNotNone(manifest_file)
                import json
                manifest_data = json.loads(manifest_file.read().decode("utf-8"))
                self.assertIn("commit_sha", manifest_data)
                self.assertIn("components", manifest_data)

            # Verify reject_dirty=True rejects uncommitted edits in src/ or scripts/
            fake_repo = tmp / "fake_repo"
            (fake_repo / "src").mkdir(parents=True)
            (fake_repo / "scripts").mkdir(parents=True)
            sample_file = fake_repo / "src" / "app.py"
            sample_file.write_text("x = 1\n", encoding="utf-8")
            subprocess.run(["git", "init"], cwd=fake_repo, check=True, capture_output=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=fake_repo, check=True, capture_output=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=fake_repo, check=True, capture_output=True)
            subprocess.run(["git", "add", "."], cwd=fake_repo, check=True, capture_output=True)
            subprocess.run(["git", "commit", "-m", "init"], cwd=fake_repo, check=True, capture_output=True)

            # Clean build succeeds even if Python created untracked __pycache__/*.pyc
            pycache_dir = fake_repo / "src" / "__pycache__"
            pycache_dir.mkdir(parents=True)
            (pycache_dir / "app.cpython-311.pyc").write_bytes(b"bytecode")
            clean_out = tmp / "clean.tar.gz"
            package_bundle.build_bundle(clean_out, repo_root=fake_repo, reject_dirty=True)
            self.assertTrue(clean_out.is_file())

            # Dirty edit in src/ is rejected when reject_dirty=True
            sample_file.write_text("x = 2\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                package_bundle.build_bundle(tmp / "dirty.tar.gz", repo_root=fake_repo, reject_dirty=True)

    def test_deploy_dry_run_parameters_and_redaction(self) -> None:
        # Run deploy_dry_run.sh and verify it exits 0 without printing secrets
        proc = subprocess.run(
            ["bash", str(DEPLOY_DRY_RUN_SCRIPT), "test-bucket", "test-stack"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0, f"deploy_dry_run.sh failed: {proc.stderr}")

        # Check dist/parameters-demo.json exists and has 0600 permissions
        params_file = REPO_ROOT / "dist" / "parameters-demo.json"
        self.assertTrue(params_file.is_file(), "parameters-demo.json must be generated")
        file_mode = stat.S_IMODE(params_file.stat().st_mode)
        self.assertEqual(file_mode, 0o600, "parameters-demo.json must have chmod 600 permissions")

        # Verify stdout does NOT print the parameter value literally
        import json
        params_data = json.loads(params_file.read_text(encoding="utf-8"))
        origin_secret = next(
            p["ParameterValue"] for p in params_data if p["ParameterKey"] == "OriginSecretHeader"
        )
        self.assertTrue(len(origin_secret) >= 32, "Secret must be at least 32 chars")
        # Ensure the secret does not appear on stdout
        self.assertNotIn(
            origin_secret,
            proc.stdout,
            "Origin secret token must be redacted and never printed to stdout",
        )

        # Cleanup test params and dist
        import shutil
        dist_dir = REPO_ROOT / "dist"
        if dist_dir.exists():
            shutil.rmtree(dist_dir)


if __name__ == "__main__":
    unittest.main()
