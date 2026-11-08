"""Edge tests for case timeline from events.jsonl (issue #15, RF-10)."""

from __future__ import annotations

import json
import threading
import unittest
from pathlib import Path
from urllib.request import urlopen

from resolveqa.contracts import (
    CaseState,
    Event,
    EventSource,
    EventType,
    ReplayRef,
)
from resolveqa.intake import Intake
from resolveqa.timeline import build_timeline_html, load_timeline
from resolveqa.web import IntakeHTTPServer


def _write_events(path: Path, events: list[Event]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(event.to_json(separators=(",", ":")) + "\n" for event in events),
        encoding="utf-8",
    )


class TestTimelineReader(unittest.TestCase):
    def test_each_transition_shows_timestamp_and_source(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            runs = Path(tmp)
            case_id = "case-timeline-1"
            events = [
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
                    ts="2026-11-07T12:01:00Z",
                    source=EventSource.ORCHESTRATOR,
                    type=EventType.STATE_CHANGED,
                    from_state=CaseState.CREATED,
                    to_state=CaseState.TRIAGING,
                ),
            ]
            _write_events(runs / case_id / "events.jsonl", events)
            entries = load_timeline(runs, case_id)
            self.assertEqual(len(entries), 2)
            self.assertEqual(entries[0].ts, "2026-11-07T12:00:00Z")
            self.assertEqual(entries[0].source, EventSource.INTAKE)
            self.assertEqual(entries[1].ts, "2026-11-07T12:01:00Z")
            self.assertEqual(entries[1].source, EventSource.ORCHESTRATOR)
            self.assertEqual(entries[1].from_state, CaseState.CREATED)
            self.assertEqual(entries[1].to_state, CaseState.TRIAGING)

    def test_no_invented_progress_when_events_missing(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            entries = load_timeline(tmp, "case-missing")
            self.assertEqual(entries, [])
            html = build_timeline_html("case-missing", entries)
            self.assertIn("Nenhum evento registrado", html)
            self.assertNotIn("triaging", html.lower())

    def test_replay_labeled_with_original_run_timestamp(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            runs = Path(tmp)
            case_id = "case-replay"
            original_ts = "2026-11-01T09:30:00Z"
            events = [
                Event(
                    event_id="r0",
                    case_id=case_id,
                    seq=0,
                    ts="2026-11-07T15:00:00Z",
                    source=EventSource.ORCHESTRATOR,
                    type=EventType.REPLAY_STARTED,
                    replay_of=ReplayRef(case_id="case-original", original_ts=original_ts),
                ),
            ]
            _write_events(runs / case_id / "events.jsonl", events)
            entries = load_timeline(runs, case_id)
            self.assertTrue(entries[0].is_replay)
            self.assertEqual(entries[0].original_ts, original_ts)
            label = entries[0].to_dict()["label"]
            self.assertIn(original_ts, str(label))
            html = build_timeline_html(case_id, entries)
            self.assertIn(original_ts, html)
            self.assertIn("replay", html.lower())


class _LiveServer:
    def __init__(self, runs_root: Path) -> None:
        self.server = IntakeHTTPServer(("127.0.0.1", 0), Intake(), runs_root=runs_root)
        self.host, self.port = self.server.server_address
        self._thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def base(self) -> str:
        return f"http://{self.host}:{self.port}"

    def __enter__(self) -> "_LiveServer":
        self._thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self.server.shutdown()
        self.server.server_close()
        self._thread.join(timeout=5)


class TestTimelineHttp(unittest.TestCase):
    def test_api_timeline_returns_real_events_only(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            runs = Path(tmp)
            case_id = "case-http-tl"
            _write_events(
                runs / case_id / "events.jsonl",
                [
                    Event(
                        event_id="e0",
                        case_id=case_id,
                        seq=0,
                        ts="2026-11-07T12:00:00Z",
                        source=EventSource.INTAKE,
                        type=EventType.CASE_CREATED,
                    )
                ],
            )
            with _LiveServer(runs) as live:
                with urlopen(f"{live.base}/api/cases/{case_id}/timeline", timeout=5) as resp:
                    payload = json.loads(resp.read().decode("utf-8"))
                self.assertEqual(payload["case_id"], case_id)
                self.assertEqual(len(payload["entries"]), 1)
                self.assertIn("nenhum progresso", payload["note"].lower())


if __name__ == "__main__":
    unittest.main()
