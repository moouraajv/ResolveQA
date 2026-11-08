"""Evidence store per case with self-contained secret redaction, SHA-256 integrity, traversal protection, and unique evidence IDs (Issue #6, RFC-0001 §3.4, RNF-04)."""

from __future__ import annotations

import hashlib
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from resolveqa.contracts import Evidence, EvidenceKind

REPO_ROOT = Path(__file__).resolve().parents[3]

_SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"-----BEGIN [A-Z0-9_ -]*PRIVATE KEY-----[\s\S]*?-----END [A-Z0-9_ -]*PRIVATE KEY-----"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b"),
    re.compile(r"\brc_[A-Za-z0-9_-]{8,}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{8,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{8,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._\-]{8,}"),
    re.compile(
        r"""(?i)(["']?(?:[A-Za-z0-9_-]*(?:api[_-]?key|token|secret|password|authorization|featherless_api_key|aws_secret_access_key)[A-Za-z0-9_-]*)["']?\s*[:=]\s*["'])([^"\r\n]+)(["'])"""
    ),
    re.compile(
        r"""(?i)(["']?(?:[A-Za-z0-9_-]*(?:api[_-]?key|token|secret|password|authorization|featherless_api_key|aws_secret_access_key)[A-Za-z0-9_-]*)["']?\s*[:=]\s*)([^\s'",;}]+)"""
    ),
)

