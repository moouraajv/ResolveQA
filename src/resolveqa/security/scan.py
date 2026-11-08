"""Secret scan over demo artifacts before they are trusted as clean (RNF-01)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

# Patterns aligned with sandbox redaction, plus common JWT/bearer forms.
_SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("github_token", re.compile(r"\b(gh[pousr]_[A-Za-z0-9_]{8,})\b")),
    ("github_pat", re.compile(r"\b(github_pat_[A-Za-z0-9_]{8,})\b")),
    ("openai_key", re.compile(r"\b(sk-[A-Za-z0-9_-]{8,})\b")),
    ("google_api_key", re.compile(r"\b(AIza[A-Za-z0-9_-]{8,})\b")),
    ("aws_access_key", re.compile(r"\b(AKIA[0-9A-Z]{16})\b")),
    ("bearer_jwt", re.compile(r"\b(eyJ[A-Za-z0-9_-]+\.eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+)\b")),
)

# Artifact name globs that #26 / #27 will produce; scan covers them when present.
DEFAULT_ARTIFACT_GLOBS: tuple[str, ...] = (
    "**/events.jsonl",
    "**/evidence/**",
    "**/*.log",
    "**/CHANGELOG.md",
    "**/changelog*",
    "**/technical_notes/**",
    "**/kb_drafts/**",
    "**/*nota*tecnica*",
    "**/*kb*draft*",
)


@dataclass(frozen=True)
class SecretFinding:
    path: str
    kind: str
    excerpt: str


def find_secrets_in_text(text: str) -> list[tuple[str, str]]:
    """Return (kind, match) pairs for secret-like substrings."""
    hits: list[tuple[str, str]] = []
    if not text:
        return hits
    for kind, pattern in _SECRET_PATTERNS:
        for match in pattern.finditer(text):
            hits.append((kind, match.group(1)))
    return hits


def scan_paths_for_secrets(
    roots: Sequence[Path | str],
    *,
    globs: Sequence[str] = DEFAULT_ARTIFACT_GLOBS,
) -> list[SecretFinding]:
    """Scan files under roots matching globs; return any secret findings."""
    findings: list[SecretFinding] = []
    seen: set[Path] = set()
    for root in roots:
        base = Path(root)
        if not base.exists():
            continue
        if base.is_file():
            candidates = [base]
        else:
            candidates = []
            for pattern in globs:
                candidates.extend(base.glob(pattern))
        for path in candidates:
            resolved = path.resolve()
            if resolved in seen or not resolved.is_file():
                continue
            seen.add(resolved)
            try:
                text = resolved.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for kind, match in find_secrets_in_text(text):
                findings.append(
                    SecretFinding(
                        path=str(resolved),
                        kind=kind,
                        excerpt=match[:12] + "…",
                    )
                )
    return findings
