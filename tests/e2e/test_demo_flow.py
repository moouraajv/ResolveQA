"""E2E demo: verified package+reply and needs_info without patch (#19)."""

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
    NeedsInfoTerminalReason,
    ReplayRef,
    RunState,
    Verdict,
    VerdictResult,
)
from resolveqa.contracts.stages import TestRun as ContractTestRun
from resolveqa.delivery import DeliveryBuilder
from resolveqa.intake import Intake
from resolveqa.playbook import load_playbook
from resolveqa.reply import ReplyComposer, ReplyOutcome
from resolveqa.store import EventStore
from resolveqa.timeline import load_timeline


def _verdict() -> Verdict:
    return Verdict(
        before=ContractTestRun("pytest -q", 1, 0.2, "evidence/before.log"),
        after=ContractTestRun("pytest -q", 0, 0.2, "evidence/after.log"),
        suite=ContractTestRun("pytest -q", 0, 0.3, "evidence/suite.log"),
        base_revision="base-sha",
        fix_revision="fix-sha",
        result=VerdictResult.VERIFIED,
        reasons=("red_before_green_after", "suite_green"),
    )


class TestDemoEndToEnd(unittest.TestCase):
    def test_verified_flow_package_reply_and_replay(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runs = root / "runs"
            pb_path = root / "playbook.json"
            pb_path.write_text(
                json.dumps(
                    {
                        "approvers": ["reviewer1"],
                        "reply": {"tone": "friendly", "max_chars": 240},
                        "docs": {
                            "changelog_path": "CHANGELOG.md",
                            "technical_notes_dir": "technical_notes",
                            "kb_drafts_dir": "kb_drafts",
                        },
                    }
                ),
                encoding="utf-8",
            )
            book = load_playbook(pb_path)
            intake = Intake()
            from resolveqa.contracts import ReportInput

            created = intake.create(
                ReportInput(
                    client_id="client-demo",
                    repo_ref="demo-target",
                    channel=ChannelType.SIMULATED_CHAT,
                    report_text="Cupom 10% em R$ 200 retornou R$ 200 em vez de R$ 180.",
                )
            )
            case_id = created.case_id
            store = EventStore(runs)
            store.append(
                Event(
                    event_id="e0",
                    case_id=case_id,
                    seq=0,
                    ts="2026-11-07T12:00:00Z",
                    source=EventSource.INTAKE,
                    type=EventType.CASE_CREATED,
                )
            )
            store.append(
                Event(
                    event_id="e1",
                    case_id=case_id,
                    seq=1,
                    ts="2026-11-07T12:08:00Z",
                    source=EventSource.VERIFICATION,
                    type=EventType.STATE_CHANGED,
                    from_state=CaseState.VERIFYING,
                    to_state=CaseState.VERIFIED,
                )
            )

            evidence = runs / case_id / "evidence"
            evidence.mkdir(parents=True)
            (evidence / "cause.txt").write_text("Cupom percentual não aplicado.\n", encoding="utf-8")
            (evidence / "diff.patch").write_text(
                "--- a/checkout.py\n+++ b/checkout.py\n+apply_coupon\n",
                encoding="utf-8",
            )
            (evidence / "before.log").write_text("RED assertion\n", encoding="utf-8")
            (evidence / "after.log").write_text("GREEN assertion\n", encoding="utf-8")
            (evidence / "suite.log").write_text("suite green\n", encoding="utf-8")
            (evidence / "corrected_behavior.txt").write_text(
                "total agora R$ 180,00\n", encoding="utf-8"
            )

            verified = RunState(
                case_id=case_id,
                client_id=created.client_id,
                repo_ref=created.repo_ref,
                channel=created.channel,
                report_text=created.report_text,
                state=CaseState.VERIFIED,
                created_at=created.created_at,
                updated_at="2026-11-07T12:08:00Z",
                base_revision="base-sha",
                fix_revision="fix-sha",
            )
            # No false verified: verdict must be VERIFIED with red-before/green-after.
            verdict = _verdict()
            self.assertEqual(verdict.result, VerdictResult.VERIFIED)
            self.assertNotEqual(verdict.before.exit_code, 0)
            self.assertEqual(verdict.after.exit_code, 0)

            delivery = DeliveryBuilder(runs_root=runs, playbook=book).build(verified, verdict)
            package = Path(delivery.url_or_path)
            self.assertTrue((package / "CHANGELOG.md").is_file())
            self.assertTrue((package / "technical_notes" / f"{case_id}.md").is_file())
            self.assertIn("## Fixed", (package / "CHANGELOG.md").read_text(encoding="utf-8"))

            message = ReplyComposer(book).compose(
                verified,
                ReplyOutcome(corrected_behavior="total agora R$ 180,00"),
                events=store.list_events(case_id),
            )
            self.assertIn("total agora R$ 180,00", message.text)

            # Persist run for labeled replay.
            replay_id = f"{case_id}-replay"
            store.append(
                Event(
                    event_id="r0",
                    case_id=replay_id,
                    seq=0,
                    ts="2026-11-08T01:00:00Z",
                    source=EventSource.ORCHESTRATOR,
                    type=EventType.REPLAY_STARTED,
                    replay_of=ReplayRef(case_id=case_id, original_ts="2026-11-07T12:00:00Z"),
                )
            )
            entries = load_timeline(runs, replay_id)
            self.assertTrue(entries[0].is_replay)
            self.assertIn("2026-11-07T12:00:00Z", str(entries[0].to_dict()["label"]))

    def test_needs_info_without_patch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runs = Path(tmp) / "runs"
            case = RunState(
                case_id="case-needs-info",
                client_id="client-demo",
                repo_ref="demo-target",
                channel=ChannelType.API,
                report_text="algo quebrou",
                state=CaseState.NEEDS_INFO,
                created_at="2026-11-07T12:00:00Z",
                updated_at="2026-11-07T12:01:00Z",
                terminal_reason=NeedsInfoTerminalReason(
                    question_to_support="qual era o valor esperado?"
                ),
            )
            store = EventStore(runs)
            store.append(
                Event(
                    event_id="n0",
                    case_id=case.case_id,
                    seq=0,
                    ts="2026-11-07T12:00:00Z",
                    source=EventSource.INTAKE,
                    type=EventType.CASE_CREATED,
                )
            )
            store.append(
                Event(
                    event_id="n1",
                    case_id=case.case_id,
                    seq=1,
                    ts="2026-11-07T12:01:00Z",
                    source=EventSource.TRIAGE,
                    type=EventType.STATE_CHANGED,
                    from_state=CaseState.TRIAGING,
                    to_state=CaseState.NEEDS_INFO,
                    reason="qual era o valor esperado?",
                )
            )
            # No evidence/diff package for needs_info.
            self.assertFalse((runs / case.case_id / "evidence" / "diff.patch").exists())
            msg = ReplyComposer().compose(case, ReplyOutcome(), events=store.list_events(case.case_id))
            self.assertIn("andamento", msg.text.lower())
            self.assertNotIn("corrigimos", msg.text.lower())
            with self.assertRaises(Exception):
                DeliveryBuilder(runs_root=runs).build(case, _verdict())


if __name__ == "__main__":
    unittest.main()
