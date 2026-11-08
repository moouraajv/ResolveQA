"""Append-only event log and evidence store per case (RFC-0001 §3.2, §3.4, RNF-04)."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import resolveqa.contracts as contracts
from resolveqa.contracts import (
    CaseState,
    Event,
    EventType,
    Evidence,
    EvidenceKind,
    RunState,
    TERMINAL_STATES,
)
from resolveqa.sandbox.executor import redact_secrets

REPO_ROOT = Path(__file__).resolve().parents[3]


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _validate_safe_identifier(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    cleaned = value.strip()
    if "/" in cleaned or "\\" in cleaned or ".." in cleaned or cleaned in {".", ".."}:
        raise ValueError(f"Unsafe path characters in {field_name}: {value!r}")
    return cleaned


def _format_terminal_reason_for_state(
    state: CaseState,
    reason_str: Optional[str],
    detail: Optional[str] = None,
) -> Any:
    """Build a terminal_reason compatible with both string and structured TerminalReason contracts."""
    if state not in TERMINAL_STATES or state == CaseState.VERIFIED:
        return None
    raw = (reason_str or "unspecified").strip()
    if hasattr(contracts, "BlockedTerminalReason"):
        if state == CaseState.BLOCKED:
            code = raw if raw in {"limit_exceeded", "not_reproduced", "patch_rejected"} else "not_reproduced"
            return contracts.BlockedTerminalReason(code=code, detail=detail)
        if state == CaseState.NEEDS_INFO:
            return contracts.NeedsInfoTerminalReason(question_to_support=detail or raw)
        if state == CaseState.INFRA_ERROR:
            return contracts.InfraErrorTerminalReason(detail=detail or raw)
    return raw


class EvidenceStore:
    """Manage `runs/<case_id>/events.jsonl` and `runs/<case_id>/evidence/<evidence_id>.<ext>`."""

    def __init__(self, runs_root: Path | str | None = None) -> None:
        self.runs_root = Path(runs_root).resolve() if runs_root is not None else (REPO_ROOT / "runs").resolve()

    def case_dir(self, case_id: str) -> Path:
        safe_case_id = _validate_safe_identifier(case_id, "case_id")
        target = (self.runs_root / safe_case_id).resolve()
        if not target.is_relative_to(self.runs_root):
            raise ValueError(f"case_id resolves outside runs_root: {case_id!r}")
        return target

    def events_path(self, case_id: str) -> Path:
        return self.case_dir(case_id) / "events.jsonl"

    def append_event(self, event: Event) -> Event:
        """Append an immutable `Event` to `runs/<case_id>/events.jsonl`, enforcing contiguous sequence."""
        existing = self.read_events(event.case_id)
        expected_seq = (existing[-1].seq + 1) if existing else 1
        if event.seq != expected_seq:
            raise ValueError(
                f"Non-contiguous event seq for case {event.case_id!r}: expected {expected_seq}, got {event.seq}"
            )
        ev_file = self.events_path(event.case_id)
        ev_file.parent.mkdir(parents=True, exist_ok=True)
        with ev_file.open("a", encoding="utf-8") as fh:
            fh.write(event.to_json() + "\n")
        return event

    def read_events(self, case_id: str) -> list[Event]:
        """Read all recorded events for `case_id` in order."""
        ev_file = self.events_path(case_id)
        if not ev_file.is_file():
            return []
        events: list[Event] = []
        for line in ev_file.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped:
                events.append(Event.from_json(stripped))
        return events

    def save_evidence(
        self,
        case_id: str,
        evidence_id: str,
        kind: EvidenceKind,
        content: str,
        extension: str = "txt",
        revision: Optional[str] = None,
        simulated: bool = False,
        created_at: Optional[str] = None,
    ) -> Evidence:
        """Scrub secrets, write an evidence file under `runs/<case_id>/evidence/`, and return `Evidence`."""
        safe_case_id = _validate_safe_identifier(case_id, "case_id")
        safe_ev_id = _validate_safe_identifier(evidence_id, "evidence_id")
        safe_ext = "".join(ch for ch in extension.lstrip(".") if ch.isalnum() or ch in {"_", "-"}) or "txt"

        c_dir = self.case_dir(safe_case_id)
        ev_dir = c_dir / "evidence"
        ev_dir.mkdir(parents=True, exist_ok=True)

        rel_path = f"evidence/{safe_ev_id}.{safe_ext}"
        full_path = (c_dir / rel_path).resolve()
        if not full_path.is_relative_to(c_dir):
            raise ValueError(f"Evidence path resolves outside case directory: {rel_path}")

        scrubbed = redact_secrets(content or "")
        raw_bytes = scrubbed.encode("utf-8")
        full_path.write_bytes(raw_bytes)
        digest = hashlib.sha256(raw_bytes).hexdigest()

        return Evidence(
            evidence_id=safe_ev_id,
            case_id=safe_case_id,
            kind=kind,
            path=rel_path,
            sha256=digest,
            created_at=created_at or _utc_now_iso(),
            revision=revision,
            simulated=simulated,
        )

    def reconstruct_state(self, case_id: str, initial_case: RunState) -> RunState:
        """Reconstruct `RunState` deterministically from `events.jsonl` (RFC-0001 §3.2)."""
        events = self.read_events(case_id)
        if not events:
            return initial_case

        current_state = initial_case.state
        last_ts = initial_case.updated_at
        last_reason: Optional[str] = None
        collected_evidence = list(initial_case.evidence_ids)

        for ev in events:
            last_ts = ev.ts
            for ref in ev.evidence_refs:
                if ref not in collected_evidence:
                    collected_evidence.append(ref)
            if ev.type == EventType.STATE_CHANGED and ev.to_state is not None:
                current_state = ev.to_state
                if ev.reason is not None:
                    last_reason = ev.reason

        term_reason = _format_terminal_reason_for_state(current_state, last_reason)
        ev_collection: Any = (
            tuple(collected_evidence)
            if isinstance(initial_case.evidence_ids, tuple)
            else list(collected_evidence)
        )
        return RunState(
            case_id=initial_case.case_id,
            client_id=initial_case.client_id,
            repo_ref=initial_case.repo_ref,
            channel=initial_case.channel,
            report_text=initial_case.report_text,
            state=current_state,
            created_at=initial_case.created_at,
            updated_at=last_ts,
            terminal_reason=term_reason,
            attempts=initial_case.attempts,
            base_revision=initial_case.base_revision,
            fix_revision=initial_case.fix_revision,
            evidence_ids=ev_collection,
        )
