"""Tests for EvidenceStore (Issue #6 / Tarefa B, RFC-0001 §3.4, RNF-04)."""

from __future__ import annotations

import hashlib
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from resolveqa.contracts import Evidence, EvidenceKind
from resolveqa.store.evidence_store import EvidenceStore, redact_secrets


class TestEvidenceStore(unittest.TestCase):
    """Validate EvidenceStore isolation, secret scrubbing, sha256, path traversal guard, and unique evidence_id."""

    def test_saves_evidence_in_runs_case_dir_with_sha256_and_scrubs_secrets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = EvidenceStore(runs_root=tmp)
            raw_content = (
                "Relato com segredo sk-secretkey1234567890 e ghp_secrettoken1234567890 "
                "e AKIAIOSFODNN7EXAMPLE e Bearer supersecretbearer12345"
            )
            with patch.dict(os.environ, {"FEATHERLESS_API_KEY": "rc_env_secret_token_999999"}, clear=False):
                ev = store.save_evidence(
                    case_id="case-001",
                    evidence_id="ev-triage-001",
                    kind=EvidenceKind.TRIAGE_RECORD,
                    content=raw_content + " rc_env_secret_token_999999",
                    extension="json",
                )

            self.assertIsInstance(ev, Evidence)
            self.assertEqual(ev.case_id, "case-001")
            self.assertEqual(ev.evidence_id, "ev-triage-001")
            self.assertEqual(ev.kind, EvidenceKind.TRIAGE_RECORD)
            self.assertEqual(ev.path, "evidence/ev-triage-001.json")

            saved_file = Path(tmp) / "case-001" / "evidence" / "ev-triage-001.json"
            self.assertTrue(saved_file.is_file())
            saved_bytes = saved_file.read_bytes()
            saved_text = saved_bytes.decode("utf-8")

            self.assertEqual(ev.sha256, hashlib.sha256(saved_bytes).hexdigest())
            for secret in (
                "sk-secretkey1234567890",
                "ghp_secrettoken1234567890",
                "AKIAIOSFODNN7EXAMPLE",
                "supersecretbearer12345",
                "rc_env_secret_token_999999",
            ):
                self.assertNotIn(secret, saved_text)
            self.assertIn("[REDACTED_SECRET]", saved_text)

    def test_refuses_overwrite_of_existing_evidence_id_and_generates_unique_ids(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = EvidenceStore(runs_root=tmp)
            ev1 = store.save_evidence(
                case_id="case-dup",
                evidence_id="ev-fixed-id",
                kind=EvidenceKind.TEST_LOG,
                content="first log",
                extension="log",
            )
            self.assertEqual(ev1.evidence_id, "ev-fixed-id")

            # Reusing the same evidence_id must fail with FileExistsError (even with a different extension)
            with self.assertRaises(FileExistsError):
                store.save_evidence(
                    case_id="case-dup",
                    evidence_id="ev-fixed-id",
                    kind=EvidenceKind.TEST_LOG,
                    content="second log",
                    extension="log",
                )
            with self.assertRaises(FileExistsError):
                store.save_evidence(
                    case_id="case-dup",
                    evidence_id="ev-fixed-id",
                    kind=EvidenceKind.TEST_LOG,
                    content="second log txt",
                    extension="txt",
                )

            # Original content must remain intact
            saved_file = Path(tmp) / "case-dup" / "evidence" / "ev-fixed-id.log"
            self.assertEqual(saved_file.read_text(encoding="utf-8"), "first log")

            # Auto-generated / next_evidence_id produces distinct IDs per write
            auto1 = store.save_evidence(
                case_id="case-dup",
                evidence_id=None,
                kind=EvidenceKind.TRIAGE_RECORD,
                content='{"attempt": 1}',
                extension="json",
            )
            auto2 = store.save_evidence(
                case_id="case-dup",
                evidence_id=None,
                kind=EvidenceKind.TRIAGE_RECORD,
                content='{"attempt": 2}',
                extension="json",
            )
            self.assertNotEqual(auto1.evidence_id, auto2.evidence_id)
            self.assertNotEqual(auto1.path, auto2.path)

    def test_blocks_path_traversal_in_case_id_and_evidence_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = EvidenceStore(runs_root=tmp)
            bad_values = ["../escape", "../../etc/passwd", "/abs/path", "a/b", "a\\b", ".", "..", ""]
            for bad in bad_values:
                with self.subTest(bad_case_id=bad):
                    with self.assertRaises(ValueError):
                        store.save_evidence(
                            case_id=bad,
                            evidence_id="ev-001",
                            kind=EvidenceKind.REPORT,
                            content="x",
                        )
                if bad:
                    with self.subTest(bad_evidence_id=bad):
                        with self.assertRaises(ValueError):
                            store.save_evidence(
                                case_id="case-ok",
                                evidence_id=bad,
                                kind=EvidenceKind.REPORT,
                                content="x",
                            )

            # Also block symlink traversal on case_dir or evidence_dir
            with tempfile.TemporaryDirectory() as outside_tmp:
                symlink_case = Path(tmp) / "case-symlink"
                symlink_case.symlink_to(outside_tmp)
                with self.assertRaises(ValueError):
                    store.save_evidence(
                        case_id="case-symlink",
                        evidence_id="ev-001",
                        kind=EvidenceKind.REPORT,
                        content="x",
                    )

    def test_does_not_depend_on_sandbox_executor_for_secret_redaction(self) -> None:
        source_path = Path(__file__).resolve().parents[2] / "src" / "resolveqa" / "store" / "evidence_store.py"
        source_text = source_path.read_text(encoding="utf-8")
        self.assertNotIn("sandbox", source_text)
        self.assertEqual(redact_secrets("token=sk-1234567890abcdef"), "token=[REDACTED_SECRET]")


if __name__ == "__main__":
    unittest.main()
