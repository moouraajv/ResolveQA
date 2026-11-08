"""Independent Verification stage and protected test oracle (Issue #12, RF-06, RFC-0001 §3.3)."""

from __future__ import annotations

import ast
import contextlib
import hashlib
import json
import os
import posixpath
import re
import shlex
import shutil
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from resolveqa.contracts import (
    ContractValidationError,
    ExecResult,
    Patch,
    ReproOutcome,
    ReproResult,
    RunState,
    SandboxStage,
    TestRun,
    Verdict,
    VerdictResult,
)
from resolveqa.contracts.validators import require_posix_relative_path
from resolveqa.sandbox import LocalSandbox

DEFAULT_MAX_FILES_CHANGED = 3
DEFAULT_TEST_TIMEOUT_S = 600.0

# Basenames (matched case-insensitively, at ANY directory level) that can alter how Python or the
# test runner starts, discovers plugins or configures itself. A patch must never touch them.
RUNNER_CONFIG_FILES = (
    "pyproject.toml",
    "pytest.ini",
    ".pytest.ini",
    "pytest.toml",
    ".pytest.toml",
    "setup.cfg",
    "setup.py",
    "tox.ini",
    "noxfile.py",
    "conftest.py",
    "unittest.cfg",
    ".unittest.cfg",
    "unittest.ini",
    "nose.cfg",
    ".noserc",
    "sitecustomize.py",
    "usercustomize.py",
    ".coveragerc",
)
VERIFIER_CONFIG_NAME = ".rqa_verifier_pytest.ini"
VERIFIER_PLUGIN_MODULE = "_rqa_verifier_plugin"
_PROTECTED_BASENAMES = frozenset(
    {*(name.lower() for name in RUNNER_CONFIG_FILES), VERIFIER_CONFIG_NAME, f"{VERIFIER_PLUGIN_MODULE}.py"}
)
_FORBIDDEN_NEW_SUFFIXES = (".py", ".pyw", ".pyc", ".pth", ".so", ".pyd")
_VALUE_TYPE_BASES = frozenset({"float", "str", "int", "Decimal", "bool", "bytes", "complex"})
_SPOOFING_DUNDERS = frozenset({"__eq__", "__ne__", "__hash__"})
_FORBIDDEN_CODE_RE = re.compile(
    r"pytest_|hookimpl|hookspec|conftest|__import__|importlib|\bexec\s*\(|\beval\s*\(|sys\.modules|\bbuiltins\b"
)

# Fixed verifier-owned runner configuration (never the patched workspace's own configuration).
_FIXED_PYTEST_INI = "[pytest]\nenable_assertion_pass_hook = true\n"

# Verifier-owned plugin loaded only for the `after` run: enforces the exact builtin type on equality checks.
_VERIFIER_PLUGIN_SOURCE = '''\
import unittest

_SCALARS = (bool, int, float, str, bytes)


def _rqa_check(first, second):
    if (isinstance(first, _SCALARS) or isinstance(second, _SCALARS)) and type(first) is not type(second):
        raise AssertionError(
            "RQA_TYPE_MISMATCH: %s != %s" % (type(first).__name__, type(second).__name__)
        )


def pytest_assertion_pass(item, lineno, orig, expl):
    return None


def pytest_configure(config):
    original_assert_equal = unittest.TestCase.assertEqual

    def assert_equal(self, first, second, msg=None):
        original_assert_equal(self, first, second, msg)
        _rqa_check(first, second)

    unittest.TestCase.assertEqual = assert_equal

    from _pytest.assertion import rewrite

    original_compare = rewrite._call_reprcompare

    def call_reprcompare(ops, results, expls, each_obj):
        out = original_compare(ops, results, expls, each_obj)
        for index, op in enumerate(ops):
            if op == "==" and results[index]:
                _rqa_check(each_obj[index], each_obj[index + 1])
        return out

    rewrite._call_reprcompare = call_reprcompare
'''

RESIDUAL_RISK_NOTE = (
    "residual_risk: value-type spoofing is only partially mitigated (no __eq__/__ne__/__hash__ or "
    "float/str/int/Decimal subclasses in the patch; exact type enforced on equality assertions). "
    "Human review of the patched code is still required."
)

CI_PATH_PREFIXES = (
    ".github/",
    ".circleci/",
    ".resolveqa/",
)

CI_EXACT_NAMES = frozenset(
    {
        *RUNNER_CONFIG_FILES,
        ".gitlab-ci.yml",
        ".gitlab-ci.yaml",
        "Jenkinsfile",
        ".travis.yml",
    }
)

_HUNK_HEADER_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
_PASSED_SUMMARY_RE = re.compile(r"\b([1-9]\d*)\s+passed\b|Ran\s+([1-9]\d*)\s+tests?.*?\bOK\b", re.DOTALL)
_SKIP_OR_XFAIL_SUMMARY_RE = re.compile(
    r"\b\d+\s+(?:skipped|xfailed|xpassed)\b|\b(?:SKIPPED|XFAIL|XPASS)\b|\bskipped=\d+|\bexpected failures=\d+",
    re.IGNORECASE,
)
_IMPORT_OR_COLLECTION_ERROR_PATTERNS = (
    "ImportError",
    "ModuleNotFoundError",
    "SyntaxError",
    "IndentationError",
    "ERROR collecting",
    "ERROR at setup",
    "collected 0 items",
    "no tests ran",
    "Ran 0 tests",
)
_SETUP_FAILURE_RE = re.compile(r"\bdef\s+(?:setUp|setUpClass|tearDown|tearDownClass)\s*\(")
_SKIP_DEC_OR_CALL_NAMES = frozenset(
    {
        "skip",
        "skipif",
        "skipIf",
        "skipUnless",
        "xfail",
        "expectedFailure",
        "skipTest",
        "SkipTest",
    }
)


def _discover_default_base_root() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "pyproject.toml").is_file() or (parent / ".git").exists():
            return parent
    return here.parents[3]


def _load_limits(base_root: Path) -> tuple[int, float]:
    limits_file = base_root / "config" / "limits.json"
    max_files = DEFAULT_MAX_FILES_CHANGED
    timeout_s = DEFAULT_TEST_TIMEOUT_S
    if limits_file.is_file():
        with contextlib.suppress(Exception):
            data = json.loads(limits_file.read_text(encoding="utf-8"))
            max_files = int(data.get("max_files_changed", DEFAULT_MAX_FILES_CHANGED))
            timeout_s = float(data.get("test_timeout_s", DEFAULT_TEST_TIMEOUT_S))
    return max_files, timeout_s


