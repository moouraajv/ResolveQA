"""Local demo HTTP surface for Intake using the Python standard library only.

Routes (ephemeral / local-demo; no auth, no cloud):
  GET  /health                 -> JSON ok
  GET  /form                   -> HTML form (report fields treated as data)
  POST /api/cases              -> JSON create {client_id, repo_ref, report_text} channel=api
  GET  /api/cases/<case_id>    -> JSON fetch by id
  GET  /api/cases/<case_id>/timeline -> JSON timeline from runs/<case_id>/events.jsonl (#15)
  GET  /cases/<case_id>/timeline     -> HTML timeline for support (#15)
  POST /api/cases/<case_id>/reply    -> JSON customer reply compose (#17)
  POST /form/cases             -> application/x-www-form-urlencoded create channel=form
  GET  /chat                   -> simulated messaging UI (permanent "Canal simulado" label)
  POST /chat/messages          -> form create via Intake channel=simulated_chat
  POST /api/chat/messages      -> JSON create via Intake channel=simulated_chat

Missing or blank client_id is refused with HTTP 400 and a clear error message.
API/form behavior from issue #13 is preserved; chat reuses the same Intake instance.
Timeline/reply never invent pipeline progress; they only reflect stored events / terminal state.
"""

from __future__ import annotations

import html
import json
import re
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
    ReportInput,
    RunState,
)
from resolveqa.intake import Intake
from resolveqa.reply import ReplyComposeError, ReplyComposer, ReplyOutcome
from resolveqa.timeline import TimelineError, build_timeline_html, load_timeline, timeline_to_dict

_CASE_ID_RE = re.compile(r"^/api/cases/([^/]+)$")
_CASE_TIMELINE_API_RE = re.compile(r"^/api/cases/([^/]+)/timeline$")
_CASE_TIMELINE_HTML_RE = re.compile(r"^/cases/([^/]+)/timeline$")
_CASE_REPLY_API_RE = re.compile(r"^/api/cases/([^/]+)/reply$")
_DEFAULT_RUNS_ROOT = Path("runs")


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

    def _write(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self) -> bytes:
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length < 0 or length > 1_000_000:
            raise ValueError("invalid Content-Length")
        return self.rfile.read(length) if length else b""

    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        if path == "/health":
            status, body, ctype = _json_bytes(
                {
                    "ok": True,
                    "storage": "ephemeral-in-memory",
                    "note": "local demo only; no durable persistence",
                }
            )
            self._write(status, body, ctype)
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
                    "storage": "ephemeral-in-memory",
                }
            )
            self._write(status, body, ctype)
            return

        status, body, ctype = _error("not found", HTTPStatus.NOT_FOUND)
        self._write(status, body, ctype)

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

        status, body, ctype = _error("not found", HTTPStatus.NOT_FOUND)
        self._write(status, body, ctype)

    def _handle_timeline_api(self, case_id: str) -> None:
        try:
            entries = load_timeline(self.server.runs_root, case_id)
        except TimelineError as err:
            status, body, ctype = _error(str(err))
            self._write(status, body, ctype)
            return
        status, body, ctype = _json_bytes(timeline_to_dict(case_id, entries))
        self._write(status, body, ctype)

    def _handle_timeline_html(self, case_id: str) -> None:
        try:
            entries = load_timeline(self.server.runs_root, case_id)
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

        status, body, ctype = _json_bytes(
            {
                "case": case.to_dict(),
                "storage": "ephemeral-in-memory",
                "note": "local demo only; no durable persistence",
            },
            status=HTTPStatus.CREATED,
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

        status, body, ctype = _json_bytes(
            {
                "case": case.to_dict(),
                "channel_label": "Canal simulado",
                "storage": "ephemeral-in-memory",
                "note": "local demo only; no durable persistence; no invented progress",
            },
            status=HTTPStatus.CREATED,
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
    ) -> None:
        self.intake = intake if intake is not None else Intake()
        self.runs_root = Path(runs_root) if runs_root is not None else _DEFAULT_RUNS_ROOT
        self.reply_composer = reply_composer if reply_composer is not None else ReplyComposer()
        super().__init__(server_address, IntakeRequestHandler)


def serve_ephemeral(host: str = "127.0.0.1", port: int = 0) -> IntakeHTTPServer:
    """Bind an ephemeral local demo server (port 0 = OS-assigned)."""
    return IntakeHTTPServer((host, port), Intake())
