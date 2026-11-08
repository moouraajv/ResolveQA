"""HTTP surface for per-case LLM usage + USD estimate (#63)."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from urllib.request import urlopen

from resolveqa.contracts import LLMResult
from resolveqa.usage import UsageStore
from resolveqa.web.server import serve_ephemeral


class TestUsageApi(unittest.TestCase):
    def test_usage_endpoint_returns_usd_estimate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runs = Path(tmp) / "runs"
            store = UsageStore(runs_root=runs)
            result = LLMResult(
                content='{"status":"needs_info","missing_fields":["expected"],"question_to_support":"x?","reproduction":null}',
                tokens_in=1_000_000,
                tokens_out=0,
                provider="featherless",
                model="Qwen/Qwen3-Coder-30B-A3B-Instruct",
                mock=False,
            )
            object.__setattr__(result, "llm_calls", 1)
            store.record(case_id="case-http-1", purpose="triage", result=result)

            server = serve_ephemeral("127.0.0.1", 0)
            server.runs_root = runs
            host, port = server.server_address
            import threading

            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                with urlopen(f"http://{host}:{port}/api/cases/case-http-1/usage", timeout=5) as resp:
                    payload = json.loads(resp.read().decode("utf-8"))
                self.assertEqual(payload["currency"], "USD")
                self.assertEqual(payload["label"], "estimate")
                self.assertEqual(payload["llm_calls"], 1)
                self.assertAlmostEqual(payload["estimated_usd"], 0.1, places=8)

                with urlopen(f"http://{host}:{port}/api/cases/case-http-1/timeline", timeout=5) as resp:
                    timeline = json.loads(resp.read().decode("utf-8"))
                self.assertIn("usage", timeline)
                self.assertEqual(timeline["usage"]["currency"], "USD")
            finally:
                server.shutdown()
                server.server_close()

    def test_usage_endpoint_empty_case_is_zero(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runs = Path(tmp) / "runs"
            runs.mkdir()
            server = serve_ephemeral("127.0.0.1", 0)
            server.runs_root = runs
            host, port = server.server_address
            import threading

            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                with urlopen(f"http://{host}:{port}/api/cases/case-empty/usage", timeout=5) as resp:
                    payload = json.loads(resp.read().decode("utf-8"))
                self.assertEqual(payload["llm_calls"], 0)
                self.assertEqual(payload["estimated_usd"], 0.0)
            finally:
                server.shutdown()
                server.server_close()


if __name__ == "__main__":
    unittest.main()
