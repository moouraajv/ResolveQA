"""Queue protocol for asynchronous case processing."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Protocol, runtime_checkable


@dataclass(frozen=True)
class CaseJob:
    """Unit of work for the cloud worker."""

    case_id: str
    attempt: int = 1
    receipt_handle: str | None = None


@runtime_checkable
class CaseQueue(Protocol):
    """Enqueue / dequeue case jobs."""

    def enqueue(self, case_id: str, *, attempt: int = 1) -> None:
        """Publish a case for worker processing."""

    def dequeue(self, *, wait_seconds: int = 5) -> Optional[CaseJob]:
        """Receive one job or None when idle."""

    def ack(self, job: CaseJob) -> None:
        """Acknowledge successful processing."""

    def nack(self, job: CaseJob, *, requeue: bool = True) -> None:
        """Release or dead-letter a failed job."""
