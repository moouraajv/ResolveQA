#!/usr/bin/env python3
"""Entrypoint for ResolveQA Ephemeral Demo Backend HTTP server.

Serves the Intake & Simulated Chat HTTP surface using the Python standard library only.
Storage is explicitly ephemeral in-memory (EphemeralCaseStore); restarting the process
resets all created cases and messages.

Origin Protection:
  When an origin secret is configured (via --origin-secret or RESOLVEQA_ORIGIN_SECRET),
  all incoming requests (GET, POST) must provide the exact header:
    X-ResolveQA-Origin-Verify: <secret>
  Direct requests without the header or with an invalid header receive HTTP 403 Forbidden.

Hackathon scope note:
  This server is an intermediate runtime step for intake and simulated chat.
  The complete end-to-end hackathon journey (reproduction, automated fix,
  verification, and PR generation) is planned for subsequent integration stages.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import sys
from http import HTTPStatus
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any

# Ensure src/ is on sys.path when executed directly as a script
_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC_DIR = _REPO_ROOT / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from resolveqa.intake import EphemeralCaseStore, Intake  # noqa: E402
from resolveqa.web.server import IntakeRequestHandler  # noqa: E402


class ProtectedIntakeRequestHandler(IntakeRequestHandler):
    """Subclass of IntakeRequestHandler that enforces X-ResolveQA-Origin-Verify on all routes."""

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


class ProtectedIntakeHTTPServer(ThreadingHTTPServer):
    """Threading HTTP server carrying a shared Intake instance and optional origin secret."""

    allow_reuse_address = True

    def __init__(
        self,
        server_address: tuple[str, int],
        intake: Intake | None = None,
        origin_secret: str | None = None,
    ) -> None:
        self.intake = intake if intake is not None else Intake()
        self.origin_secret = (
            origin_secret.strip() if origin_secret and origin_secret.strip() else None
        )
        super().__init__(server_address, ProtectedIntakeRequestHandler)


def _create_server(
    host: str, port: int, origin_secret: str | None = None
) -> ProtectedIntakeHTTPServer:
    """Create a ProtectedIntakeHTTPServer with an explicit ephemeral in-memory case store."""
    store = EphemeralCaseStore()
    intake = Intake(store)
    return ProtectedIntakeHTTPServer((host, port), intake=intake, origin_secret=origin_secret)


def run() -> None:
    parser = argparse.ArgumentParser(
        description="ResolveQA Ephemeral Demo Backend Server (Pure Python Stdlib)"
    )
    parser.add_argument(
        "--host",
        default=os.environ.get("RESOLVEQA_HOST", "0.0.0.0"),
        help="Host address to bind (default: 0.0.0.0 or RESOLVEQA_HOST)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("RESOLVEQA_PORT", "8080")),
        help="Port to bind (default: 8080 or RESOLVEQA_PORT)",
    )
    parser.add_argument(
        "--origin-secret",
        default=os.environ.get("RESOLVEQA_ORIGIN_SECRET"),
        help="Optional origin secret token required in X-ResolveQA-Origin-Verify header",
    )
    args = parser.parse_args()

    origin_secret = args.origin_secret.strip() if args.origin_secret else None
    server = _create_server(args.host, args.port, origin_secret=origin_secret)
    bound_host, bound_port = server.server_address

    print("=" * 70, flush=True)
    print("ResolveQA Ephemeral Demo Backend Server", flush=True)
    print(f"Listening on:    http://{bound_host}:{bound_port}", flush=True)
    print("Storage:         Ephemeral in-memory (no persistence; resets on restart)", flush=True)
    print(
        f"Origin Header:   {'ENFORCED (X-ResolveQA-Origin-Verify)' if origin_secret else 'DISABLED (local dev mode)'}",
        flush=True,
    )
    print("Input Handling:  HTML-escaped inputs, report text treated strictly as data", flush=True)
    print("Hackathon Scope: Intermediate runtime step (Intake + Simulated Chat)", flush=True)
    print("                 End-to-end agent pipeline (reproduce/fix/PR) not attached.", flush=True)
    print("-" * 70, flush=True)
    print("Available Routes:", flush=True)
    print("  GET  /health              -> JSON healthcheck & ephemeral storage notice", flush=True)
    print("  GET  /form                -> Web intake form", flush=True)
    print("  POST /form/cases          -> Create case via web form", flush=True)
    print("  POST /api/cases           -> Create case via JSON API", flush=True)
    print("  GET  /api/cases/<case_id> -> Retrieve case by ID", flush=True)
    print("  GET  /chat                -> Simulated chat web UI ('Canal simulado')", flush=True)
    print("  POST /chat/messages       -> Submit message via simulated chat form", flush=True)
    print("  POST /api/chat/messages   -> Submit message via simulated chat JSON API", flush=True)
    print("=" * 70, flush=True)

    def _handle_shutdown(signum: int, frame: Any) -> None:
        sig_name = signal.Signals(signum).name
        print(f"\n[ResolveQA] Received signal {sig_name}; shutting down server...", flush=True)
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