def compute_tree_revision(root_dir: Path) -> str:
    """Compute a deterministic SHA-256 revision digest over all regular files in `root_dir`."""
    hasher = hashlib.sha256()
    ignored_dirs = {".git", "__pycache__", ".pytest_cache", ".venv"}
    entries: list[tuple[str, Path]] = []
    for path in root_dir.rglob("*"):
        rel_parts = path.relative_to(root_dir).parts
        if any(part in ignored_dirs for part in rel_parts):
            continue
        if path.name.endswith(".pyc") or not path.is_file() or path.is_symlink():
            continue
        rel_posix = "/".join(rel_parts)
        entries.append((rel_posix, path))

    entries.sort(key=lambda item: item[0])
    for rel_posix, file_path in entries:
        content = file_path.read_bytes()
        file_sha = hashlib.sha256(content).hexdigest()
        hasher.update(f"{rel_posix}:{file_sha}\n".encode("utf-8"))
    return hasher.hexdigest()


def _is_test_path(rel_path: str, repro_test_path: str | None = None) -> bool:
    norm = posixpath.normpath(rel_path.strip("/"))
    if repro_test_path and norm == posixpath.normpath(repro_test_path.strip("/")):
        return True
    parts = norm.split("/")
    filename = parts[-1]
    if "tests" in parts or "test" in parts:
        return True
    if filename.startswith("test_") or filename.endswith("_test.py") or filename == "conftest.py":
        return True
    return False


def _is_protected_runner_file(rel_path: str) -> bool:
    base = posixpath.basename(posixpath.normpath(rel_path.strip("/"))).lower()
    return base in _PROTECTED_BASENAMES or base.endswith(".pth") or (
        base.startswith("pytest_") and base.endswith(".py")
    )


def _is_ci_or_runner_config_path(rel_path: str) -> bool:
    norm = posixpath.normpath(rel_path.strip("/"))
    if norm in CI_EXACT_NAMES or _is_protected_runner_file(norm):
        return True
    for prefix in CI_PATH_PREFIXES:
        if norm.startswith(prefix) or f"/{prefix}" in norm:
            return True
    return False


def _snapshot_runner_configs(workspace_dir: Path) -> dict[str, str]:
    """Hash every runner/interpreter configuration file at any directory level."""
    snapshot: dict[str, str] = {}
    for candidate in sorted(workspace_dir.rglob("*")):
        rel = candidate.relative_to(workspace_dir).as_posix()
        if not _is_protected_runner_file(rel):
            continue
        if candidate.is_file():
            snapshot[rel] = hashlib.sha256(candidate.read_bytes()).hexdigest()
    return snapshot


@dataclass(frozen=True)
class OracleAnalysis:
    """Static AST analysis of a reproduction test file."""

    valid_syntax: bool
    has_skip_or_xfail: bool
    test_count: int
    assertion_count: int
    has_trivial_assertion: bool
    assertion_signatures: tuple[str, ...]
    reasons: tuple[str, ...]


def _attr_or_name_tokens(node: ast.AST) -> list[str]:
    if isinstance(node, ast.Name):
        return [node.id]
    if isinstance(node, ast.Attribute):
        return _attr_or_name_tokens(node.value) + [node.attr]
    if isinstance(node, ast.Call):
        return _attr_or_name_tokens(node.func)
    return []


def _is_trivial_expr(expr: ast.AST) -> bool:
    """Return True if an assertion expression is constant truthy or compares identical subtrees."""
    if isinstance(expr, ast.Constant):
        return bool(expr.value) is True or bool(expr.value)
    if isinstance(expr, ast.UnaryOp) and isinstance(expr.op, ast.Not):
        if isinstance(expr.operand, ast.Constant) and not bool(expr.operand.value):
            return True
    if isinstance(expr, ast.Compare) and len(expr.ops) == 1 and len(expr.comparators) == 1:
        op = expr.ops[0]
        left_dump = ast.dump(expr.left)
        right_dump = ast.dump(expr.comparators[0])
        if isinstance(op, (ast.Eq, ast.Is, ast.GtE, ast.LtE)) and left_dump == right_dump:
            return True
    return False


def inspect_test_oracle(source_text: str) -> OracleAnalysis:
    """Inspect reproduction test source code for skip/xfail markers and assertion integrity."""
    try:
        tree = ast.parse(source_text)
    except SyntaxError as exc:
        return OracleAnalysis(
            valid_syntax=False,
            has_skip_or_xfail=False,
            test_count=0,
            assertion_count=0,
            has_trivial_assertion=False,
            assertion_signatures=(),
            reasons=(f"test_invalid (infra_error): syntax error in reproduction test at line {exc.lineno}",),
        )

    reasons: list[str] = []
    has_skip_or_xfail = False

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            for dec in node.decorator_list:
                tokens = _attr_or_name_tokens(dec)
                if any(tok in _SKIP_DEC_OR_CALL_NAMES for tok in tokens):
                    has_skip_or_xfail = True
                    reasons.append(
                        f"test_skipped_or_xfail: decorator {'.'.join(tokens)} on {node.name} is forbidden"
                    )
        elif isinstance(node, ast.Call):
            tokens = _attr_or_name_tokens(node.func)
            if any(tok in _SKIP_DEC_OR_CALL_NAMES for tok in tokens):
                has_skip_or_xfail = True
                reasons.append(f"test_skipped_or_xfail: call to {'.'.join(tokens)} is forbidden")

    test_funcs = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_")
    ]

    if not test_funcs:
        reasons.append("test_invalid (infra_error): reproduction test contains no test_* functions")

    total_assertions = 0
    has_trivial = False
    signatures: list[str] = []

    for func in test_funcs:
        func_assertions = 0
        strong_assertions = 0
        for child in ast.walk(func):
            if isinstance(child, ast.Assert):
                func_assertions += 1
                signatures.append(ast.dump(child.test))
                if _is_trivial_expr(child.test):
                    has_trivial = True
                    reasons.append(
                        f"assertion_weakened: trivial/tautological assert statement in {func.name}"
                    )
                elif isinstance(child.test, ast.Compare) and all(
                    isinstance(op, (ast.IsNot, ast.Is)) for op in child.test.ops
                ) and any(
                    isinstance(comp, ast.Constant) and comp.value is None
                    for comp in child.test.comparators
                ):
                    # `assert x is not None` alone is a weak existence check
                    pass
                elif (
                    isinstance(child.test, ast.Call)
                    and _attr_or_name_tokens(child.test.func)[-1:] == ["isinstance"]
                ):
                    pass
                else:
                    strong_assertions += 1
            elif isinstance(child, ast.Call):
                tokens = _attr_or_name_tokens(child.func)
                if not tokens:
                    continue
                last = tokens[-1]
                if last.startswith("assert") or (tokens[-2:] == ["pytest", "raises"]):
                    func_assertions += 1
                    signatures.append(ast.dump(child))
                    if last in {"assertTrue", "assert_"} and child.args and _is_trivial_expr(child.args[0]):
                        has_trivial = True
                        reasons.append(
                            f"assertion_weakened: trivial {last} call in {func.name}"
                        )
                    elif last == "assertEqual" and len(child.args) >= 2:
                        if ast.dump(child.args[0]) == ast.dump(child.args[1]):
                            has_trivial = True
                            reasons.append(
                                f"assertion_weakened: tautological assertEqual in {func.name}"
                            )
                        else:
                            strong_assertions += 1
                    elif last in {"assertIsNotNone", "assertIsInstance"}:
                        pass
                    else:
                        strong_assertions += 1
        total_assertions += func_assertions
        if func_assertions == 0:
            reasons.append(
                f"assertion_removed: test function '{func.name}' contains no assertions"
            )
        elif strong_assertions == 0 and not has_trivial:
            has_trivial = True
            reasons.append(
                f"assertion_weakened: test function '{func.name}' only has weak existence/type checks without value assertion"
            )

    return OracleAnalysis(
        valid_syntax=True,
        has_skip_or_xfail=has_skip_or_xfail,
        test_count=len(test_funcs),
        assertion_count=total_assertions,
        has_trivial_assertion=has_trivial,
        assertion_signatures=tuple(signatures),
        reasons=tuple(dict.fromkeys(reasons)),
    )


