"""RF-05: real repair, portable persisted diff, isolation and policy rejection."""

import hashlib
import json
import shutil
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from resolveqa.contracts import Evidence, EvidenceKind, ReproOutcome, ReproResult, RunState, TriageRecord
from resolveqa.fix import FixStage, PatchRejected


@pytest.fixture
def inputs(tmp_path):
    root = Path(__file__).resolve().parents[2]
    shutil.copytree(root / "demo-target", tmp_path / "demo-target")
    (tmp_path / "config").mkdir()
    shutil.copyfile(root / "config/limits.json", tmp_path / "config/limits.json")
    case = RunState(
        case_id="case-fix", client_id="synthetic", repo_ref="demo-target",
        channel="simulated_chat", report_text="10% coupon leaves 200 instead of 180",
        state="reproduced", created_at="2026-11-08T00:00:00Z",
        updated_at="2026-11-08T00:00:00Z", base_revision="68c2955",
    )
    triage = TriageRecord(input="200, 10%", expected="180", observed="200",
                          suspect_files=("checkout.py",))
    repro = ReproResult(test_path="tests/test_generated_coupon.py", test_source_ref="test-source",
                        exit_code=1, outcome=ReproOutcome.RED_ON_ASSERTION,
                        failing_assertion="assert 200 == 180")
    return tmp_path, case, triage, repro


def test_real_minimal_patch_persists_and_applies(inputs):
    root, case, triage, repro = inputs
    stage = FixStage(root)
    source = root / case.repo_ref
    # Newly generated reproduction, separate from all baseline tests.
    test = source / repro.test_path
    test.write_text("from checkout import calculate_total\n"
                    "def test_coupon():\n"
                    "    assert calculate_total(200, coupon_code='DESC10') == 180\n")
    original = {p.relative_to(source): p.read_bytes() for p in source.rglob("*") if p.is_file()}
    with stage.sandbox.isolated_copy(case.repo_ref) as workspace:
        command = [sys.executable, "-m", "pytest", repro.test_path, "-q", "-p", "no:cacheprovider"]
        env = stage.sandbox.build_clean_env(workspace)
        before = subprocess.run(command, cwd=workspace, env=env, capture_output=True, text=True)
        assert before.returncode == 1
        assert "assert 200.0 == 180" in before.stdout
        patch = stage.run(case, triage, repro)
        diff_path = root / patch.diff_ref
        diff = diff_path.read_bytes()
        assert patch.files_changed == ("checkout.py",)
        assert not patch.touches_tests and not patch.touches_ci
        assert b"-    return round(float(subtotal), 2)" in diff
        assert b"+    return round(float(subtotal) - discount, 2)" in diff
        metadata = Evidence.from_json(diff_path.with_suffix(".json").read_text())
        assert metadata.kind == EvidenceKind.DIFF
        assert metadata.sha256 == hashlib.sha256(diff).hexdigest()
        assert metadata.case_id == case.case_id and not metadata.simulated
        assert root / "runs" / case.case_id / metadata.path == diff_path
        applied = subprocess.run(["git", "apply", "-"], input=diff, cwd=workspace,
                                 env=env, capture_output=True)
        assert applied.returncode == 0, applied.stderr
        after = subprocess.run(command, cwd=workspace, env=env, capture_output=True, text=True)
        assert after.returncode == 0, after.stdout + after.stderr
        suite = subprocess.run(command[:3] + ["tests", "-q", "-p", "no:cacheprovider"],
                               cwd=workspace, env=env, capture_output=True, text=True)
        assert suite.returncode == 0, suite.stdout + suite.stderr
        assert test.read_bytes() == (workspace / repro.test_path).read_bytes()
    assert original == {p.relative_to(source): p.read_bytes() for p in source.rglob("*") if p.is_file()}
    second = stage.run(case, triage, repro)
    assert second.diff_ref != patch.diff_ref
    assert diff_path.read_bytes() == diff


@pytest.mark.parametrize("path", ["tests/test_checkout.py", "test_checkout.py", ".github/workflows/ci.yml",
                                      ".gitlab-ci.yml", "pytest.ini", "repro_custom.py"])
def test_rejects_actual_test_and_ci_writes(inputs, path):
    root, case, triage, repro = inputs
    repro = replace(repro, test_path="repro_custom.py")

    class UnsafeRepair(FixStage):
        @staticmethod
        def _repair(workspace):
            FixStage._repair(workspace)
            target = workspace / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("changed\n")

    with pytest.raises(PatchRejected, match="tests or CI"):
        UnsafeRepair(root).run(case, triage, repro)
    assert not (root / "runs").exists()


