"""Local demo HTTP surface for Intake using the Python standard library only.

Routes (ephemeral / local-demo; no auth, no cloud):
  GET  /health                 -> JSON ok
  GET  /form                   -> HTML form (report fields treated as data)
  POST /api/cases              -> JSON create {client_id, repo_ref, report_text} channel=api
  GET  /api/cases/<case_id>    -> JSON fetch by id
  GET  /api/cases/<case_id>/timeline -> JSON timeline from runs/<case_id>/events.jsonl (#15)
  GET  /cases/<case_id>/timeline     -> HTML timeline for support (#15)
  POST /api/cases/<case_id>/reply    -> JSON customer reply compose (#17)
  POST /api/cases/<case_id>/delivery -> build local unpublished evidence package (#16)
  POST /api/cases/<case_id>/advance  -> operator/demo advance (happy path or to_state)
  POST /form/cases             -> application/x-www-form-urlencoded create channel=form
  GET  /chat                   -> simulated messaging UI (permanent "Canal simulado" label)
  POST /chat/messages          -> form create via Intake channel=simulated_chat
  POST /api/chat/messages      -> JSON create via Intake channel=simulated_chat
  OPTIONS /*                   -> CORS preflight for allow-listed Origins

Missing or blank client_id is refused with HTTP 400 and a clear error message.
API/form behavior from issue #13 is preserved; chat reuses the same Intake instance.
Timeline/reply never invent pipeline progress; they only reflect stored events / terminal state.
CORS allow-list: RESOLVEQA_CORS_ORIGINS (comma/newline) or demo defaults (localhost:3000 + public front).
Advance updates the case store (+ events.jsonl) for Quadro sync; it does not run agents.
When RESOLVEQA_QUEUE is set, POST /api/cases returns 202 and enqueues the worker.
GET /api/snapshot and GET /api/events (SSE) support the production Quadro.
"""

from __future__ import annotations

import html
import json
import os
import re
import time
import uuid
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Optional
from urllib.parse import parse_qs

from resolveqa.channel import build_chat_html, submit_simulated_chat_report
from resolveqa.contracts import (
    CaseState,
    ChannelType,
    ContractValidationError,
    Event,
    EventSource,
    EventType,
    ReportInput,
    RunState,
    Verdict,
)
from resolveqa.intake.service import utc_now_iso
from resolveqa.intake import Intake
from resolveqa.delivery import DeliveryBuilder, DeliveryError
from resolveqa.playbook import Playbook, load_playbook
from resolveqa.reply import ReplyComposeError, ReplyComposer, ReplyOutcome
from resolveqa.store import EventStore, EventStoreError
from resolveqa.timeline import TimelineError, build_timeline_html, load_timeline, timeline_to_dict

_CASE_ID_RE = re.compile(r"^/api/cases/([^/]+)$")
_CASE_TIMELINE_API_RE = re.compile(r"^/api/cases/([^/]+)/timeline$")
_CASE_TIMELINE_HTML_RE = re.compile(r"^/cases/([^/]+)/timeline$")
_CASE_REPLY_API_RE = re.compile(r"^/api/cases/([^/]+)/reply$")
_CASE_DELIVERY_API_RE = re.compile(r"^/api/cases/([^/]+)/delivery$")
_CASE_ADVANCE_API_RE = re.compile(r"^/api/cases/([^/]+)/advance$")
_DEFAULT_RUNS_ROOT = Path("runs")
_DEFAULT_CORS_ORIGINS = (
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "https://d10ry6ff7l79jo.cloudfront.net",
)


def _parse_cors_origins(raw: str | None) -> frozenset[str]:
    """Parse a comma/newline-separated allow-list of browser Origins."""
    if raw is None:
        return frozenset(_DEFAULT_CORS_ORIGINS)
    items = [part.strip() for part in re.split(r"[\n,]", raw) if part.strip()]
    return frozenset(items)


def _json_bytes(payload: Any, *, status: int = HTTPStatus.OK) -> tuple[int, bytes, str]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    return int(status), body, "application/json; charset=utf-8"


def _error(message: str, status: int = HTTPStatus.BAD_REQUEST) -> tuple[int, bytes, str]:
    return _json_bytes({"error": message}, status=status)


def _require_client_id(raw: Any) -> Optional[str]:
    """Return client_id or None when absent/blank (caller must refuse clearly)."""
    if raw is None:
        return None
    if not isinstance(raw, str):
        return None
    stripped = raw.strip()
    return stripped or None