def _strip_diff_prefix(raw_path: str) -> str:
    path_token = raw_path.split("\t", 1)[0].strip()
    if path_token == "/dev/null":
        return "/dev/null"
    if path_token.startswith(("a/", "b/")):
        path_token = path_token[2:]
    return require_posix_relative_path(path_token, "diff_path")


def _apply_hunks_to_lines(original_lines: list[str], hunks: list[tuple[int, list[str]]]) -> list[str]:
    result_lines = list(original_lines)
    offset = 0

    for orig_start, hunk_lines in hunks:
        expected_old: list[str] = []
        replacement_new: list[str] = []
        for raw_line in hunk_lines:
            if raw_line.startswith("\\"):
                continue
            prefix = raw_line[:1]
            body = raw_line[1:]
            if prefix == " ":
                expected_old.append(body)
                replacement_new.append(body)
            elif prefix == "-":
                expected_old.append(body)
            elif prefix == "+":
                replacement_new.append(body)
            else:
                raise ValueError(f"Unsupported unified diff hunk line: {raw_line!r}")

        target_idx = max(0, (orig_start - 1) + offset)
        old_len = len(expected_old)

        if old_len == 0:
            result_lines[target_idx:target_idx] = replacement_new
            offset += len(replacement_new)
            continue

        matched_idx: int | None = None
        if result_lines[target_idx : target_idx + old_len] == expected_old:
            matched_idx = target_idx
        else:
            # Search nearby lines in case of minor line number shift
            for delta in range(1, len(result_lines) + 1):
                for candidate in (target_idx - delta, target_idx + delta):
                    if 0 <= candidate <= len(result_lines) - old_len:
                        if result_lines[candidate : candidate + old_len] == expected_old:
                            matched_idx = candidate
                            break
                if matched_idx is not None:
                    break

        if matched_idx is None:
            raise ValueError(f"Unified diff hunk at line {orig_start} did not match target file content")

        result_lines[matched_idx : matched_idx + old_len] = replacement_new
        offset = (matched_idx - (orig_start - 1)) + (len(replacement_new) - old_len)

    return result_lines


def apply_unified_diff(target_dir: Path, diff_text: str) -> tuple[str, ...]:
    """Parse and apply a unified diff strictly inside `target_dir`, returning touched relative paths."""
    lines = diff_text.splitlines()
    idx = 0
    touched_files: list[str] = []

    while idx < len(lines):
        line = lines[idx]
        if not line.startswith("--- "):
            idx += 1
            continue

        old_raw = line[4:].strip()
        idx += 1
        if idx >= len(lines) or not lines[idx].startswith("+++ "):
            raise ValueError("Malformed unified diff: missing '+++ ' header after '--- '")
        new_raw = lines[idx][4:].strip()
        idx += 1

        old_path = _strip_diff_prefix(old_raw)
        new_path = _strip_diff_prefix(new_raw)

        hunks: list[tuple[int, list[str]]] = []
        while idx < len(lines) and not lines[idx].startswith("--- ") and not lines[idx].startswith("diff --git "):
            header_line = lines[idx]
            match = _HUNK_HEADER_RE.match(header_line)
            if not match:
                if not header_line.strip():
                    idx += 1
                    continue
                raise ValueError(f"Invalid unified diff hunk header: {header_line!r}")
            orig_start = int(match.group(1))
            idx += 1
            hunk_body: list[str] = []
            while idx < len(lines):
                cur = lines[idx]
                if (
                    cur.startswith("@@ ")
                    or cur.startswith("--- ")
                    or cur.startswith("diff --git ")
                ):
                    break
                if cur == "" and idx == len(lines) - 1:
                    idx += 1
                    break
                if cur == "":
                    # Treat bare empty line inside hunk as context empty line
                    hunk_body.append(" ")
                else:
                    hunk_body.append(cur)
                idx += 1
            hunks.append((orig_start, hunk_body))

        if new_path == "/dev/null":
            if old_path == "/dev/null":
                raise ValueError("Invalid diff with both old and new paths as /dev/null")
            file_to_delete = (target_dir / old_path).resolve()
            if not file_to_delete.is_relative_to(target_dir.resolve()):
                raise ValueError(f"Diff path escapes target_dir: {old_path}")
            if file_to_delete.exists():
                file_to_delete.unlink()
            touched_files.append(
                file_to_delete.relative_to(target_dir.resolve()).as_posix()
            )
        else:
            rel_target = new_path if new_path != "/dev/null" else old_path
            target_file = (target_dir / rel_target).resolve()
            if not target_file.is_relative_to(target_dir.resolve()):
                raise ValueError(f"Diff path escapes target_dir: {rel_target}")
            if old_path == "/dev/null" or not target_file.exists():
                orig_lines: list[str] = []
            else:
                orig_lines = target_file.read_text(encoding="utf-8").splitlines()
            updated_lines = _apply_hunks_to_lines(orig_lines, hunks)
            target_file.parent.mkdir(parents=True, exist_ok=True)
            trailing_nl = "\n" if updated_lines else ""
            target_file.write_text("\n".join(updated_lines) + trailing_nl, encoding="utf-8")
            touched_files.append(
                target_file.relative_to(target_dir.resolve()).as_posix()
            )

    if not touched_files:
        raise ValueError("Unified diff contained no applicable file changes")

    return tuple(dict.fromkeys(touched_files))


