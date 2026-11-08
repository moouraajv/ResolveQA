#!/usr/bin/env python3
"""Entrypoint for ResolveQA Ephemeral Demo Backend HTTP server.

Serves the Intake & Simulated Chat HTTP surface using the Python standard library only.
Storage is explicitly ephemeral in-memory (EphemeralCaseStore); restarting the process
resets all created cases and messages.

Hackathon scope note:
  This server is an intermediate runtime step for intake and simulated chat.
  The complete end-to-end hackathon journey (reproduction, automated fix,
  verification, and PR generation) is planned for subsequent integration stages.
"""

from __future__ import annotations

import argparse
import os
import signal
import sys
from pathlib import Path
from typing import Any

# Ensure src/ is on sys.path when executed directly as a script
_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC_DIR = _REPO_ROOT / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from resolveqa.intake import EphemeralCaseStore, Intake  # noqa: E402
from resolveqa.web.server import IntakeHTTPServer  # noqa: E402


def _create_server(host: str, port: int) -> IntakeHTTPServer:
    """Create an IntakeHTTPServer with an explicit ephemeral in-memory case store."""
    store = EphemeralCaseStore()
    intake = Intake(store)
    return IntakeHTTPServer((host, port), intake=intake)


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
    args = parser.parse_args()

    server = _create_server(args.host, args.port)
    bound_host, bound_port = server.server_address

    print("=" * 70, flush=True)
    print("ResolveQA Ephemeral Demo Backend Server", flush=True)
    print(f"Listening on: http://{bound_host}:{bound_port}", flush=True)
    print("Storage:      Ephemeral in-memory (no persistence; resets on restart)", flush=True)
    print("Security:     HTML-escaped inputs, report data treated as data", flush=True)
    print("Hackathon:    Intermediate runtime step (Intake + Simulated Chat)", flush=True)
    print("              End-to-end agent pipeline (reproduce/fix/PR) not attached.", flush=True)
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
        # shutdown() must be called from another thread or scheduled
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
