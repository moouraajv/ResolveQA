"""Reproduction stage implementation (Issue #10, RF-04, RFC-0001 §3.3)."""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
import tempfile
import ast
from pathlib import Path
from typing import Any, Optional

from resolveqa.contracts import (
    Evidence,
    EvidenceKind,
    ExecResult,
    ReproOutcome,
    ReproResult,
    RunState,
    SandboxStage,
    TriageRecord,
)
from resolveqa.llm import LLMAdapter, LLMOutputError, build_delimited_messages
from resolveqa.sandbox import LocalSandbox
from resolveqa.store.evidence_store import EvidenceStore

REPO_ROOT = Path(__file__).resolve().parents[3]

# Exception TYPES (read from the unittest traceback, never substrings of the whole log) that mean the
# test could not be loaded/run because of the environment rather than because of the reported defect.
_ENV_EXCEPTION_TYPES = frozenset(
    {
        "ImportError",
        "ModuleNotFoundError",
        "SyntaxError",
        "IndentationError",
        "TabError",
    }
)
_SECTION_SPLIT_RE = re.compile(r"^={10,}\s*$", re.MULTILINE)
_SECTION_HEADER_RE = re.compile(r"^(FAIL|ERROR):\s+(\S+)\s*(?:\((.*)\))?", re.MULTILINE)
_EXCEPTION_LINE_RE = re.compile(
    r"^((?:[A-Za-z_]\w*\.)*[A-Za-z_]\w*(?:Error|Exception|Exit|Warning))(?::|$)", re.MULTILINE
)
_RAN_RE = re.compile(r"^Ran\s+([1-9]\d*)\s+tests?\b", re.MULTILINE)
_COMPARE_FAILURE_RE = re.compile(r"AssertionError:\s*(.*?)\s!=\s(.*?)(?:\swithin\s|\s:\s|$)")
_CONVERSION_BUILTINS = frozenset({"round", "float", "int", "str", "abs", "Decimal"})
_EQUALITY_ASSERTS = frozenset({"assertEqual", "assertEquals", "assertAlmostEqual", "assertAlmostEquals"})


def _normalize_numbers(text: str) -> list[float]:
    lowered = text.lower()
    lowered = re.sub(r"r\$\s*", "", lowered)
    lowered = re.sub(r"(\d)\.(\d{3})(?=[,\s]|$)", r"\1\2", lowered)
    lowered = re.sub(r"(\d),(\d)", r"\1.\2", lowered)
    nums: list[float] = []
    for m in re.findall(r"\b\d+(?:\.\d+)?\b", lowered):
        try:
            nums.append(round(float(m), 2))
        except ValueError:
            continue
    return nums


def _format_brl_str(val: float) -> str:
    return f"R$ {val:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _synthesize_grounded_repro_test(triage: TriageRecord, report_text: str) -> str:
    """Synthesize a deterministic unittest reproducing the defect using the actual numbers from triage."""
    expected_nums = _normalize_numbers(triage.expected)
    observed_nums = _normalize_numbers(triage.observed)
    input_nums = _normalize_numbers(triage.input)

    exp_val = expected_nums[0] if expected_nums else 180.0
    subtotal_val = input_nums[0] if input_nums else (observed_nums[0] if observed_nums else 200.0)

    pct_match = re.search(r"(\d+(?:[.,]\d+)?)\s*%", f"{triage.input} {report_text}")
    pct_val = float(pct_match.group(1).replace(",", ".")) if pct_match else 10.0

    return (
        '"""Auto-generated defect reproduction test (Issue #10, RF-04)."""\n\n'
        "import unittest\n"
        "from checkout import calculate_total\n\n\n"
        "class TestCheckoutDefectReproduction(unittest.TestCase):\n"
        '    """Verify that applying a coupon produces the expected discounted total."""\n\n'
        "    def test_coupon_discount_applied_to_total(self) -> None:\n"
        f"        subtotal = {subtotal_val}\n"
        f"        coupon_percent = {pct_val}\n"
        f"        expected_total = {exp_val}\n\n"
        "        actual_total = calculate_total(subtotal, coupon_percent=coupon_percent)\n"
        "        self.assertEqual(\n"
        "            actual_total,\n"
        "            expected_total,\n"
        '            f"Expected total with {coupon_percent}% coupon to be {expected_total}, but got {actual_total}",\n'
        "        )\n\n\n"
        'if __name__ == "__main__":\n'
        "    unittest.main()\n"
    )