def _inspect_patched_code_for_subversion(
    after_dir: Path,
    touched_files: tuple[str, ...],
    repro_test_path: str,
) -> list[str]:
    """Detect if patched non-test code tries to invoke skip/xfail/os._exit or tamper with the test file/framework at runtime."""
    reasons: list[str] = []
    repro_basename = posixpath.basename(repro_test_path)
    forbidden_Test_framework_refs = {"unittest", "pytest", "TestCase", "assertEqual"}

    for rel_path in touched_files:
        if _is_test_path(rel_path, repro_test_path):
            continue
        candidate = after_dir / rel_path
        if not candidate.is_file() or not rel_path.endswith(".py"):
            continue
        with contextlib.suppress(Exception):
            source = candidate.read_text(encoding="utf-8")
            if repro_basename in source or repro_test_path in source:
                reasons.append(
                    f"test_modified: patched file '{rel_path}' references reproduction test '{repro_test_path}'"
                )
            tree = ast.parse(source)
            for node in ast.walk(tree):
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    mod_names = [alias.name.split(".")[0] for alias in node.names]
                    if isinstance(node, ast.ImportFrom) and node.module:
                        mod_names.append(node.module.split(".")[0])
                    if any(m in {"unittest", "pytest"} for m in mod_names):
                        reasons.append(
                            f"assertion_weakened: patched file '{rel_path}' imports test framework {mod_names}"
                        )
                elif isinstance(node, ast.Attribute) and node.attr in forbidden_Test_framework_refs:
                    reasons.append(
                        f"assertion_weakened: patched file '{rel_path}' accesses test framework attribute '{node.attr}'"
                    )
                elif isinstance(node, ast.Call):
                    tokens = _attr_or_name_tokens(node.func)
                    if any(tok in _SKIP_DEC_OR_CALL_NAMES for tok in tokens):
                        reasons.append(
                            f"test_skipped_or_xfail: patched file '{rel_path}' invokes {'.'.join(tokens)}"
                        )
                    elif tokens[-2:] in (["os", "_exit"], ["sys", "exit"]):
                        reasons.append(
                            f"patch_rejected: patched file '{rel_path}' calls {'.'.join(tokens)} to bypass test runner"
                        )
    return reasons


def _flagged_spoofing_nodes(source: str) -> dict[str, str]:
    """Return `{ast.dump: description}` for __eq__/__ne__/__hash__ definitions and value-type subclasses."""
    flagged: dict[str, str] = {}
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return flagged
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in _SPOOFING_DUNDERS:
            flagged[ast.dump(node)] = f"defines {node.name}"
        elif isinstance(node, ast.ClassDef):
            for base in node.bases:
                tokens = _attr_or_name_tokens(base)
                if tokens and tokens[-1] in _VALUE_TYPE_BASES:
                    flagged[ast.dump(node)] = f"class {node.name} subclasses {tokens[-1]}"
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name) and target.id in _SPOOFING_DUNDERS:
                    flagged[ast.dump(node)] = f"assigns {target.id}"
    return flagged


def _inspect_patch_hardening(
    before_dir: Path,
    after_dir: Path,
    touched_files: tuple[str, ...],
    repro_test_path: str,
) -> list[str]:
    """Reject new Python/loader files, pytest hooks/conftest, dynamic imports and value-type spoofing."""
    reasons: list[str] = []
    for rel_path in touched_files:
        after_file = after_dir / rel_path
        before_file = before_dir / rel_path
        lowered = rel_path.lower()
        is_new = not before_file.exists()
        if is_new and after_file.exists() and lowered.endswith(_FORBIDDEN_NEW_SUFFIXES):
            reasons.append(
                f"patch_rejected: patch creates new file '{rel_path}' outside the allowed target code files"
            )
        if _is_test_path(rel_path, repro_test_path) or not lowered.endswith(".py") or not after_file.is_file():
            continue
        try:
            source = after_file.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            reasons.append(f"patch_rejected: patched file '{rel_path}' is not valid UTF-8")
            continue
        before_source = before_file.read_text(encoding="utf-8", errors="replace") if before_file.is_file() else ""
        for match in sorted({m.group(0).strip() for m in _FORBIDDEN_CODE_RE.finditer(source)}):
            if match in before_source and match not in {"pytest_", "hookimpl", "hookspec", "conftest"}:
                continue
            reasons.append(
                f"patch_rejected: patched file '{rel_path}' contains forbidden pytest hook/dynamic import construct '{match}'"
            )
        before_flags = _flagged_spoofing_nodes(before_source)
        for dump, description in _flagged_spoofing_nodes(source).items():
            if dump not in before_flags:
                reasons.append(
                    f"patch_rejected: patched file '{rel_path}' {description} (value_type_spoofing risk)"
                )
    return reasons


_FAILED_LINE_RE = re.compile(r"^FAILED\s+(\S+?)::(\S+)", re.MULTILINE)
_ERROR_LINE_RE = re.compile(r"^ERROR\s+\S+", re.MULTILINE)
_E_LINE_RE = re.compile(r"^E\s+(.*)$", re.MULTILINE)
_EXPECTED_TOKEN_RE = re.compile(r"-?\d+(?:[.,]\d+)?|'[^'\n]*'|\"[^\"\n]*\"")


def _repro_test_function_names(source_text: str) -> set[str]:
    try:
        tree = ast.parse(source_text)
    except SyntaxError:
        return set()
    return {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_")
    }


def _check_before_red_matches_report(
    log: str,
    norm_test_path: str,
    test_names: set[str],
    failing_assertion: str | None,
) -> list[str]:
    """RED must come from the reproduction test_* and carry the expected value of the report (X2)."""
    reasons: list[str] = []
    failed = _FAILED_LINE_RE.findall(log)
    if not failed:
        reasons.append("test_invalid: before run did not report a FAILED reproduction test_* function")
    for failed_path, failed_node in failed:
        leaf = failed_node.split("::")[-1].split("[")[0]
        if posixpath.normpath(failed_path) != norm_test_path or leaf not in test_names:
            reasons.append(
                f"test_invalid: before failure '{failed_path}::{failed_node}' is not a test_* of the reproduction test"
            )
    if _ERROR_LINE_RE.search(log):
        reasons.append("test_invalid (infra_error): before run reported ERROR entries besides the reproduction failure")

    expected_text = (failing_assertion or "").split("AssertionError", 1)[-1]
    tokens = list(dict.fromkeys(_EXPECTED_TOKEN_RE.findall(expected_text)))
    if not tokens:
        reasons.append(
            "test_invalid: ReproResult.failing_assertion has no expected value to cross-check the before failure"
        )
        return reasons
    assertion_lines = "\n".join(m.group(1) for m in _E_LINE_RE.finditer(log))
    if "AssertionError" not in assertion_lines:
        reasons.append("test_invalid: before test did not fail with AssertionError")
    else:
        missing = [t for t in tokens if t not in assertion_lines]
        if missing:
            reasons.append(
                f"test_invalid: before AssertionError does not contain the reported value(s) {missing} "
                "(failing_assertion); the RED does not reproduce the report"
            )
    return reasons


