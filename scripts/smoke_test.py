#!/usr/bin/env python3
"""Smoke test script for ResolveQA backend endpoints.

Tests against a running ResolveQA server (local loopback, container, or remote endpoint).
Uses standard library urllib only (zero external dependencies).

Endpoints tested:
  1. GET  /health              -> HTTP 200, checks ephemeral storage declaration
  2. GET  /form                -> HTTP 200, checks HTML form presentation
  3. POST /api/cases (invalid) -> HTTP 400, checks client_id refusal
  4. POST /api/cases (valid)   -> HTTP 201, creates case and extracts case_id
  5. GET  /api/cases/<case_id> -> HTTP 200, verifies case retrieval
  6. GET  /chat                -> HTTP 200, checks 'Canal simulado' label
  7. POST /api/chat/messages   -> HTTP 201, creates case via simulated chat API
  8. POST /chat/messages       -> HTTP 201, creates case via simulated chat form
  9. GET  /api/cases/notfound  -> HTTP 404, verifies error response

Usage:
  python scripts/smoke_test.py [--base-url http://127.0.0.1:8080]
"""

from __future__ import annotations

import argparse
import json
import sys
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


def _request(
    base_url: str,
    method: str,
    path: str,
    *,
    json_data: dict | None = None,
    form_data: dict | None = None,
    headers: dict | None = None,
) -> tuple[int, dict | str]:
    url = f"{base_url.rstrip('/')}{path}"
    req_headers = headers.copy() if headers else {}

    body: bytes | None = None
    if json_data is not None:
        body = json.dumps(json_data).encode("utf-8")
        req_headers["Content-Type"] = "application/json; charset=utf-8"
        req_headers["Accept"] = "application/json"
    elif form_data is not None:
        body = urlencode(form_data).encode("utf-8")
        req_headers["Content-Type"] = "application/x-www-form-urlencoded"

    req = Request(url, data=body, headers=req_headers, method=method)
    try:
        with urlopen(req, timeout=10) as resp:
            raw = resp.read().decode("utf-8")
            status = resp.status
            ctype = resp.headers.get("Content-Type", "")
            if "application/json" in ctype:
                return status, json.loads(raw)
            return status, raw
    except HTTPError as err:
        raw = err.read().decode("utf-8")
        ctype = err.headers.get("Content-Type", "")
        if "application/json" in ctype:
            try:
                return err.code, json.loads(raw)
            except Exception:
                return err.code, raw
        return err.code, raw


