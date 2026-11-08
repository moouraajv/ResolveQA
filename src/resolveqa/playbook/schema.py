"""Schema and models for project playbook policy (.resolveqa/playbook.toml).

Issue #22 (Track A — RFC-0001 §3.3, §5, §6, §8, PRD RF-05, RF-06, RNF-03).
"""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass, field
from enum import Enum
import posixpath
from typing import Any


class PlaybookError(ValueError):
    """Raised when playbook TOML/JSON is invalid, malformed, or violates policy."""

    def __init__(self, message: str, field: str | None = None) -> None:
        super().__init__(message)
        self.field = field


class PlaybookSyntaxError(PlaybookError):
    """Raised when playbook TOML has syntax errors, indicating line and column."""

    def __init__(self, message: str, line: int | None = None, column: int | None = None) -> None:
        super().__init__(message)
        self.line = line
        self.column = column


class ReplyTone(str, Enum):
    """Closed enum for customer reply tone (Issue #22, #25)."""

    NEUTRAL = "neutral"
    FRIENDLY = "friendly"
    FORMAL = "formal"


@dataclass(frozen=True)
class ApproverWarning:
    """Recorded when an approver entry is invalid or has no access — never silent."""

    approver: str
    detail: str


# RNF-03 Baseline Limits (maximum allowed looseness)
BASELINE_LIMITS = {
    "max_fix_attempts": 2,
    "max_llm_calls": 12,
    "test_timeout_s": 600.0,
    "max_files_changed": 3,
    "max_output_bytes": 65536,
}

DEFAULT_PROTECTED_TESTS = (
    ".resolveqa/playbook.toml",
    ".resolveqa/**",
    "tests/**",
    "test_*.py",
    "*_test.py",
    "conftest.py",
)

DEFAULT_FORBIDDEN_PATHS = (
    ".resolveqa/playbook.toml",
    ".resolveqa/**",
    ".git/**",
    ".github/**",
)


@dataclass(frozen=True)
class PlaybookLimits:
    """Configurable limits that must be at least as strict as RNF-03 baseline."""

    max_fix_attempts: int = 2
    max_llm_calls: int = 12
    test_timeout_s: float = 600.0
    max_files_changed: int = 3
    max_output_bytes: int = 65536

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_fix_attempts": self.max_fix_attempts,
            "max_llm_calls": self.max_llm_calls,
            "test_timeout_s": self.test_timeout_s,
            "max_files_changed": self.max_files_changed,
            "max_output_bytes": self.max_output_bytes,
        }


@dataclass(frozen=True)
class PathsConfig:
    """Path allow/forbid patterns for proposed fixes."""

    allowed: tuple[str, ...] = ("**",)
    forbidden: tuple[str, ...] = DEFAULT_FORBIDDEN_PATHS

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": list(self.allowed),
            "forbidden": list(self.forbidden),
        }


@dataclass(frozen=True)
class TestsConfig:
    """Protected test paths and patterns."""

    __test__ = False
    protected: tuple[str, ...] = DEFAULT_PROTECTED_TESTS

    def to_dict(self) -> dict[str, Any]:
        return {
            "protected": list(self.protected),
        }


@dataclass(frozen=True)
class ReplyConfig:
    """Customer notification message preferences."""

    tone: ReplyTone = ReplyTone.NEUTRAL
    max_chars: int = 500

    def to_dict(self) -> dict[str, Any]:
        return {
            "tone": self.tone.value,
            "max_chars": self.max_chars,
        }


@dataclass(frozen=True)
class DocsConfig:
    """Documentation destinations in delivery packages."""

    changelog_path: str = "CHANGELOG.md"
    technical_notes_dir: str = "technical_notes"
    kb_drafts_dir: str = "kb_drafts"

    def to_dict(self) -> dict[str, Any]:
        return {
            "changelog_path": self.changelog_path,
            "technical_notes_dir": self.technical_notes_dir,
            "kb_drafts_dir": self.kb_drafts_dir,
        }