class Verification:
    """Deterministic independent Verifier stage (RFC-0001 §3.3, RF-06)."""

    def __init__(
        self,
        sandbox: SandboxStage | None = None,
        base_root: Path | str | None = None,
        max_files_changed: int | None = None,
        test_timeout_s: float | None = None,
        allow_inline_test_source: bool = False,
    ) -> None:
        if base_root is not None:
            self.base_root = Path(base_root).resolve()
        elif sandbox is not None and hasattr(sandbox, "base_root"):
            self.base_root = Path(getattr(sandbox, "base_root")).resolve()
        else:
            self.base_root = _discover_default_base_root()

        cfg_max_files, cfg_timeout = _load_limits(self.base_root)
        self.max_files_changed = int(
            max_files_changed if max_files_changed is not None else cfg_max_files
        )
        self.test_timeout_s = float(
            test_timeout_s if test_timeout_s is not None else cfg_timeout
        )
        self.sandbox: SandboxStage = (
            sandbox
            if sandbox is not None
            else LocalSandbox(base_root=self.base_root, default_timeout_s=self.test_timeout_s)
        )
        # `test_source_ref` is an evidence reference. Inline source is accepted only when explicitly enabled (tests).
        self.allow_inline_test_source = bool(allow_inline_test_source)

    def _pytest_command(self, *targets: str, with_plugin: bool = False) -> str:
        """Build the verifier-controlled pytest command; never uses the patched workspace configuration."""
        parts = [
            "env",
            "PYTEST_DISABLE_PLUGIN_AUTOLOAD=1",
            shlex.quote(sys.executable),
            "-m",
            "pytest",
            "-c",
            VERIFIER_CONFIG_NAME,
            "--rootdir=.",
            "-o",
            "addopts=",
            "-p",
            "no:cacheprovider",
        ]
        if with_plugin:
            parts += ["-p", VERIFIER_PLUGIN_MODULE]
        parts += ["-v", "-rfE", *(shlex.quote(t) for t in targets)]
        return " ".join(parts)

    @property
    def suite_command(self) -> str:
        return self._pytest_command()

    @staticmethod
    def _install_fixed_runner_config(workdir: Path, with_plugin: bool) -> None:
        """(Re)write verifier-owned config/plugin AFTER the patch so the workspace cannot influence them."""
        (workdir / VERIFIER_CONFIG_NAME).write_text(_FIXED_PYTEST_INI, encoding="utf-8")
        plugin_file = workdir / f"{VERIFIER_PLUGIN_MODULE}.py"
        if with_plugin:
            plugin_file.write_text(_VERIFIER_PLUGIN_SOURCE, encoding="utf-8")
        elif plugin_file.exists():
            plugin_file.unlink()

    def _resolve_test_source(
        self,
        case: RunState,
        repro: ReproResult,
        source_repo_dir: Path,
         normalized_test_path: str,
    ) -> tuple[bytes | None, str | None]:
        """Resolve reproduction test bytes from `repro.test_source_ref` or target workspace."""
        ref = repro.test_source_ref
        if "\n" in ref or ref.lstrip().startswith(
            ("import ", "from ", "def ", "class ", "#", "@", '"""', "'''")
        ):
            if not self.allow_inline_test_source:
                return None, "test_invalid: inline test_source_ref is only accepted in tests; use an evidence reference"
            return ref.encode("utf-8"), None

        case_dir = (self.base_root / "runs" / case.case_id).resolve()
        candidate_paths: list[Path] = []
        raw_ref_path = Path(ref)
        if raw_ref_path.is_absolute():
            candidate_paths.append(raw_ref_path)
        elif ".." not in raw_ref_path.parts:
            candidate_paths.append(self.base_root / "runs" / case.case_id / raw_ref_path)
            candidate_paths.append(source_repo_dir / raw_ref_path)

        for cand in candidate_paths:
            if cand.is_symlink():
                return None, f"test_invalid: symlink test_source_ref is forbidden ({ref!r})"
            resolved_cand = cand.resolve()
            allowed = resolved_cand.is_relative_to(case_dir) or (
                not raw_ref_path.is_absolute() and resolved_cand.is_relative_to(source_repo_dir.resolve())
            )
            if not allowed:
                if raw_ref_path.is_absolute():
                    return None, f"test_invalid: absolute test_source_ref outside the case folder is forbidden ({ref!r})"
                continue
            if resolved_cand.is_file():
                return resolved_cand.read_bytes(), None

        in_repo_test = source_repo_dir / normalized_test_path
        if in_repo_test.is_file():
            data = in_repo_test.read_bytes()
            clean_hex = ref.removeprefix("sha256:").strip()
            if len(clean_hex) == 64 and all(c in "0123456789abcdef" for c in clean_hex):
                actual_hex = hashlib.sha256(data).hexdigest()
                if actual_hex != clean_hex:
                    return (
                        None,
                        f"test_modified: test file sha256 ({actual_hex}) does not match test_source_ref ({clean_hex})",
                    )
            return data, None

        return None, f"test_invalid (infra_error): could not load reproduction test source from {ref!r}"

    def _apply_patch_to_workspace(
        self,
        case: RunState,
        patch: Patch,
        after_dir: Path,
    ) -> tuple[tuple[str, ...], str | None, bool]:
        """Apply `patch.diff_ref` into `after_dir`. Returns `(touched_files, error_reason, is_env_error)`."""
        diff_ref = patch.diff_ref.strip()

        # 1. Inline unified diff
        if "--- " in diff_ref and "+++ " in diff_ref:
            try:
                touched = apply_unified_diff(after_dir, patch.diff_ref)
                return touched, None, False
            except Exception as exc:
                return (), f"patch_rejected: failed to apply unified diff ({exc})", False

        # 2. Inline JSON mapping {"path": "new_content"}
        if diff_ref.startswith("{") and diff_ref.endswith("}"):
            try:
                mapping = json.loads(diff_ref)
                if not isinstance(mapping, dict) or not mapping:
                    return (), "patch_rejected: empty or non-object JSON patch payload", False
                touched_list: list[str] = []
                for raw_k, raw_v in mapping.items():
                    rel_k = require_posix_relative_path(str(raw_k), "patch_file_path")
                    dest = (after_dir / rel_k).resolve()
                    if not dest.is_relative_to(after_dir.resolve()):
                        return (), f"patch_rejected: path escapes workspace: {rel_k}", False
                    if raw_v is None:
                        if dest.exists():
                            dest.unlink()
                    else:
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        dest.write_text(str(raw_v), encoding="utf-8")
                    touched_list.append(dest.relative_to(after_dir.resolve()).as_posix())
                return tuple(dict.fromkeys(touched_list)), None, False
            except Exception as exc:
                return (), f"patch_rejected: invalid JSON patch ({exc})", False

        # 3. File or directory fixture path
        allowed_roots = (self.base_root.resolve(), Path(tempfile.gettempdir()).resolve())
        candidate_paths: list[Path] = []
        ref_path = Path(diff_ref)
        if not ref_path.is_absolute() and ".." not in ref_path.parts:
            candidate_paths.append(self.base_root / ref_path)
            candidate_paths.append(self.base_root / "runs" / case.case_id / ref_path)
        elif ref_path.is_absolute():
            candidate_paths.append(ref_path)

        for cand in candidate_paths:
            if cand.is_symlink():
                return (), f"patch_rejected: symlink diff_ref is forbidden ({diff_ref!r})", False
            resolved_cand = cand.resolve()
            if not any(resolved_cand.is_relative_to(root) for root in allowed_roots):
                continue
            if resolved_cand.is_file():
                try:
                    content = resolved_cand.read_text(encoding="utf-8")
                    touched = apply_unified_diff(after_dir, content)
                    return touched, None, False
                except Exception as exc:
                    return (), f"patch_rejected: failed to apply diff file {resolved_cand.name} ({exc})", False
            if resolved_cand.is_dir():
                touched_dir_files: list[str] = []
                for item in resolved_cand.rglob("*"):
                    if item.is_symlink():
                        return (), "patch_rejected: symlink inside patch directory is forbidden", False
                    if item.is_file():
                        rel = item.relative_to(resolved_cand).as_posix()
                        dest = after_dir / rel
                        resolved_dest = dest.resolve()
                        if not resolved_dest.is_relative_to(after_dir.resolve()):
                            return (), f"patch_rejected: path escapes workspace: {rel}", False
                        if not dest.exists() or dest.read_bytes() != item.read_bytes():
                            touched_dir_files.append(
                                resolved_dest.relative_to(after_dir.resolve()).as_posix()
                            )
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(item, dest)
                return tuple(sorted(set(touched_dir_files))), None, False

        return (), f"patch_rejected: unsupported or missing diff_ref {diff_ref!r}", False

    @contextlib.contextmanager
    def _staging_root(self):
        """Create a private (0700) staging directory inside `base_root/runs` so `LocalSandbox.exec` accepts relative workdirs."""
        runs_dir = self.base_root / "runs"
        created_runs_dir = not runs_dir.exists()
        tmp_dir: str | None = None
        try:
            runs_dir.mkdir(parents=True, exist_ok=True)
            tmp_dir = tempfile.mkdtemp(prefix=".verify_", dir=str(runs_dir))
            yield Path(tmp_dir)
        finally:
            if tmp_dir is not None:
                shutil.rmtree(tmp_dir, ignore_errors=True)
            if created_runs_dir and runs_dir.is_dir():
                with contextlib.suppress(OSError):
                    if not any(runs_dir.iterdir()):
                        runs_dir.rmdir()

    def _exec_test_run(self, workdir: Path, command: str) -> tuple[TestRun, ExecResult]:
        try:
            rel_workdir = workdir.resolve().relative_to(self.base_root.resolve()).as_posix()
        except ValueError:
            rel_workdir = workdir.name

        t0 = time.monotonic()
        exec_res = self.sandbox.exec(rel_workdir, command, timeout_s=self.test_timeout_s)
        duration_s = round(max(0.0, time.monotonic() - t0), 4)
        combined_log = "\n".join(
            part for part in (exec_res.stdout_ref.strip(), exec_res.stderr_ref.strip()) if part
        )
        return (
            TestRun(
                command=command,
                exit_code=exec_res.exit_code,
                duration_s=duration_s,
                log_ref=combined_log,
            ),
            exec_res,
        )

    @staticmethod
    def _sentinel_test_run(command: str, exit_code: int = 1, log_ref: str = "not executed") -> TestRun:
        return TestRun(command=command, exit_code=exit_code, duration_s=0.0, log_ref=log_ref)

    def run(self, case: RunState, repro: ReproResult, patch: Patch) -> Verdict:
        """Execute independent before/after/suite verification and emit a deterministic Verdict."""
        if not isinstance(case, RunState):
            raise ContractValidationError(f"Expected RunState for 'case', got {type(case).__name__}")
        if not isinstance(repro, ReproResult):
            raise ContractValidationError(f"Expected ReproResult for 'repro', got {type(repro).__name__}")
        if not isinstance(patch, Patch):
            raise ContractValidationError(f"Expected Patch for 'patch', got {type(patch).__name__}")

        provisional_base = case.base_revision or "unknown-base-revision"
        provisional_fix = case.fix_revision or hashlib.sha256(
            f"{provisional_base}:{patch.diff_ref}".encode("utf-8")
        ).hexdigest()[:40]

        try:
            norm_test_path = require_posix_relative_path(repro.test_path, "repro.test_path")
        except ContractValidationError as exc:
            cmd = self._pytest_command(repro.test_path)
            sentinel = self._sentinel_test_run(cmd, exit_code=2, log_ref=str(exc))
            return Verdict(
                before=sentinel,
                after=sentinel,
                suite=self._sentinel_test_run(self.suite_command, exit_code=2, log_ref=str(exc)),
                base_revision=provisional_base,
                fix_revision=provisional_fix,
                result=VerdictResult.REJECTED,
                reasons=(f"test_invalid: {exc}",),
            )

        single_test_cmd = self._pytest_command(norm_test_path)

        # Check if reproduction stage already reported an environment failure
        if repro.outcome == ReproOutcome.ENV_ERROR:
            sentinel = self._sentinel_test_run(
                single_test_cmd,
                exit_code=repro.exit_code or 2,
                log_ref=repro.log_ref or "reproduction stage reported env_error",
            )
            return Verdict(
                before=sentinel,
                after=sentinel,
                suite=self._sentinel_test_run(self.suite_command, exit_code=2, log_ref="skipped due to env_error"),
                base_revision=provisional_base,
                fix_revision=provisional_fix,
                result=VerdictResult.ENV_ERROR,
                reasons=("infra_error: reproduction stage reported env_error",),
            )

        # Resolve target repository directory via Sandbox rules
        try:
            if hasattr(self.sandbox, "resolve_workdir"):
                source_repo_dir = getattr(self.sandbox, "resolve_workdir")(case.repo_ref)
            else:
                rel_repo = require_posix_relative_path(case.repo_ref, "case.repo_ref")
                source_repo_dir = (self.base_root / rel_repo).resolve()
                if not source_repo_dir.is_dir():
                    raise FileNotFoundError(f"Repository directory not found: {case.repo_ref}")
        except Exception as exc:
            sentinel = self._sentinel_test_run(single_test_cmd, exit_code=2, log_ref=str(exc))
            return Verdict(
                before=sentinel,
                after=sentinel,
                suite=self._sentinel_test_run(self.suite_command, exit_code=2, log_ref=str(exc)),
                base_revision=provisional_base,
                fix_revision=provisional_fix,
                result=VerdictResult.ENV_ERROR,
                reasons=(f"infra_error: invalid or missing target repository ({exc})",),
            )

        base_revision = case.base_revision or compute_tree_revision(source_repo_dir)
        fix_revision = case.fix_revision or hashlib.sha256(
            f"{base_revision}:{patch.diff_ref}:{','.join(patch.files_changed)}".encode("utf-8")
        ).hexdigest()[:40]

        rejection_reasons: list[str] = []

        if repro.outcome != ReproOutcome.RED_ON_ASSERTION or repro.exit_code == 0:
            rejection_reasons.append(
                f"test_invalid: reproduction outcome must be red_on_assertion with exit_code != 0 (got {repro.outcome.value}, exit_code={repro.exit_code})"
            )

        # Static checks on Patch metadata
        if patch.touches_tests:
            rejection_reasons.append("patch_rejected: patch.touches_tests is True")
        if patch.touches_ci:
            rejection_reasons.append("patch_rejected: patch.touches_ci is True")
        if len(patch.files_changed) == 0:
            rejection_reasons.append("patch_rejected: patch.files_changed is empty")
        if len(patch.files_changed) > self.max_files_changed:
            rejection_reasons.append(
                f"patch_rejected: files_changed ({len(patch.files_changed)}) exceeds max_files_changed ({self.max_files_changed})"
            )

        declared_files_norm: list[str] = []
        for raw_f in patch.files_changed:
            try:
                norm_f = require_posix_relative_path(raw_f, "patch.files_changed")
                declared_files_norm.append(norm_f)
                if _is_test_path(norm_f, norm_test_path):
                    rejection_reasons.append(
                        f"patch_rejected: patch touches test file '{norm_f}'"
                    )
                if _is_ci_or_runner_config_path(norm_f):
                    rejection_reasons.append(
                        f"patch_rejected: patch touches CI or runner configuration '{norm_f}'"
                    )
            except ContractValidationError as exc:
                rejection_reasons.append(f"patch_rejected: invalid path in files_changed ({exc})")

        before_test_bytes, load_err = self._resolve_test_source(
            case, repro, source_repo_dir, norm_test_path
        )
        if before_test_bytes is None:
            sentinel = self._sentinel_test_run(single_test_cmd, exit_code=2, log_ref=load_err or "missing test")
            return Verdict(
                before=sentinel,
                after=sentinel,
                suite=self._sentinel_test_run(self.suite_command, exit_code=2, log_ref=load_err or "missing test"),
                base_revision=base_revision,
                fix_revision=fix_revision,
                result=VerdictResult.REJECTED,
                reasons=(load_err or "test_invalid: missing reproduction test source",),
            )

        before_test_sha256 = hashlib.sha256(before_test_bytes).hexdigest()
        before_test_text = before_test_bytes.decode("utf-8", errors="replace")
        before_oracle = inspect_test_oracle(before_test_text)
        rejection_reasons.extend(before_oracle.reasons)

        with self._staging_root() as staging_dir:
            before_dir = staging_dir / "before"
            after_dir = staging_dir / "after"
            ignore_fn = shutil.ignore_patterns(".git", "__pycache__", ".pytest_cache", ".venv", "*.pyc")
            shutil.copytree(source_repo_dir, before_dir, symlinks=True, ignore=ignore_fn)
            shutil.copytree(source_repo_dir, after_dir, symlinks=True, ignore=ignore_fn)

            before_test_file = (before_dir / norm_test_path).resolve()
            after_test_file = (after_dir / norm_test_path).resolve()
            before_test_file.parent.mkdir(parents=True, exist_ok=True)
            after_test_file.parent.mkdir(parents=True, exist_ok=True)
            before_test_file.write_bytes(before_test_bytes)
            after_test_file.write_bytes(before_test_bytes)

            before_runner_configs = _snapshot_runner_configs(before_dir)

            # Apply patch to after_dir
            touched_by_patch, patch_err, patch_is_env_err = self._apply_patch_to_workspace(
                case, patch, after_dir
            )
            if patch_err is not None:
                if patch_is_env_err:
                    sentinel = self._sentinel_test_run(single_test_cmd, exit_code=2, log_ref=patch_err)
                    return Verdict(
                        before=sentinel,
                        after=sentinel,
                        suite=self._sentinel_test_run(self.suite_command, exit_code=2, log_ref=patch_err),
                        base_revision=base_revision,
                        fix_revision=fix_revision,
                        result=VerdictResult.ENV_ERROR,
                        reasons=(patch_err,),
                    )
                rejection_reasons.append(patch_err)

            if len(touched_by_patch) > self.max_files_changed:
                rejection_reasons.append(
                    f"patch_rejected: diff touched {len(touched_by_patch)} files, exceeding max_files_changed ({self.max_files_changed})"
                )

            for touched_rel in touched_by_patch:
                if _is_test_path(touched_rel, norm_test_path):
                    rejection_reasons.append(
                        f"patch_rejected: diff touches protected test file '{touched_rel}'"
                    )
                if _is_ci_or_runner_config_path(touched_rel):
                    rejection_reasons.append(
                        f"runner_config_modified: diff touches CI or runner configuration '{touched_rel}'"
                    )
                if declared_files_norm and touched_rel not in declared_files_norm:
                    rejection_reasons.append(
                        f"patch_rejected: diff modified undeclared file '{touched_rel}'"
                    )

            # Differential oracle check: compare before and after reproduction test file
            if not after_test_file.is_file():
                rejection_reasons.append(
                    f"test_deleted: reproduction test '{norm_test_path}' was deleted or removed"
                )
            else:
                after_test_bytes = after_test_file.read_bytes()
                after_test_sha256 = hashlib.sha256(after_test_bytes).hexdigest()
                if after_test_sha256 != before_test_sha256:
                    rejection_reasons.append(
                        f"test_modified: reproduction test sha256 changed before ({before_test_sha256[:12]}) vs after ({after_test_sha256[:12]})"
                    )
                    after_oracle = inspect_test_oracle(
                        after_test_bytes.decode("utf-8", errors="replace")
                    )
                    rejection_reasons.extend(after_oracle.reasons)
                    if after_oracle.assertion_count < before_oracle.assertion_count:
                        rejection_reasons.append(
                            "assertion_removed: reproduction test has fewer assertions after patch"
                        )
                    elif after_oracle.assertion_signatures != before_oracle.assertion_signatures:
                        rejection_reasons.append(
                            "assertion_weakened: reproduction test assertions were altered by patch"
                        )

            # Check runner configuration integrity before vs after
            after_runner_configs = _snapshot_runner_configs(after_dir)
            if after_runner_configs != before_runner_configs:
                rejection_reasons.append(
                    "runner_config_modified: test runner configuration sha256 changed between before and after"
                )

            # Inspect patched code for runtime skip/xfail or process exit tricks
            rejection_reasons.extend(
                _inspect_patched_code_for_subversion(after_dir, touched_by_patch, norm_test_path)
            )
            rejection_reasons.extend(
                _inspect_patch_hardening(before_dir, after_dir, touched_by_patch, norm_test_path)
            )

            computed_fix_rev = compute_tree_revision(after_dir)
            if case.fix_revision:
                fix_revision = case.fix_revision
            else:
                fix_revision = computed_fix_rev

            if compute_tree_revision(before_dir) == computed_fix_rev and patch_err is None:
                rejection_reasons.append(
                    "patch_rejected: patch produced no effective change in repository tree"
                )

            if rejection_reasons:
                sentinel_before = self._sentinel_test_run(
                    single_test_cmd, exit_code=1, log_ref="skipped execution: static policy or oracle check failed"
                )
                sentinel_after = self._sentinel_test_run(
                    single_test_cmd, exit_code=1, log_ref="skipped execution: static policy or oracle check failed"
                )
                sentinel_suite = self._sentinel_test_run(
                    self.suite_command, exit_code=1, log_ref="skipped execution: static policy or oracle check failed"
                )
                return Verdict(
                    before=sentinel_before,
                    after=sentinel_after,
                    suite=sentinel_suite,
                    base_revision=base_revision,
                    fix_revision=fix_revision,
                    result=VerdictResult.REJECTED,
                    reasons=tuple(dict.fromkeys(rejection_reasons)),
                )

            # Fixed verifier-owned configuration (never the patched workspace's own configuration).
            self._install_fixed_runner_config(before_dir, with_plugin=False)
            self._install_fixed_runner_config(after_dir, with_plugin=True)
            after_test_cmd = self._pytest_command(norm_test_path, with_plugin=True)

            # 1. Execute `before` test run
            before_run, before_exec = self._exec_test_run(before_dir, single_test_cmd)
            if before_exec.timed_out or before_run.exit_code in (124, 127) or "INTERNALERROR" in before_run.log_ref:
                sentinel_after = self._sentinel_test_run(single_test_cmd, exit_code=124, log_ref="aborted after before env_error")
                sentinel_suite = self._sentinel_test_run(self.suite_command, exit_code=124, log_ref="aborted after before env_error")
                return Verdict(
                    before=before_run,
                    after=sentinel_after,
                    suite=sentinel_suite,
                    base_revision=base_revision,
                    fix_revision=fix_revision,
                    result=VerdictResult.ENV_ERROR,
                    reasons=("infra_error: environment or timeout failure during before test execution",),
                )

            # Validate `before` failed specifically on AssertionError without import/collection/setup errors
            if before_run.exit_code == 0:
                rejection_reasons.append(
                    "before_not_red: reproduction test passed on base revision before fix (exit_code == 0)"
                )
            else:
                if any(pat in before_run.log_ref for pat in _IMPORT_OR_COLLECTION_ERROR_PATTERNS) or before_run.exit_code in (2, 3, 4, 5):
                    rejection_reasons.append(
                        "test_invalid (infra_error): before test failed with import, collection, or setup error instead of AssertionError"
                    )
                if _SETUP_FAILURE_RE.search(before_run.log_ref):
                    rejection_reasons.append(
                        "test_invalid (infra_error): before test failed during setUp/tearDown preparation instead of AssertionError"
                    )
                if _SKIP_OR_XFAIL_SUMMARY_RE.search(before_run.log_ref):
                    rejection_reasons.append(
                        "test_skipped_or_xfail: before test run reported skipped or xfail"
                    )
                rejection_reasons.extend(
                    _check_before_red_matches_report(
                        before_run.log_ref,
                        norm_test_path,
                        _repro_test_function_names(before_test_text),
                        repro.failing_assertion,
                    )
                )

            if rejection_reasons:
                sentinel_after = self._sentinel_test_run(
                    single_test_cmd, exit_code=1, log_ref="skipped after invalid before test run"
                )
                sentinel_suite = self._sentinel_test_run(
                    self.suite_command, exit_code=1, log_ref="skipped after invalid before test run"
                )
                return Verdict(
                    before=before_run,
                    after=sentinel_after,
                    suite=sentinel_suite,
                    base_revision=base_revision,
                    fix_revision=fix_revision,
                    result=VerdictResult.REJECTED,
                    reasons=tuple(dict.fromkeys(rejection_reasons)),
                )

            # 2. Execute `after` test run
            if after_test_file.is_file():
                after_run, after_exec = self._exec_test_run(after_dir, after_test_cmd)
            else:
                after_run = self._sentinel_test_run(
                    single_test_cmd,
                    exit_code=2,
                    log_ref=f"reproduction test '{norm_test_path}' was deleted",
                )
                after_exec = ExecResult(exit_code=2, stdout_ref="", stderr_ref=after_run.log_ref, timed_out=False)

            if after_exec.timed_out or after_run.exit_code in (124, 127) or "INTERNALERROR" in after_run.log_ref:
                sentinel_suite = self._sentinel_test_run(self.suite_command, exit_code=124, log_ref="aborted after after-run env_error")
                return Verdict(
                    before=before_run,
                    after=after_run,
                    suite=sentinel_suite,
                    base_revision=base_revision,
                    fix_revision=fix_revision,
                    result=VerdictResult.ENV_ERROR,
                    reasons=("infra_error: timeout or sandbox environment error during after test execution",),
                )

            if _SKIP_OR_XFAIL_SUMMARY_RE.search(after_run.log_ref):
                rejection_reasons.append(
                    "test_skipped_or_xfail: reproduction test was skipped or marked xfail on after run"
                )
            if "RQA_TYPE_MISMATCH" in after_run.log_ref:
                rejection_reasons.append(
                    "patch_rejected: returned value does not have the exact expected type (value_type_spoofing)"
                )
            if after_run.exit_code != 0:
                rejection_reasons.append(
                    f"after_not_green: reproduction test failed after applying patch (exit_code={after_run.exit_code})"
                )
            elif not _PASSED_SUMMARY_RE.search(after_run.log_ref):
                rejection_reasons.append(
                    "after_not_green: after test run exited 0 without recording any passed test"
                )

            # 3. Execute `suite` test run on patched workspace
            suite_run, suite_exec = self._exec_test_run(after_dir, self.suite_command)
            if suite_exec.timed_out or suite_run.exit_code in (124, 127) or "INTERNALERROR" in suite_run.log_ref:
                return Verdict(
                    before=before_run,
                    after=after_run,
                    suite=suite_run,
                    base_revision=base_revision,
                    fix_revision=fix_revision,
                    result=VerdictResult.ENV_ERROR,
                    reasons=("infra_error: timeout or sandbox environment error during suite execution",),
                )

            if _SKIP_OR_XFAIL_SUMMARY_RE.search(suite_run.log_ref):
                rejection_reasons.append(
                    "test_skipped_or_xfail: test suite reported skipped or xfail tests after patch"
                )
            if suite_run.exit_code != 0:
                rejection_reasons.append(
                    f"suite_failed: target test suite failed after applying patch (exit_code={suite_run.exit_code})"
                )
            elif not _PASSED_SUMMARY_RE.search(suite_run.log_ref):
                rejection_reasons.append(
                    "suite_failed: suite run exited 0 without recording any passed test"
                )

        deduped_reasons = tuple(dict.fromkeys(rejection_reasons))
        if deduped_reasons:
            return Verdict(
                before=before_run,
                after=after_run,
                suite=suite_run,
                base_revision=base_revision,
                fix_revision=fix_revision,
                result=VerdictResult.REJECTED,
                reasons=deduped_reasons,
            )

        return Verdict(
            before=before_run,
            after=after_run,
            suite=suite_run,
            base_revision=base_revision,
            fix_revision=fix_revision,
            result=VerdictResult.VERIFIED,
            reasons=(RESIDUAL_RISK_NOTE,),
        )


Verifier = Verification
