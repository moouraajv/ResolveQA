"""Edge tests for Intake API + form over real HTTP on an ephemeral loopback port (issue #13, RF-01)."""

from __future__ import annotations

import json
import threading
import unittest
from dataclasses import FrozenInstanceError
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from resolveqa.contracts import CaseState, ChannelType, IntakeStage, ReportInput, RunState
from resolveqa.intake import EphemeralCaseStore, Intake
from resolveqa.web import IntakeHTTPServer, build_form_html


class _LiveServer:
    """Context manager that serves IntakeHTTPServer on 127.0.0.1:0 in a daemon thread."""

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
        parsed = json.loads(body) if body else {"error": body}
        return err.code, parsed


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


def _http_get_text(url: str) -> tuple[int, str]:
    req = Request(url, method="GET")
    with urlopen(req, timeout=5) as resp:
        return resp.status, resp.read().decode("utf-8")


class TestIntakeUnit(unittest.TestCase):
    def test_intake_implements_protocol_and_creates_unique_created_cases(self) -> None:
        intake = Intake()
        self.assertIsInstance(intake, IntakeStage)
        report = ReportInput(
            client_id="client-demo",
            repo_ref="demo-target",
            channel=ChannelType.API,
            report_text="Apliquei um cupom de 10% em uma compra de R$ 200, mas o total continuou em R$ 200.",
        )
        first = intake.create(report)
        second = intake.create(report)
        self.assertEqual(first.state, CaseState.CREATED)
        self.assertEqual(second.state, CaseState.CREATED)
        self.assertNotEqual(first.case_id, second.case_id)
        self.assertIs(intake.get(first.case_id), first)
        self.assertIsInstance(first, RunState)

    def test_created_run_state_is_frozen(self) -> None:
        intake = Intake()
        case = intake.create(
            ReportInput(
                client_id="c1",
                repo_ref="repo/x",
                channel=ChannelType.FORM,
                report_text="texto do relato",
            )
        )
        with self.assertRaises(FrozenInstanceError):
            case.state = CaseState.TRIAGING  # type: ignore[misc]
        with self.assertRaises(FrozenInstanceError):
            case.client_id = "other"  # type: ignore[misc]


class TestIntakeHTTP(unittest.TestCase):
    def test_api_create_and_get_by_id(self) -> None:
        with _LiveServer() as live:
            status, created = _http_json(
                "POST",
                f"{live.base}/api/cases",
                {
                    "client_id": "client-demo",
                    "repo_ref": "demo-target",
                    "report_text": "Relato de cupom: total ficou R$ 200.",
                },
            )
            self.assertEqual(status, 201)
            case = created["case"]
            self.assertEqual(case["state"], "created")
            self.assertEqual(case["channel"], "api")
            self.assertEqual(case["client_id"], "client-demo")
            self.assertTrue(case["case_id"])
            self.assertEqual(created["storage"], "ephemeral-in-memory")

            status_get, fetched = _http_json("GET", f"{live.base}/api/cases/{case['case_id']}")
            self.assertEqual(status_get, 200)
            self.assertEqual(fetched["case"]["case_id"], case["case_id"])
            self.assertEqual(fetched["case"]["report_text"], "Relato de cupom: total ficou R$ 200.")

    def test_api_refuses_missing_or_blank_client_id_clearly(self) -> None:
        with _LiveServer() as live:
            for payload in (
                {"repo_ref": "demo-target", "report_text": "sem client"},
                {"client_id": "", "repo_ref": "demo-target", "report_text": "blank"},
                {"client_id": "   ", "repo_ref": "demo-target", "report_text": "spaces"},
            ):
                with self.subTest(payload=payload):
                    status, body = _http_json("POST", f"{live.base}/api/cases", payload)
                    self.assertEqual(status, 400)
                    self.assertIn("client_id", body["error"])
                    self.assertIn("required", body["error"].lower())

    def test_form_create_and_get_by_id(self) -> None:
        with _LiveServer() as live:
            status, html_page = _http_form(
                f"{live.base}/form/cases",
                {
                    "client_id": "client-form",
                    "repo_ref": "org/repo",
                    "report_text": "Texto <script>alert(1)</script> do relato",
                },
            )
            self.assertEqual(status, 201)
            self.assertIn("case-", html_page)
            self.assertIn("client-form", html_page)
            self.assertIn("&lt;script&gt;", html_page)
            self.assertNotIn("<script>alert(1)</script>", html_page)

            # Extract case_id from the success page
            marker = "<strong>case_id:</strong> "
            self.assertIn(marker, html_page)
            start = html_page.index(marker) + len(marker)
            end = html_page.index("</p>", start)
            case_id = html_page[start:end].strip()

            status_get, fetched = _http_json("GET", f"{live.base}/api/cases/{case_id}")
            self.assertEqual(status_get, 200)
            self.assertEqual(fetched["case"]["channel"], "form")
            self.assertEqual(fetched["case"]["state"], "created")
            self.assertEqual(
                fetched["case"]["report_text"],
                "Texto <script>alert(1)</script> do relato",
            )

    def test_form_refuses_missing_client_id(self) -> None:
        with _LiveServer() as live:
            status, html_page = _http_form(
                f"{live.base}/form/cases",
                {
                    "client_id": "",
                    "repo_ref": "org/repo",
                    "report_text": "sem client",
                },
            )
            self.assertEqual(status, 400)
            self.assertIn("client_id is required", html_page)

    def test_get_unknown_case_returns_404(self) -> None:
        with _LiveServer() as live:
            status, body = _http_json("GET", f"{live.base}/api/cases/case-does-not-exist")
            self.assertEqual(status, 404)
            self.assertIn("not found", body["error"])

    def test_form_page_marks_fields_as_data(self) -> None:
        with _LiveServer() as live:
            status, page = _http_get_text(f"{live.base}/form")
            self.assertEqual(status, 200)
            self.assertIn("dados", page.lower())
            self.assertIn("efêmero", page.lower())

    def test_build_form_html_escapes_notice(self) -> None:
        page = build_form_html(notice='<img src=x onerror=alert(1)>')
        self.assertNotIn("<img src=x", page)
        self.assertIn("&lt;img src=x", page)


if __name__ == "__main__":
    unittest.main()