def run_smoke_tests(base_url: str) -> bool:
    print(f"[SmokeTest] Running endpoint validations against {base_url}...")
    passed = 0
    total = 0

    def check(name: str, cond: bool, detail: str = "") -> None:
        nonlocal passed, total
        total += 1
        if cond:
            passed += 1
            print(f"  [PASS] {name} {detail}")
        else:
            print(f"  [FAIL] {name} - {detail}")

    # 1. GET /health
    try:
        st, data = _request(base_url, "GET", "/health")
        check(
            "GET /health",
            st == 200 and isinstance(data, dict) and data.get("ok") is True and data.get("storage") == "ephemeral-in-memory",
            f"status={st}, storage={data.get('storage') if isinstance(data, dict) else 'non-json'}",
        )
    except Exception as exc:
        check("GET /health", False, f"Exception: {exc}")

    # 2. GET /form
    try:
        st, data = _request(base_url, "GET", "/form")
        check(
            "GET /form",
            st == 200 and isinstance(data, str) and "Intake de relato" in data and "armazenamento efêmero" in data,
            f"status={st}, html_len={len(data) if isinstance(data, str) else 0}",
        )
    except Exception as exc:
        check("GET /form", False, f"Exception: {exc}")

    # 3. POST /api/cases (refuse missing client_id)
    try:
        st, data = _request(
            base_url,
            "POST",
            "/api/cases",
            json_data={"repo_ref": "octocat/Hello-World", "report_text": "Bug report without client id"},
        )
        check(
            "POST /api/cases (missing client_id rejected)",
            st == 400 and isinstance(data, dict) and "client_id is required" in data.get("error", ""),
            f"status={st}, error={data.get('error') if isinstance(data, dict) else data}",
        )
    except Exception as exc:
        check("POST /api/cases (missing client_id)", False, f"Exception: {exc}")

    # 4. POST /api/cases (valid create)
    created_case_id: str | None = None
    try:
        st, data = _request(
            base_url,
            "POST",
            "/api/cases",
            json_data={
                "client_id": "cli-user-42",
                "repo_ref": "octocat/Hello-World",
                "report_text": "Smoke test report for ephemeral AWS demo packaging",
            },
        )
        is_created = st == 201 and isinstance(data, dict) and "case" in data
        if is_created:
            created_case_id = data["case"].get("case_id")
        check(
            "POST /api/cases (valid)",
            bool(is_created and created_case_id),
            f"status={st}, case_id={created_case_id}",
        )
    except Exception as exc:
        check("POST /api/cases (valid)", False, f"Exception: {exc}")

    # 5. GET /api/cases/<case_id>
    if created_case_id:
        try:
            st, data = _request(base_url, "GET", f"/api/cases/{created_case_id}")
            case_match = (
                st == 200
                and isinstance(data, dict)
                and data.get("case", {}).get("case_id") == created_case_id
                and data.get("case", {}).get("client_id") == "cli-user-42"
            )
            check(
                f"GET /api/cases/{created_case_id}",
                case_match,
                f"status={st}, state={data.get('case', {}).get('state') if isinstance(data, dict) else 'none'}",
            )
        except Exception as exc:
            check(f"GET /api/cases/{created_case_id}", False, f"Exception: {exc}")
    else:
        check("GET /api/cases/<id>", False, "Skipped due to previous creation failure")

    # 6. GET /chat
    try:
        st, data = _request(base_url, "GET", "/chat")
        check(
            "GET /chat",
            st == 200 and isinstance(data, str) and "Canal simulado" in data,
            f"status={st}, contains 'Canal simulado'",
        )
    except Exception as exc:
        check("GET /chat", False, f"Exception: {exc}")

    # 7. POST /api/chat/messages
    try:
        st, data = _request(
            base_url,
            "POST",
            "/api/chat/messages",
            json_data={
                "client_id": "chat-user-99",
                "repo_ref": "octocat/Hello-World",
                "report_text": "Simulated chat report for smoke test",
            },
        )
        chat_ok = (
            st == 201
            and isinstance(data, dict)
            and data.get("channel_label") == "Canal simulado"
            and data.get("case", {}).get("channel") == "simulated_chat"
        )
        check(
            "POST /api/chat/messages",
            chat_ok,
            f"status={st}, channel_label={data.get('channel_label') if isinstance(data, dict) else 'none'}",
        )
    except Exception as exc:
        check("POST /api/chat/messages", False, f"Exception: {exc}")

    # 8. POST /chat/messages (form)
    try:
        st, data = _request(
            base_url,
            "POST",
            "/chat/messages",
            form_data={
                "client_id": "form-chat-user",
                "repo_ref": "octocat/Hello-World",
                "report_text": "Form-based chat message smoke test",
            },
        )
        check(
            "POST /chat/messages (form)",
            st == 201 and isinstance(data, str) and "Canal simulado" in data,
            f"status={st}, html response rendered",
        )
    except Exception as exc:
        check("POST /chat/messages (form)", False, f"Exception: {exc}")

    # 9. GET /api/cases/non-existent
    try:
        st, data = _request(base_url, "GET", "/api/cases/non-existent-case-id-12345")
        check(
            "GET /api/cases/<non-existent>",
            st == 404 and isinstance(data, dict) and "not found" in data.get("error", "").lower(),
            f"status={st}, error={data.get('error') if isinstance(data, dict) else data}",
        )
    except Exception as exc:
        check("GET /api/cases/<non-existent>", False, f"Exception: {exc}")

    print(f"[SmokeTest] Result: {passed}/{total} tests passed.")
    return passed == total


def main() -> None:
    parser = argparse.ArgumentParser(description="ResolveQA Smoke Test Suite")
    parser.add_argument(
        "--base-url",
        default="http://127.0.0.1:8080",
        help="Base URL of ResolveQA backend (default: http://127.0.0.1:8080)",
    )
    args = parser.parse_args()

    success = run_smoke_tests(args.base_url)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
