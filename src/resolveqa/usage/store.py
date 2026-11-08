"""Append-only per-case LLM usage ledger at runs/<case_id>/usage.jsonl."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from resolveqa.contracts import LLMResult
from resolveqa.store.evidence_store import redact_secrets

REPO_ROOT = Path(__file__).resolve().parents[3]
_SAFE_CASE_ID = re.compile(r"^[A-Za-z0-9_-]+$")


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _validate_case_id(case_id: str) -> str:
    if not isinstance(case_id, str) or not case_id.strip():
        raise ValueError("case_id must be a non-empty string")
    cleaned = case_id.strip()
    if cleaned != case_id:
        raise ValueError("case_id must not include surrounding whitespace")
    if cleaned in {".", ".."} or not _SAFE_CASE_ID.match(cleaned) or ".." in cleaned:
        raise ValueError(f"case_id is not allowed: {case_id!r}")
    return cleaned


@dataclass(frozen=True)
class UsageRecord:
    """One successful LLM.complete observation for a case (no prompt bodies)."""

    case_id: str
    ts: str
    purpose: str
    provider: str
    model: str
    tokens_in: int
    tokens_out: int
    mock: bool
    llm_calls: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "ts": self.ts,
            "purpose": self.purpose,
            "provider": self.provider,
            "model": self.model,
            "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out,
            "mock": self.mock,
            "llm_calls": self.llm_calls,
        }

    @classmethod
    def from_dict(cls, data: Any) -> "UsageRecord":
        if not isinstance(data, dict):
            raise ValueError(f"usage row must be an object, got {type(data).__name__}")
        return cls(
            case_id=_validate_case_id(str(data["case_id"])),
            ts=str(data["ts"]),
            purpose=str(data["purpose"]),
            provider=redact_secrets(str(data["provider"])),
            model=redact_secrets(str(data["model"])),
            tokens_in=int(data["tokens_in"]),
            tokens_out=int(data["tokens_out"]),
            mock=bool(data["mock"]),
            llm_calls=int(data["llm_calls"]),
        )


class UsageStore:
    """Persist usage rows under runs/<case_id>/usage.jsonl."""

    def __init__(self, runs_root: Path | str | None = None) -> None:
        self.runs_root = Path(runs_root).resolve() if runs_root is not None else (REPO_ROOT / "runs").resolve()

    def case_dir(self, case_id: str) -> Path:
        safe = _validate_case_id(case_id)
        raw = self.runs_root / safe
        if raw.is_symlink():
            raise ValueError(f"Symlink not allowed for case_dir: {case_id!r}")
        target = raw.resolve()
        if not target.is_relative_to(self.runs_root):
            raise ValueError(f"case_id resolves outside runs_root: {case_id!r}")
        return raw

    def usage_path(self, case_id: str) -> Path:
        path = self.case_dir(case_id) / "usage.jsonl"
        if path.is_symlink():
            raise ValueError(f"usage.jsonl must not be a symlink for case_id={case_id!r}")
        return path

    def record(
        self,
        *,
        case_id: str,
        purpose: str,
        result: LLMResult,
        ts: str | None = None,
    ) -> UsageRecord:
        """Append one usage row from an LLMResult. Never stores prompt text."""
        safe = _validate_case_id(case_id)
        llm_calls = int(getattr(result, "llm_calls", 0) or 0)
        row = UsageRecord(
            case_id=safe,
            ts=ts or _utc_now(),
            purpose=str(purpose).strip().lower(),
            provider=redact_secrets(result.provider),
            model=redact_secrets(result.model),
            tokens_in=int(result.tokens_in),
            tokens_out=int(result.tokens_out),
            mock=bool(result.mock),
            llm_calls=llm_calls,
        )
        case_dir = self.case_dir(safe)
        case_dir.mkdir(parents=True, exist_ok=True)
        path = self.usage_path(safe)
        line = json.dumps(row.to_dict(), ensure_ascii=False) + "\n"
        with path.open("a", encoding="utf-8") as handle:
            handle.write(line)
        return row

    def list_records(self, case_id: str) -> list[UsageRecord]:
        path = self.usage_path(case_id)
        if not path.exists():
            return []
        rows: list[UsageRecord] = []
        for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                rows.append(UsageRecord.from_dict(json.loads(line)))
            except (ValueError, json.JSONDecodeError, KeyError, TypeError) as err:
                raise ValueError(f"invalid usage.jsonl line {line_no} for {case_id!r}: {err}") from err
        return rows


def load_case_usage(runs_root: Path | str, case_id: str) -> list[UsageRecord]:
    """Convenience reader used by timeline/API layers."""
    return UsageStore(runs_root=runs_root).list_records(case_id)