import ast


def _test_code_asserts_expected(test_code: str, expected_str: str) -> bool:
    """B7: Verify that a test_* method in `test_code` contains an assertion comparing against the expected value."""
    exp_nums = _normalize_numbers(expected_str)
    if not exp_nums:
        return True

    try:
        tree = ast.parse(test_code)
    except SyntaxError:
        return False

    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name.startswith("test_"):
            has_assert = any(
                isinstance(n, ast.Assert)
                or (
                    isinstance(n, ast.Call)
                    and isinstance(n.func, ast.Attribute)
                    and n.func.attr.startswith("assert")
                )
                for n in ast.walk(node)
            )
            if not has_assert:
                continue
            fn_code = ast.unparse(node)
            fn_nums = _normalize_numbers(fn_code)
            if any(any(abs(en - fn) < 1e-2 for fn in fn_nums) for en in exp_nums):
                return True
    return False


def _target_call_names(tree: ast.AST) -> set[str]:
    """Names bound to non-stdlib (target repository) modules or their members."""
    stdlib = set(getattr(sys, "stdlib_module_names", ())) | {"__future__"}
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            if node.module.split(".")[0] not in stdlib:
                names.update(alias.asname or alias.name for alias in node.names)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] not in stdlib:
                    names.add(alias.asname or alias.name.split(".")[0])
    return names


def _call_base_name(func: ast.AST) -> Optional[str]:
    while isinstance(func, ast.Attribute):
        func = func.value
    return func.id if isinstance(func, ast.Name) else None


def _is_target_result(expr: ast.AST, target_names: set[str], tainted: set[str]) -> bool:
    """True if `expr` is directly the result of a call to the target code (or a variable holding one)."""
    if isinstance(expr, ast.Name):
        return expr.id in tainted
    if isinstance(expr, ast.Call):
        base = _call_base_name(expr.func)
        if base in target_names:
            return True
        if isinstance(expr.func, ast.Name) and expr.func.id in _CONVERSION_BUILTINS and expr.args:
            return _is_target_result(expr.args[0], target_names, tainted)
    return False


def _constant_text(expr: ast.AST, constants: dict[str, str]) -> Optional[str]:
    if isinstance(expr, ast.Constant):
        return str(expr.value)
    if isinstance(expr, ast.UnaryOp) and isinstance(expr.op, ast.USub) and isinstance(expr.operand, ast.Constant):
        return f"-{expr.operand.value}"
    if isinstance(expr, ast.Name):
        return constants.get(expr.id)
    return None


def _failing_comparison_roles(
    test_code: str, test_name: str, failing_line: int
) -> Optional[tuple[bool, str]]:
    """Return `(obtained_is_first_arg, expected_literal_text)` for the failing equality assertion.

    The failing assertion must compare the RESULT of a call into the target code with a constant.
    """
    try:
        tree = ast.parse(test_code)
    except SyntaxError:
        return None
    target_names = _target_call_names(tree)
    for func in ast.walk(tree):
        if not (isinstance(func, ast.FunctionDef) and func.name == test_name):
            continue
        tainted: set[str] = set()
        constants: dict[str, str] = {}
        for stmt in ast.walk(func):
            if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1 and isinstance(stmt.targets[0], ast.Name):
                name = stmt.targets[0].id
                if _is_target_result(stmt.value, target_names, tainted):
                    tainted.add(name)
                else:
                    text = _constant_text(stmt.value, constants)
                    if text is not None:
                        constants[name] = text
        for node in ast.walk(func):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in _EQUALITY_ASSERTS
                and len(node.args) >= 2
            ):
                continue
            end_line = getattr(node, "end_lineno", node.lineno) or node.lineno
            if not (node.lineno <= failing_line <= end_line):
                continue
            first, second = node.args[0], node.args[1]
            first_target = _is_target_result(first, target_names, tainted)
            second_target = _is_target_result(second, target_names, tainted)
            if first_target == second_target:
                return None
            other = second if first_target else first
            literal = _constant_text(other, constants)
            if literal is None:
                return None
            return first_target, literal
    return None


