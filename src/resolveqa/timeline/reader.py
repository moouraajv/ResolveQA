"""Read honest case timelines from runs/<case_id>/events.jsonl (RF-10, RNF-04)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from resolveqa.contracts import CaseState, Event, EventSource, EventType, ReplayRef


class TimelineError(ValueError):
    """Raised when a timeline cannot be loaded honestly from disk."""


@dataclass(frozen=True)
class TimelineEntry:
    """One real event projected for support display — never simulated progress."""

    seq: int
    ts: str
    source: EventSource
    type: EventType
    from_state: CaseState | None
    to_state: CaseState | None
    reason: str | None
    evidence_refs: tuple[str, ...]
    is_replay: bool
    original_ts: str | None
    replay_case_id: str | None

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "seq": self.seq,
            "ts": self.ts,
            "source": self.source.value,
            "type": self.type.value,
            "from_state": None if self.from_state is None else self.from_state.value,
            "to_state": None if self.to_state is None else self.to_state.value,
            "reason": self.reason,
            "evidence_refs": list(self.evidence_refs),
            "is_replay": self.is_replay,
        }
        label = f"{self.type.value} · {self.ts} · origem={self.source.value}"
        if self.from_state is not None and self.to_state is not None:
            label += f" · {self.from_state.value} → {self.to_state.value}"
        if self.is_replay:
            payload["original_ts"] = self.original_ts
            payload["replay_case_id"] = self.replay_case_id
            label += f" · Replay · horário do run original: {self.original_ts}"
        payload["label"] = label
        return payload


def _validate_case_id(case_id: str) -> str:
    if not isinstance(case_id, str) or not case_id.strip():
        raise TimelineError("case_id must be a non-empty string")
    if case_id != case_id.strip():
        raise TimelineError("case_id must not include surrounding whitespace")
    if case_id in {".", ".."} or any(ch in case_id for ch in ("/", "\\", "\0")) or ".." in case_id:
        raise TimelineError(f"case_id is not allowed: {case_id!r}")
    return case_id


def events_path(runs_root: Path | str, case_id: str) -> Path:
    """Resolve runs/<case_id>/events.jsonl without leaving the runs root."""
    root = Path(runs_root).resolve()
    safe_id = _validate_case_id(case_id)
    case_dir = (root / safe_id).resolve()
    try:
        case_dir.relative_to(root)
    except ValueError as err:
        raise TimelineError(f"case_id resolves outside runs root: {case_id!r}") from err
    path = case_dir / "events.jsonl"
    if path.is_symlink():
        raise TimelineError(f"events.jsonl must not be a symlink for case_id={case_id!r}")
    return path


def _entry_from_event(event: Event) -> TimelineEntry:
    replay: ReplayRef | None = event.replay_of
    return TimelineEntry(
        seq=event.seq,
        ts=event.ts,
        source=event.source,
        type=event.type,
        from_state=event.from_state,
        to_state=event.to_state,
        reason=event.reason,
        evidence_refs=event.evidence_refs,
        is_replay=replay is not None,
        original_ts=None if replay is None else replay.original_ts,
        replay_case_id=None if replay is None else replay.case_id,
    )


def load_timeline(runs_root: Path | str, case_id: str) -> list[TimelineEntry]:
    """Load the real event sequence. Empty file/missing path => empty timeline (no invented steps)."""
    path = events_path(runs_root, case_id)
    if not path.exists():
        return []
    entries: list[TimelineEntry] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_no, raw in enumerate(handle, start=1):
            line = raw.strip()
            if not line:
                continue
            try:
                event = Event.from_json(line)
            except Exception as err:
                raise TimelineError(f"Invalid event at {path}:{line_no}: {err}") from err
            if event.case_id != case_id:
                raise TimelineError(
                    f"Event case_id mismatch at {path}:{line_no}: "
                    f"expected {case_id!r}, got {event.case_id!r}"
                )
            entries.append(_entry_from_event(event))
    return entries
