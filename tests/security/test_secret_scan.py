"""Secret scan over demo artifacts (issue #18, RNF-01)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from resolveqa.security import find_secrets_in_text, scan_paths_for_secrets


class TestSecretScan(unittest.TestCase):
    def test_clean_demo_artifacts_have_no_findings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            case_dir = root / "runs" / "case-demo"
            evidence = case_dir / "evidence"
            evidence.mkdir(parents=True)
            (case_dir / "events.jsonl").write_text(
                '{"event_id":"e0","case_id":"case-demo","seq":0,'
                '"ts":"2026-11-07T12:00:00Z","source":"intake","type":"CaseCreated"}\n',
                encoding="utf-8",
            )
            (evidence / "report.txt").write_text(
                "Relato: total saiu R$ 200,00 em vez de R$ 180,00.\n",
                encoding="utf-8",
            )
            (case_dir / "run.log").write_text("suite green\n", encoding="utf-8")
            # Paths that #26 / #27 will populate — scanner must cover them.
            (root / "CHANGELOG.md").write_text(
                "## Fixed\n- case-demo: total agora R$ 180,00\n",
                encoding="utf-8",
            )
            notes = root / "technical_notes"
            notes.mkdir()
            (notes / "case-demo.md").write_text(
                "# Nota técnica\nCausa: cupom aplicado duas vezes.\n",
                encoding="utf-8",
            )
            kb = root / "kb_drafts"
            kb.mkdir()
            (kb / "case-demo.md").write_text(
                "Rascunho — requer revisão humana\nSintoma: total errado.\n",
                encoding="utf-8",
            )

            findings = scan_paths_for_secrets([root, case_dir])
            self.assertEqual(findings, [])

    def test_scan_detects_planted_secret(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "run.log").write_text(
                "export OPENAI_API_KEY=sk-thisIsNotARealSecretValue123\n",
                encoding="utf-8",
            )
            findings = scan_paths_for_secrets([root])
            self.assertTrue(any(f.kind == "openai_key" for f in findings))

    def test_find_secrets_in_text_helpers(self) -> None:
        self.assertEqual(find_secrets_in_text("sem segredo aqui"), [])
        hits = find_secrets_in_text("token=ghp_abcdefghijklmnop")
        self.assertTrue(hits)


if __name__ == "__main__":
    unittest.main()
