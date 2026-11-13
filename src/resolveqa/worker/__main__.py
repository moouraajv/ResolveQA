"""CLI: python -m resolveqa.worker"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from resolveqa.intake.dynamo_store import DynamoCaseStore  # noqa: E402
from resolveqa.intake.file_store import FileCaseStore  # noqa: E402
from resolveqa.queue.memory import MemoryCaseQueue  # noqa: E402
from resolveqa.queue.sqs import SqsCaseQueue  # noqa: E402
from resolveqa.worker.loop import run_forever  # noqa: E402


def _configure_logging() -> None:
    level = os.environ.get("RESOLVEQA_LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ResolveQA cloud agent worker")
    parser.add_argument("--root", default=str(_REPO_ROOT), help="Repository / runtime root")
    parser.add_argument(
        "--store",
        choices=("file", "dynamodb"),
        default=os.environ.get("RESOLVEQA_CASE_STORE", "file"),
    )
    parser.add_argument(
        "--queue",
        choices=("memory", "file", "sqs"),
        default=os.environ.get(
            "RESOLVEQA_QUEUE",
            "sqs" if os.environ.get("RESOLVEQA_SQS_URL") else "file",
        ),
    )
    parser.add_argument("--wait", type=int, default=5)
    args = parser.parse_args(argv)
    _configure_logging()
    root = Path(args.root).resolve()
    runs = root / "runs"

    if args.store == "dynamodb":
        table = os.environ.get("RESOLVEQA_DDB_TABLE")
        if not table:
            raise SystemExit("RESOLVEQA_DDB_TABLE is required for --store dynamodb")
        case_store = DynamoCaseStore(
            table,
            region=os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION"),
        )
    else:
        case_store = FileCaseStore(runs)

    if args.queue == "sqs":
        url = os.environ.get("RESOLVEQA_SQS_URL")
        if not url:
            raise SystemExit("RESOLVEQA_SQS_URL is required for --queue sqs")
        queue = SqsCaseQueue(
            url,
            region=os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION"),
        )
    elif args.queue == "file":
        from resolveqa.queue.file_queue import FileCaseQueue

        queue = FileCaseQueue(runs)
    else:
        queue = MemoryCaseQueue()
        logging.getLogger("resolveqa.worker").warning(
            "memory queue selected — only works if API and worker share this process"
        )

    run_forever(case_store=case_store, queue=queue, root=root, wait_seconds=args.wait)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
