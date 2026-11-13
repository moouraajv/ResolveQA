"""EventStore wrapper that mirrors StateChanged transitions into a CaseStore."""

from __future__ import annotations

from typing import Any, Callable

from resolveqa.contracts import Event, EventType, RunState
from resolveqa.store.events import EventStore


class SyncingEventStore:
    """Delegate to EventStore and push reconstructed RunState to a case store."""

    def __init__(
        self,
        events: EventStore,
        *,
        seed: RunState,
        on_case: Callable[[RunState], None],
    ) -> None:
        self._events = events
        self._seed = seed
        self._current = seed
        self._on_case = on_case

    def __getattr__(self, name: str) -> Any:
        return getattr(self._events, name)

    def list_events(self, case_id: str):
        return self._events.list_events(case_id)

    def next_seq(self, case_id: str) -> int:
        return self._events.next_seq(case_id)

    def reconstruct_state(self, base: RunState) -> RunState:
        return self._events.reconstruct_state(base)

    def append(self, event: Event) -> Event:
        written = self._events.append(event)
        if event.type in {EventType.STATE_CHANGED, EventType.LIMIT_REACHED}:
            self._current = self._events.reconstruct_state(self._seed)
            self._on_case(self._current)
        return written

    @property
    def current(self) -> RunState:
        return self._current
