"""LLM usage persistence and USD cost estimates (issues #60–#63)."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from resolveqa.contracts import Attempts, CaseState, ChannelType, LLMResult, RunState
from resolveqa.llm import LLMAdapter, build_delimited_messages
from resolveqa.usage import (
    UsageStore,
    estimate_case_cost,
    load_pricing,
    model_rate_key,
)


def _case(case_id: str = "case-usage-1") -> RunState:
    return RunState(
        case_id=case_id,
        client_id="client-demo",
        repo_ref="demo-target",
        channel=ChannelType.API,
        report_text="Cupom 10% em R$ 200 retornou R$ 200 em vez de R$ 180.",
        state=CaseState.TRIAGING,
        created_at="2026-11-08T12:00:00Z",
        updated_at="2026-11-08T12:00:00Z",
        attempts=Attempts(fix=0, llm_calls=0),
    )


class TestUsageCost(unittest.TestCase):
    def test_pricing_table_is_usd(self) -> None:
        table = load_pricing()
        self.assertEqual(table.currency, "USD")
        self.assertEqual(table.label, "estimate")
        key = model_rate_key("featherless", "Qwen/Qwen3-Coder-30B-A3B-Instruct")
        self.assertIn(key, table.models)

    def test_persist_and_estimate_real_and_mock_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runs = Path(tmp) / "runs"
            store = UsageStore(runs_root=runs)
            real = LLMResult(
                content='{"status":"needs_info","missing_fields":["expected"],"question_to_support":"x?","reproduction":null}',
                tokens_in=1_000_000,
                tokens_out=500_000,
                provider="featherless",
                model="Qwen/Qwen3-Coder-30B-A3B-Instruct",
                mock=False,
            )
            object.__setattr__(real, "llm_calls", 1)
            mock = LLMResult(
                content='{"status":"needs_info","missing_fields":["expected"],"question_to_support":"x?","reproduction":null}',
                tokens_in=100,
                tokens_out=50,
                provider="mock",
                model="deterministic-mock-v1",
                mock=True,
            )
            object.__setattr__(mock, "llm_calls", 2)
            store.record(case_id="case-usage-1", purpose="triage", result=real)
            store.record(case_id="case-usage-1", purpose="reproduction", result=mock)
            rows = store.list_records("case-usage-1")
            self.assertEqual(len(rows), 2)
            path = runs / "case-usage-1" / "usage.jsonl"
            self.assertTrue(path.is_file())
            raw = path.read_text(encoding="utf-8")
            self.assertNotIn("Cupom", raw)
            summary = estimate_case_cost("case-usage-1", rows)
            self.assertEqual(summary.currency, "USD")
            self.assertEqual(summary.label, "estimate")
            self.assertEqual(summary.llm_calls, 2)
            self.assertEqual(summary.tokens_in, 1_000_100)
            self.assertEqual(summary.tokens_out, 500_050)
            # 1M in * 0.1 + 0.5M out * 0.2 = 0.1 + 0.1 = 0.2; mock adds 0
            self.assertAlmostEqual(summary.estimated_usd, 0.2, places=8)
            self.assertEqual(summary.mock_calls, 1)
            statuses = {line.status for line in summary.lines}
            self.assertIn("priced", statuses)
            self.assertIn("mock_zero", statuses)

    def test_adapter_writes_usage_without_prompt_bodies(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runs = Path(tmp) / "runs"
            store = UsageStore(runs_root=runs)
            case = _case("case-adapter-1")
            llm = LLMAdapter(case=case, usage_store=store, use_real=False)
            msgs = build_delimited_messages("triage system", {"report_text": case.report_text})
            result = llm.complete("triage", msgs, case=case)
            self.assertTrue(result.mock)
            rows = store.list_records(case.case_id)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0].purpose, "triage")
            blob = (runs / case.case_id / "usage.jsonl").read_text(encoding="utf-8")
            self.assertNotIn(case.report_text, blob)
            payload = json.loads(blob.strip())
            self.assertEqual(set(payload), {
                "case_id",
                "ts",
                "purpose",
                "provider",
                "model",
                "tokens_in",
                "tokens_out",
                "mock",
                "llm_calls",
            })

    def test_unpriced_model_is_explicit(self) -> None:
        from resolveqa.usage.store import UsageRecord

        row = UsageRecord(
            case_id="case-x",
            ts="2026-11-08T12:00:00Z",
            purpose="triage",
            provider="featherless",
            model="unknown/model",
            tokens_in=10,
            tokens_out=5,
            mock=False,
            llm_calls=1,
        )
        summary = estimate_case_cost("case-x", [row])
        self.assertEqual(summary.unpriced_calls, 1)
        self.assertEqual(summary.estimated_usd, 0.0)
        self.assertEqual(summary.lines[0].status, "unpriced")
        self.assertIsNone(summary.lines[0].estimated_usd)


if __name__ == "__main__":
    unittest.main()
