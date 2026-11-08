"""Edge tests for simulated chat channel (issue #14, RF-02, RNF-07)."""

from __future__ import annotations

import json
import threading
import unittest
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from resolveqa.channel import SIMULATED_CHANNEL_LABEL, build_chat_html, submit_simulated_chat_report
from resolveqa.contracts import CaseState, ChannelType
from resolveqa.intake import EphemeralCaseStore, Intake
from resolveqa.web import IntakeHTTPServer


class _LiveServer:
    def __init__(self) -> None:
        self.server = IntakeHTTPServer(("127.0.0.1", 0), Intake(EphemeralCaseStore()))
        self.host, self.port = self.server.server_address
        self._thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def base(self) -> str:
        return f"http://{self.host}:{self.port}"

    def __enter__(self) -> "_LiveServer":
        self._thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self.server.shutdown()
        self.server.server_close()
        self._thread.join(timeout=5)


def _http_json(method: str, url: str, payload: dict | None = None) -> tuple[int, dict]:
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json; charset=utf-8"
    req = Request(url, data=data, headers=headers, method=method)
    try:
        with urlopen(req, timeout=5) as resp:
            body = resp.read().decode("utf-8")
            return resp.status, json.loads(body) if body else {}
    except HTTPError as err:
        body = err.read().decode("utf-8")
        return err.code, json.loads(body) if body else {"error": body}


def _http_form(url: str, fields: dict[str, str]) -> tuple[int, str]:
    data = urlencode(fields).encode("utf-8")
    req = Request(
        url,
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded; charset=utf-8"},
        method="POST",
    )
    try:
        with urlopen(req, timeout=5) as resp:
            return resp.status, resp.read().decode("utf-8")
    except HTTPError as err:
        return err.code, err.read().decode("utf-8")


def _http_get(url: str) -> tuple[int, str]:
    with urlopen(Request(url, method="GET"), timeout=5) as resp:
        return resp.status, resp.read().decode("utf-8")


class TestSimulatedChatUnit(unittest.TestCase):
    def test_label_constant_and_html_banner(self) -> None:
        self.assertEqual(SIMULATED_CHANNEL_LABEL, "Canal simulado")
        page = build_chat_html()
        self.assertIn("Canal simulado", page)
        self.assertIn('data-channel-label="simulated"', page)
        self.assertIn('name="viewport"', page)
        self.assertIn("efêmero", page.lower())

    def test_submit_uses_simulated_chat_channel(self) -> None:
        intake = Intake()
        case = submit_simulated_chat_report(
            intake,
            client_id="client-chat",
            repo_ref="demo-target",
            report_text="Relato via chat simulado",
        )
        self.assertEqual(case.channel, ChannelType.SIMULATED_CHAT)
        self.assertEqual(case.state, CaseState.CREATED)


class TestSimulatedChatHTTP(unittest.TestCase):
    def test_chat_page_shows_permanent_simulated_label(self) -> None:
        with _LiveServer() as live:
            status, page = _http_get(f"{live.base}/chat")
            self.assertEqual(status, 200)
            self.assertIn("Canal simulado", page)
            self.assertIn("channel-banner", page)
            # Honest UI: no fabricated pipeline states on first paint.
            self.assertNotIn("triaging", page.lower())
            self.assertNotIn("verified", page.lower())

    def test_chat_json_send_creates_case_with_simulated_channel_and_get(self) -> None:
        with _LiveServer() as live:
            status, created = _http_json(
                "POST",
                f"{live.base}/api/chat/messages",
                {
                    "client_id": "client-chat",
                    "repo_ref": "demo-target",
                    "report_text": "Cupom 10% não aplicou em R$ 200.",
                },
            )
            self.assertEqual(status, 201)
            case = created["case"]
            self.assertEqual(case["channel"], "simulated_chat")
            self.assertEqual(case["state"], "created")
            self.assertEqual(created["channel_label"], "Canal simulado")

            status_get, fetched = _http_json("GET", f"{live.base}/api/cases/{case['case_id']}")
            self.assertEqual(status_get, 200)
            self.assertEqual(fetched["case"]["channel"], "simulated_chat")
            self.assertEqual(fetched["case"]["case_id"], case["case_id"])

    def test_chat_form_send_receipt_and_html_escape(self) -> None:
        hostile = 'Relato <script>alert("x")</script> & mais'
        with _LiveServer() as live:
            status, page = _http_form(
                f"{live.base}/chat/messages",
                {
                    "client_id": "client-form-chat",
                    "repo_ref": "org/repo",
                    "report_text": hostile,
                },
            )
            self.assertEqual(status, 201)
            self.assertIn("Canal simulado", page)
            self.assertIn("Recibo honesto", page)
            self.assertIn("case_id:", page)
            self.assertIn("&lt;script&gt;", page)
            self.assertNotIn('<script>alert("x")</script>', page)
            self.assertIn("simulated_chat", page)

            # Extract case_id from receipt line
            marker = "case_id="
            self.assertIn(marker, page)
            start = page.index(marker) + len(marker)
            end = page.index(";", start)
            case_id = page[start:end].strip()
            status_get, fetched = _http_json("GET", f"{live.base}/api/cases/{case_id}")
            self.assertEqual(status_get, 200)
            self.assertEqual(fetched["case"]["report_text"], hostile)
            self.assertEqual(fetched["case"]["channel"], "simulated_chat")

    def test_chat_rejects_missing_required_fields(self) -> None:
        with _LiveServer() as live:
            status, body = _http_json(
                "POST",
                f"{live.base}/api/chat/messages",
                {"repo_ref": "demo-target", "report_text": "sem client"},
            )
            self.assertEqual(status, 400)
            self.assertIn("client_id", body["error"])

            status, body = _http_json(
                "POST",
                f"{live.base}/api/chat/messages",
                {"client_id": "c", "repo_ref": None, "report_text": "x"},
            )
            self.assertEqual(status, 400)
            self.assertIn("repo_ref", body["error"])

            status, body = _http_json(
                "POST",
                f"{live.base}/api/chat/messages",
                {"client_id": "c", "repo_ref": "r", "report_text": 123},
            )
            self.assertEqual(status, 400)
            self.assertIn("report_text", body["error"])

            status, page = _http_form(
                f"{live.base}/chat/messages",
                {"client_id": "", "repo_ref": "r", "report_text": "x"},
            )
            self.assertEqual(status, 400)
            self.assertIn("client_id is required", page)

    def test_issue13_api_and_form_still_work_with_correct_channels(self) -> None:
        """Regression: #13 API/form must remain available and keep their channels."""
        with _LiveServer() as live:
            status, created = _http_json(
                "POST",
                f"{live.base}/api/cases",
                {
                    "client_id": "client-api",
                    "repo_ref": "demo-target",
                    "report_text": "via API",
                },
            )
            self.assertEqual(status, 201)
            self.assertEqual(created["case"]["channel"], "api")

            status, page = _http_form(
                f"{live.base}/form/cases",
                {
                    "client_id": "client-form",
                    "repo_ref": "demo-target",
                    "report_text": "via form",
                },
            )
            self.assertEqual(status, 201)
            self.assertIn("case-", page)
            # form page is intake form, not chat banner
            status_chat, chat = _http_get(f"{live.base}/chat")
            self.assertEqual(status_chat, 200)
            self.assertIn("Canal simulado", chat)


if __name__ == "__main__":
    unittest.main()