def test_file_limit_counts_actual_diff(inputs):
    root, case, triage, repro = inputs

    class OversizedRepair(FixStage):
        @staticmethod
        def _repair(workspace):
            FixStage._repair(workspace)
            for name in ("a.py", "b.py", "c.py"):
                (workspace / name).write_text("new = True\n")

    with pytest.raises(PatchRejected, match="max_files_changed"):
        OversizedRepair(root).run(case, triage, repro)
    # A changed configured limit is read, not replaced by a hardcoded value.
    (root / "config/limits.json").write_text(json.dumps({"max_files_changed": 0}))
    with pytest.raises(PatchRejected, match="positive integer"):
        FixStage(root).run(case, triage, repro)


@pytest.mark.parametrize("outcome,exit_code", [(ReproOutcome.GREEN, 0), (ReproOutcome.ENV_ERROR, 1),
                                             (ReproOutcome.RED_ON_ASSERTION, 0)])
def test_requires_reproduced_assertion(inputs, outcome, exit_code):
    root, case, triage, repro = inputs
    with pytest.raises(PatchRejected, match="reproduction"):
        FixStage(root).run(case, triage, replace(repro, outcome=outcome, exit_code=exit_code))


def test_rejects_red_without_failing_assertion_before_writing(inputs):
    root, case, triage, repro = inputs
    with pytest.raises(PatchRejected, match="reproduction"):
        FixStage(root).run(
            case,
            triage,
            replace(repro, outcome=ReproOutcome.RED_ON_ASSERTION, exit_code=1, failing_assertion=None),
        )
    assert not (root / "runs").exists()


def test_patch_rejected_is_contract_validation_error():
    from resolveqa.contracts import ContractValidationError

    assert issubclass(PatchRejected, ContractValidationError)


def test_preserves_crlf_line_endings(inputs):
    root, case, triage, repro = inputs
    path = root / case.repo_ref / "checkout.py"
    lf = path.read_bytes()
    assert b"\r\n" not in lf
    path.write_bytes(lf.replace(b"\n", b"\r\n"))
    before = path.read_bytes()
    assert before.count(b"\r\n") == lf.count(b"\n")
    patch = FixStage(root).run(case, triage, repro)
    after = path.read_bytes()
    # Source repo copy is untouched; the isolated repair must not leak CRLF→LF.
    assert after == before
    diff = (root / patch.diff_ref).read_bytes()
    assert b"float(subtotal) - discount" in diff
    # Diff should not rewrite every line solely due to newline conversion.
    assert diff.count(b"\n") < 20


def test_rejects_unknown_cause_and_unrelated_triage(inputs):
    root, case, triage, repro = inputs
    with pytest.raises(PatchRejected, match="Triage"):
        FixStage(root).run(case, replace(triage, suspect_files=("unrelated.py",)), repro)
    path = root / case.repo_ref / "checkout.py"
    path.write_text(path.read_text().replace("return round(float(subtotal), 2)", "return 0"))
    with pytest.raises(PatchRejected, match="cause not found"):
        FixStage(root).run(case, triage, repro)


def test_rejects_evidence_traversal_and_symlink(inputs, tmp_path):
    root, case, triage, repro = inputs
    with pytest.raises(PatchRejected, match="case_id"):
        FixStage(root).run(replace(case, case_id="../escape"), triage, repro)
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "runs").symlink_to(outside, target_is_directory=True)
    with pytest.raises(PatchRejected, match="symlinks"):
        FixStage(root).run(case, triage, repro)
    assert list(outside.iterdir()) == []


# ==============================================================================
# LLMFixStage Tests (Issue #11 - LLM-based repair with Plan B fallback)
# ==============================================================================

from resolveqa.contracts import FixStage as FixStageProtocol
from resolveqa.fix import LLMFix, LLMFixStage
from resolveqa.llm import LLMAdapter, LLMProviderError


def test_llm_fix_implements_fix_stage_protocol():
    stage = LLMFixStage()
    assert isinstance(stage, FixStageProtocol)
    assert LLMFix is LLMFixStage


