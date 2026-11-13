"""Filesystem job queue for local multi-process spine (no AWS)."""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Optional

from .protocol import CaseJob


class FileCaseQueue:
    """Drop JSON jobs under runs/_queue/pending; claim into inflight/."""

    def __init__(self, root: Path | str) -> None:
        base = Path(root).resolve() / "_queue"
        self.pending = base / "pending"
        self.inflight = base / "inflight"
        self.pending.mkdir(parents=True, exist_ok=True)
        self.inflight.mkdir(parents=True, exist_ok=True)

    def enqueue(self, case_id: str, *, attempt: int = 1) -> None:
        if not isinstance(case_id, str) or not case_id.strip():
            raise ValueError("case_id must be a non-empty string")
        name = f"{int(time.time() * 1000)}-{uuid.uuid4().hex}.json"
        path = self.pending / name
        payload = {"case_id": case_id.strip(), "attempt": int(attempt)}
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
        tmp.replace(path)

    def dequeue(self, *, wait_seconds: int = 5) -> Optional[CaseJob]:
        deadline = time.time() + max(0, wait_seconds)
        while True:
            files = sorted(self.pending.glob("*.json"))
            for src in files:
                dest = self.inflight / src.name
                try:
                    src.replace(dest)
                except FileNotFoundError:
                    continue
                data = json.loads(dest.read_text(encoding="utf-8"))
                return CaseJob(
                    case_id=str(data["case_id"]),
                    attempt=int(data.get("attempt", 1)),
                    receipt_handle=str(dest),
                )
            if time.time() >= deadline:
                return None
            time.sleep(0.2)

    def ack(self, job: CaseJob) -> None:
        if not job.receipt_handle:
            return
        path = Path(job.receipt_handle)
        if path.is_file():
            path.unlink()

    def nack(self, job: CaseJob, *, requeue: bool = True) -> None:
        if job.receipt_handle:
            path = Path(job.receipt_handle)
            if path.is_file():
                path.unlink()
        if requeue:
            self.enqueue(job.case_id, attempt=job.attempt + 1)