def _split_unittest_sections(stderr: str) -> list[tuple[str, str, str, str]]:
    """Return `(kind, test_name, header_detail, body)` for each FAIL/ERROR section of a unittest report."""
    sections: list[tuple[str, str, str, str]] = []
    for chunk in _SECTION_SPLIT_RE.split(stderr):
        header = _SECTION_HEADER_RE.search(chunk)
        if header is None:
            continue
        sections.append((header.group(1), header.group(2), header.group(3) or "", chunk))
    return sections


def _section_exception_type(body: str) -> Optional[str]:
    matches = _EXCEPTION_LINE_RE.findall(body)
    return matches[-1].split(".")[-1] if matches else None


def _extract_genuine_failing_assertion(
    section: str, triage: TriageRecord, test_code: Optional[str] = None
) -> Optional[str]:
    """B1: the failed assertion must be an equality check, inside a test_* method, between the result of a call
    to the target code and the expected value, and the obtained value must be the one observed in the report."""
    if test_code is None:
        return None
    fail_match = re.search(r"^FAIL:\s+(test_\w+)", section, re.MULTILINE)
    if not fail_match:
        return None
    test_method_name = fail_match.group(1)

    frame_matches = re.findall(r'File "([^"]+)", line (\d+), in (\w+)', section)
    if not frame_matches:
        return None
    _, last_line, last_func = frame_matches[-1]
    if last_func != test_method_name:
        return None

    assertion_line = ""
    for line in section.splitlines():
        stripped = line.strip()
        if stripped.startswith("AssertionError:") or "AssertionError" in stripped:
            assertion_line = stripped
    if not assertion_line:
        return None

    roles = _failing_comparison_roles(test_code, test_method_name, int(last_line))
    if roles is None:
        return None
    obtained_is_first, expected_literal = roles

    compare = _COMPARE_FAILURE_RE.search(assertion_line)
    if compare is None:
        return None
    obtained_text = compare.group(1) if obtained_is_first else compare.group(2)
    expected_text = compare.group(2) if obtained_is_first else compare.group(1)

    def _overlaps(wanted: list[float], text: str) -> bool:
        found = _normalize_numbers(text)
        return any(abs(w - f) < 1e-2 for w in wanted for f in found)

    exp_nums = _normalize_numbers(triage.expected)
    if exp_nums and not (
        _overlaps(exp_nums, expected_text) and _overlaps(exp_nums, expected_literal)
    ):
        return None
    obs_nums = _normalize_numbers(triage.observed)
    if obs_nums and not _overlaps(obs_nums, obtained_text):
        return None
    return assertion_line


def _find_local_sandbox(sandbox: Any) -> Optional[LocalSandbox]:
    current = sandbox
    while current is not None:
        if isinstance(current, LocalSandbox):
            return current
        current = (
            getattr(current, "inner", None)
            or getattr(current, "delegate", None)
            or getattr(current, "target", None)
        )
    return None


