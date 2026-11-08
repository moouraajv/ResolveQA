"""Edge tests for playbook-driven reply tone, approvers, docs and KB (#24–#27)."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from resolveqa.contracts import (
    CaseState,
    ChannelType,
    Event,
    EventSource,
    EventType,
    RunState,
    Verdict,
    VerdictResult,
)
from resolveqa.contracts.stages import TestRun as ContractTestRun
from resolveqa.delivery import DeliveryBuilder
from resolveqa.playbook import ReplyTone, load_playbook
from resolveqa.reply import ReplyComposer, ReplyOutcome


def _case(state: CaseState = CaseState.VERIFIED, case_id: str = "case-pb-1") -> RunState:
    return RunState(
        case_id=case_id,
        client_id="client-demo",
        repo_ref="demo-target",
        channel=ChannelType.SIMULATED_CHAT,
        report_text="total saiu R$ 200,00 em vez de R$ 180,00",
        state=state,
        created_at="2026-11-07T12:00:00Z",
        updated_at="2026-11-07T12:10:00Z",
        base_revision="base-sha",
        fix_revision="fix-sha",
    )


def _events(case_id: str = "case-pb-1") -> list[Event]:
    return [
        Event(
            event_id="e0",
            case_id=case_id,
            seq=0,
            ts="2026-11-07T12:00:00Z",
            source=EventSource.INTAKE,
            type=EventType.CASE_CREATED,
        ),
        Event(
            event_id="e1",
            case_id=case_id,
            seq=1,
            ts="2026-11-07T12:09:00Z",
            source=EventSource.VERIFICATION,
            type=EventType.STATE_CHANGED,
            from_state=CaseState.VERIFYING,
            to_state=CaseState.VERIFIED,
        ),
    ]


def _verdict() -> Verdict:
    return Verdict(
        before=ContractTestRun("pytest -q", 1, 0.2, "evidence/before.log"),
        after=ContractTestRun("pytest -q", 0, 0.2, "evidence/after.log"),
        suite=ContractTestRun("pytest -q", 0, 0.3, "evidence/suite.log"),
        base_revision="base-sha",
        fix_revision="fix-sha",
        result=VerdictResult.VERIFIED,
        reasons=("red_before_green_after",),
    )


def _seed(runs: Path, case_id: str) -> None:
    evidence = runs / case_id / "evidence"
    evidence.mkdir(parents=True)
    (evidence / "cause.txt").write_text("Cupom não aplicado.\n", encoding="utf-8")
    (evidence / "diff.patch").write_text(
        "diff --git a/checkout.py b/checkout.py\n--- a/checkout.py\n+++ b/checkout.py\n+return total*0.9\n",
        encoding="utf-8",
    )
    (evidence / "before.log").write_text("FAILED\n", encoding="utf-8")
    (evidence / "after.log").write_text("PASSED\n", encoding="utf-8")
    (evidence / "suite.log").write_text("ok\n", encoding="utf-8")
    (evidence / "corrected_behavior.txt").write_text("total agora R$ 180,00\n", encoding="utf-8")


class TestPlaybookReplyAndDelivery(unittest.TestCase):
    def test_tone_and_max_chars_preserve_facts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "playbook.json"
            path.write_text(
                json.dumps(
                    {
                        "reply": {"tone": "formal", "max_chars": 120},
                    }
                ),
                encoding="utf-8",
            )
            book = load_playbook(path)
            assert book is not None
            self.assertEqual(book.reply_tone, ReplyTone.FORMAL)
            msg = ReplyComposer(book).compose(
                _case(),
                ReplyOutcome(corrected_behavior="total agora R$ 180,00"),
                events=_events(),
            )
            self.assertIn("total agora R$ 180,00", msg.text)
            self.assertIn("Informamos", msg.text)
            self.assertLessEqual(len(msg.text), 120)

            # Without playbook: default tone.
            default = ReplyComposer(None).compose(
                _case(),
                ReplyOutcome(corrected_behavior="total agora R$ 180,00"),
                events=_events(),
            )
            self.assertIn("Corrigimos o problema", default.text)

    def test_approvers_changelog_note_and_kb_in_package(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runs = root / "runs"
            pb = root / "playbook.json"
            pb.write_text(
                json.dumps(
                    {
                        "approvers": ["alice", "!bob", 123, "bad name"],
                        "docs": {
                            "changelog_path": "CHANGELOG.md",
                            "technical_notes_dir": "technical_notes",
                            "kb_drafts_dir": "kb_drafts",
                        },
                    }
                ),
                encoding="utf-8",
            )
            book = load_playbook(pb)
            assert book is not None
            self.assertIn("alice", book.approvers)
            self.assertIn("bob", book.approvers)
            self.assertTrue(book.approver_warnings)

            case = _case(case_id="case-docs-1")
            _seed(runs, case.case_id)
            result = DeliveryBuilder(runs_root=runs, playbook=book).build(case, _verdict())
            package = Path(result.url_or_path)
            self.assertTrue((package / "APPROVERS.md").is_file())
            approvers_md = (package / "APPROVERS.md").read_text(encoding="utf-8")
            self.assertIn("@alice", approvers_md)
            self.assertIn("warning", approvers_md.lower())
            self.assertIn("auto_merge: false", approvers_md)

            changelog = (package / "CHANGELOG.md").read_text(encoding="utf-8")
            self.assertIn("## Fixed", changelog)
            self.assertIn(case.case_id, changelog)
            self.assertIn("total agora R$ 180,00", changelog)

            note = (package / "technical_notes" / f"{case.case_id}.md").read_text(encoding="utf-8")
            self.assertIn("sha256=", note)
            self.assertIn("base-sha", note)
            self.assertIn("fix-sha", note)
            self.assertIn("checkout.py", note)

            kb = (package / "kb_drafts" / f"{case.case_id}.md").read_text(encoding="utf-8")
            self.assertIn("Rascunho — requer revisão humana", kb)
            self.assertIn("## Sintoma", kb)
            self.assertIn("revisão humana", kb)
            self.assertIn("publicado automaticamente", kb.lower())
            self.assertIn("não", kb.lower())
            self.assertNotIn("return total", kb)  # no source code dump


if __name__ == "__main__":
    unittest.main()
