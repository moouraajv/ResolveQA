"""Playbook gate for patch verification and verdict policy compliance.

Issue #23 (Track A — RFC-0001 §3.3, §5, §6.2, §8, PRD RF-05, RF-06, RNF-03, RNF-05).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
import posixpath
import re
from typing import Any, Sequence

from resolveqa.contracts import Patch, Verdict
from resolveqa.playbook import (
    Playbook,
    PlaybookError,
    PlaybookSyntaxError,
    load_playbook_from_base,
)

_DIFF_HEADER_RE = re.compile(r"^(?:---|\+\+\+)\s+(.+)$")
_HUNK_HEADER_RE = re.compile(r"^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@")


@dataclass(frozen=True)
class PolicyRuleResult:
    """Records the outcome of evaluating a specific playbook rule category."""

    rule_name: str
    passed: bool
    detail: str
    playbook_sha256: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_name": self.rule_name,
            "passed": self.passed,
            "detail": self.detail,
            "playbook_sha256": self.playbook_sha256,
        }


def _normalize_posix_path(raw: str) -> str:
    cleaned = raw.strip().replace("\\", "/")
    norm = posixpath.normpath(cleaned)
    if norm.startswith("./"):
        norm = norm[2:]
    return norm


def _strip_diff_prefix(raw: str) -> str:
    cleaned = raw.strip()
    if cleaned == "/dev/null":
        return "/dev/null"
    if cleaned.startswith('"') and cleaned.endswith('"') and len(cleaned) >= 2:
        cleaned = cleaned[1:-1]
    cleaned = cleaned.split("\t")[0].strip()
    if cleaned.startswith("a/") or cleaned.startswith("b/"):
        cleaned = cleaned[2:]
    return _normalize_posix_path(cleaned)


def extract_diff_target_paths(diff_text: str) -> list[str]:
    """Extract destination file paths touched by a unified diff or JSON patch.

    Returns normalized relative POSIX paths.
    """
    cleaned = diff_text.strip()
    if not cleaned:
        return []

    # 1. JSON patch mapping: {"path": "content"}
    if cleaned.startswith("{") and cleaned.endswith("}"):
        try:
            data = json.loads(cleaned)
            if isinstance(data, dict):
                paths: list[str] = []
                for k in data.keys():
                    norm = _normalize_posix_path(str(k))
                    if norm and norm != ".":
                        paths.append(norm)
                return paths
        except Exception:
            pass

    # 2. Unified diff format
    lines = cleaned.splitlines()
    touched: list[str] = []
    idx = 0
    while idx < len(lines):
        line = lines[idx]
        if line.startswith("--- "):
            old_raw = line[4:].strip()
            idx += 1
            if idx < len(lines) and lines[idx].startswith("+++ "):
                new_raw = lines[idx][4:].strip()
                old_p = _strip_diff_prefix(old_raw)
                new_p = _strip_diff_prefix(new_raw)
                target = new_p if new_p != "/dev/null" else old_p
                if target and target != "/dev/null" and target != ".":
                    touched.append(target)
        idx += 1

    return list(dict.fromkeys(touched))


@dataclass(frozen=True)
class PlaybookGateResult:
    """Outcome of playbook gate evaluation."""

    passed: bool
    reasons: tuple[str, ...]
    playbook: Playbook
    playbook_sha256: str | None
    policy_rules: tuple[PolicyRuleResult, ...]
    effective_max_files: int
    effective_timeout_s: float
    is_invalid_playbook: bool = False

    def annotate_verdict(self, verdict: Verdict) -> Verdict:
        """Attach playbook policy metadata to a Verdict instance."""
        object.__setattr__(verdict, "playbook_sha256", self.playbook_sha256)
        object.__setattr__(verdict, "policy_rules", self.policy_rules)
        object.__setattr__(
            verdict,
            "policy_rule",
            self.policy_rules[0] if self.policy_rules else None,
        )
        object.__setattr__(verdict, "playbook", self.playbook)
        return verdict

    def check_touched_files(self, touched_files: Sequence[str]) -> tuple[str, ...]:
        """Post-patch verification check for actual modified files."""
        playbook = self.playbook
        reasons: list[str] = []

        if len(touched_files) > self.effective_max_files:
            reasons.append(
                f"patch_rejected: diff touched {len(touched_files)} files, exceeding playbook max_files_changed ({self.effective_max_files})"
            )

        for raw_f in touched_files:
            norm = _normalize_posix_path(str(raw_f))
            if norm == ".resolveqa/playbook.toml" or norm.startswith(".resolveqa/"):
                reasons.append(f"patch_rejected: diff touches protected playbook '{norm}'")
                continue
            if playbook.is_path_forbidden(norm):
                reasons.append(f"patch_rejected: diff touches forbidden path '{norm}' (playbook)")
            if not playbook.is_path_allowed(norm):
                reasons.append(f"patch_rejected: diff touches path '{norm}' not in allowed paths (playbook)")
            if playbook.is_test_protected(norm):
                reasons.append(f"patch_rejected: diff touches protected test '{norm}' (playbook)")

        return tuple(dict.fromkeys(reasons))


class PlaybookGate:
    """Deterministic policy gate enforcing project playbook rules in Verification."""

    def __init__(
        self,
        playbook: Playbook | None = None,
        default_max_files: int = 3,
        default_timeout_s: float = 600.0,
    ) -> None:
        self.preset_playbook = playbook
        self.default_max_files = default_max_files
        self.default_timeout_s = default_timeout_s

    def resolve_playbook(
        self,
        source_repo_dir: Path | str,
        base_revision: str | None = None,
    ) -> tuple[Playbook, str | None, str | None]:
        """Load or retrieve the target project playbook.

        Returns:
            (playbook, sha256, error_reason)
        """
        if self.preset_playbook is not None:
            return self.preset_playbook, self.preset_playbook.sha256, None

        target_dir = Path(source_repo_dir).resolve()
        try:
            pb, sha = load_playbook_from_base(target_dir, base_revision=base_revision)
            return pb, sha, None
        except (PlaybookSyntaxError, PlaybookError) as exc:
            return Playbook.create_default(), None, f"playbook_invalid: {exc}"
        except Exception as exc:
            return Playbook.create_default(), None, f"playbook_invalid: could not load playbook ({exc})"

    def evaluate_patch(
        self,
        source_repo_dir: Path | str,
        patch: Patch,
        base_revision: str | None = None,
    ) -> PlaybookGateResult:
        """Statically evaluate patch candidate against project playbook before applying changes."""
        repo_dir = Path(source_repo_dir).resolve()
        playbook, sha256, load_err = self.resolve_playbook(repo_dir, base_revision=base_revision)

        if load_err is not None:
            rule = PolicyRuleResult(
                rule_name="playbook_validity",
                passed=False,
                detail=load_err,
                playbook_sha256=sha256,
            )
            return PlaybookGateResult(
                passed=False,
                reasons=(f"patch_rejected: {load_err}", load_err),
                playbook=playbook,
                playbook_sha256=sha256,
                policy_rules=(rule,),
                effective_max_files=self.default_max_files,
                effective_timeout_s=self.default_timeout_s,
                is_invalid_playbook=True,
            )

        # Apply playbook limits if stricter than defaults
        effective_max_files = min(self.default_max_files, playbook.limits.max_files_changed)
        effective_timeout_s = min(self.default_timeout_s, playbook.limits.test_timeout_s)

        reasons: list[str] = []
        rules: list[PolicyRuleResult] = []

        # 1. Check declared files count
        declared_paths = [
            _normalize_posix_path(f)
            for f in patch.files_changed
            if f and f.strip()
        ]
        if len(declared_paths) > effective_max_files:
            msg = f"patch_rejected: files_changed ({len(declared_paths)}) exceeds playbook max_files_changed ({effective_max_files})"
            reasons.append(msg)
            rules.append(PolicyRuleResult("limits_max_files", False, msg, sha256))
        else:
            rules.append(
                PolicyRuleResult(
                    "limits_max_files",
                    True,
                    f"files_changed within limit ({effective_max_files})",
                    sha256,
                )
            )

        # 2. Extract and inspect paths from diff
        diff_paths = extract_diff_target_paths(patch.diff_ref)
        all_candidate_paths = list(dict.fromkeys(declared_paths + diff_paths))

        if len(all_candidate_paths) > effective_max_files:
            msg = f"patch_rejected: diff touches {len(all_candidate_paths)} files, exceeding playbook max_files_changed ({effective_max_files})"
            if msg not in reasons:
                reasons.append(msg)

        # 3. Path rules: forbidden, allowed, tests protected, playbook file protection
        forbidden_hits: list[str] = []
        not_allowed_hits: list[str] = []
        protected_test_hits: list[str] = []
        playbook_modified: bool = False

        for cand in all_candidate_paths:
            # Check for directory traversal / escape attempts
            if cand.startswith("/") or cand.startswith("..") or "/../" in cand or cand == "..":
                reasons.append(f"patch_rejected: path escapes target workspace: '{cand}'")
                continue

            # Protection of .resolveqa/playbook.toml and .resolveqa/**
            if cand == ".resolveqa/playbook.toml" or cand.startswith(".resolveqa/"):
                playbook_modified = True
                reasons.append(f"patch_rejected: diff touches protected playbook '{cand}'")
                continue

            # Check if existing file is a symlink resolving to protected or forbidden target
            symlink_target_rel: str | None = None
            cand_abs = (repo_dir / cand).resolve()
            if not cand_abs.is_relative_to(repo_dir):
                reasons.append(f"patch_rejected: diff path escapes target directory: '{cand}'")
                continue
            if cand_abs.exists():
                symlink_target_rel = cand_abs.relative_to(repo_dir).as_posix()

            check_paths = [cand]
            if symlink_target_rel and symlink_target_rel != cand:
                check_paths.append(symlink_target_rel)

            for p in check_paths:
                if playbook.is_path_forbidden(p):
                    forbidden_hits.append(p)
                    reasons.append(f"patch_rejected: diff touches forbidden path '{p}' (playbook)")
                if not playbook.is_path_allowed(p):
                    not_allowed_hits.append(p)
                    reasons.append(f"patch_rejected: diff touches path '{p}' not in allowed paths (playbook)")
                if playbook.is_test_protected(p):
                    protected_test_hits.append(p)
                    reasons.append(f"patch_rejected: diff touches protected test '{p}' (playbook)")

        rules.append(
            PolicyRuleResult(
                rule_name="paths_forbidden",
                passed=len(forbidden_hits) == 0,
                detail=(
                    "no forbidden paths touched"
                    if not forbidden_hits
                    else f"forbidden paths touched: {forbidden_hits}"
                ),
                playbook_sha256=sha256,
            )
        )
        rules.append(
            PolicyRuleResult(
                rule_name="paths_allowed",
                passed=len(not_allowed_hits) == 0,
                detail=(
                    "all paths within allowed scope"
                    if not not_allowed_hits
                    else f"unallowed paths touched: {not_allowed_hits}"
                ),
                playbook_sha256=sha256,
            )
        )
        rules.append(
            PolicyRuleResult(
                rule_name="tests_protected",
                passed=len(protected_test_hits) == 0 and not playbook_modified,
                detail=(
                    "protected tests and playbook intact"
                    if not protected_test_hits and not playbook_modified
                    else "protected tests or playbook touched"
                ),
                playbook_sha256=sha256,
            )
        )

        deduped_reasons = tuple(dict.fromkeys(reasons))
        passed = len(deduped_reasons) == 0

        # General summary rule
        summary_rule = PolicyRuleResult(
            rule_name="playbook_policy",
            passed=passed,
            detail=(
                "all playbook policy rules passed"
                if passed
                else f"policy violations: {len(deduped_reasons)}"
            ),
            playbook_sha256=sha256,
        )
        all_rules = (summary_rule, *rules)

        return PlaybookGateResult(
            passed=passed,
            reasons=deduped_reasons,
            playbook=playbook,
            playbook_sha256=sha256,
            policy_rules=all_rules,
            effective_max_files=effective_max_files,
            effective_timeout_s=effective_timeout_s,
            is_invalid_playbook=False,
        )

    def check_touched_files(
        self,
        touched_files: Sequence[str],
        gate_result: PlaybookGateResult,
    ) -> tuple[str, ...]:
        """Post-patch verification check for actual modified files."""
        playbook = gate_result.playbook
        reasons: list[str] = []

        if len(touched_files) > gate_result.effective_max_files:
            reasons.append(
                f"patch_rejected: diff touched {len(touched_files)} files, exceeding playbook max_files_changed ({gate_result.effective_max_files})"
            )

        for raw_f in touched_files:
            norm = _normalize_posix_path(str(raw_f))
            if norm == ".resolveqa/playbook.toml" or norm.startswith(".resolveqa/"):
                reasons.append(f"patch_rejected: diff touches protected playbook '{norm}'")
                continue
            if playbook.is_path_forbidden(norm):
                reasons.append(f"patch_rejected: diff touches forbidden path '{norm}' (playbook)")
            if not playbook.is_path_allowed(norm):
                reasons.append(f"patch_rejected: diff touches path '{norm}' not in allowed paths (playbook)")
            if playbook.is_test_protected(norm):
                reasons.append(f"patch_rejected: diff touches protected test '{norm}' (playbook)")

        return tuple(dict.fromkeys(reasons))


def evaluate_playbook_gate(
    source_repo_dir: Path | str,
    patch: Patch,
    playbook: Playbook | None = None,
    default_max_files: int = 3,
    default_timeout_s: float = 600.0,
    base_revision: str | None = None,
) -> PlaybookGateResult:
    """Helper to evaluate patch against playbook in a single call."""
    gate = PlaybookGate(
        playbook=playbook,
        default_max_files=default_max_files,
        default_timeout_s=default_timeout_s,
    )
    return gate.evaluate_patch(source_repo_dir, patch, base_revision=base_revision)
