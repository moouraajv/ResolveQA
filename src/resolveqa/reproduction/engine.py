"""Reproduction stage implementation (Issue #10, RF-04, RFC-0001 §3.3)."""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
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

_GENUINE_ENV_ERROR_MARKERS = (
    "ImportError",
    "ModuleNotFoundError",
    "SyntaxError",
    "IndentationError",
    "TabError",
    "No such file or directory",
    "command not found",
    "Target repository",
    "does not exist",
)


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


def _extract_genuine_failing_assertion(log: str, triage: TriageRecord) -> Optional[str]:
    """B1: Verify that the failure is from a test method (FAIL: test_*), not setUp/import/module,

    that the AssertionError originated inside a test_* method, and that triage.expected is in the failed comparison.
    """
    fail_match = re.search(r"^FAIL:\s+(test_\w+)", log, re.MULTILINE)
    if not fail_match:
        return None
    test_method_name = fail_match.group(1)

    fail_sections = re.split(r"={10,}", log)
    target_section = ""
    for sec in fail_sections:
        if f"FAIL: {test_method_name}" in sec:
            target_section = sec
            break

    if not target_section:
        target_section = log

    frame_matches = re.findall(r'File "([^"]+)", line \d+, in (\w+)', target_section)
    if not frame_matches:
        return None
    _, last_func = frame_matches[-1]
    if last_func == "<module>" or last_func == "setUp" or not last_func.startswith("test_"):
        return None

    assertion_line = ""
    for line in target_section.splitlines():
        stripped = line.strip()
        if (
            stripped.startswith("AssertionError:")
            or stripped.startswith("assert ")
            or "AssertionError" in stripped
        ):
            assertion_line = stripped

    if not assertion_line:
        return None

    exp_nums = _normalize_numbers(triage.expected)
    if exp_nums:
        assertion_nums = _normalize_numbers(assertion_line)
        has_expected_in_comparison = any(
            any(abs(en - an) < 1e-2 for an in assertion_nums) for en in exp_nums
        )
        if not has_expected_in_comparison:
            has_expected_text = any(
                str(int(en)) in assertion_line if en.is_integer() else f"{en:.2f}" in assertion_line
                for en in exp_nums
            )
            if not has_expected_text:
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

    def _execute_in_sandbox(self, case: RunState, test_code: str, test_rel_path: str) -> ExecResult:
        """B2 & B5: Prepare isolated copy in tempfile.mkdtemp outside repo with test_code, and run it via self.sandbox.exec."""
        source_repo = (self.base_root / case.repo_ref).resolve()
        if not source_repo.is_relative_to(self.base_root) or not source_repo.is_dir():
            return ExecResult(
                exit_code=1,
                stdout_ref="",
                stderr_ref=f"Target repository {case.repo_ref!r} does not exist in {self.base_root}",
                timed_out=False,
            )

        temp_parent = Path(tempfile.mkdtemp(prefix="resolveqa_repro_"))
        stage_dir = temp_parent / Path(case.repo_ref).name
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
            if local is not None:
                old_base = local.base_root
                try:
                    local.base_root = temp_parent
                    return self.sandbox.exec(
                        stage_dir.name,
                        f"python3 -m unittest {test_rel_path}",
                        timeout_s=self.timeout_s,
                    )
                finally:
                    local.base_root = old_base
            else:
                try:
                    return self.sandbox.exec(
                        str(stage_dir),
                        f"python3 -m unittest {test_rel_path}",
                        timeout_s=self.timeout_s,
                    )
                except Exception:
                    return self.sandbox.exec(
                        stage_dir.name,
                        f"python3 -m unittest {test_rel_path}",
                        timeout_s=self.timeout_s,
                    )
        finally:
            shutil.rmtree(temp_parent, ignore_errors=True)

    def _classify_outcome(
        self, exec_res: ExecResult, triage: TriageRecord
    ) -> tuple[ReproOutcome, Optional[str]]:
        """B1 & B3: Classify execution outcome.

        - RED_ON_ASSERTION: Genuine assertion failure in a test_* method comparing against expected.
        - GREEN: Test passed OR defect not reproduced (assertion not linked to expected, or target code exception TypeError/AttributeError/NameError).
        - ENV_ERROR: Genuine environment/infrastructure errors (ImportError, syntax error, timeout, missing repo).
        """
        if exec_res.timed_out:
            return (ReproOutcome.ENV_ERROR, None)

        combined_log = f"{exec_res.stdout_ref}\n{exec_res.stderr_ref}"

        # Check for genuine environment/import failures first
        for marker in _GENUINE_ENV_ERROR_MARKERS:
            if marker in combined_log:
                return (ReproOutcome.ENV_ERROR, None)

        if exec_res.exit_code == 0:
            return (ReproOutcome.GREEN, None)

        # B1: Check for genuine test assertion failure matching triage.expected
        failing_assertion = _extract_genuine_failing_assertion(combined_log, triage)
        if failing_assertion is not None:
            return (ReproOutcome.RED_ON_ASSERTION, failing_assertion)

        # B3 DECISÃO DA EQUIPE:
        # Asserção não ligada ao esperado e exceções de código-alvo (TypeError, AttributeError, NameError)
        # NÃO são RED nem env_error: devolve GREEN ("não reproduzido") para o orquestrador bloquear com blocked/not_reproduced.
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
        exec_res = self._execute_in_sandbox(case, test_code, test_rel_path)
        outcome, failing_assertion = self._classify_outcome(exec_res, triage)

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
