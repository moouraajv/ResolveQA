"""Automated tests for ResolveQA AWS packaging, Dockerfile, CloudFormation template, and origin security."""

from __future__ import annotations

import subprocess
import sys
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
        self.assertIn("urllib.request", content)
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

        # Origin secret must NOT have a default value
        self.assertIn("OriginSecretHeader:", content)
        self.assertIn("NoEcho: true", content)
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

        # CloudFront HTTPS enforcement and CacheDisabled policy
        self.assertIn("ViewerProtocolPolicy: redirect-to-https", content)
        self.assertIn("4135ea2d-6df8-44a3-9df3-44184ec0b026", content)

    def test_deploy_docs_clarifications_and_cost_breakdown(self) -> None:
        self.assertTrue(DEPLOY_DOC_PATH.is_file(), "docs/deploy-backend.md must exist")
        doc = DEPLOY_DOC_PATH.read_text(encoding="utf-8")

        self.assertIn("EphemeralCaseStore", doc)
        self.assertIn("jornada completa e real de resolução de bugs", doc)
        self.assertIn("SubscriptionRequiredException", doc)
        self.assertNotIn("usuário proibiu assinaturas", doc)
        self.assertIn("IPv4 Público", doc)
        self.assertIn("pl-3b927c52", doc)


class LocalServerRuntimeAndOriginSecurityTest(unittest.TestCase):
    """Spawns an ephemeral server locally and tests origin security and smoke tests."""

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

    def test_package_bundle_generation_and_integrity(self) -> None:
        import package_bundle

        target, digest, size_bytes = package_bundle.build_bundle()
        self.assertTrue(target.is_file(), "Bundle file must exist")
        self.assertGreater(size_bytes, 1000, "Bundle must contain files")
        self.assertEqual(len(digest), 64, "SHA-256 digest must be 64 hex characters")

        # Re-verify checksum directly
        import hashlib
        h = hashlib.sha256(target.read_bytes()).hexdigest()
        self.assertEqual(digest, h)


if __name__ == "__main__":
    unittest.main()
