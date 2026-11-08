"""Automated tests for ResolveQA AWS packaging, Dockerfile, and server entrypoints."""

from __future__ import annotations

import re
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


class BackendPackagingValidationTest(unittest.TestCase):
    """Verifies packaging artifacts, Dockerfile security, and CloudFormation template."""

    def test_dockerfile_security_and_directives(self) -> None:
        self.assertTrue(DOCKERFILE_PATH.is_file(), "Dockerfile must exist")
        content = DOCKERFILE_PATH.read_text(encoding="utf-8")

        # Base image
        self.assertIn("FROM python:3.11-slim", content)

        # Non-root user setup
        self.assertRegex(content, r"useradd .*resolveqa", "Must create non-root user resolveqa")
        self.assertIn("USER resolveqa", content, "Must switch to non-root USER resolveqa")

        # Port and environment
        self.assertIn("EXPOSE 8080", content)
        self.assertIn("PYTHONDONTWRITEBYTECODE=1", content)
        self.assertIn("PYTHONUNBUFFERED=1", content)
        self.assertIn("PYTHONPATH=/app/src", content)

        # Healthcheck using stdlib
        self.assertIn("HEALTHCHECK", content)
        self.assertIn("urllib.request", content)
        self.assertIn("/health", content)

        # Entrypoint
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

    def test_cloudformation_template_structure(self) -> None:
        self.assertTrue(TEMPLATE_PATH.is_file(), "infra/aws/template.yaml must exist")
        content = TEMPLATE_PATH.read_text(encoding="utf-8")

        # AWS version and metadata
        self.assertIn("AWSTemplateFormatVersion: '2010-09-09'", content)
        self.assertIn("Ephemeral Demo Backend", content)

        # Required parameters
        for param in ["EnvironmentName", "InstanceType", "AmiId", "VpcId", "SubnetId", "OriginSecretHeader"]:
            with self.subTest(parameter=param):
                self.assertIn(f"{param}:", content)

        # Core resources
        for resource in ["BackendSecurityGroup:", "BackendInstance:", "CloudFrontDistribution:"]:
            with self.subTest(resource=resource):
                self.assertIn(resource, content)

        # CloudFront HTTPS enforcement
        self.assertIn("ViewerProtocolPolicy: redirect-to-https", content)

        # Cache disabled policy ID for real-time dynamic requests
        self.assertIn("4135ea2d-6df8-44a3-9df3-44184ec0b026", content)

        # Required outputs
        for output in [
            "CloudFrontDomainName:",
            "CloudFrontBaseUrl:",
            "HealthEndpoint:",
            "FormEndpoint:",
            "ChatEndpoint:",
            "EphemeralStorageNotice:",
        ]:
            with self.subTest(output=output):
                self.assertIn(output, content)

    def test_deploy_docs_clarifications(self) -> None:
        self.assertTrue(DEPLOY_DOC_PATH.is_file(), "docs/deploy-backend.md must exist")
        doc = DEPLOY_DOC_PATH.read_text(encoding="utf-8")

        # Must explicitly mention hackathon scope, ephemeral storage, and agent pipeline distinction
        self.assertIn("EphemeralCaseStore", doc)
        self.assertIn("jornada completa e real de resolução de bugs", doc)
        self.assertIn("SubscriptionRequiredException", doc)
        self.assertIn("CloudFront", doc)


class LocalServerRuntimeAndSmokeTest(unittest.TestCase):
    """Spawns an ephemeral server locally and runs smoke test validations."""

    def test_ephemeral_server_and_smoke_test_suite(self) -> None:
        import sys
        scripts_dir = str(REPO_ROOT / "scripts")
        if scripts_dir not in sys.path:
            sys.path.insert(0, scripts_dir)

        import run_server
        import smoke_test

        # Create server on loopback with OS-assigned ephemeral port
        server = run_server._create_server("127.0.0.1", 0)
        host, port = server.server_address
        base_url = f"http://{host}:{port}"

        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        try:
            # Allow server thread to initialize
            time.sleep(0.1)

            # Execute smoke tests against the running server
            result = smoke_test.run_smoke_tests(base_url)
            self.assertTrue(result, "All smoke tests must pass against the live server")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_smoke_test_failure_on_unreachable_endpoint(self) -> None:
        import sys
        scripts_dir = str(REPO_ROOT / "scripts")
        if scripts_dir not in sys.path:
            sys.path.insert(0, scripts_dir)

        import smoke_test

        # Port 1 is virtually guaranteed to fail/refuse connection
        result = smoke_test.run_smoke_tests("http://127.0.0.1:1")
        self.assertFalse(result, "Smoke test must return False when endpoint is unreachable")


if __name__ == "__main__":
    unittest.main()
