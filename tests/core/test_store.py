"""Tests for append-only event store and case_id path guards (issue #6)."""

from __future__ import annotations

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
)
from resolveqa.store import EventStore, EventStoreError, validate_case_id


def _base_case(case_id: str = "case-safe-001") -> RunState:
    return RunState(
        case_id=case_id,
        client_id="client-demo",
        repo_ref="demo-target",
        channel=ChannelType.API,
        report_text="coupon applies 10% but total stays 200",
        state=CaseState.CREATED,
        created_at="2026-11-07T20:00:00Z",
        updated_at="2026-11-07T20:00:00Z",
    )


class TestEventStore(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.runs_root = Path(self._tmp.name) / "runs"
        self.store = EventStore(self.runs_root)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_validate_case_id_rejects_traversal_and_separators(self) -> None:
        for bad in (
            "",
            " ",
            ".",
            "..",
            "../x",
            "a/../b",
            "a/b",
            "a\\b",
            "/abs",
            "x\0y",
        ):
            with self.subTest(case_id=bad):
                with self.assertRaises(EventStoreError):
                    validate_case_id(bad)

    def test_case_dir_rejects_traversal_case_id(self) -> None:
        with self.assertRaises(EventStoreError):
            self.store.case_dir("../escape")

    def test_append_only_preserves_history(self) -> None:
        case_id = "case-append-1"
        first = Event(
            event_id="evt-1",
            case_id=case_id,
            seq=0,
            ts="2026-11-07T20:00:00Z",
            source=EventSource.INTAKE,
            type=EventType.CASE_CREATED,
        )
        second = Event(
            event_id="evt-2",
            case_id=case_id,
            seq=1,
            ts="2026-11-07T20:00:01Z",
            source=EventSource.ORCHESTRATOR,
            type=EventType.STATE_CHANGED,
            from_state=CaseState.CREATED,
            to_state=CaseState.TRIAGING,
        )
        self.store.append(first)
        self.store.append(second)

        path = self.store.events_path(case_id)
        raw = path.read_text(encoding="utf-8")
        lines = [line for line in raw.splitlines() if line.strip()]
        self.assertEqual(len(lines), 2)
        self.assertIn('"event_id":"evt-1"', lines[0])
        self.assertIn('"event_id":"evt-2"', lines[1])

        # Re-append with same/lower seq must fail without truncating file.
        with self.assertRaises(EventStoreError):
            self.store.append(first)
        after = path.read_text(encoding="utf-8")
        self.assertEqual(raw, after)
        self.assertEqual(len(self.store.list_events(case_id)), 2)

    def test_append_requires_contiguous_seq(self) -> None:
        case_id = "case-seq"
        self.store.append(
            Event(
                event_id="evt-0",
                case_id=case_id,
                seq=0,
                ts="2026-11-07T20:00:00Z",
                source=EventSource.INTAKE,
                type=EventType.CASE_CREATED,
            )
        )
        with self.assertRaises(EventStoreError):
            self.store.append(
                Event(
                    event_id="evt-gap",
                    case_id=case_id,
                    seq=3,
                    ts="2026-11-07T20:00:03Z",
                    source=EventSource.ORCHESTRATOR,
                    type=EventType.STATE_CHANGED,
                    from_state=CaseState.CREATED,
                    to_state=CaseState.TRIAGING,
                )
            )

    def test_reconstruct_state_from_events(self) -> None:
        base = _base_case("case-replay-1")
        self.store.append(
            Event(
                event_id="evt-0",
                case_id=base.case_id,
                seq=0,
                ts=base.created_at,
                source=EventSource.INTAKE,
                type=EventType.CASE_CREATED,
            )
        )
        self.store.append(
            Event(
                event_id="evt-1",
                case_id=base.case_id,
                seq=1,
                ts="2026-11-07T20:01:00Z",
                source=EventSource.ORCHESTRATOR,
                type=EventType.STATE_CHANGED,
                from_state=CaseState.CREATED,
                to_state=CaseState.TRIAGING,
            )
        )
        self.store.append(
            Event(
                event_id="evt-2",
                case_id=base.case_id,
                seq=2,
                ts="2026-11-07T20:02:00Z",
                source=EventSource.TRIAGE,
                type=EventType.STATE_CHANGED,
                from_state=CaseState.TRIAGING,
                to_state=CaseState.NEEDS_INFO,
                reason="Which coupon percent was applied?",
            )
        )
        rebuilt = self.store.reconstruct_state(base)
        self.assertEqual(rebuilt.state, CaseState.NEEDS_INFO)
        self.assertIsNotNone(rebuilt.terminal_reason)
        self.assertEqual(
            rebuilt.terminal_reason.question_to_support,  # type: ignore[union-attr]
            "Which coupon percent was applied?",
        )
        self.assertEqual(rebuilt.updated_at, "2026-11-07T20:02:00Z")
        # Base remains immutable / unchanged.
        self.assertEqual(base.state, CaseState.CREATED)


if __name__ == "__main__":
    unittest.main()