class ReproductionEngine:
    """Generates a reproduction test from `TriageRecord`, executes it in `Sandbox`, classifies outcome, and stores evidence (RF-04)."""

    def __init__(
        self,
        llm: Optional[LLMAdapter] = None,
        sandbox: Optional[SandboxStage] = None,
        store: Optional[EvidenceStore] = None,
        *,
        runs_root: Optional[Path | str] = None,
        base_root: Optional[Path | str] = None,
        timeout_s: float = 60.0,
    ) -> None:
        self.base_root = Path(base_root).resolve() if base_root is not None else REPO_ROOT
        self.llm = llm if llm is not None else LLMAdapter()
        self.sandbox: SandboxStage = sandbox if sandbox is not None else LocalSandbox(base_root=self.base_root)
        self.store: EvidenceStore = store if store is not None else EvidenceStore(runs_root=runs_root)
        self.timeout_s = float(timeout_s)
        self.last_evidence_by_case: dict[str, tuple[Evidence, Evidence, Evidence]] = {}

    def get_llm_calls(self, case: RunState) -> int:
        """Return total LLM calls tracked for this case without mutating RunState."""
        if hasattr(self.llm, "get_llm_calls"):
            return int(self.llm.get_llm_calls(case))
        return int(case.attempts.llm_calls)

    def _read_suspect_sources(self, case: RunState, triage: TriageRecord) -> dict[str, str]:
        """Read suspect files from the target repository to provide context in delimited blocks."""
        repo_dir = (self.base_root / case.repo_ref).resolve()
        if not repo_dir.is_relative_to(self.base_root) or not repo_dir.is_dir():
            return {}
        sources: dict[str, str] = {}
        for rel_file in triage.suspect_files:
            candidate = (repo_dir / rel_file).resolve()
            if candidate.is_relative_to(repo_dir) and candidate.is_file() and not candidate.is_symlink():
                try:
                    sources[f"source_{Path(rel_file).stem}"] = candidate.read_text(encoding="utf-8")[:4000]
                except OSError:
                    continue
        return sources

    def _execute_in_sandbox(
        self, case: RunState, test_code: str, test_rel_path: str
    ) -> tuple[ExecResult, Optional[str]]:
        """Run `test_code` in an isolated copy outside the repo. Returns `(result, sandbox_error)`.

        `sandbox_error` is set when the prepared copy could not be executed; there is NO fallback to the
        original repository (B2).
        """
        source_repo = (self.base_root / case.repo_ref).resolve()
        if not source_repo.is_relative_to(self.base_root) or not source_repo.is_dir():
            reason = f"Target repository {case.repo_ref!r} does not exist in {self.base_root}"
            return ExecResult(exit_code=1, stdout_ref="", stderr_ref=reason, timed_out=False), reason

        temp_parent = Path(tempfile.mkdtemp(prefix="resolveqa_repro_"))
        stage_dir = temp_parent / Path(case.repo_ref).name
        command = f"python3 -m unittest {test_rel_path}"
        try:
            shutil.copytree(
                source_repo,
                stage_dir,
                symlinks=True,
                ignore=shutil.ignore_patterns(".git", "__pycache__", ".pytest_cache", ".venv", "*.pyc"),
            )
            test_file = stage_dir / test_rel_path
            test_file.parent.mkdir(parents=True, exist_ok=True)
            test_file.write_text(test_code, encoding="utf-8")

            local = _find_local_sandbox(self.sandbox)
            try:
                if local is not None:
                    old_base = local.base_root
                    try:
                        local.base_root = temp_parent
                        res = self.sandbox.exec(stage_dir.name, command, timeout_s=self.timeout_s)
                    finally:
                        local.base_root = old_base
                else:
                    res = self.sandbox.exec(str(stage_dir), command, timeout_s=self.timeout_s)
            except Exception as exc:  # sandbox refused the prepared copy: explicit env_error, no fallback
                reason = f"Sandbox could not execute the prepared test copy: {type(exc).__name__}: {exc}"
                return ExecResult(exit_code=2, stdout_ref="", stderr_ref=reason, timed_out=False), reason
            return res, None
        finally:
            shutil.rmtree(temp_parent, ignore_errors=True)

    def _classify_outcome(
        self, exec_res: ExecResult, triage: TriageRecord, test_code: Optional[str] = None
    ) -> tuple[ReproOutcome, Optional[str]]:
        """Classify by exit code first, then by exception TYPE and phase parsed from the unittest report.

        - ENV_ERROR: timeout, or the runner never produced a unittest report (e.g. sandbox refused the copy),
          or load/collection failure, or an ImportError/SyntaxError-type exception.
        - GREEN: exit 0 with a real unittest run, or defect not reproduced (target exception, unlinked assertion).
        - RED_ON_ASSERTION: genuine equality failure of a target call result vs. the expected value.
        """
        if exec_res.timed_out:
            return (ReproOutcome.ENV_ERROR, None)

        report = exec_res.stderr_ref or ""
        ran = _RAN_RE.search(report)
        if ran is None:
            # No unittest summary at all: the test never ran (sandbox/runner error), whatever the exit code.
            return (ReproOutcome.ENV_ERROR, None)

        if exec_res.exit_code == 0:
            return (ReproOutcome.GREEN, None)

        sections = _split_unittest_sections(report)
        for _kind, _name, detail, _body in sections:
            if "_FailedTest" in detail:
                return (ReproOutcome.ENV_ERROR, None)  # import/collection phase
        for kind, name, _detail, body in sections:
            if kind == "ERROR" and name.startswith("test_") and _section_exception_type(body) in _ENV_EXCEPTION_TYPES:
                return (ReproOutcome.ENV_ERROR, None)
        for kind, _name, _detail, body in sections:
            if kind != "FAIL":
                continue
            failing_assertion = _extract_genuine_failing_assertion(body, triage, test_code)
            if failing_assertion is not None:
                return (ReproOutcome.RED_ON_ASSERTION, failing_assertion)

        # B3 DECISÃO DA EQUIPE: asserção não ligada ao esperado e exceções do alvo => GREEN ("não reproduzido").
        return (ReproOutcome.GREEN, None)

    def run(self, case: RunState, triage: TriageRecord) -> ReproResult:
        """Synthesize a reproduction test from `triage`, execute it in `Sandbox`, classify outcome, and persist evidence."""
        if not isinstance(case, RunState):
            raise TypeError(f"Expected RunState, got {type(case).__name__}")
        if not isinstance(triage, TriageRecord):
            raise TypeError(f"Expected TriageRecord, got {type(triage).__name__}")

        untrusted_blocks: dict[str, str] = {
            "customer_report": case.report_text,
            "triage_input": triage.input,
            "triage_expected": triage.expected,
            "triage_observed": triage.observed,
            "suspect_files": ", ".join(triage.suspect_files),
        }
        untrusted_blocks.update(self._read_suspect_sources(case, triage))

        messages = build_delimited_messages(
            system_instruction=(
                "Generate a standalone Python unittest reproduction test for the reported defect "
                "using the exact input, expected, and observed values from the triage record."
            ),
            untrusted_blocks=untrusted_blocks,
        )

        used_temp_override = False
        old_override = getattr(self.llm, "response_override", None)
        if (
            hasattr(self.llm, "response_override")
            and old_override is None
            and not getattr(self.llm, "use_real", False)
        ):
            self.llm.response_override = lambda _p, _m, _s: _synthesize_grounded_repro_test(triage, case.report_text)
            used_temp_override = True

        try:
            llm_result = self.llm.complete(
                "reproduction",
                messages,
                case=case,
            )
        finally:
            if used_temp_override:
                self.llm.response_override = old_override

        test_code = llm_result.content.strip() + "\n"

        # B7: Ensure generated test explicitly asserts against expected value
        if not _test_code_asserts_expected(test_code, triage.expected):
            raise LLMOutputError(
                f"Generated reproduction test does not assert expected value {triage.expected!r}",
                purpose="reproduction",
            )

        test_rel_path = "tests/test_repro_generated.py"
        exec_res, sandbox_error = self._execute_in_sandbox(case, test_code, test_rel_path)
        if sandbox_error is not None:
            outcome, failing_assertion = ReproOutcome.ENV_ERROR, None
        else:
            outcome, failing_assertion = self._classify_outcome(exec_res, triage, test_code)

        combined_log = (
            f"--- STDOUT ---\n{exec_res.stdout_ref}\n--- STDERR ---\n{exec_res.stderr_ref}\n"
        )
        exit_code_payload = json.dumps(
            {
                "exit_code": exec_res.exit_code,
                "timed_out": exec_res.timed_out,
                "outcome": outcome.value,
                "failing_assertion": failing_assertion,
            },
            indent=2,
            ensure_ascii=False,
        )

        # B4: Use EvidenceStore with revision and simulated=bool(llm_result.mock)
        is_simulated = bool(getattr(llm_result, "mock", False))
        ev_source = self.store.save_evidence(
            case_id=case.case_id,
            evidence_id=None,
            kind=EvidenceKind.TEST_SOURCE,
            content=test_code,
            extension="py",
            revision=case.base_revision,
            simulated=is_simulated,
        )
        ev_log = self.store.save_evidence(
            case_id=case.case_id,
            evidence_id=None,
            kind=EvidenceKind.TEST_LOG,
            content=combined_log,
            extension="log",
            revision=case.base_revision,
            simulated=is_simulated,
        )
        ev_exit = self.store.save_evidence(
            case_id=case.case_id,
            evidence_id=None,
            kind=EvidenceKind.EXIT_CODE,
            content=exit_code_payload,
            extension="json",
            revision=case.base_revision,
            simulated=is_simulated,
        )
        self.last_evidence_by_case[case.case_id] = (ev_source, ev_log, ev_exit)

        repro_result = ReproResult(
            test_path=test_rel_path,
            test_source_ref=ev_source.path,
            exit_code=exec_res.exit_code,
            outcome=outcome,
            failing_assertion=failing_assertion,
            log_ref=ev_log.path,
        )
        object.__setattr__(
            repro_result,
            "evidence_ids",
            (ev_source.evidence_id, ev_log.evidence_id, ev_exit.evidence_id),
        )
        return repro_result


Reproduction = ReproductionEngine