def _matches_any_glob(path: str, patterns: tuple[str, ...]) -> bool:
    norm = posixpath.normpath(path.strip().replace("\\", "/")).lstrip("./")
    basename = posixpath.basename(norm)
    for pat in patterns:
        norm_pat = posixpath.normpath(pat.replace("\\", "/")).lstrip("./")
        if fnmatch.fnmatch(norm, norm_pat):
            return True
        if fnmatch.fnmatch(basename, norm_pat):
            return True
        if not norm_pat.startswith("**/") and fnmatch.fnmatch(norm, f"**/{norm_pat}"):
            return True
        if norm_pat.endswith("/**") and norm == norm_pat[:-3]:
            return True
    return False


@dataclass(frozen=True)
class Playbook:
    """Immutable project policy configuration loaded from .resolveqa/playbook.toml."""

    version: int = 1
    paths: PathsConfig = field(default_factory=PathsConfig)
    tests: TestsConfig = field(default_factory=TestsConfig)
    reply: ReplyConfig = field(default_factory=ReplyConfig)
    docs: DocsConfig = field(default_factory=DocsConfig)
    limits: PlaybookLimits = field(default_factory=PlaybookLimits)
    approvers: tuple[str, ...] = ()
    approver_warnings: tuple[ApproverWarning, ...] = ()
    is_default: bool = False
    source_path: str | None = None
    sha256: str | None = None
    base_revision: str | None = None

    @property
    def default(self) -> bool:
        """Alias for is_default."""
        return self.is_default

    @property
    def has_approvers(self) -> bool:
        return bool(self.approvers)

    # Convenience properties for Trilha B backwards compatibility
    @property
    def paths_allowed(self) -> tuple[str, ...]:
        return self.paths.allowed

    @property
    def paths_forbidden(self) -> tuple[str, ...]:
        return self.paths.forbidden

    @property
    def tests_protected(self) -> tuple[str, ...]:
        return self.tests.protected

    @property
    def reply_tone(self) -> ReplyTone:
        return self.reply.tone

    @property
    def reply_max_chars(self) -> int:
        return self.reply.max_chars

    @property
    def changelog_path(self) -> str:
        return self.docs.changelog_path

    @property
    def technical_notes_dir(self) -> str:
        return self.docs.technical_notes_dir

    @property
    def kb_drafts_dir(self) -> str:
        return self.docs.kb_drafts_dir

    def is_path_allowed(self, path: str) -> bool:
        """Return True if path matches paths.allowed and is not in paths.forbidden."""
        if self.is_path_forbidden(path):
            return False
        return _matches_any_glob(path, self.paths.allowed)

    def is_path_forbidden(self, path: str) -> bool:
        """Return True if path matches paths.forbidden or is internal resolveqa configuration."""
        norm = posixpath.normpath(path.strip().replace("\\", "/")).lstrip("./")
        if norm == ".resolveqa/playbook.toml" or norm.startswith(".resolveqa/"):
            return True
        return _matches_any_glob(path, self.paths.forbidden)

    def is_test_protected(self, path: str) -> bool:
        """Return True if path matches any protected test pattern."""
        norm = posixpath.normpath(path.strip().replace("\\", "/")).lstrip("./")
        if norm == ".resolveqa/playbook.toml" or norm.startswith(".resolveqa/"):
            return True
        return _matches_any_glob(path, self.tests.protected)

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "paths": self.paths.to_dict(),
            "tests": self.tests.to_dict(),
            "approvers": list(self.approvers),
            "reply": self.reply.to_dict(),
            "docs": self.docs.to_dict(),
            "limits": self.limits.to_dict(),
            "is_default": self.is_default,
            "sha256": self.sha256,
        }

    @classmethod
    def create_default(
        cls,
        source_path: str | None = None,
        base_revision: str | None = None,
    ) -> Playbook:
        """Return default playbook policy marked as default."""
        return cls(
            version=1,
            paths=PathsConfig(),
            tests=TestsConfig(),
            reply=ReplyConfig(),
            docs=DocsConfig(),
            limits=PlaybookLimits(),
            approvers=(),
            approver_warnings=(),
            is_default=True,
            source_path=source_path,
            sha256=None,
            base_revision=base_revision,
        )

    @classmethod
    def default_policy(
        cls,
        source_path: str | None = None,
        base_revision: str | None = None,
    ) -> Playbook:
        return cls.create_default(source_path=source_path, base_revision=base_revision)

