"""Web package (Trilha B): stdlib HTTP surface for Intake (local demo)."""

from .server import IntakeHTTPServer, IntakeRequestHandler, build_form_html, serve_ephemeral

__all__ = [
    "IntakeHTTPServer",
    "IntakeRequestHandler",
    "build_form_html",
    "serve_ephemeral",
]