def build_form_html(*, notice: str | None = None, case: RunState | None = None) -> str:
    """Render the intake form. User-supplied text is HTML-escaped (data, not instructions)."""
    notice_block = ""
    if notice:
        notice_block = f'<p class="notice">{html.escape(notice, quote=True)}</p>'
    case_block = ""
    if case is not None:
        case_block = (
            '<section class="case-created">'
            "<h2>Caso criado (armazenamento efêmero / demo local)</h2>"
            f"<p><strong>case_id:</strong> {html.escape(case.case_id, quote=True)}</p>"
            f"<p><strong>state:</strong> {html.escape(case.state.value, quote=True)}</p>"
            f"<p><strong>client_id:</strong> {html.escape(case.client_id, quote=True)}</p>"
            f"<p><strong>repo_ref:</strong> {html.escape(case.repo_ref, quote=True)}</p>"
            "<p><strong>report_text (dado):</strong></p>"
            f"<pre>{html.escape(case.report_text, quote=False)}</pre>"
            "</section>"
        )
    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8"/>
  <title>ResolveQA Intake (demo local)</title>
  <style>
    body {{ font-family: system-ui, sans-serif; margin: 2rem; max-width: 40rem; }}
    label {{ display: block; margin-top: 0.75rem; font-weight: 600; }}
    input, textarea {{ width: 100%; box-sizing: border-box; }}
    .notice {{ color: #8a1f1f; }}
    .banner {{ background: #f4f4f4; padding: 0.5rem 0.75rem; margin-bottom: 1rem; }}
  </style>
</head>
<body>
  <p class="banner">Demo local — armazenamento efêmero em memória; sem autenticação, sem persistência.</p>
  <h1>Intake de relato</h1>
  <p>Os campos abaixo são tratados como <em>dados</em>, não como instruções ao sistema.</p>
  {notice_block}
  {case_block}
  <form method="post" action="/form/cases" accept-charset="utf-8">
    <label for="client_id">client_id (obrigatório)</label>
    <input id="client_id" name="client_id" type="text" required/>
    <label for="repo_ref">repo_ref</label>
    <input id="repo_ref" name="repo_ref" type="text" required/>
    <label for="report_text">report_text (relato)</label>
    <textarea id="report_text" name="report_text" rows="6" required></textarea>
    <p style="margin-top:1rem"><button type="submit">Criar caso</button></p>
  </form>
</body>
</html>
"""


class IntakeRequestHandler(BaseHTTPRequestHandler):
    """HTTP handler bound to a shared Intake instance via server.intake."""

    server_version = "ResolveQAIntake/0.1"

    @property
    def intake(self) -> Intake:
        return self.server.intake  # type: ignore[attr-defined]

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
        # Keep test output quiet; still available if server.log is enabled later.
        return

    @property
    def cors_origins(self) -> frozenset[str]:
        return getattr(self.server, "cors_origins", frozenset())  # type: ignore[attr-defined]

    def _cors_origin(self) -> str | None:
        origin = (self.headers.get("Origin") or "").strip()
        if origin and origin in self.cors_origins:
            return origin
        return None

    def _apply_cors_headers(self) -> None:
        origin = self._cors_origin()
        if origin is None:
            return
        self.send_header("Access-Control-Allow-Origin", origin)
        self.send_header("Vary", "Origin")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS, HEAD")
        self.send_header(
            "Access-Control-Allow-Headers",
            "Content-Type, Accept, X-Requested-With",
        )
        self.send_header("Access-Control-Max-Age", "86400")

    def _write(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self._apply_cors_headers()
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self) -> bytes:
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length < 0 or length > 1_000_000:
            raise ValueError("invalid Content-Length")
        return self.rfile.read(length) if length else b""

    def do_OPTIONS(self) -> None:  # noqa: N802
        """Browser CORS preflight for cross-origin Admin/Quadro clients."""
        origin = self._cors_origin()
        if origin is None:
            self.send_response(HTTPStatus.FORBIDDEN)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_header("Content-Length", "0")
        self._apply_cors_headers()
        self.end_headers()

    def _storage_label(self) -> str:
        return getattr(self.server, "storage_label", "ephemeral-in-memory")

    def _queue_enabled(self) -> bool:
        return getattr(self.server, "queue_enabled", False)

    def _allow_operator_advance(self) -> bool:
        return getattr(self.server, "allow_operator_advance", True)

    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        if path == "/health":
            status, body, ctype = _json_bytes(
                {
                    "ok": True,
                    "storage": self._storage_label(),
                    "queue": self._queue_enabled(),
                    "operator_advance": self._allow_operator_advance(),
                    "note": (
                        "cloud spine: create enqueues worker"
                        if self._queue_enabled()
                        else "local demo; operator advance does not run agents"
                    ),
                }
            )
            self._write(status, body, ctype)
            return

        if path == "/api/snapshot":
            self._handle_snapshot()
            return

        if path == "/api/events":
            self._handle_events_sse()
            return

        if path in {"/", "/form"}:
            page = build_form_html().encode("utf-8")
            self._write(HTTPStatus.OK, page, "text/html; charset=utf-8")
            return

        if path == "/chat":
            page = build_chat_html().encode("utf-8")
            self._write(HTTPStatus.OK, page, "text/html; charset=utf-8")
            return

        timeline_api = _CASE_TIMELINE_API_RE.match(path)
        if timeline_api:
            self._handle_timeline_api(timeline_api.group(1))
            return

        timeline_html = _CASE_TIMELINE_HTML_RE.match(path)
        if timeline_html:
            self._handle_timeline_html(timeline_html.group(1))
            return

        match = _CASE_ID_RE.match(path)
        if match:
            case_id = match.group(1)
            case = self.intake.get(case_id)
            if case is None:
                status, body, ctype = _error(f"case_id not found: {case_id}", HTTPStatus.NOT_FOUND)
                self._write(status, body, ctype)
                return
            status, body, ctype = _json_bytes(
                {
                    "case": case.to_dict(),
                    "storage": self._storage_label(),
                }
            )
            self._write(status, body, ctype)
            return

        status, body, ctype = _error("not found", HTTPStatus.NOT_FOUND)
        self._write(status, body, ctype)

    def _handle_snapshot(self) -> None:
        cases = self.intake.list_cases()
        events: list[dict[str, Any]] = []
        for case in cases:
            for event in self._load_case_events(case.case_id):
                events.append(event.to_dict())
        events.sort(key=lambda e: (e.get("case_id", ""), int(e.get("seq", 0))))
        status, body, ctype = _json_bytes(
            {
                "cases": [c.to_dict() for c in cases],
                "events": events,
                "spans": [],
                "documents": [],
            }
        )
        self._write(status, body, ctype)

    def _handle_events_sse(self) -> None:
        """SSE stream of Event payloads; polls EventStore for new lines."""
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self._apply_cors_headers()
        self.end_headers()
        seen: set[str] = set()
        # Seed with current history so reconnecting clients catch up once.
        for case in self.intake.list_cases():
            for event in self._load_case_events(case.case_id):
                seen.add(event.event_id)
                payload = json.dumps(event.to_dict(), ensure_ascii=False)
                chunk = f"event: {event.type.value}\ndata: {payload}\n\n".encode("utf-8")
                try:
                    self.wfile.write(chunk)
                    self.wfile.flush()
                except BrokenPipeError:
                    return
        idle_rounds = 0
        while idle_rounds < 120:  # ~10 minutes at 5s
            emitted = False
            for case in self.intake.list_cases():
                for event in self._load_case_events(case.case_id):
                    if event.event_id in seen:
                        continue
                    seen.add(event.event_id)
                    emitted = True
                    payload = json.dumps(event.to_dict(), ensure_ascii=False)
                    chunk = f"event: {event.type.value}\ndata: {payload}\n\n".encode("utf-8")
                    try:
                        self.wfile.write(chunk)
                        self.wfile.flush()
                    except BrokenPipeError:
                        return
            if not emitted:
                idle_rounds += 1
                try:
                    self.wfile.write(b": keepalive\n\n")
                    self.wfile.flush()
                except BrokenPipeError:
                    return
            else:
                idle_rounds = 0
            time.sleep(5)

    def do_POST(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        try:
            raw = self._read_body()
        except ValueError:
            status, body, ctype = _error("invalid request body")
            self._write(status, body, ctype)
            return

        if path == "/api/cases":
            self._handle_api_create(raw)
            return
        if path == "/form/cases":
            self._handle_form_create(raw)
            return
        if path == "/api/chat/messages":
            self._handle_chat_api_create(raw)
            return
        if path == "/chat/messages":
            self._handle_chat_form_create(raw)
            return

        reply_api = _CASE_REPLY_API_RE.match(path)
        if reply_api:
            self._handle_reply_api(reply_api.group(1), raw)
            return

        delivery_api = _CASE_DELIVERY_API_RE.match(path)
        if delivery_api:
            self._handle_delivery_api(delivery_api.group(1), raw)
            return

        advance_api = _CASE_ADVANCE_API_RE.match(path)
        if advance_api:
            self._handle_advance_api(advance_api.group(1), raw)
            return

        status, body, ctype = _error("not found", HTTPStatus.NOT_FOUND)
        self._write(status, body, ctype)

    def _load_timeline_entries(self, case_id: str):
        """Prefer EventStore when available; fall back to timeline reader."""
        try:
            store = EventStore(self.server.runs_root)
            events = store.list_events(case_id)
            # Project through timeline reader for stable labels/replay handling.
            path = Path(self.server.runs_root) / case_id / "events.jsonl"
            if events and not path.exists():
                raise TimelineError("events listed by store but events.jsonl missing")
            return load_timeline(self.server.runs_root, case_id)
        except EventStoreError as err:
            raise TimelineError(str(err)) from err

    def _handle_timeline_api(self, case_id: str) -> None:
        try:
            entries = self._load_timeline_entries(case_id)
        except TimelineError as err:
            status, body, ctype = _error(str(err))
            self._write(status, body, ctype)
            return
        status, body, ctype = _json_bytes(timeline_to_dict(case_id, entries))
        self._write(status, body, ctype)

    def _handle_timeline_html(self, case_id: str) -> None:
        try:
            entries = self._load_timeline_entries(case_id)
        except TimelineError as err:
            page = (
                "<!DOCTYPE html><html lang=\"pt-BR\"><body>"
                f"<p>{html.escape(str(err), quote=False)}</p>"
                "</body></html>"
            ).encode("utf-8")
            self._write(HTTPStatus.BAD_REQUEST, page, "text/html; charset=utf-8")
            return
        page = build_timeline_html(case_id, entries).encode("utf-8")
        self._write(HTTPStatus.OK, page, "text/html; charset=utf-8")

    def _load_case_events(self, case_id: str) -> list[Event]:
        path = Path(self.server.runs_root) / case_id / "events.jsonl"
        if not path.exists():
            return []
        events: list[Event] = []
        with path.open("r", encoding="utf-8") as handle:
            for raw in handle:
                line = raw.strip()
                if line:
                    events.append(Event.from_json(line))
        return events

    def _handle_advance_api(self, case_id: str, raw: bytes) -> None:
        """Operator/demo control: advance case state and persist to the ephemeral store."""
        payload: dict[str, Any] = {}
        if raw:
            try:
                parsed = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                status, body, ctype = _error("invalid JSON body")
                self._write(status, body, ctype)
                return
            if parsed is None:
                parsed = {}
            if not isinstance(parsed, dict):
                status, body, ctype = _error("JSON body must be an object")
                self._write(status, body, ctype)
                return
            payload = parsed

        to_state = payload.get("to_state")
        if to_state is not None and not isinstance(to_state, str):
            status, body, ctype = _error("to_state must be a string when provided")
            self._write(status, body, ctype)
            return

        try:
            updated, previous = self.intake.advance(
                case_id,
                to_state=to_state.strip() if isinstance(to_state, str) and to_state.strip() else None,
                allow_operator_advance=self._allow_operator_advance(),
            )
        except ContractValidationError as err:
            message = str(err)
            code = (
                HTTPStatus.NOT_FOUND
                if message.startswith("case_id not found")
                else HTTPStatus.BAD_REQUEST
            )
            status, body, ctype = _error(message, code)
            self._write(status, body, ctype)
            return

        ts = utc_now_iso()
        event: Event | None = None
        try:
            store = EventStore(self.server.runs_root)
            event = Event(
                event_id=f"evt-{uuid.uuid4().hex}",
                case_id=case_id,
                seq=store.next_seq(case_id),
                ts=ts,
                source=EventSource.ORCHESTRATOR,
                type=EventType.STATE_CHANGED,
                from_state=previous,
                to_state=updated.state,
                reason=(
                    payload["reason"].strip()
                    if isinstance(payload.get("reason"), str) and payload["reason"].strip()
                    else "Avanço manual pelo Quadro; sincronizado no armazenamento do backend."
                ),
                evidence_refs=(),
            )
            store.append(event)
        except (EventStoreError, ContractValidationError):
            event = None

        status, body, ctype = _json_bytes(
            {
                "case": updated.to_dict(),
                "event": event.to_dict() if event is not None else None,
                "storage": self._storage_label(),
                "note": "Estado atualizado no store do backend; não executa agentes.",
            }
        )
        self._write(status, body, ctype)

    def _handle_reply_api(self, case_id: str, raw: bytes) -> None:
        case = self.intake.get(case_id)
        if case is None:
            status, body, ctype = _error(f"case_id not found: {case_id}", HTTPStatus.NOT_FOUND)
            self._write(status, body, ctype)
            return

        payload: dict[str, Any] = {}
        if raw:
            try:
                parsed = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                status, body, ctype = _error("invalid JSON body")
                self._write(status, body, ctype)
                return
            if not isinstance(parsed, dict):
                status, body, ctype = _error("JSON body must be an object")
                self._write(status, body, ctype)
                return
            payload = parsed

        # Optional override for demo fixtures that already reached a terminal state on disk.
        state_override = payload.get("state")
        if isinstance(state_override, str) and state_override.strip():
            try:
                case = RunState(
                    case_id=case.case_id,
                    client_id=case.client_id,
                    repo_ref=case.repo_ref,
                    channel=case.channel,
                    report_text=case.report_text,
                    state=CaseState(state_override),
                    created_at=case.created_at,
                    updated_at=case.updated_at,
                    terminal_reason=case.terminal_reason,
                    attempts=case.attempts,
                    base_revision=case.base_revision,
                    fix_revision=case.fix_revision,
                    evidence_ids=case.evidence_ids,
                )
            except (ValueError, ContractValidationError) as err:
                status, body, ctype = _error(str(err))
                self._write(status, body, ctype)
                return

        outcome = ReplyOutcome(
            corrected_behavior=payload.get("corrected_behavior"),
            support_question=payload.get("support_question"),
            blocked_detail=payload.get("blocked_detail"),
        )
        try:
            message = self.server.reply_composer.compose(
                case,
                outcome,
                events=self._load_case_events(case_id),
            )
        except ReplyComposeError as err:
            status, body, ctype = _error(str(err))
            self._write(status, body, ctype)
            return

        status, body, ctype = _json_bytes(
            {
                "message": message.to_dict(),
                "note": "Mensagem composta apenas após regras RF-09; não inventa progresso.",
            }
        )
        self._write(status, body, ctype)

    def _handle_delivery_api(self, case_id: str, raw: bytes) -> None:
        case = self.intake.get(case_id)
        if case is None:
            status, body, ctype = _error(f"case_id not found: {case_id}", HTTPStatus.NOT_FOUND)
            self._write(status, body, ctype)
            return

        if not raw:
            status, body, ctype = _error("JSON body with verdict is required")
            self._write(status, body, ctype)
            return
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            status, body, ctype = _error("invalid JSON body")
            self._write(status, body, ctype)
            return
        if not isinstance(payload, dict) or "verdict" not in payload:
            status, body, ctype = _error("JSON body must include 'verdict'")
            self._write(status, body, ctype)
            return

        try:
            verdict = Verdict.from_dict(payload["verdict"])
            # Allow demo callers to present a verified case snapshot without mutating Intake store.
            if isinstance(payload.get("state"), str) and payload["state"].strip():
                case = RunState(
                    case_id=case.case_id,
                    client_id=case.client_id,
                    repo_ref=case.repo_ref,
                    channel=case.channel,
                    report_text=case.report_text,
                    state=CaseState(payload["state"]),
                    created_at=case.created_at,
                    updated_at=case.updated_at,
                    terminal_reason=case.terminal_reason,
                    attempts=case.attempts,
                    base_revision=payload.get("base_revision", case.base_revision),
                    fix_revision=payload.get("fix_revision", case.fix_revision),
                    evidence_ids=case.evidence_ids,
                )
            result = self.server.delivery_builder.build(case, verdict)
        except (ContractValidationError, DeliveryError, ValueError) as err:
            status, body, ctype = _error(str(err))
            self._write(status, body, ctype)
            return

        status, body, ctype = _json_bytes(
            {
                "delivery": result.to_dict(),
                "note": "Pacote local 'PR não publicado'; sem merge automático.",
            },
            status=HTTPStatus.CREATED,
        )
        self._write(status, body, ctype)

    def _handle_api_create(self, raw: bytes) -> None:
        if not raw:
            status, body, ctype = _error("JSON body is required")
            self._write(status, body, ctype)
            return
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            status, body, ctype = _error("invalid JSON body")
            self._write(status, body, ctype)
            return
        if not isinstance(payload, dict):
            status, body, ctype = _error("JSON body must be an object")
            self._write(status, body, ctype)
            return

        client_id = _require_client_id(payload.get("client_id"))
        if client_id is None:
            status, body, ctype = _error(
                "client_id is required and must be a non-empty string; request refused."
            )
            self._write(status, body, ctype)
            return

        try:
            # Pass raw JSON values through to ReportInput so type/emptiness
            # invariants stay in contracts (no str() coercion that turns null/123
            # into the strings "None"/"123").
            report = ReportInput(
                client_id=client_id,
                repo_ref=payload.get("repo_ref"),
                channel=ChannelType.API,
                report_text=payload.get("report_text"),
            )
            case = self.intake.create(report)
        except ContractValidationError as err:
            status, body, ctype = _error(str(err))
            self._write(status, body, ctype)
            return

        queued = self._queue_enabled()
        status, body, ctype = _json_bytes(
            {
                "case": case.to_dict(),
                "storage": self._storage_label(),
                "queued": queued,
                "note": (
                    "accepted; worker will run the agent pipeline"
                    if queued
                    else "created; no worker queue configured"
                ),
            },
            status=HTTPStatus.ACCEPTED if queued else HTTPStatus.CREATED,
        )
        self._write(status, body, ctype)

    def _handle_form_create(self, raw: bytes) -> None:
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            page = build_form_html(notice="Corpo do formulário inválido (encoding).").encode("utf-8")
            self._write(HTTPStatus.BAD_REQUEST, page, "text/html; charset=utf-8")
            return

        fields = parse_qs(text, keep_blank_values=True)
        client_raw = fields.get("client_id", [None])[0]
        client_id = _require_client_id(client_raw)
        if client_id is None:
            page = build_form_html(
                notice="client_id is required and must be a non-empty string; request refused."
            ).encode("utf-8")
            self._write(HTTPStatus.BAD_REQUEST, page, "text/html; charset=utf-8")
            return

        repo_ref = (fields.get("repo_ref", [""])[0] or "").strip()
        report_text = fields.get("report_text", [""])[0] or ""

        try:
            report = ReportInput(
                client_id=client_id,
                repo_ref=repo_ref,
                channel=ChannelType.FORM,
                report_text=report_text,
            )
            case = self.intake.create(report)
        except ContractValidationError as err:
            page = build_form_html(notice=str(err)).encode("utf-8")
            self._write(HTTPStatus.BAD_REQUEST, page, "text/html; charset=utf-8")
            return

        page = build_form_html(case=case).encode("utf-8")
        self._write(HTTPStatus.CREATED, page, "text/html; charset=utf-8")

    def _handle_chat_api_create(self, raw: bytes) -> None:
        if not raw:
            status, body, ctype = _error("JSON body is required")
            self._write(status, body, ctype)
            return
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            status, body, ctype = _error("invalid JSON body")
            self._write(status, body, ctype)
            return
        if not isinstance(payload, dict):
            status, body, ctype = _error("JSON body must be an object")
            self._write(status, body, ctype)
            return

        client_id = _require_client_id(payload.get("client_id"))
        if client_id is None:
            status, body, ctype = _error(
                "client_id is required and must be a non-empty string; request refused."
            )
            self._write(status, body, ctype)
            return

        try:
            case = submit_simulated_chat_report(
                self.intake,
                client_id=client_id,
                repo_ref=payload.get("repo_ref"),
                report_text=payload.get("report_text"),
            )
        except ContractValidationError as err:
            status, body, ctype = _error(str(err))
            self._write(status, body, ctype)
            return

        queued = self._queue_enabled()
        status, body, ctype = _json_bytes(
            {
                "case": case.to_dict(),
                "channel_label": "Canal simulado",
                "storage": self._storage_label(),
                "queued": queued,
                "note": (
                    "accepted; worker will run the agent pipeline"
                    if queued
                    else "local demo; no invented progress"
                ),
            },
            status=HTTPStatus.ACCEPTED if queued else HTTPStatus.CREATED,
        )
        self._write(status, body, ctype)

    def _handle_chat_form_create(self, raw: bytes) -> None:
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            page = build_chat_html(
                notice="Corpo do formulário inválido (encoding)."
            ).encode("utf-8")
            self._write(HTTPStatus.BAD_REQUEST, page, "text/html; charset=utf-8")
            return

        fields = parse_qs(text, keep_blank_values=True)
        client_raw = fields.get("client_id", [None])[0]
        client_id = _require_client_id(client_raw)
        repo_ref = (fields.get("repo_ref", [""])[0] or "").strip()
        report_text = fields.get("report_text", [""])[0] or ""

        if client_id is None:
            page = build_chat_html(
                notice="client_id is required and must be a non-empty string; request refused.",
                preset_repo_ref=repo_ref,
            ).encode("utf-8")
            self._write(HTTPStatus.BAD_REQUEST, page, "text/html; charset=utf-8")
            return

        try:
            case = submit_simulated_chat_report(
                self.intake,
                client_id=client_id,
                repo_ref=repo_ref,
                report_text=report_text,
            )
        except ContractValidationError as err:
            page = build_chat_html(
                notice=str(err),
                outbound_text=report_text or None,
                preset_client_id=client_id,
                preset_repo_ref=repo_ref,
            ).encode("utf-8")
            self._write(HTTPStatus.BAD_REQUEST, page, "text/html; charset=utf-8")
            return

        page = build_chat_html(
            outbound_text=case.report_text,
            case=case,
            preset_client_id=case.client_id,
            preset_repo_ref=case.repo_ref,
        ).encode("utf-8")
        self._write(HTTPStatus.CREATED, page, "text/html; charset=utf-8")


class IntakeHTTPServer(ThreadingHTTPServer):
    """Threading HTTP server carrying a shared Intake instance."""

    allow_reuse_address = True

    def __init__(
        self,
        server_address: tuple[str, int],
        intake: Intake | None = None,
        *,
        runs_root: Path | str | None = None,
        reply_composer: ReplyComposer | None = None,
        delivery_builder: DeliveryBuilder | None = None,
        playbook: Playbook | None = None,
        playbook_path: Path | str | None = None,
        cors_origins: frozenset[str] | set[str] | list[str] | None = None,
        storage_label: str | None = None,
        queue_enabled: bool | None = None,
        allow_operator_advance: bool | None = None,
    ) -> None:
        self.intake = intake if intake is not None else Intake()
        self.runs_root = Path(runs_root) if runs_root is not None else _DEFAULT_RUNS_ROOT
        loaded = playbook if playbook is not None else load_playbook(playbook_path)
        self.playbook = loaded
        self.reply_composer = (
            reply_composer if reply_composer is not None else ReplyComposer(loaded)
        )
        self.delivery_builder = (
            delivery_builder
            if delivery_builder is not None
            else DeliveryBuilder(runs_root=self.runs_root, playbook=loaded)
        )
        if cors_origins is None:
            self.cors_origins = _parse_cors_origins(os.environ.get("RESOLVEQA_CORS_ORIGINS"))
        else:
            self.cors_origins = frozenset(cors_origins)
        from resolveqa.runtime_boot import storage_label as _label

        self.storage_label = storage_label or _label(self.intake.store)
        self.queue_enabled = (
            bool(getattr(self.intake, "queue", None) is not None)
            if queue_enabled is None
            else queue_enabled
        )
        if allow_operator_advance is None:
            # Cloud/production: disable fake progress when a worker queue is attached.
            env = (os.environ.get("RESOLVEQA_ALLOW_OPERATOR_ADVANCE") or "").strip().lower()
            if env in {"1", "true", "yes"}:
                self.allow_operator_advance = True
            elif env in {"0", "false", "no"}:
                self.allow_operator_advance = False
            else:
                self.allow_operator_advance = not self.queue_enabled
        else:
            self.allow_operator_advance = allow_operator_advance
        super().__init__(server_address, IntakeRequestHandler)


def serve_ephemeral(host: str = "127.0.0.1", port: int = 0) -> IntakeHTTPServer:
    """Bind an ephemeral local demo server (port 0 = OS-assigned)."""
    return IntakeHTTPServer((host, port), Intake())
