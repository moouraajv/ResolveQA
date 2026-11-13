"""In-memory case queue for tests and local two-process spine."""

from __future__ import annotations

import queue
import threading
from typing import Optional

from .protocol import CaseJob


class MemoryCaseQueue:
    """Thread-safe FIFO queue used when SQS is not configured."""

    def __init__(self) -> None:
        self._q: queue.Queue[CaseJob] = queue.Queue()
        self._inflight: dict[str, CaseJob] = {}
        self._lock = threading.RLock()

    def enqueue(self, case_id: str, *, attempt: int = 1) -> None:
        if not isinstance(case_id, str) or not case_id.strip():
            raise ValueError("case_id must be a non-empty string")
        self._q.put(CaseJob(case_id=case_id.strip(), attempt=int(attempt)))

    def dequeue(self, *, wait_seconds: int = 5) -> Optional[CaseJob]:
        try:
            job = self._q.get(timeout=max(0, wait_seconds))
        except queue.Empty:
            return None
        with self._lock:
            self._inflight[job.case_id] = job
        return job

    def ack(self, job: CaseJob) -> None:
        with self._lock:
            self._inflight.pop(job.case_id, None)

    def nack(self, job: CaseJob, *, requeue: bool = True) -> None:
        with self._lock:
            self._inflight.pop(job.case_id, None)
        if requeue:
            self.enqueue(job.case_id, attempt=job.attempt + 1)
