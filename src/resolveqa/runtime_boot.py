"""Shared bootstrapping for API server and worker (store + queue selection)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from resolveqa.intake.dynamo_store import DynamoCaseStore
from resolveqa.intake.file_store import FileCaseStore
from resolveqa.intake.store import EphemeralCaseStore
from resolveqa.queue.file_queue import FileCaseQueue
from resolveqa.queue.memory import MemoryCaseQueue
from resolveqa.queue.sqs import SqsCaseQueue


def resolve_root(explicit: str | Path | None = None) -> Path:
    if explicit is not None:
        return Path(explicit).resolve()
    env = os.environ.get("RESOLVEQA_ROOT")
    if env:
        return Path(env).resolve()
    return Path(__file__).resolve().parents[2]


def build_case_store(*, root: Path | None = None) -> Any:
    """Select case store from RESOLVEQA_CASE_STORE (memory|file|dynamodb)."""
    kind = (os.environ.get("RESOLVEQA_CASE_STORE") or "memory").strip().lower()
    root = resolve_root(root)
    if kind == "file":
        return FileCaseStore(root / "runs")
    if kind == "dynamodb":
        table = os.environ.get("RESOLVEQA_DDB_TABLE")
        if not table:
            raise RuntimeError("RESOLVEQA_DDB_TABLE is required for dynamodb store")
        return DynamoCaseStore(
            table,
            region=os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION"),
        )
    return EphemeralCaseStore()


def build_case_queue(*, root: Path | None = None) -> Any | None:
    """Select queue from RESOLVEQA_QUEUE. Empty/none disables enqueue (legacy intake)."""
    kind = (os.environ.get("RESOLVEQA_QUEUE") or "").strip().lower()
    if not kind or kind in {"none", "off", "disabled"}:
        return None
    root = resolve_root(root)
    if kind == "memory":
        return MemoryCaseQueue()
    if kind == "file":
        return FileCaseQueue(root / "runs")
    if kind == "sqs":
        url = os.environ.get("RESOLVEQA_SQS_URL")
        if not url:
            raise RuntimeError("RESOLVEQA_SQS_URL is required for sqs queue")
        return SqsCaseQueue(
            url,
            region=os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION"),
        )
    raise RuntimeError(f"unknown RESOLVEQA_QUEUE={kind!r}")


def storage_label(store: Any) -> str:
    name = type(store).__name__
    if name == "EphemeralCaseStore":
        return "ephemeral-in-memory"
    if name == "FileCaseStore":
        return "file"
    if name == "DynamoCaseStore":
        return "dynamodb"
    return name
