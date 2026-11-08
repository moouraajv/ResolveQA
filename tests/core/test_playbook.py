"""Unit tests for project playbook schema and loader (Issue #22, RF-05, RF-06, RNF-03)."""

from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from resolveqa.playbook import (
    BASELINE_LIMITS,
    DEFAULT_FORBIDDEN_PATHS,
    DEFAULT_PROTECTED_TESTS,
    ApproverWarning,
    DocsConfig,
    PathsConfig,
    Playbook,
    PlaybookError,
    PlaybookLimits,
    PlaybookSyntaxError,
    ReplyConfig,
    ReplyTone,
    TestsConfig,
    load_playbook,
    load_playbook_from_base,
    parse_playbook_dict,
    parse_playbook_toml,
    validate_glob_pattern,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
DEMO_TARGET_DIR = REPO_ROOT / "demo-target"

VALID_TOML = """\
version = 1
approvers = ["alice", "!bob_guest", "charlie"]

[paths]
allowed = ["src/**", "lib/*.py"]
forbidden = ["private/**", "internal/*"]

[tests]
protected = ["my_tests/**"]

[reply]
tone = "formal"
max_chars = 350

[docs]
changelog_path = "DOCS_CHANGELOG.md"
technical_notes_dir = "notes"
kb_drafts_dir = "drafts"

[limits]
max_fix_attempts = 1
max_llm_calls = 8
test_timeout_s = 120.0
max_files_changed = 2
max_output_bytes = 32768
"""


class TestPlaybookLoader(unittest.TestCase):
    """Validate Issue #22 acceptance criteria for playbook schema, loader, and validation."""

    def test_valid_toml_parsing_and_schema_fields(self) -> None:
        pb = parse_playbook_toml(VALID_TOML, source_path="dummy.toml")
        self.assertEqual(pb.version, 1)
        self.assertIn("src/**", pb.paths.allowed)
        self.assertIn("lib/*.py", pb.paths.allowed)
        self.assertIn("private/**", pb.paths.forbidden)
        # Verify default forbidden paths are preserved
        self.assertIn(".resolveqa/playbook.toml", pb.paths.forbidden)
        self.assertIn(".resolveqa/**", pb.paths.forbidden)

        # Verify tests.protected appends to default protected paths
        self.assertIn("my_tests/**", pb.tests.protected)
        for def_test in DEFAULT_PROTECTED_TESTS:
            self.assertIn(def_test, pb.tests.protected)

        # Verify approvers and warnings
        self.assertEqual(pb.approvers, ("alice", "bob_guest", "charlie"))
        self.assertEqual(len(pb.approver_warnings), 1)
        self.assertEqual(pb.approver_warnings[0].approver, "bob_guest")
        self.assertTrue(pb.has_approvers)

        # Verify reply
        self.assertEqual(pb.reply.tone, ReplyTone.FORMAL)
        self.assertEqual(pb.reply_tone, ReplyTone.FORMAL)
        self.assertEqual(pb.reply.max_chars, 350)
        self.assertEqual(pb.reply_max_chars, 350)

        # Verify docs
        self.assertEqual(pb.docs.changelog_path, "DOCS_CHANGELOG.md")
        self.assertEqual(pb.changelog_path, "DOCS_CHANGELOG.md")
        self.assertEqual(pb.docs.technical_notes_dir, "notes")
        self.assertEqual(pb.docs.kb_drafts_dir, "drafts")

        # Verify limits
        self.assertEqual(pb.limits.max_fix_attempts, 1)
        self.assertEqual(pb.limits.max_llm_calls, 8)
        self.assertEqual(pb.limits.test_timeout_s, 120.0)
        self.assertEqual(pb.limits.max_files_changed, 2)
        self.assertEqual(pb.limits.max_output_bytes, 32768)

        # Verify default flag and sha256
        self.assertFalse(pb.is_default)
        self.assertFalse(pb.default)
        self.assertIsNotNone(pb.sha256)
        expected_sha = hashlib.sha256(VALID_TOML.encode("utf-8")).hexdigest()
        self.assertEqual(pb.sha256, expected_sha)

    def test_malformed_toml_is_rejected_with_line_and_column(self) -> None:
        malformed_snippet = "version = 1\n[paths\nallowed = ['x']"
        with self.assertRaises(PlaybookSyntaxError) as ctx:
            parse_playbook_toml(malformed_snippet)

        err = ctx.exception
        self.assertIsNotNone(err.line, "Syntax error must record line number")
        self.assertIsNotNone(err.column, "Syntax error must record column number")
        err_msg = str(err)
        self.assertIn("line", err_msg)
        self.assertIn("column", err_msg)

    def test_unknown_keys_rejected_with_field_name(self) -> None:
        # Unknown root key
        with self.assertRaises(PlaybookError) as ctx:
            parse_playbook_dict({"version": 1, "unknown_field": True})
        self.assertIn("unknown_field", str(ctx.exception))
        self.assertEqual(ctx.exception.field, "unknown_field")

        # Unknown key in sub-tables
        sub_tables = [
            ({"paths": {"allowed": ["*"], "extra_paths": 123}}, "paths.extra_paths"),
            ({"tests": {"protected": ["*"], "extra_tests": 123}}, "tests.extra_tests"),
            ({"reply": {"tone": "friendly", "unknown_reply": 1}}, "reply.unknown_reply"),
            ({"docs": {"changelog_path": "a", "unknown_docs": 1}}, "docs.unknown_docs"),
            ({"limits": {"max_fix_attempts": 1, "bad_limit": 1}}, "limits.bad_limit"),
        ]
        for data, expected_field in sub_tables:
            with self.subTest(field=expected_field):
                with self.assertRaises(PlaybookError) as ctx:
                    parse_playbook_dict(data)
                self.assertIn(expected_field.split(".")[-1], str(ctx.exception))
                self.assertEqual(ctx.exception.field, expected_field)

    def test_invalid_types_rejected_with_field_name(self) -> None:
        invalid_type_cases = [
            ({"version": "not-an-int"}, "version"),
            ({"version": True}, "version"),
            ({"paths": "should-be-table"}, "paths"),
            ({"paths": {"allowed": "not-a-list"}}, "paths.allowed"),
            ({"paths": {"forbidden": "not-a-list"}}, "paths.forbidden"),
            ({"tests": "should-be-table"}, "tests"),
            ({"tests": {"protected": "not-a-list"}}, "tests.protected"),
            ({"approvers": "not-a-list"}, "approvers"),
            ({"approvers": 123}, "approvers"),
            ({"reply": "should-be-table"}, "reply"),
            ({"reply": {"tone": "invalid_tone"}}, "reply.tone"),
            ({"reply": {"max_chars": "not-an-int"}}, "reply.max_chars"),
            ({"reply": {"max_chars": -5}}, "reply.max_chars"),
            ({"docs": "should-be-table"}, "docs"),
            ({"docs": {"changelog_path": ""}}, "docs.changelog_path"),
            ({"limits": "should-be-table"}, "limits"),
            ({"limits": {"max_fix_attempts": "two"}}, "limits.max_fix_attempts"),
            ({"limits": {"test_timeout_s": "slow"}}, "limits.test_timeout_s"),
        ]
        for data, expected_field in invalid_type_cases:
            with self.subTest(field=expected_field):
                with self.assertRaises(PlaybookError) as ctx:
                    parse_playbook_dict(data)
                self.assertEqual(ctx.exception.field, expected_field)

    def test_invalid_glob_patterns_rejected(self) -> None:
        invalid_globs = [
            ("../traversal/**", "parent traversal"),
            ("foo/../../bar", "parent traversal"),
            ("/absolute/path/**", "absolute"),
            ("unmatched_[bracket.py", "unclosed brackets"),
        ]
        for bad_glob, reason in invalid_globs:
            with self.subTest(glob=bad_glob, reason=reason):
                with self.assertRaises(PlaybookError):
                    validate_glob_pattern(bad_glob, "paths.allowed")

                # Test via TOML parser
                toml_text = f"version = 1\n[paths]\nallowed = ['{bad_glob}']"
                with self.assertRaises(PlaybookError) as ctx:
                    parse_playbook_toml(toml_text)
                self.assertEqual(ctx.exception.field, "paths.allowed")

    def test_limits_must_be_strictly_within_rnf03_baseline(self) -> None:
        # Values exceeding RNF-03 baseline must be refused
        too_loose_limits = [
            ({"max_fix_attempts": 3}, "limits.max_fix_attempts"),
            ({"max_llm_calls": 13}, "limits.max_llm_calls"),
            ({"test_timeout_s": 601.0}, "limits.test_timeout_s"),
            ({"max_files_changed": 4}, "limits.max_files_changed"),
            ({"max_output_bytes": 70000}, "limits.max_output_bytes"),
        ]
        for lim, expected_field in too_loose_limits:
            with self.subTest(limit_field=expected_field):
                with self.assertRaises(PlaybookError) as ctx:
                    parse_playbook_dict({"limits": lim})
                self.assertEqual(ctx.exception.field, expected_field)
                self.assertIn("cannot be looser than", str(ctx.exception))

        # Values stricter than or equal to RNF-03 baseline must be accepted
        exact_baseline = {
            "max_fix_attempts": BASELINE_LIMITS["max_fix_attempts"],
            "max_llm_calls": BASELINE_LIMITS["max_llm_calls"],
            "test_timeout_s": BASELINE_LIMITS["test_timeout_s"],
            "max_files_changed": BASELINE_LIMITS["max_files_changed"],
            "max_output_bytes": BASELINE_LIMITS["max_output_bytes"],
        }
        pb_baseline = parse_playbook_dict({"limits": exact_baseline})
        self.assertEqual(pb_baseline.limits.max_fix_attempts, 2)
        self.assertEqual(pb_baseline.limits.max_llm_calls, 12)

        stricter = {
            "max_fix_attempts": 1,
            "max_llm_calls": 5,
            "test_timeout_s": 60.0,
            "max_files_changed": 1,
            "max_output_bytes": 1024,
        }
        pb_strict = parse_playbook_dict({"limits": stricter})
        self.assertEqual(pb_strict.limits.max_fix_attempts, 1)
        self.assertEqual(pb_strict.limits.max_llm_calls, 5)

    def test_tests_protected_only_adds_paths_never_removes(self) -> None:
        # When user defines custom tests.protected, all default paths remain protected
        pb = parse_playbook_dict({"tests": {"protected": ["special_tests/**"]}})
        self.assertIn("special_tests/**", pb.tests.protected)
        for def_test in DEFAULT_PROTECTED_TESTS:
            self.assertIn(def_test, pb.tests.protected)

        # When user defines empty protected tests, default paths still exist
        pb_empty = parse_playbook_dict({"tests": {"protected": []}})
        for def_test in DEFAULT_PROTECTED_TESTS:
            self.assertIn(def_test, pb_empty.tests.protected)

    def test_playbook_toml_is_unconditionally_protected(self) -> None:
        # .resolveqa/playbook.toml must be in paths.forbidden and tests.protected
        pb = parse_playbook_dict({})
        self.assertTrue(pb.is_path_forbidden(".resolveqa/playbook.toml"))
        self.assertTrue(pb.is_test_protected(".resolveqa/playbook.toml"))
        self.assertFalse(pb.is_path_allowed(".resolveqa/playbook.toml"))

        # User cannot allow .resolveqa/playbook.toml in paths.allowed
        with self.assertRaises(PlaybookError) as ctx:
            parse_playbook_dict({"paths": {"allowed": [".resolveqa/playbook.toml"]}})
        self.assertEqual(ctx.exception.field, "paths.allowed")

    def test_missing_file_returns_default_policy_marked_as_default(self) -> None:
        # When calling load_playbook on nonexistent path or empty directory
        with tempfile.TemporaryDirectory() as tmpdir:
            pb_empty_repo = load_playbook(tmpdir)
            self.assertTrue(pb_empty_repo.is_default)
            self.assertTrue(pb_empty_repo.default)
            self.assertIsNone(pb_empty_repo.sha256)
            self.assertEqual(pb_empty_repo.version, 1)
            self.assertEqual(pb_empty_repo.reply_tone, ReplyTone.NEUTRAL)
            self.assertEqual(pb_empty_repo.reply_max_chars, 500)
            self.assertEqual(pb_empty_repo.changelog_path, "CHANGELOG.md")
            self.assertEqual(pb_empty_repo.limits.max_fix_attempts, 2)

            # load_playbook(None)
            pb_none = load_playbook(None)
            self.assertTrue(pb_none.is_default)

            # load_playbook_from_base on empty repo
            pb_base, sha = load_playbook_from_base(tmpdir, base_revision="base-sha-123")
            self.assertTrue(pb_base.is_default)
            self.assertIsNone(sha)
            self.assertEqual(pb_base.base_revision, "base-sha-123")

    def test_load_playbook_from_base_records_sha256_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir)
            dot_resolveqa = repo_path / ".resolveqa"
            dot_resolveqa.mkdir()
            pb_file = dot_resolveqa / "playbook.toml"
            pb_file.write_text(VALID_TOML, encoding="utf-8")

            pb, sha256 = load_playbook_from_base(repo_path, base_revision="commit-sha-abc")
            self.assertFalse(pb.is_default)
            self.assertIsNotNone(sha256)
            expected_sha = hashlib.sha256(VALID_TOML.encode("utf-8")).hexdigest()
            self.assertEqual(sha256, expected_sha)
            self.assertEqual(pb.sha256, expected_sha)
            self.assertEqual(pb.base_revision, "commit-sha-abc")

    def test_demo_target_playbook_is_valid_and_covered(self) -> None:
        demo_pb_path = DEMO_TARGET_DIR / ".resolveqa" / "playbook.toml"
        self.assertTrue(demo_pb_path.is_file(), "demo-target/.resolveqa/playbook.toml must exist")

        pb, sha256 = load_playbook_from_base(DEMO_TARGET_DIR)
        self.assertFalse(pb.is_default)
        self.assertIsNotNone(sha256)
        self.assertEqual(pb.version, 1)
        self.assertIn("checkout.py", pb.paths.allowed)
        self.assertIn("tests/**", pb.tests.protected)
        self.assertEqual(pb.reply.tone, ReplyTone.FRIENDLY)
        self.assertEqual(pb.reply.max_chars, 280)
        self.assertTrue(pb.is_path_allowed("checkout.py"))
        self.assertFalse(pb.is_path_allowed("tests/test_checkout.py"))
        self.assertTrue(pb.is_test_protected("tests/test_checkout.py"))
        self.assertTrue(pb.is_path_forbidden(".resolveqa/playbook.toml"))

    def test_json_compatibility_mode_for_trilha_b(self) -> None:
        # Ensure json files loaded by Trilha B remain supported
        with tempfile.TemporaryDirectory() as tmpdir:
            json_file = Path(tmpdir) / "playbook.demo.json"
            json_file.write_text(
                '{"approvers": ["reviewer1", "!external"], "reply": {"tone": "friendly", "max_chars": 200}, "docs": {"changelog_path": "CHANGES.md"}}',
                encoding="utf-8",
            )
            pb = load_playbook(json_file)
            self.assertFalse(pb.is_default)
            self.assertEqual(pb.approvers, ("reviewer1", "external"))
            self.assertEqual(len(pb.approver_warnings), 1)
            self.assertEqual(pb.reply_tone, ReplyTone.FRIENDLY)
            self.assertEqual(pb.reply_max_chars, 200)
            self.assertEqual(pb.changelog_path, "CHANGES.md")

    # ==========================================================================
    # QA Adjustments Tests (Issue #22 - PR #57: P1, P2, P3, P4, P5, P7)
    # ==========================================================================

    def test_p1_rejects_unsafe_paths_in_allowed_and_forbidden(self) -> None:
        """P1: Rejeita caminho absoluto, letra de unidade, barra invertida e '..'."""
        pb = Playbook.create_default()  # allowed=['**']
        unsafe_paths = [
            "/etc/passwd",
            "../fora.py",
            "../../home/x/.ssh/id_rsa",
            "C:/x.py",
            "foo\\bar.py",
            "a/../b.py",
        ]
        for bad_path in unsafe_paths:
            with self.subTest(path=bad_path):
                self.assertFalse(
                    pb.is_path_allowed(bad_path),
                    f"is_path_allowed must be False for unsafe path: {bad_path}",
                )
                self.assertTrue(
                    pb.is_path_forbidden(bad_path),
                    f"is_path_forbidden must be True for unsafe path: {bad_path}",
                )

    def test_p2_removeprefix_no_false_positives(self) -> None:
        """P2: removeprefix('./') não gera falsos positivos em resolveqa/ e github/."""
        pb = Playbook.create_default()
        # resolveqa/legit.py and github/legit.py must not be forbidden/protected
        self.assertFalse(pb.is_path_forbidden("resolveqa/legit.py"))
        self.assertFalse(pb.is_test_protected("resolveqa/legit.py"))
        self.assertTrue(pb.is_path_allowed("resolveqa/legit.py"))

        self.assertFalse(pb.is_path_forbidden("github/legit.py"))
        self.assertTrue(pb.is_path_allowed("github/legit.py"))

        # Genuine .resolveqa and .github files must still be forbidden
        self.assertTrue(pb.is_path_forbidden(".resolveqa/playbook.toml"))
        self.assertTrue(pb.is_test_protected(".resolveqa/playbook.toml"))
        self.assertFalse(pb.is_path_allowed(".resolveqa/playbook.toml"))

        self.assertTrue(pb.is_path_forbidden(".github/workflows/ci.yml"))
        self.assertFalse(pb.is_path_allowed(".github/workflows/ci.yml"))

    def test_p3_runner_and_ci_configs_in_default_protected_and_forbidden(self) -> None:
        """P3: DEFAULT_FORBIDDEN_PATHS e DEFAULT_PROTECTED_TESTS incluem runner e CI."""
        expected_configs = [
            "pyproject.toml",
            "pytest.toml",
            ".pytest.toml",
            ".pytest.ini",
            "pytest.ini",
            "setup.cfg",
            "tox.ini",
            "conftest.py",
            "**/conftest.py",
            ".github/**",
            ".gitlab-ci.yml",
        ]
        for cfg in expected_configs:
            with self.subTest(config=cfg):
                self.assertIn(cfg, DEFAULT_FORBIDDEN_PATHS)
                self.assertIn(cfg, DEFAULT_PROTECTED_TESTS)

        pb = Playbook.create_default()
        test_files = [
            "pyproject.toml",
            "pytest.toml",
            ".pytest.toml",
            ".pytest.ini",
            "pytest.ini",
            "setup.cfg",
            "tox.ini",
            "conftest.py",
            "tests/conftest.py",
            "sub/nested/conftest.py",
            ".gitlab-ci.yml",
        ]
        for target in test_files:
            with self.subTest(file=target):
                self.assertTrue(
                    pb.is_path_forbidden(target),
                    f"{target} must be forbidden by default",
                )
                self.assertTrue(
                    pb.is_test_protected(target),
                    f"{target} must be protected by default",
                )
                self.assertFalse(
                    pb.is_path_allowed(target),
                    f"{target} must not be allowed by default",
                )

    def test_p4_allowed_matches_full_relative_path_not_basename(self) -> None:
        """P4: allowed casa pelo caminho relativo completo, não pelo basename."""
        pb = parse_playbook_dict({"paths": {"allowed": ["checkout.py"]}})
        self.assertTrue(pb.is_path_allowed("checkout.py"))
        self.assertTrue(pb.is_path_allowed("./checkout.py"))
        self.assertFalse(
            pb.is_path_allowed("evil/checkout.py"),
            "evil/checkout.py must not match allowed=['checkout.py'] by basename",
        )
        self.assertFalse(
            pb.is_path_allowed("sub/checkout.py"),
            "sub/checkout.py must not match allowed=['checkout.py']",
        )

    def test_p5_rejects_string_version_and_nested_approvers_without_mutation(self) -> None:
        """P5: version='1' (string) é recusado e [tests] approvers é recusado sem mutar dict."""
        # 1. version as string must be rejected
        with self.assertRaises(PlaybookError) as ctx:
            parse_playbook_dict({"version": "1"})
        self.assertEqual(ctx.exception.field, "version")

        # 2. [tests] approvers must be rejected and input dict must not be mutated
        input_data = {
            "tests": {
                "protected": ["tests/**"],
                "approvers": ["alice", "bob"],
            }
        }
        with self.assertRaises(PlaybookError) as ctx2:
            parse_playbook_dict(input_data)
        self.assertEqual(ctx2.exception.field, "tests.approvers")
        # Ensure input_data was NOT mutated
        self.assertNotIn("approvers", input_data)
        self.assertIn("approvers", input_data["tests"])
        self.assertEqual(input_data["tests"]["approvers"], ["alice", "bob"])

    def test_p7_load_playbook_restricts_paths_to_repo_or_config(self) -> None:
        """P7: load_playbook(path) é restrito ao repositório-alvo ou a config/."""
        # Reading outside files must be refused
        with self.assertRaises(PlaybookError):
            load_playbook("/etc/passwd")

        with self.assertRaises(PlaybookError):
            load_playbook("../../../etc/passwd")

        with self.assertRaises(PlaybookError):
            load_playbook("/etc")

        # Loading within repo, config, or demo-target must succeed
        pb_demo = load_playbook("config/playbook.demo.json")
        self.assertFalse(pb_demo.is_default)
        self.assertEqual(pb_demo.reply_tone, ReplyTone.FRIENDLY)

        pb_repo = load_playbook(DEMO_TARGET_DIR)
        self.assertFalse(pb_repo.is_default)


if __name__ == "__main__":
    unittest.main()
