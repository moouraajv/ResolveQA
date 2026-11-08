"""Triage stage implementation (RFC-0001 section 3.3, PRD RF-03, Issue #9).

Converts an immutable `RunState` bug report into either:
- `TriageRecord` (when input, expected, and observed behavior are identified), or
- `NeedsInfo` (when critical values are missing, providing a question for support).

All untrusted case fields (`report_text`, `repo_ref`, `case_id`, `channel`) are
wrapped in `<untrusted_data>` blocks before calling the LLM adapter (RNF-02).
Does not mutate `RunState` or manage stage state transitions directly.
"""

from __future__ import annotations

import json
from typing import Any

from resolveqa.contracts import (
    ContractValidationError,
    LLMResult,
    LLMStage,
    NeedsInfo,
    RunState,
    TriageRecord,
)
from resolveqa.llm import (
    LLMAdapter,
    LLMOutputError,
    build_delimited_messages,
    validate_llm_output,
)

DEFAULT_TRIAGE_SYSTEM_INSTRUCTION = (
    "You are the ResolveQA Triage stage (RF-03, RFC-0001 section 3.3).\n"
    "Analyze the bug report provided inside <untrusted_data> blocks and respond "
    "ONLY with a single JSON object matching one of two statuses:\n"
    "1) If the report contains sufficient concrete data to reproduce the defect "
    "(input parameters, expected output, and observed output), return:\n"
    '   {"status": "triaged", "input": "<inputs>", "expected": "<expected value>", '
    '"observed": "<observed value>", "suspect_files": ["<relative_path>"], '
    '"confidence": <float between 0.0 and 1.0>}\n'
    "2) If expected or observed values or inputs are missing or ambiguous, return:\n"
    '   {"status": "needs_info", "missing_fields": ["<field>", ...], '
    '"question_to_support": "<clear question asking support/customer for the missing values>"}'
)

TRIAGE_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["status"],
    "properties": {
        "status": {
            "type": "string",
            "enum": ["triaged", "needs_info"],
        },
    },
}


class Triage:
    """Stateless Triage stage implementing `TriageStage` protocol (RFC-0001 section 3.3)."""

    def __init__(
        self,
        llm: LLMStage | None = None,
        *,
        system_instruction: str = DEFAULT_TRIAGE_SYSTEM_INSTRUCTION,
        schema: dict[str, Any] | None = None,
    ) -> None:
        if not isinstance(system_instruction, str) or not system_instruction.strip():
            raise ValueError("system_instruction must be a non-empty string")
        self.llm: LLMStage = llm if llm is not None else LLMAdapter()
        self.system_instruction = system_instruction.strip()
        self.schema: dict[str, Any] = (
            dict(schema) if schema is not None else dict(TRIAGE_OUTPUT_SCHEMA)
        )

    def run(self, case: RunState) -> TriageRecord | NeedsInfo:
        """Analyze `case` via the configured LLM adapter and return `TriageRecord` or `NeedsInfo`."""
        if not isinstance(case, RunState):
            raise ContractValidationError(
                f"Triage.run expects RunState, got {type(case).__name__}."
            )

        bind_case = getattr(self.llm, "bind_case", None)
        if callable(bind_case):
            bind_case(case)

        messages = build_delimited_messages(
            system_instruction=self.system_instruction,
            untrusted_blocks={
                "case_id": case.case_id,
                "repo_ref": case.repo_ref,
                "channel": case.channel.value,
                "report_text": case.report_text,
            },
        )

        llm_result = self.llm.complete("triage", messages, self.schema)
        if not isinstance(llm_result, LLMResult):
            raise LLMOutputError(
                f"Triage expected LLMResult from LLM adapter, got {type(llm_result).__name__}",
                purpose="triage",
            )

        validate_llm_output("triage", llm_result.content, schema=self.schema)
        payload = json.loads(llm_result.content)

        status = payload.get("status")
        if status == "triaged":
            return TriageRecord(
                input=payload["input"],
                expected=payload["expected"],
                observed=payload["observed"],
                suspect_files=tuple(payload["suspect_files"]),
                confidence=float(payload["confidence"]),
            )
        if status == "needs_info":
            return NeedsInfo(
                missing_fields=tuple(payload["missing_fields"]),
                question_to_support=payload["question_to_support"],
            )

        raise LLMOutputError(
            f"Unsupported triage status: {status!r}",
            purpose="triage",
        )


def run_triage(
    case: RunState,
    llm: LLMStage | None = None,
) -> TriageRecord | NeedsInfo:
    """Convenience helper to execute `Triage.run` on `case`."""
    return Triage(llm=llm).run(case)
