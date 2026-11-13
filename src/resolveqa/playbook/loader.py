"""Project playbook loader and schema validator (.resolveqa/playbook.toml).

Issue #22 (Track A — RFC-0001 §3.3, §5, §6, §8, PRD RF-05, RF-06, RNF-03).
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
import posixpath
import re
import tempfile
import tomllib
from pathlib import Path
from typing import Any

_TOML_LOC_RE = re.compile(r"\(at line (\d+), column (\d+)\)")

from .schema import (
    BASELINE_LIMITS,
    DEFAULT_FORBIDDEN_PATHS,
    DEFAULT_PROTECTED_TESTS,
    ApproverWarning,
    DocsConfig,
    PathsConfig,
    Playbook,
    PlaybookError,
    PlaybookLimits,
    PlaybookSyntaxError,
    ReplyConfig,
    ReplyTone,
    TestsConfig,
)

ALLOWED_ROOT_KEYS = frozenset(
    {"version", "paths", "tests", "approvers", "reply", "docs", "limits"}
)
ALLOWED_PATHS_KEYS = frozenset({"allowed", "forbidden"})
ALLOWED_TESTS_KEYS = frozenset({"protected"})
ALLOWED_REPLY_KEYS = frozenset({"tone", "max_chars"})
ALLOWED_DOCS_KEYS = frozenset({"changelog_path", "technical_notes_dir", "kb_drafts_dir"})
ALLOWED_LIMITS_KEYS = frozenset(
    {"max_fix_attempts", "max_llm_calls", "test_timeout_s", "max_files_changed", "max_output_bytes"}
)

_DRIVE_LETTER_RE = re.compile(r"^[a-zA-Z]:")


def validate_glob_pattern(pattern: Any, field_name: str) -> str:
    """Validate that pattern is a valid relative POSIX glob, rejecting traversal and syntax errors."""
    if not isinstance(pattern, str) or not pattern.strip():
        raise PlaybookError(
            f"Field '{field_name}' must contain non-empty string patterns, got {pattern!r}",
            field=field_name,
        )
    norm = pattern.strip().replace("\\", "/")
    if norm.startswith("/") or _DRIVE_LETTER_RE.match(norm):
        raise PlaybookError(
            f"Invalid glob pattern in '{field_name}': absolute paths are forbidden: '{pattern}'",
            field=field_name,
        )
    parts = norm.split("/")
    if any(p == ".." for p in parts):
        raise PlaybookError(
            f"Invalid glob pattern in '{field_name}': '..' parent traversal is forbidden: '{pattern}'",
            field=field_name,
        )
    if norm.count("[") != norm.count("]"):
        raise PlaybookError(
            f"Invalid glob pattern in '{field_name}': unclosed brackets in '{pattern}'",
            field=field_name,
        )
    try:
        re.compile(fnmatch.translate(norm))
    except Exception as err:
        raise PlaybookError(
            f"Invalid glob pattern in '{field_name}': '{pattern}' ({err})",
            field=field_name,
        ) from err

    return norm


def _validate_approver(raw: object) -> tuple[str | None, ApproverWarning | None]:
    if not isinstance(raw, str) or not raw.strip():
        return None, ApproverWarning(
            approver=repr(raw),
            detail="approver must be a non-empty string; ignored for review request",
        )
    name = raw.strip()
    # Heuristic: entries starting with '!' are flagged with warning
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


def _validate_table_keys(
    table: dict[str, Any],
    allowed_keys: frozenset[str],
    section_name: str,
) -> None:
    for key in table:
        if key not in allowed_keys:
            full_field = f"{section_name}.{key}" if section_name else str(key)
            raise PlaybookError(
                f"Unknown key '{key}' in section '{section_name}'",
                field=full_field,
            )


def parse_playbook_dict(
    data: Any,
    source_path: str | None = None,
    sha256: str | None = None,
    base_revision: str | None = None,
) -> Playbook:
    """Validate playbook dictionary and build an immutable Playbook model."""
    if not isinstance(data, dict):
        raise PlaybookError("Playbook root must be a table/object", field="root")

    _validate_table_keys(data, ALLOWED_ROOT_KEYS, "")

    # 1. version
    raw_version = data.get("version", 1)
    if isinstance(raw_version, bool) or not isinstance(raw_version, int):
        raise PlaybookError(
            f"Field 'version' must be an integer, got {type(raw_version).__name__}",
            field="version",
        )
    version = raw_version
    if version < 1:
        raise PlaybookError("Field 'version' must be >= 1", field="version")

    # 2. paths
    paths_data = data.get("paths", {})
    if paths_data is None:
        paths_data = {}
    if not isinstance(paths_data, dict):
        raise PlaybookError("Field 'paths' must be a table", field="paths")
    _validate_table_keys(paths_data, ALLOWED_PATHS_KEYS, "paths")

    allowed_list = paths_data.get("allowed", ["**"])
    if not isinstance(allowed_list, (list, tuple)):
        raise PlaybookError("Field 'paths.allowed' must be a list of strings", field="paths.allowed")
    validated_allowed = tuple(validate_glob_pattern(item, "paths.allowed") for item in allowed_list)

    # Check that paths.allowed does not attempt to unprotect .resolveqa
    for pat in validated_allowed:
        if pat == ".resolveqa/playbook.toml" or pat.startswith((".resolveqa/", ".resolveqa/**")):
            raise PlaybookError(
                f"Field 'paths.allowed' cannot allow protected playbook configuration: '{pat}'",
                field="paths.allowed",
            )

    forbidden_list = paths_data.get("forbidden", [])
    if not isinstance(forbidden_list, (list, tuple)):
        raise PlaybookError("Field 'paths.forbidden' must be a list of strings", field="paths.forbidden")
    validated_forbidden = tuple(validate_glob_pattern(item, "paths.forbidden") for item in forbidden_list)

    # .resolveqa/playbook.toml is always forbidden for patches
    combined_forbidden = tuple(
        dict.fromkeys(DEFAULT_FORBIDDEN_PATHS + validated_forbidden)
    )
    paths_cfg = PathsConfig(allowed=validated_allowed, forbidden=combined_forbidden)

    # 3. tests
    tests_data = data.get("tests", {})
    if tests_data is None:
        tests_data = {}
    if not isinstance(tests_data, dict):
        raise PlaybookError("Field 'tests' must be a table", field="tests")
    _validate_table_keys(tests_data, ALLOWED_TESTS_KEYS, "tests")

    user_protected = tests_data.get("protected", [])
    if not isinstance(user_protected, (list, tuple)):
        raise PlaybookError("Field 'tests.protected' must be a list of strings", field="tests.protected")
    validated_protected = tuple(validate_glob_pattern(item, "tests.protected") for item in user_protected)

    # tests.protected only adds to default protected tests, never removes any
    combined_protected = tuple(
        dict.fromkeys(DEFAULT_PROTECTED_TESTS + validated_protected)
    )
    tests_cfg = TestsConfig(protected=combined_protected)

    # 4. approvers
    approvers_data = data.get("approvers", [])
    if approvers_data is None:
        approvers_data = []
    if not isinstance(approvers_data, (list, tuple)):
        raise PlaybookError("Field 'approvers' must be a list of strings", field="approvers")

    approvers: list[str] = []
    warnings: list[ApproverWarning] = []
    for item in approvers_data:
        name, warning = _validate_approver(item)
        if warning is not None:
            warnings.append(warning)
        if name is not None:
            approvers.append(name)

    # 5. reply
    reply_data = data.get("reply", {})
    if reply_data is None:
        reply_data = {}
    if not isinstance(reply_data, dict):
        raise PlaybookError("Field 'reply' must be a table", field="reply")
    _validate_table_keys(reply_data, ALLOWED_REPLY_KEYS, "reply")

    tone_raw = reply_data.get("tone", ReplyTone.NEUTRAL.value)
    try:
        reply_tone = ReplyTone(str(tone_raw).lower())
    except ValueError as err:
        allowed_tones = [t.value for t in ReplyTone]
        raise PlaybookError(
            f"Field 'reply.tone' must be one of {allowed_tones}, got {tone_raw!r}",
            field="reply.tone",
        ) from err

    max_chars = reply_data.get("max_chars", 500)
    if isinstance(max_chars, bool) or not isinstance(max_chars, int) or max_chars <= 0:
        raise PlaybookError(
            f"Field 'reply.max_chars' must be a positive integer, got {max_chars!r}",
            field="reply.max_chars",
        )
    reply_cfg = ReplyConfig(tone=reply_tone, max_chars=max_chars)

    # 6. docs
    docs_data = data.get("docs", {})
    if docs_data is None:
        docs_data = {}
    if not isinstance(docs_data, dict):
        raise PlaybookError("Field 'docs' must be a table", field="docs")
    _validate_table_keys(docs_data, ALLOWED_DOCS_KEYS, "docs")

    def _doc_path(key: str, default: str) -> str:
        value = docs_data.get(key, default)
        field_name = f"docs.{key}"
        if not isinstance(value, str) or not value.strip():
            raise PlaybookError(f"Field '{field_name}' must be a non-empty string", field=field_name)
        text = value.strip().replace("\\", "/")
        if text.startswith("/") or _DRIVE_LETTER_RE.match(text) or any(seg == ".." for seg in text.split("/")):
            raise PlaybookError(
                f"Field '{field_name}' must be a relative path without '..'",
                field=field_name,
            )
        return text

    docs_cfg = DocsConfig(
        changelog_path=_doc_path("changelog_path", "CHANGELOG.md"),
        technical_notes_dir=_doc_path("technical_notes_dir", "technical_notes"),
        kb_drafts_dir=_doc_path("kb_drafts_dir", "kb_drafts"),
    )

    # 7. limits (optional, must be at least as strict as RNF-03)
    limits_data = data.get("limits")
    if limits_data is not None:
        if not isinstance(limits_data, dict):
            raise PlaybookError("Field 'limits' must be a table", field="limits")
        _validate_table_keys(limits_data, ALLOWED_LIMITS_KEYS, "limits")

        fix_attempts = limits_data.get("max_fix_attempts", BASELINE_LIMITS["max_fix_attempts"])
        if isinstance(fix_attempts, bool) or not isinstance(fix_attempts, int):
            raise PlaybookError("Field 'limits.max_fix_attempts' must be an integer", field="limits.max_fix_attempts")
        if fix_attempts > BASELINE_LIMITS["max_fix_attempts"] or fix_attempts < 1:
            raise PlaybookError(
                f"Field 'limits.max_fix_attempts' ({fix_attempts}) cannot be looser than RNF-03 baseline ({BASELINE_LIMITS['max_fix_attempts']})",
                field="limits.max_fix_attempts",
            )

        llm_calls = limits_data.get("max_llm_calls", BASELINE_LIMITS["max_llm_calls"])
        if isinstance(llm_calls, bool) or not isinstance(llm_calls, int):
            raise PlaybookError("Field 'limits.max_llm_calls' must be an integer", field="limits.max_llm_calls")
        if llm_calls > BASELINE_LIMITS["max_llm_calls"] or llm_calls < 1:
            raise PlaybookError(
                f"Field 'limits.max_llm_calls' ({llm_calls}) cannot be looser than RNF-03 baseline ({BASELINE_LIMITS['max_llm_calls']})",
                field="limits.max_llm_calls",
            )

        timeout_s = limits_data.get("test_timeout_s", BASELINE_LIMITS["test_timeout_s"])
        if isinstance(timeout_s, bool) or not isinstance(timeout_s, (int, float)):
            raise PlaybookError("Field 'limits.test_timeout_s' must be numeric", field="limits.test_timeout_s")
        timeout_float = float(timeout_s)
        if timeout_float > BASELINE_LIMITS["test_timeout_s"] or timeout_float <= 0:
            raise PlaybookError(
                f"Field 'limits.test_timeout_s' ({timeout_s}) cannot be looser than RNF-03 baseline ({BASELINE_LIMITS['test_timeout_s']})",
                field="limits.test_timeout_s",
            )

        files_changed = limits_data.get("max_files_changed", BASELINE_LIMITS["max_files_changed"])
        if isinstance(files_changed, bool) or not isinstance(files_changed, int):
            raise PlaybookError("Field 'limits.max_files_changed' must be an integer", field="limits.max_files_changed")
        if files_changed > BASELINE_LIMITS["max_files_changed"] or files_changed < 1:
            raise PlaybookError(
                f"Field 'limits.max_files_changed' ({files_changed}) cannot be looser than RNF-03 baseline ({BASELINE_LIMITS['max_files_changed']})",
                field="limits.max_files_changed",
            )

        max_out = limits_data.get("max_output_bytes", BASELINE_LIMITS["max_output_bytes"])
        if isinstance(max_out, bool) or not isinstance(max_out, int):
            raise PlaybookError("Field 'limits.max_output_bytes' must be an integer", field="limits.max_output_bytes")
        if max_out > BASELINE_LIMITS["max_output_bytes"] or max_out <= 0:
            raise PlaybookError(
                f"Field 'limits.max_output_bytes' ({max_out}) cannot be looser than baseline ({BASELINE_LIMITS['max_output_bytes']})",
                field="limits.max_output_bytes",
            )

        limits_cfg = PlaybookLimits(
            max_fix_attempts=fix_attempts,
            max_llm_calls=llm_calls,
            test_timeout_s=timeout_float,
            max_files_changed=files_changed,
            max_output_bytes=max_out,
        )
    else:
        limits_cfg = PlaybookLimits()

    return Playbook(
        version=version,
        paths=paths_cfg,
        tests=tests_cfg,
        reply=reply_cfg,
        docs=docs_cfg,
        limits=limits_cfg,
        approvers=tuple(approvers),
        approver_warnings=tuple(warnings),
        is_default=False,
        source_path=source_path,
        sha256=sha256,
        base_revision=base_revision,
    )


def parse_playbook_toml(
    content: str | bytes,
    source_path: str | None = None,
    sha256: str | None = None,
    base_revision: str | None = None,
) -> Playbook:
    """Parse TOML string or bytes using tomllib and validate against playbook schema."""
    text = content.decode("utf-8") if isinstance(content, bytes) else content
    if sha256 is None:
        sha256 = hashlib.sha256(text.encode("utf-8")).hexdigest()

    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as err:
        # Python ≥3.12 exposes lineno/colno; 3.11 only embeds them in the message.
        line = getattr(err, "lineno", None)
        col = getattr(err, "colno", None)
        if line is None or col is None:
            match = _TOML_LOC_RE.search(str(err))
            if match:
                line = int(match.group(1))
                col = int(match.group(2))
        loc_msg = f"line {line}, column {col}" if line is not None and col is not None else str(err)
        raise PlaybookSyntaxError(
            f"Malformed TOML at {loc_msg}: {err}",
            line=line,
            column=col,
        ) from err

    return parse_playbook_dict(
        data,
        source_path=source_path,
        sha256=sha256,
        base_revision=base_revision,
    )


REPO_ROOT = Path(__file__).resolve().parents[3]


def _is_allowed_playbook_location(target_path: Path, repo_dir: Path | str | None = None) -> bool:
    """Return True if target_path resolves within target repository, config/, or temporary test directory."""
    try:
        resolved = target_path.resolve()
    except Exception:
        return False

    allowed_bases: list[Path] = [
        (REPO_ROOT / "config").resolve(),
        (Path.cwd() / "config").resolve(),
        REPO_ROOT.resolve(),
        Path.cwd().resolve(),
        Path(tempfile.gettempdir()).resolve(),
        Path("/tmp").resolve(),
    ]
    if repo_dir is not None:
        try:
            allowed_bases.append(Path(repo_dir).resolve())
        except Exception:
            pass

    for base in allowed_bases:
        try:
            if resolved.is_relative_to(base):
                return True
        except (ValueError, AttributeError):
            continue
    return False


def load_playbook_from_base(
    repo_dir: Path | str,
    base_revision: str | None = None,
) -> tuple[Playbook, str | None]:
    """Load playbook from target repository base_revision.

    Never reads from mutable Fix workspace.
    Returns (Playbook, sha256) where sha256 is recorded as evidence.
    If .resolveqa/playbook.toml is missing, returns default policy marked as default.
    """
    target_path = Path(repo_dir)
    if not _is_allowed_playbook_location(target_path):
        raise PlaybookError(f"Repository path {str(repo_dir)!r} must be within target repository or config/")

    repo_path = target_path.resolve()
    candidate = repo_path / ".resolveqa" / "playbook.toml"
    if not candidate.is_file():
        default_pb = Playbook.create_default(
            source_path=str(candidate),
            base_revision=base_revision,
        )
        return default_pb, None

    raw_bytes = candidate.read_bytes()
    sha256 = hashlib.sha256(raw_bytes).hexdigest()
    playbook = parse_playbook_toml(
        raw_bytes,
        source_path=str(candidate),
        sha256=sha256,
        base_revision=base_revision,
    )
    return playbook, sha256


def load_playbook(
    path: Path | str | None = None,
    repo_dir: Path | str | None = None,
) -> Playbook:
    """Load playbook from given path, file, or repository root.

    Restricted to target repository or config/.
    - path is None: returns default policy marked as default.
    - path is directory: searches for path/.resolveqa/playbook.toml; if absent, returns default.
    - path is file: loads TOML (or JSON for backwards compatibility).
    - missing file within allowed location: returns default policy marked as default.
    """
    if path is None:
        return Playbook.create_default()

    target_path = Path(path)
    if not _is_allowed_playbook_location(target_path, repo_dir):
        raise PlaybookError(f"Playbook path {str(path)!r} must be within target repository or config/")

    if target_path.is_dir():
        pb, _ = load_playbook_from_base(target_path)
        return pb

    if not target_path.is_file():
        # Check if caller passed a repo path or missing file path
        cand = target_path / ".resolveqa" / "playbook.toml"
        if cand.is_file():
            pb, _ = load_playbook_from_base(target_path)
            return pb
        return Playbook.create_default(source_path=str(target_path))

    raw_bytes = target_path.read_bytes()
    sha256 = hashlib.sha256(raw_bytes).hexdigest()

    # JSON compatibility mode for Trilha B
    if target_path.suffix.lower() == ".json":
        try:
            data = json.loads(raw_bytes.decode("utf-8"))
        except json.JSONDecodeError as err:
            raise PlaybookError(f"Invalid playbook JSON at {target_path}: {err}") from err
        return parse_playbook_dict(data, source_path=str(target_path), sha256=sha256)

    return parse_playbook_toml(raw_bytes, source_path=str(target_path), sha256=sha256)
