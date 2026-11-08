"""Ephemeral in-memory case store for local Intake demos (not durable persistence)."""

from __future__ import annotations

import threading
from typing import Optional

from resolveqa.contracts import RunState


class EphemeralCaseStore:
    """Thread-safe in-memory map of case_id -> RunState.

    Explicitly ephemeral / local-demo only: process restart clears all cases.
    Does not promise durability, replication, or Trilha A store integration.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._cases: dict[str, RunState] = {}

    def put(self, case: RunState) -> None:
        with self._lock:
            self._cases[case.case_id] = case

    def get(self, case_id: str) -> Optional[RunState]:
        with self._lock:
            return self._cases.get(case_id)

    def __len__(self) -> int:
        with self._lock:
            return len(self._cases)
