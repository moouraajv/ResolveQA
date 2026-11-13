#!/usr/bin/env python3
"""Entrypoint for ResolveQA HTTP API (intake + optional cloud queue enqueue).

Storage/queue selected via env:
  RESOLVEQA_CASE_STORE=memory|file|dynamodb
  RESOLVEQA_QUEUE=none|file|sqs|memory
  RESOLVEQA_ALLOW_OPERATOR_ADVANCE=0|1
  RESOLVEQA_ORIGIN_SECRET=...
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import sys
from http import HTTPStatus
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC_DIR = _REPO_ROOT / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from resolveqa.intake import Intake  # noqa: E402
from resolveqa.runtime_boot import (  # noqa: E402
    build_case_queue,
    build_case_store,
    resolve_root,
    storage_label,
)
from resolveqa.web.server import IntakeHTTPServer, IntakeRequestHandler  # noqa: E402


class ProtectedIntakeRequestHandler(IntakeRequestHandler):
    """Subclass that enforces X-ResolveQA-Origin-Verify when configured."""

    def _verify_origin_header(self) -> bool:
        expected_secret: str | None = getattr(self.server, "origin_secret", None)
        if not expected_secret:
            return True
        provided_token = self.headers.get("X-ResolveQA-Origin-Verify")
        if provided_token != expected_secret:
            body = json.dumps(
                {"error": "forbidden: missing or invalid origin verification header"},
                ensure_ascii=False,
            ).encode("utf-8")
            self.send_response(HTTPStatus.FORBIDDEN)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            return False
        return True

    def do_GET(self) -> None:  # noqa: N802
        if not self._verify_origin_header():
            return
        super().do_GET()

    def do_POST(self) -> None:  # noqa: N802
        if not self._verify_origin_header():
            return
        super().do_POST()

    def do_OPTIONS(self) -> None:  # noqa: N802
        if not self._verify_origin_header():
            return
        super().do_OPTIONS()


class ProtectedIntakeHTTPServer(IntakeHTTPServer):
    """IntakeHTTPServer with optional origin secret and protected handler."""

    def __init__(
        self,
        server_address: tuple[str, int],
        *,
        intake: Intake,
        origin_secret: str | None = None,
        runs_root: Path | None = None,
        storage_label_value: str | None = None,
    ) -> None:
        self.origin_secret = (
            origin_secret.strip() if origin_secret and origin_secret.strip() else None
        )
        super().__init__(
            server_address,
            intake,
            runs_root=runs_root,
            storage_label=storage_label_value,
        )
        self.RequestHandlerClass = ProtectedIntakeRequestHandler


def _create_server(host: str, port: int, origin_secret: str | None = None) -> ProtectedIntakeHTTPServer:
    root = resolve_root()
    runs = root / "runs"
    store = build_case_store(root=root)
    queue = build_case_queue(root=root)
    intake = Intake(store, queue=queue)
    return ProtectedIntakeHTTPServer(
        (host, port),
        intake=intake,
        origin_secret=origin_secret,
        runs_root=runs,
        storage_label_value=storage_label(store),
    )


def run() -> None:
    parser = argparse.ArgumentParser(description="ResolveQA Backend HTTP Server")
    parser.add_argument("--host", default=os.environ.get("RESOLVEQA_HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("RESOLVEQA_PORT", "8080")))
    parser.add_argument(
        "--origin-secret",
        default=os.environ.get("RESOLVEQA_ORIGIN_SECRET"),
        help="Optional origin secret for X-ResolveQA-Origin-Verify",
    )
    args = parser.parse_args()
    origin_secret = args.origin_secret.strip() if args.origin_secret else None
    server = _create_server(args.host, args.port, origin_secret=origin_secret)
    bound_host, bound_port = server.server_address

    print("=" * 70, flush=True)
    print("ResolveQA Backend HTTP Server", flush=True)
    print(f"Listening on:    http://{bound_host}:{bound_port}", flush=True)
    print(f"Storage:         {server.storage_label}", flush=True)
    print(f"Queue:           {'enabled' if server.queue_enabled else 'disabled'}", flush=True)
    print(
        f"Operator advance:{'allowed' if server.allow_operator_advance else 'disabled (cloud)'}",
        flush=True,
    )
    print(
        f"Origin Header:   {'ENFORCED' if origin_secret else 'DISABLED (local)'}",
        flush=True,
    )
    print("-" * 70, flush=True)
    print("Routes: /health /api/cases /api/snapshot /api/events /chat ...", flush=True)
    print("=" * 70, flush=True)

    def _handle_shutdown(signum: int, frame: Any) -> None:
        sig_name = signal.Signals(signum).name
        print(f"\n[ResolveQA] Received {sig_name}; shutting down...", flush=True)
        import threading

        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGINT, _handle_shutdown)
    signal.signal(signal.SIGTERM, _handle_shutdown)

    try:
        server.serve_forever()
    finally:
        server.server_close()
        print("[ResolveQA] Server closed cleanly.", flush=True)


if __name__ == "__main__":
    run()