def test_llm_fix_valid_patch_fixes_coupon_and_repro_passes(inputs):
    """Test 1: patch válido corrige o cupom (teste de reprodução falha antes e passa depois numa cópia)."""
    root, case, triage, repro = inputs
    stage = LLMFixStage(root, llm=LLMAdapter())
    source = root / case.repo_ref

    test = source / repro.test_path
    test.write_text(
        "from checkout import calculate_total\n"
        "def test_coupon():\n"
        "    assert calculate_total(200, coupon_code='DESC10') == 180\n"
    )

    with stage.sandbox.isolated_copy(case.repo_ref) as workspace:
        command = [sys.executable, "-m", "pytest", repro.test_path, "-q", "-p", "no:cacheprovider"]
        env = stage.sandbox.build_clean_env(workspace)

        # Before fix: repro test fails
        before = subprocess.run(command, cwd=workspace, env=env, capture_output=True, text=True)
        assert before.returncode == 1
        assert "assert 200.0 == 180" in before.stdout

        # Run LLM fix
        patch = stage.run(case, triage, repro)
        diff_path = root / patch.diff_ref
        assert diff_path.is_file()
        diff = diff_path.read_bytes()

        assert patch.files_changed == ("checkout.py",)
        assert not patch.touches_tests and not patch.touches_ci
        assert b"-    return round(float(subtotal), 2)" in diff
        assert b"+    return round(float(subtotal) - discount, 2)" in diff

        # Evidence verified
        metadata = Evidence.from_json(diff_path.with_suffix(".json").read_text())
        assert metadata.kind == EvidenceKind.DIFF
        assert metadata.sha256 == hashlib.sha256(diff).hexdigest()
        assert metadata.case_id == case.case_id
        assert metadata.simulated  # Mock LLM is marked simulated

        # Apply patch via git apply
        applied = subprocess.run(
            ["git", "apply", "-"],
            input=diff,
            cwd=workspace,
            env=env,
            capture_output=True,
        )
        assert applied.returncode == 0, applied.stderr

        # After fix: repro test passes
        after = subprocess.run(command, cwd=workspace, env=env, capture_output=True, text=True)
        assert after.returncode == 0, after.stdout + after.stderr

        # Full target test suite passes
        suite = subprocess.run(
            command[:3] + ["tests", "-q", "-p", "no:cacheprovider"],
            cwd=workspace,
            env=env,
            capture_output=True,
            text=True,
        )
        assert suite.returncode == 0, suite.stdout + suite.stderr


def test_llm_fix_rejects_patch_touching_tests_or_ci(inputs):
    """Test 2: patch que mexe em teste é recusado com PatchRejected."""
    root, case, triage, repro = inputs
    bad_patch_payload = json.dumps({
        "file": "tests/test_checkout.py",
        "search": "def test_something():",
        "replace": "def test_something(): pass",
    })
    llm = LLMAdapter(response_override=bad_patch_payload)
    stage = LLMFixStage(root, llm=llm)

    with pytest.raises(PatchRejected, match="protected|outside allowed|rejected by validation"):
        stage.run(case, triage, repro)


def test_llm_fix_rejects_patch_with_4_files(inputs):
    """Test 3: patch com 4 arquivos é recusado (excede max_files_changed=3)."""
    root, case, triage, repro = inputs

    # Create dummy files in target repo so search/replace can target them
    source = root / case.repo_ref
    for name in ("a.py", "b.py", "c.py"):
        (source / name).write_text("x = 1\n")

    triage_4 = replace(triage, suspect_files=("checkout.py", "a.py", "b.py", "c.py"))
    patch_4_payload = json.dumps([
        {
            "file": "checkout.py",
            "search": "    discount = round(float(subtotal) * (pct / 100.0), 2)\n    return round(float(subtotal), 2)",
            "replace": "    discount = round(float(subtotal) * (pct / 100.0), 2)\n    return round(float(subtotal) - discount, 2)",
        },
        {"file": "a.py", "search": "x = 1", "replace": "x = 2"},
        {"file": "b.py", "search": "x = 1", "replace": "x = 2"},
        {"file": "c.py", "search": "x = 1", "replace": "x = 2"},
    ])
    llm = LLMAdapter(response_override=patch_4_payload)
    stage = LLMFixStage(root, llm=llm)

    with pytest.raises(PatchRejected, match="max_files_changed"):
        stage.run(case, triage_4, repro)


def test_llm_fix_failure_falls_back_to_labeled_plan_b(inputs):
    """Test 4: falha do LLM cai no plano B rotulado (simulated=True)."""
    root, case, triage, repro = inputs

    class FailingLLM:
        def complete(self, *args, **kwargs):
            raise LLMProviderError("Simulated LLM network timeout")

    stage = LLMFixStage(root, llm=FailingLLM(), allow_fallback=True)
    patch = stage.run(case, triage, repro)

    assert patch.files_changed == ("checkout.py",)
    assert not patch.touches_tests and not patch.touches_ci

    diff_path = root / patch.diff_ref
    assert diff_path.is_file()
    metadata = Evidence.from_json(diff_path.with_suffix(".json").read_text())
    assert metadata.kind == EvidenceKind.DIFF
    assert metadata.simulated is True  # Plan B is explicitly labeled as simulated
    assert b"+    return round(float(subtotal) - discount, 2)" in diff_path.read_bytes()


def test_llm_fix_without_fallback_raises_on_llm_failure(inputs):
    """When allow_fallback=False, LLM failure raises PatchRejected without falling back."""
    root, case, triage, repro = inputs

    class FailingLLM:
        def complete(self, *args, **kwargs):
            raise LLMProviderError("LLM error")

    stage = LLMFixStage(root, llm=FailingLLM(), allow_fallback=False)
    with pytest.raises(PatchRejected, match="LLM fix generation failed"):
        stage.run(case, triage, repro)