_SENSITIVE_ENV_PREFIXES = ("OPENAI_", "ANTHROPIC_", "GEMINI_", "GITHUB_", "GH_", "AWS_", "FEATHERLESS_")
_SENSITIVE_ENV_SUFFIXES = ("_TOKEN", "_KEY", "_SECRET", "_PASSWORD", "_CREDENTIALS")
_SAFE_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def redact_secrets(text: str) -> str:
    """Scrub secret tokens, API keys, and sensitive environment variable values from `text`."""
    if not text:
        return ""
    scrubbed = str(text)

    for env_key, env_val in os.environ.items():
        upper = env_key.upper()
        is_sensitive = upper.startswith(_SENSITIVE_ENV_PREFIXES) or upper.endswith(_SENSITIVE_ENV_SUFFIXES)
        if is_sensitive and env_val and len(env_val.strip()) >= 6 and env_val in scrubbed:
            scrubbed = scrubbed.replace(env_val, "[REDACTED_SECRET]")

    scrubbed = _SECRET_PATTERNS[0].sub("[REDACTED_SECRET]", scrubbed)
    scrubbed = _SECRET_PATTERNS[1].sub("[REDACTED_SECRET]", scrubbed)
    scrubbed = _SECRET_PATTERNS[2].sub("[REDACTED_SECRET]", scrubbed)
    scrubbed = _SECRET_PATTERNS[3].sub("[REDACTED_SECRET]", scrubbed)
    scrubbed = _SECRET_PATTERNS[4].sub("[REDACTED_SECRET]", scrubbed)
    scrubbed = _SECRET_PATTERNS[5].sub("[REDACTED_SECRET]", scrubbed)
    scrubbed = _SECRET_PATTERNS[6].sub(r"\1[REDACTED_SECRET]", scrubbed)
    scrubbed = _SECRET_PATTERNS[7].sub(r"\1[REDACTED_SECRET]\3", scrubbed)
    scrubbed = _SECRET_PATTERNS[8].sub(r"\1[REDACTED_SECRET]", scrubbed)
    return scrubbed


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _validate_safe_identifier(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    cleaned = value.strip()
    if not _SAFE_IDENTIFIER_RE.match(cleaned):
        raise ValueError(
            f"Invalid characters in {field_name}: {value!r}. Only [A-Za-z0-9_-] are allowed without glob/traversal characters."
        )
    return cleaned


def _evidence_id_exists(directory: Path, evidence_id: str) -> bool:
    if not directory.exists() or not directory.is_dir():
        return False
    target_prefix = f"{evidence_id}."
    for child in directory.iterdir():
        if child.name == evidence_id or child.name.startswith(target_prefix):
            return True
    return False


class EvidenceStore:
    """Manage `runs/<case_id>/evidence/<evidence_id>.<ext>` with SHA-256, secret scrubbing, and overwrite protection."""

    def __init__(self, runs_root: Path | str | None = None) -> None:
        self.runs_root = Path(runs_root).resolve() if runs_root is not None else (REPO_ROOT / "runs").resolve()
        self._counters: dict[str, int] = {}

    def case_dir(self, case_id: str) -> Path:
        safe_case_id = _validate_safe_identifier(case_id, "case_id")
        raw_target = self.runs_root / safe_case_id
        if raw_target.is_symlink():
            raise ValueError(f"Symlink not allowed for case_dir: {case_id!r}")
        target = raw_target.resolve()
        if not target.is_relative_to(self.runs_root):
            raise ValueError(f"case_id resolves outside runs_root: {case_id!r}")
        return target

    def evidence_dir(self, case_id: str) -> Path:
        c_dir = self.case_dir(case_id)
        raw_ev_dir = c_dir / "evidence"
        if raw_ev_dir.is_symlink():
            raise ValueError(f"Symlink not allowed for evidence directory: {case_id!r}")
        ev_dir = raw_ev_dir.resolve()
        if not ev_dir.is_relative_to(c_dir) or not ev_dir.is_relative_to(self.runs_root):
            raise ValueError(f"evidence directory resolves outside case_dir: {case_id!r}")
        return raw_ev_dir

    def next_evidence_id(self, case_id: str, prefix: str = "ev") -> str:
        """Generate a unique `evidence_id` for `case_id` that does not collide with any existing file."""
        safe_case_id = _validate_safe_identifier(case_id, "case_id")
        safe_prefix = "".join(ch for ch in (prefix or "ev") if ch.isalnum() or ch in {"_", "-"}).strip("-_") or "ev"
        ev_dir = self.evidence_dir(safe_case_id)
        seq = self._counters.get(safe_case_id, 0) + 1
        while True:
            candidate = f"{safe_prefix}-{seq:04d}-{uuid.uuid4().hex[:8]}"
            if not _evidence_id_exists(ev_dir, candidate):
                self._counters[safe_case_id] = seq
                return candidate
            seq += 1

    def save_evidence(
        self,
        case_id: str,
        evidence_id: Optional[str] = None,
        kind: EvidenceKind = EvidenceKind.REPORT,
        content: str = "",
        extension: str = "txt",
        revision: Optional[str] = None,
        simulated: bool = False,
        created_at: Optional[str] = None,
    ) -> Evidence:
        """Scrub secrets, write an immutable evidence file under `runs/<case_id>/evidence/`, and return `Evidence`.

        Refuses to overwrite any existing `evidence_id` for the same case (`FileExistsError`).
        If `evidence_id` is `None`, generates a guaranteed-unique `evidence_id` automatically.
        """
        safe_case_id = _validate_safe_identifier(case_id, "case_id")
        if evidence_id is None:
            kind_slug = getattr(kind, "value", str(kind)).replace("_", "-")
            safe_ev_id = self.next_evidence_id(safe_case_id, prefix=f"ev-{kind_slug}")
        else:
            safe_ev_id = _validate_safe_identifier(evidence_id, "evidence_id")

        safe_ext = "".join(ch for ch in extension.lstrip(".") if ch.isalnum() or ch in {"_", "-"}).strip("-_") or "txt"

        c_dir = self.case_dir(safe_case_id)
        ev_dir = self.evidence_dir(safe_case_id)
        if ev_dir.is_symlink():
            raise ValueError(f"Symlink not allowed for evidence directory: {safe_case_id!r}")
        ev_dir.mkdir(parents=True, exist_ok=True)
        if ev_dir.is_symlink():
            raise ValueError(f"Symlink not allowed for evidence directory: {safe_case_id!r}")

        rel_path = f"evidence/{safe_ev_id}.{safe_ext}"
        raw_full_path = c_dir / rel_path
        if raw_full_path.is_symlink():
            raise ValueError(f"Symlink not allowed for evidence file: {rel_path}")
        full_path = raw_full_path.resolve()
        if not full_path.is_relative_to(c_dir) or not full_path.is_relative_to(self.runs_root):
            raise ValueError(f"Evidence path resolves outside case directory: {rel_path}")

        if full_path.exists() or _evidence_id_exists(ev_dir, safe_ev_id):
            raise FileExistsError(
                f"Evidence ID {safe_ev_id!r} already exists for case {safe_case_id!r}; overwrite is forbidden."
            )

        scrubbed = redact_secrets(content or "")
        raw_bytes = scrubbed.encode("utf-8")
        with full_path.open("xb") as fh:
            fh.write(raw_bytes)
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
