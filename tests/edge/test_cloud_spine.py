"""Local cloud spine: file store + file queue + worker + snapshot API."""

from __future__ import annotations

import json
import threading
import time
import unittest
from http.client import HTTPConnection
from pathlib import Path

from resolveqa.contracts import CaseState, ChannelType, ReportInput
from resolveqa.intake import FileCaseStore, Intake
from resolveqa.pipeline import run_pipeline
from resolveqa.queue import FileCaseQueue
from resolveqa.web.server import IntakeHTTPServer
from resolveqa.worker.loop import process_job


ROOT = Path(__file__).resolve().parents[2]


class CloudSpineTests(unittest.TestCase):
    def test_file_store_roundtrip(self) -> None:
        runs = ROOT / "runs" / "_test_spine_store"
        store = FileCaseStore(runs)
        intake = Intake(store)
        case = intake.create(
            ReportInput(
                client_id="resolveqa",
                repo_ref="targets/resolveqa-checkout",
                channel=ChannelType.API,
                report_text="Comprei R$ 200,00, cupom DESC10 10%, total R$ 200,00; esperado R$ 180,00.",
            )
        )
        loaded = store.get(case.case_id)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.state, CaseState.CREATED)
        self.assertTrue(any(c.case_id == case.case_id for c in store.list_cases()))

    def test_enqueue_and_worker_processes_coupon(self) -> None:
        runs = ROOT / "runs" / "_test_spine_queue"
        if runs.exists():
            for path in sorted(runs.rglob("*"), reverse=True):
                if path.is_file():
                    path.unlink()
        store = FileCaseStore(runs)
        queue = FileCaseQueue(runs)
        intake = Intake(store, queue=queue)
        case = intake.create(
            ReportInput(
                client_id="resolveqa",
                repo_ref="targets/resolveqa-checkout",
                channel=ChannelType.API,
                report_text=(
                    "Comprei R$ 200,00 no site, apliquei o cupom DESC10 de 10% "
                    "e o total continuou R$ 200,00. Deveria ser R$ 180,00."
                ),
            )
        )
        job = queue.dequeue(wait_seconds=2)
        self.assertIsNotNone(job)
        assert job is not None
        self.assertEqual(job.case_id, case.case_id)

        from resolveqa.demo.llm import create_demo_llm

        def on_case(updated):
            store.put(updated)

        result = run_pipeline(
            case,
            root=ROOT,
            llm=create_demo_llm(real=False),
            real=False,
            on_case=on_case,
        )
        store.put(result.case)
        queue.ack(job)
        self.assertEqual(result.case.state, CaseState.VERIFIED)
        self.assertEqual(store.get(case.case_id).state, CaseState.VERIFIED)

    def test_api_create_returns_202_when_queued(self) -> None:
        runs = ROOT / "runs" / "_test_spine_api"
        store = FileCaseStore(runs)
        queue = FileCaseQueue(runs)
        intake = Intake(store, queue=queue)
        server = IntakeHTTPServer(
            ("127.0.0.1", 0),
            intake,
            runs_root=runs,
            allow_operator_advance=False,
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            host, port = server.server_address
            conn = HTTPConnection(host, port, timeout=5)
            body = json.dumps(
                {
                    "client_id": "resolveqa",
                    "repo_ref": "targets/resolveqa-checkout",
                    "report_text": "Relato mínimo com cupom 10% total 200 esperado 180.",
                }
            ).encode("utf-8")
            conn.request(
                "POST",
                "/api/cases",
                body=body,
                headers={"Content-Type": "application/json"},
            )
            resp = conn.getresponse()
            payload = json.loads(resp.read().decode("utf-8"))
            self.assertEqual(resp.status, 202)
            self.assertTrue(payload.get("queued"))
            case_id = payload["case"]["case_id"]

            conn.request("GET", "/api/snapshot")
            snap_resp = conn.getresponse()
            snap = json.loads(snap_resp.read().decode("utf-8"))
            self.assertEqual(snap_resp.status, 200)
            self.assertTrue(any(c["case_id"] == case_id for c in snap["cases"]))

            conn.request(
                "POST",
                f"/api/cases/{case_id}/advance",
                body=b"{}",
                headers={"Content-Type": "application/json"},
            )
            adv = conn.getresponse()
            adv.read()
            self.assertEqual(adv.status, 400)
        finally:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    unittest.main()
