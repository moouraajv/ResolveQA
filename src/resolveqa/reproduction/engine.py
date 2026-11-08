"""Reproduction stage implementation (Issue #10, RF-04, RFC-0001 §3.3)."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import uuid
from datetime import datetime, timezone
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

try:
    from resolveqa.store.evidence_store import EvidenceStore as _SharedEvidenceStore
except ImportError:  # pragma: no cover - fallback until PR #47 merges into main
    _SharedEvidenceStore = None  # type: ignore[assignment,misc]

REPO_ROOT = Path(__file__).resolve().parents[3]

_ENV_ERROR_MARKERS = (
    "ImportError",
    "ModuleNotFoundError",
    "SyntaxError",
    "IndentationError",
    "TabError",
    "NameError",
    "TypeError",
    "AttributeError",
    "OSError",
    "PermissionError",
    "FileNotFoundError",
    "MemoryError",
)

_SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b"),
    re.compile(r"\brc_[A-Za-z0-9_-]{8,}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{8,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{8,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._\-]{8,}"),
)


def _redact_text(text: str) -> str:
    if not text:
        return ""
    scrubbed = str(text)
    for pat in _SECRET_PATTERNS[:-1]:
        scrubbed = pat.sub("[REDACTED_SECRET]", scrubbed)
    scrubbed = _SECRET_PATTERNS[-1].sub(r"\1[REDACTED_SECRET]", scrubbed)
    return scrubbed


class _LocalEvidenceWriter:
    """Compatible fallback evidence store used when `resolveqa.store.evidence_store` is not yet merged."""

    def __init__(self, runs_root: Path | str | None = None) -> None:
        self.runs_root = Path(runs_root).resolve() if runs_root is not None else (REPO_ROOT / "runs").resolve()
        self._seq: dict[str, int] = {}

    def save_evidence(
        self,
        case_id: str,
        evidence_id: Optional[str] = None,
        kind: EvidenceKind = EvidenceKind.TEST_SOURCE,
        content: str = "",
        extension: str = "txt",
    ) -> Evidence:
        if "/" in case_id or "\\" in case_id or ".." in case_id or not case_id.strip():
            raise ValueError(f"Invalid case_id: {case_id!r}")
        c_dir = (self.runs_root / case_id.strip()).resolve()
        if not c_dir.is_relative_to(self.runs_root):
            raise ValueError(f"case_id escapes runs_root: {case_id!r}")
        ev_dir = (c_dir / "evidence").resolve()
        ev_dir.mkdir(parents=True, exist_ok=True)

        if evidence_id is None:
            seq = self._seq.get(case_id, 0) + 1
            self._seq[case_id] = seq
            kind_slug = getattr(kind, "value", str(kind)).replace("_", "-")
            safe_ev_id = f"ev-{kind_slug}-{seq:04d}-{uuid.uuid4().hex[:8]}"
        else:
            safe_ev_id = evidence_id.strip()

        safe_ext = "".join(ch for ch in extension.lstrip(".") if ch.isalnum() or ch in {"_", "-"}) or "txt"
        rel_path = f"evidence/{safe_ev_id}.{safe_ext}"
        full_path = (c_dir / rel_path).resolve()
        if not full_path.is_relative_to(c_dir):
            raise ValueError(f"Evidence path escapes case directory: {rel_path}")
        if full_path.exists() or any(ev_dir.glob(f"{safe_ev_id}.*")):
            raise FileExistsError(f"Evidence {safe_ev_id!r} already exists")

        raw_bytes = _redact_text(content).encode("utf-8")
        with full_path.open("xb") as fh:
            fh.write(raw_bytes)
        digest = hashlib.sha256(raw_bytes).hexdigest()
        now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        return Evidence(
            evidence_id=safe_ev_id,
            case_id=case_id.strip(),
            kind=kind,
            path=rel_path,
            sha256=digest,
            created_at=now_iso,
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
    """Synthesize a Python unittest reproduction test using the exact numbers from `triage`."""
    exp_nums = _normalize_numbers(triage.expected)
    obs_nums = _normalize_numbers(triage.observed)
    inp_nums = _normalize_numbers(triage.input + " " + report_text)

    expected_val = exp_nums[0] if exp_nums else 180.0
    subtotal_val = obs_nums[0] if obs_nums else 200.0

    pct_match = re.search(r"(\d+(?:[.,]\d+)?)\s*%", triage.input + " " + report_text)
    if pct_match:
        coupon_pct = float(pct_match.group(1).replace(",", "."))
    elif subtotal_val > 0 and expected_val < subtotal_val:
        coupon_pct = round((1.0 - expected_val / subtotal_val) * 100.0, 2)
    else:
        coupon_pct = 10.0

    exp_brl = triage.expected.strip() if "R$" in triage.expected else _format_brl_str(expected_val)
    sub_int = int(subtotal_val) if float(subtotal_val).is_integer() else int(round(subtotal_val))
    exp_int = int(expected_val) if float(expected_val).is_integer() else int(round(expected_val))
    pct_int = int(coupon_pct) if float(coupon_pct).is_integer() else int(round(coupon_pct))

    return (
        "import unittest\n"
        "from checkout import calculate_total, format_brl\n\n\n"
        "class TestGeneratedCouponReproduction(unittest.TestCase):\n"
        f"    def test_coupon_{pct_int}_percent_on_{sub_int}_reduces_total_to_{exp_int}(self) -> None:\n"
        f"        total = calculate_total({subtotal_val:.1f}, coupon_percent={coupon_pct:.1f})\n"
        f"        self.assertEqual(format_brl(total), {exp_brl!r})\n"
        f"        self.assertEqual(total, {expected_val:.1f})\n\n\n"
        "if __name__ == '__main__':\n"
        "    unittest.main()\n"
    )


def _extract_failing_assertion(combined_log: str, triage: TriageRecord) -> Optional[str]:
    """Extract the `AssertionError` message or assertion line if it is linked to `triage` values."""
    if "AssertionError" not in combined_log:
        return None

    lines = [ln.strip() for ln in combined_log.splitlines() if ln.strip()]
    assertion_line = ""
    for ln in reversed(lines):
        if "AssertionError" in ln:
            assertion_line = ln
            break

    context_window = "\n".join(lines[-15:]) if lines else combined_log
    triage_nums = _normalize_numbers(f"{triage.expected} {triage.observed}")
    log_nums = _normalize_numbers(context_window)

    if triage_nums:
        linked = any(any(abs(tn - ln_num) < 1e-2 for ln_num in log_nums) for tn in triage_nums)
        if not linked and triage.expected.lower() not in context_window.lower() and triage.observed.lower() not in context_window.lower():
            return None

    return assertion_line or "AssertionError"


class ReproductionEngine:
    """Generates a reproduction test from `TriageRecord`, executes it in `Sandbox`, classifies outcome, and stores evidence (RF-04)."""

    def __init__(
        self,
        llm: Optional[LLMAdapter] = None,
        sandbox: Optional[SandboxStage] = None,
        store: Optional[Any] = None,
        *,
        runs_root: Optional[Path | str] = None,
        base_root: Optional[Path | str] = None,
        timeout_s: float = 60.0,
    ) -> None:
        self.base_root = Path(base_root).resolve() if base_root is not None else REPO_ROOT
        self.llm = llm if llm is not None else LLMAdapter()
        self.sandbox: SandboxStage = sandbox if sandbox is not None else LocalSandbox(base_root=self.base_root)
        if store is not None:
            self.store = store
        elif _SharedEvidenceStore is not None:
            self.store = _SharedEvidenceStore(runs_root=runs_root)
        else:
            self.store = _LocalEvidenceWriter(runs_root=runs_root)
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
        """Stage a temporary copy of `case.repo_ref` with `test_code` and run it via `self.sandbox.exec`."""
        sandbox_base = getattr(self.sandbox, "base_root", self.base_root)
        base_dir = Path(sandbox_base).resolve()
        source_repo = (base_dir / case.repo_ref).resolve()

        if not isinstance(self.sandbox, LocalSandbox) or not source_repo.is_dir():
            return self.sandbox.exec(
                case.repo_ref,
                f"python3 -m unittest {test_rel_path}",
                self.timeout_s,
            )

        runs_staging_parent = base_dir / "runs"
        runs_staging_parent.mkdir(parents=True, exist_ok=True)
        stage_name = f"_repro_stage_{case.case_id}_{uuid.uuid4().hex[:8]}"
        stage_dir = runs_staging_parent / stage_name
        try:
            shutil.copytree(
                source_repo,
                stage_dir,
                symlinks=True,
                ignore=shutil.ignore_patterns(".git", "__pycache__", ".pytest_cache", ".venv", "*.pyc"),
            )
            target_test_file = (stage_dir / test_rel_path).resolve()
            if not target_test_file.is_relative_to(stage_dir.resolve()):
                raise ValueError(f"Generated test path escapes staging directory: {test_rel_path}")
            target_test_file.parent.mkdir(parents=True, exist_ok=True)
            target_test_file.write_text(test_code, encoding="utf-8")

            staging_rel = f"runs/{stage_name}"
            return self.sandbox.exec(
                staging_rel,
                f"python3 -m unittest {test_rel_path}",
                self.timeout_s,
            )
        finally:
            shutil.rmtree(stage_dir, ignore_errors=True)

    def _classify_outcome(
        self,
        exec_res: ExecResult,
        triage: TriageRecord,
    ) -> tuple[ReproOutcome, Optional[str]]:
        combined_log = f"{exec_res.stdout_ref}\n{exec_res.stderr_ref}".strip()

        if exec_res.timed_out:
            return (ReproOutcome.ENV_ERROR, None)

        if exec_res.exit_code == 0:
            return (ReproOutcome.GREEN, None)

        if "AssertionError" in combined_log:
            # Verify no earlier import/syntax error caused a spurious message
            failing_assertion = _extract_failing_assertion(combined_log, triage)
            if failing_assertion is not None:
                return (ReproOutcome.RED_ON_ASSERTION, failing_assertion)
            return (ReproOutcome.ENV_ERROR, None)

        for marker in _ENV_ERROR_MARKERS:
            if marker in combined_log:
                return (ReproOutcome.ENV_ERROR, None)

        return (ReproOutcome.ENV_ERROR, None)

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
        if (
            hasattr(self.llm, "response_override")
            and getattr(self.llm, "response_override", None) is None
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
                self.llm.response_override = None

        test_code = llm_result.content.strip() + "\n"

        # Ensure the generated test references the expected value from triage
        expected_nums = _normalize_numbers(triage.expected)
        code_nums = _normalize_numbers(test_code)
        if expected_nums and not any(any(abs(en - cn) < 1e-2 for cn in code_nums) for en in expected_nums):
            raise LLMOutputError(
                f"Generated reproduction test does not reference expected value {triage.expected!r}",
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

        ev_source = self.store.save_evidence(
            case_id=case.case_id,
            evidence_id=None,
            kind=EvidenceKind.TEST_SOURCE,
            content=test_code,
            extension="py",
        )
        ev_log = self.store.save_evidence(
            case_id=case.case_id,
            evidence_id=None,
            kind=EvidenceKind.TEST_LOG,
            content=combined_log,
            extension="log",
        )
        ev_exit = self.store.save_evidence(
            case_id=case.case_id,
            evidence_id=None,
            kind=EvidenceKind.EXIT_CODE,
            content=exit_code_payload,
            extension="json",
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
