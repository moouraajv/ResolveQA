"""Triage stage implementation (Issue #9, RF-03, RFC-0001 §3.3)."""

from __future__ import annotations

import json
from pathlib import Path, PurePosixPath
from typing import Any, Optional

from resolveqa.contracts import (
    ContractValidationError,
    EvidenceKind,
    NeedsInfo,
    RunState,
    TriageRecord,
)
from resolveqa.llm import LLMAdapter, LLMOutputError, build_delimited_messages
from resolveqa.store import EvidenceStore

_PLACEHOLDER_VALUES = frozenset({
    "",
    "?",
    "n/a",
    "na",
    "none",
    "null",
    "undefined",
    "desconhecido",
    "não informado",
    "nao informado",
    "indefinido",
})


def _is_placeholder(value: Any) -> bool:
    if not isinstance(value, str):
        return True
    return value.strip().lower() in _PLACEHOLDER_VALUES


def _ensure_question_mark(question: str) -> str:
    cleaned = question.strip()
    if not cleaned:
        return (
            "Para reproduzirmos o problema com precisão, você pode informar os dados de entrada, "
            "o valor esperado e o valor observado?"
        )
    if "?" not in cleaned:
        cleaned = cleaned.rstrip(".!;:") + "?"
    return cleaned


def _validate_relative_repo_path(path_str: str) -> str:
    if not isinstance(path_str, str) or not path_str.strip():
        raise LLMOutputError("suspect_files entries must be non-empty strings.")
    cleaned = path_str.strip()
    if cleaned.startswith(("/", "\\")) or "\\" in cleaned:
        raise LLMOutputError(f"Unsafe suspect file path outside repository: {path_str!r}")
    posix = PurePosixPath(cleaned)
    if posix.is_absolute() or ".." in posix.parts:
        raise LLMOutputError(f"Path traversal detected in suspect_files: {path_str!r}")
    return str(posix)


class TriageEngine:
    """Converts an unstructured customer defect report into TriageRecord or NeedsInfo (RF-03)."""

    def __init__(
        self,
        llm: Optional[LLMAdapter] = None,
        store: Optional[EvidenceStore] = None,
        base_root: Optional[Path | str] = None,
    ) -> None:
        self.llm = llm if llm is not None else LLMAdapter()
        self.store = store
        self.base_root = Path(base_root).resolve() if base_root is not None else None

    def get_llm_calls(self, case: RunState) -> int:
        """Return total LLM calls tracked for this case without mutating RunState."""
        if hasattr(self.llm, "get_llm_calls"):
            return int(self.llm.get_llm_calls(case))
        return int(case.attempts.llm_calls)

    def run(self, case: RunState) -> TriageRecord | NeedsInfo:
        """Analyze case.report_text and return TriageRecord or NeedsInfo without mutating case."""
        if not isinstance(case, RunState):
            raise TypeError(f"Expected RunState, got {type(case).__name__}")

        messages = build_delimited_messages(
            system_instruction=(
                "Analyze the customer defect report and extract structured triage fields "
                "(input, expected, observed, suspect_files, confidence) as JSON, or return "
                "needs_info JSON with missing_fields and question_to_support when concrete "
                "input/expected/observed values are absent."
            ),
            untrusted_blocks={
                "customer_report": case.report_text,
                "repo_ref": case.repo_ref,
                "client_id": case.client_id,
            },
        )

        llm_result = self.llm.complete(
            "triage",
            messages,
            schema={"type": "triage"},
            case=case,
        )

        try:
            payload = json.loads(llm_result.content)
        except json.JSONDecodeError as exc:
            raise LLMOutputError(f"Triage LLM output is not valid JSON: {exc}") from exc

        if not isinstance(payload, dict):
            raise LLMOutputError("Triage LLM output must be a JSON object.")

        if (
            payload.get("status") == "needs_info"
            or ("missing_fields" in payload and "question_to_support" in payload)
        ):
            missing = payload.get("missing_fields") or ["expected", "observed"]
            question = _ensure_question_mark(str(payload.get("question_to_support") or ""))
            try:
                return NeedsInfo(
                    missing_fields=list(missing),
                    question_to_support=question,
                )
            except ContractValidationError as exc:
                raise LLMOutputError(f"Invalid NeedsInfo payload from LLM: {exc}") from exc

        expected_raw = payload.get("expected")
        observed_raw = payload.get("observed")
        input_raw = payload.get("input")

        missing_fields: list[str] = []
        if _is_placeholder(input_raw):
            missing_fields.append("input")
        if _is_placeholder(expected_raw):
            missing_fields.append("expected")
        if _is_placeholder(observed_raw):
            missing_fields.append("observed")

        if missing_fields:
            return NeedsInfo(
                missing_fields=missing_fields,
                question_to_support=(
                    "Para reproduzirmos o problema com precisão, você pode informar o valor da compra, "
                    "o cupom ou entrada utilizada, o valor esperado e o valor observado no sistema?"
                ),
            )

        raw_suspects = payload.get("suspect_files", [])
        if not isinstance(raw_suspects, (list, tuple)):
            raise LLMOutputError("'suspect_files' in triage output must be a list.")
        validated_suspects = [_validate_relative_repo_path(p) for p in raw_suspects]

        try:
            record = TriageRecord(
                input=str(input_raw).strip(),
                expected=str(expected_raw).strip(),
                observed=str(observed_raw).strip(),
                suspect_files=validated_suspects,
                confidence=float(payload.get("confidence", 1.0)),
            )
        except (ContractValidationError, ValueError, TypeError) as exc:
            raise LLMOutputError(f"Invalid TriageRecord payload from LLM: {exc}") from exc

        if record.expected == record.observed:
            raise LLMOutputError(
                "Incoherent TriageRecord: 'expected' and 'observed' cannot be identical."
            )

        if self.store is not None:
            self.store.save_evidence(
                case_id=case.case_id,
                evidence_id="ev-triage-record",
                kind=EvidenceKind.TRIAGE_RECORD,
                content=record.to_json(indent=2),
                extension="json",
            )

        return record


Triage = TriageEngine
