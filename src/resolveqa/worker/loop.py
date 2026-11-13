"""Worker loop: dequeue case jobs and execute the agent pipeline."""

from __future__ import annotations

import logging
import os
import signal
import time
from pathlib import Path
from typing import Any, Optional

from resolveqa.contracts import CaseState, TERMINAL_STATES
from resolveqa.pipeline import run_pipeline
from resolveqa.queue.protocol import CaseJob, CaseQueue

logger = logging.getLogger("resolveqa.worker")

ROOT = Path(__file__).resolve().parents[3]


def _build_llm(*, real: bool) -> Any:
    if real:
        from resolveqa.llm import LLMAdapter

        return LLMAdapter(use_real=True)
    from resolveqa.demo.llm import create_demo_llm

    return create_demo_llm(real=False)


def process_job(
    job: CaseJob,
    *,
    case_store: Any,
    queue: CaseQueue,
    root: Path | str = ROOT,
    real: bool | None = None,
) -> None:
    """Process a single case job; ack on success, nack (requeue) on infra failure."""
    if real is None:
        real = os.environ.get("RESOLVEQA_LIVE") == "1"
    case = case_store.get(job.case_id)
    if case is None:
        logger.error("case_id not found in store: %s", job.case_id)
        queue.ack(job)
        return
    if case.state in TERMINAL_STATES:
        logger.info("skip terminal case %s (%s)", case.case_id, case.state.value)
        queue.ack(job)
        return
    if case.state != CaseState.CREATED:
        # Worker only starts from created; mid-flight resume is a later milestone.
        logger.warning(
            "refusing non-created case %s in state %s",
            case.case_id,
            case.state.value,
        )
        queue.ack(job)
        return

    llm = _build_llm(real=real)

    def on_case(updated: Any) -> None:
        case_store.put(updated)

    try:
        result = run_pipeline(
            case,
            root=root,
            llm=llm,
            real=real,
            on_case=on_case,
        )
        case_store.put(result.case)
        queue.ack(job)
        logger.info("case %s finished as %s", result.case.case_id, result.case.state.value)
    except Exception:
        logger.exception("pipeline failed for %s", job.case_id)
        queue.nack(job, requeue=job.attempt < 3)
        raise


def run_forever(
    *,
    case_store: Any,
    queue: CaseQueue,
    root: Path | str = ROOT,
    wait_seconds: int = 5,
    real: bool | None = None,
) -> None:
    """Block and process jobs until SIGINT/SIGTERM."""
    stop = {"flag": False}

    def _stop(*_args: object) -> None:
        stop["flag"] = True

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)
    logger.info("worker started (wait=%ss)", wait_seconds)
    while not stop["flag"]:
        job: Optional[CaseJob] = queue.dequeue(wait_seconds=wait_seconds)
        if job is None:
            continue
        try:
            process_job(job, case_store=case_store, queue=queue, root=root, real=real)
        except Exception:
            # Already nacked inside process_job; keep looping.
            time.sleep(0.5)
    logger.info("worker stopped")
