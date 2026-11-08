"""Minimal playbook JSON loader for Trilha B delivery/reply settings."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class PlaybookError(ValueError):
    """Invalid playbook content or path."""


class ReplyTone(str, Enum):
    """Closed enum for customer reply tone (#25)."""

    NEUTRAL = "neutral"
    FRIENDLY = "friendly"
    FORMAL = "formal"


@dataclass(frozen=True)
class ApproverWarning:
    """Recorded when an approver entry is invalid or has no access — never silent."""

    approver: str
    detail: str


@dataclass(frozen=True)
class Playbook:
    """Project settings used by Reply/Delivery until Track A freezes the full schema."""

    approvers: tuple[str, ...] = ()
    approver_warnings: tuple[ApproverWarning, ...] = ()
    reply_tone: ReplyTone = ReplyTone.NEUTRAL
    reply_max_chars: int = 500
    changelog_path: str = "CHANGELOG.md"
    technical_notes_dir: str = "technical_notes"
    kb_drafts_dir: str = "kb_drafts"
    source_path: str | None = None

    @property
    def has_approvers(self) -> bool:
        return bool(self.approvers)


def _validate_approver(raw: object) -> tuple[str | None, ApproverWarning | None]:
    if not isinstance(raw, str) or not raw.strip():
        return None, ApproverWarning(
            approver=repr(raw),
            detail="approver must be a non-empty string; ignored for review request",
        )
    name = raw.strip()
    # "No access" heuristic for demo: entries starting with "!" are flagged.
    if name.startswith("!"):
        cleaned = name.lstrip("!").strip() or name
        return cleaned, ApproverWarning(
            approver=cleaned,
            detail="approver marked without access; review still requested with warning",
        )
    if any(ch.isspace() for ch in name) or "/" in name or "\\" in name:
        return None, ApproverWarning(
            approver=name,
            detail="approver format invalid; recorded as warning, not silently dropped",
        )
    return name, None


def load_playbook(path: Path | str | None) -> Playbook | None:
    """Load playbook JSON. Missing path => None (callers keep #16/#17 defaults)."""
    if path is None:
        return None
    playbook_path = Path(path)
    if not playbook_path.is_file():
        return None
    try:
        data = json.loads(playbook_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as err:
        raise PlaybookError(f"Invalid playbook JSON at {playbook_path}: {err}") from err
    if not isinstance(data, dict):
        raise PlaybookError("Playbook root must be a JSON object")

    approvers: list[str] = []
    warnings: list[ApproverWarning] = []
    raw_approvers = data.get("approvers", [])
    if raw_approvers is None:
        raw_approvers = []
    if not isinstance(raw_approvers, list):
        raise PlaybookError("'approvers' must be a list")
    for item in raw_approvers:
        name, warning = _validate_approver(item)
        if warning is not None:
            warnings.append(warning)
        if name is not None:
            approvers.append(name)

    reply = data.get("reply") or {}
    if reply is None:
        reply = {}
    if not isinstance(reply, dict):
        raise PlaybookError("'reply' must be an object")
    tone_raw = reply.get("tone", ReplyTone.NEUTRAL.value)
    try:
        tone = ReplyTone(str(tone_raw))
    except ValueError as err:
        raise PlaybookError(
            f"reply.tone must be one of {[t.value for t in ReplyTone]}, got {tone_raw!r}"
        ) from err
    max_chars = reply.get("max_chars", 500)
    if not isinstance(max_chars, int) or isinstance(max_chars, bool) or max_chars <= 0:
        raise PlaybookError("reply.max_chars must be a positive integer")

    docs = data.get("docs") or {}
    if docs is None:
        docs = {}
    if not isinstance(docs, dict):
        raise PlaybookError("'docs' must be an object")

    def _doc_path(key: str, default: str) -> str:
        value = docs.get(key, default)
        if not isinstance(value, str) or not value.strip():
            raise PlaybookError(f"docs.{key} must be a non-empty string")
        text = value.strip().replace("\\", "/")
        if text.startswith("/") or ".." in text.split("/"):
            raise PlaybookError(f"docs.{key} must be a relative path without '..'")
        return text

    return Playbook(
        approvers=tuple(approvers),
        approver_warnings=tuple(warnings),
        reply_tone=tone,
        reply_max_chars=max_chars,
        changelog_path=_doc_path("changelog_path", "CHANGELOG.md"),
        technical_notes_dir=_doc_path("technical_notes_dir", "technical_notes"),
        kb_drafts_dir=_doc_path("kb_drafts_dir", "kb_drafts"),
        source_path=str(playbook_path),
    )
