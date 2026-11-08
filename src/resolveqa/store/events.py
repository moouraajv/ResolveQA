"""Append-only per-case event store under runs/<case_id>/events.jsonl (RFC-0001 §3.2, RNF-04)."""

from __future__ import annotations

from pathlib import Path

from resolveqa.contracts import (
    BlockedReason,
    BlockedTerminalReason,
    CaseState,
    Event,
    EventType,
    InfraErrorTerminalReason,
    NeedsInfoTerminalReason,
    RunState,
    TERMINAL_STATES,
    TerminalReason,
)


class EventStoreError(ValueError):
    """Raised when the event store rejects a case id, path, or append invariant."""


def validate_case_id(case_id: str) -> str:
    """Reject empty, absolute, or traversal-capable case identifiers."""
    if not isinstance(case_id, str) or not case_id.strip():
        raise EventStoreError("case_id must be a non-empty string")
    if case_id != case_id.strip():
        raise EventStoreError("case_id must not include surrounding whitespace")
    if case_id in {".", ".."}:
        raise EventStoreError(f"case_id is not allowed: {case_id!r}")
    if any(ch in case_id for ch in ("/", "\\", "\0")):
        raise EventStoreError(f"case_id must not contain path separators: {case_id!r}")
    if ".." in case_id:
        raise EventStoreError(f"case_id must not contain '..': {case_id!r}")
    return case_id


def terminal_reason_from_event(
    to_state: CaseState,
    reason: str | None,
) -> TerminalReason | None:
    """Rebuild a structured terminal reason from a StateChanged reason string."""
    if to_state == CaseState.VERIFIED:
        return None
    if to_state not in TERMINAL_STATES:
        return None
    if reason is None or not reason.strip():
        raise EventStoreError(
            f"StateChanged to {to_state.value} requires a non-empty reason for reconstruction"
        )
    if to_state == CaseState.BLOCKED:
        return BlockedTerminalReason(code=BlockedReason(reason))
    if to_state == CaseState.NEEDS_INFO:
        return NeedsInfoTerminalReason(question_to_support=reason)
    if to_state == CaseState.INFRA_ERROR:
        return InfraErrorTerminalReason(detail=reason)
    raise EventStoreError(f"Unhandled terminal state for reconstruction: {to_state.value}")


def reason_for_terminal(terminal_reason: TerminalReason | None) -> str | None:
    """Serialize a structured terminal reason into Event.reason."""
    if terminal_reason is None:
        return None
    if isinstance(terminal_reason, BlockedTerminalReason):
        return terminal_reason.code.value
    if isinstance(terminal_reason, NeedsInfoTerminalReason):
        return terminal_reason.question_to_support
    if isinstance(terminal_reason, InfraErrorTerminalReason):
        return terminal_reason.detail
    raise EventStoreError(
        f"Unsupported terminal_reason type: {type(terminal_reason).__name__}"
    )


class EventStore:
    """Filesystem event log: append-only JSONL under runs/<case_id>/events.jsonl."""

    def __init__(self, runs_root: Path | str) -> None:
        self.runs_root = Path(runs_root).resolve()
        self.runs_root.mkdir(parents=True, exist_ok=True)

    def case_dir(self, case_id: str) -> Path:
        """Return the resolved case directory, ensuring it stays under runs_root."""
        safe_id = validate_case_id(case_id)
        target = (self.runs_root / safe_id).resolve()
        try:
            target.relative_to(self.runs_root)
        except ValueError as err:
            raise EventStoreError(
                f"case_id resolves outside runs root: {case_id!r}"
            ) from err
        return target

    def events_path(self, case_id: str) -> Path:
        """Return events.jsonl path after rejecting symlinks and escapes."""
        return self._events_file(case_id)

    def _events_file(self, case_id: str) -> Path:
        case_dir = self.case_dir(case_id)
        path = case_dir / "events.jsonl"
        if path.is_symlink():
            raise EventStoreError(
                f"events.jsonl must not be a symlink for case_id={case_id!r}"
            )
        if path.exists():
            resolved = path.resolve()
            try:
                resolved.relative_to(self.runs_root)
            except ValueError as err:
                raise EventStoreError(
                    f"events.jsonl resolves outside runs root for case_id={case_id!r}"
                ) from err
            if resolved.name != "events.jsonl":
                raise EventStoreError(
                    f"events.jsonl resolved to unexpected name: {resolved.name!r}"
                )
            try:
                resolved.parent.resolve().relative_to(self.runs_root)
            except ValueError as err:
                raise EventStoreError(
                    f"events.jsonl parent escapes runs root for case_id={case_id!r}"
                ) from err
        return path

    def list_events(self, case_id: str) -> list[Event]:
        path = self._events_file(case_id)
        if not path.exists():
            return []
        events: list[Event] = []
        with path.open("r", encoding="utf-8") as handle:
            for line_no, raw in enumerate(handle, start=1):
                line = raw.strip()
                if not line:
                    continue
                try:
                    events.append(Event.from_json(line))
                except Exception as err:
                    raise EventStoreError(
                        f"Invalid event at {path}:{line_no}: {err}"
                    ) from err
        return events

    def next_seq(self, case_id: str) -> int:
        events = self.list_events(case_id)
        if not events:
            return 0
        return events[-1].seq + 1

    def append(self, event: Event) -> Event:
        """Append one event. Never truncates or rewrites history."""
        safe_id = validate_case_id(event.case_id)
        if event.case_id != safe_id:
            raise EventStoreError("event.case_id failed validation")

        existing = self.list_events(event.case_id)
        expected_seq = 0 if not existing else existing[-1].seq + 1
        if event.seq != expected_seq:
            raise EventStoreError(
                f"Event seq must be contiguous: expected {expected_seq}, got {event.seq}"
            )
        if existing and event.seq <= existing[-1].seq:
            raise EventStoreError("Refusing to overwrite or reorder event history")

        case_dir = self.case_dir(event.case_id)
        case_dir.mkdir(parents=True, exist_ok=True)
        path = self._events_file(event.case_id)
        # Re-check immediately before open to reduce symlink TOCTOU window.
        if path.is_symlink():
            raise EventStoreError(
                f"events.jsonl must not be a symlink for case_id={event.case_id!r}"
            )
        # Append-only: open with 'a' exclusively; never 'w'/'w+'.
        with path.open("a", encoding="utf-8") as handle:
            handle.write(event.to_json(separators=(",", ":")) + "\n")
        return event

    def reconstruct_state(self, base: RunState) -> RunState:
        """Rebuild case state by replaying StateChanged events onto an immutable base."""
        if not isinstance(base, RunState):
            raise EventStoreError(
                f"reconstruct_state expects RunState, got {type(base).__name__}"
            )
        current = base
        for event in self.list_events(base.case_id):
            if event.type != EventType.STATE_CHANGED:
                continue
            if event.from_state != current.state:
                raise EventStoreError(
                    "StateChanged from_state does not match reconstructed state: "
                    f"event={event.from_state}, current={current.state}"
                )
            assert event.to_state is not None
            terminal = None
            if event.to_state in TERMINAL_STATES and event.to_state != CaseState.VERIFIED:
                terminal = terminal_reason_from_event(event.to_state, event.reason)
            current = current.transition_to(
                event.to_state,
                updated_at=event.ts,
                terminal_reason=terminal,
            )
        return current
