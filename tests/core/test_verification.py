"""Real process tests for RF-06; no Fix/LLM dependency or execution doubles."""

import difflib
import hashlib
import json
import shutil
from dataclasses import replace
from pathlib import Path

import pytest

from resolveqa.contracts import Evidence, Patch, ReproResult, RunState, Verdict
from resolveqa.verification import VerificationStage


@pytest.fixture
def setup(tmp_path):
    repository = Path(__file__).resolve().parents[2]
    shutil.copytree(repository / 'demo-target', tmp_path / 'demo-target')
    (tmp_path / 'config').mkdir()
    shutil.copyfile(repository / 'config/limits.json', tmp_path / 'config/limits.json')
    case = RunState(case_id='verification-case', client_id='synthetic', repo_ref='demo-target',
                    channel='api', report_text='Coupon should reduce 200 to 180', state='verifying',
                    created_at='2026-11-08T00:00:00Z', updated_at='2026-11-08T00:00:00Z',
                    base_revision='untrusted-input-revision', fix_revision='untrusted-fix-revision')
    directory = tmp_path / 'runs' / case.case_id / 'evidence'
    directory.mkdir(parents=True)
    source = directory / 'reproduction.py'
    source.write_text("from checkout import calculate_total\n"
                      "def test_generated_coupon():\n"
                      "    assert calculate_total(200, coupon_code='DESC10') == 180\n")
    repro = ReproResult(test_path='tests/test_generated_coupon.py',
                        test_source_ref=source.relative_to(tmp_path).as_posix(),
                        exit_code=1, outcome='red_on_assertion', failing_assertion='assert 200.0 == 180')
    original = (tmp_path / 'demo-target/checkout.py').read_text()

    def make_patch(replacement='return round(float(subtotal) - discount, 2)', path='checkout.py'):
        old = original if path == 'checkout.py' else 'old = True\n'
        new = old.replace('return round(float(subtotal), 2)', replacement) if path == 'checkout.py' else 'new = True\n'
        diff = ''.join(difflib.unified_diff(old.splitlines(keepends=True), new.splitlines(keepends=True),
                                             fromfile='a/' + path, tofile='b/' + path))
        artifact = directory / 'fixture.diff'
        artifact.write_text(diff)
        return Patch(diff_ref=artifact.relative_to(tmp_path).as_posix(), files_changed=(path,))

    return tmp_path, case, repro, make_patch


def run(setup, patch=None):
    root, case, repro, make_patch = setup
    return VerificationStage(root).run(case, repro, patch or make_patch())


def logs(root, verdict):
    return [json.loads((root / record.log_ref).read_text())
            for record in (verdict.before, verdict.after, verdict.suite)]


def test_verified_requires_real_executions_and_evidence(setup):
    root, case, repro, make_patch = setup
    original = {p.relative_to(root / case.repo_ref): p.read_bytes()
                for p in (root / case.repo_ref).rglob('*') if p.is_file()}
    verdict = run(setup)
    assert verdict.result == 'verified', verdict.reasons
    assert [verdict.before.exit_code, verdict.after.exit_code, verdict.suite.exit_code] == [1, 0, 0]
    assert verdict.base_revision.startswith('sha256:')
    assert verdict.fix_revision.startswith('sha256:')
    assert verdict.base_revision != verdict.fix_revision
    assert verdict.base_revision != case.base_revision
    reports = logs(root, verdict)
    assert all(log['executed'] and not log['env_error'] for log in reports)
    assert reports[0]['reports']['assertions'] == 1
    assert reports[1]['reports']['passed'] == 1
    assert reports[2]['reports']['passed'] == 5
    assert verdict.before.command == verdict.after.command
    assert 'assert 200.0 == 180' in reports[0]['stdout']
    for record in (verdict.before, verdict.after, verdict.suite):
        path = root / record.log_ref
        evidence = Evidence.from_json(path.with_suffix('.meta.json').read_text())
        assert evidence.kind == 'test_log' and not evidence.simulated
        assert evidence.sha256 == hashlib.sha256(path.read_bytes()).hexdigest()
        assert root / 'runs' / case.case_id / evidence.path == path
    artifacts = list((root / 'runs' / case.case_id / 'evidence').glob('*.meta.json'))
    verdict_refs = [Evidence.from_json(p.read_text()) for p in artifacts
                    if json.loads(p.read_text())['kind'] == 'verdict']
    assert len(verdict_refs) == 1
    persisted = root / 'runs' / case.case_id / verdict_refs[0].path
    assert Verdict.from_json(persisted.read_text()) == verdict
    assert original == {p.relative_to(root / case.repo_ref): p.read_bytes()
                        for p in (root / case.repo_ref).rglob('*') if p.is_file()}


def test_rejects_patch_that_does_not_fix_assertion(setup):
    root, _, _, make_patch = setup
    verdict = run(setup, make_patch('return round(float(subtotal) * 1, 2)'))
    assert verdict.result == 'rejected'
    assert verdict.before.exit_code == verdict.after.exit_code == 1
    assert verdict.suite.command.startswith('NOT_RUN')
    assert logs(root, verdict)[2]['executed'] is False


def test_rejects_regression_in_suite(setup):
    *_, make_patch = setup
    verdict = run(setup, make_patch('return round(float(subtotal) - discount - (1 if pct == 0 else 0), 2)'))
    assert verdict.result == 'rejected'
    assert verdict.after.exit_code == 0 and verdict.suite.exit_code == 1


def test_rejects_green_before(setup):
    root, _, repro, _ = setup
    (root / repro.test_source_ref).write_text('def test_green():\n    assert True\n')
    verdict = run(setup)
    assert verdict.result == 'rejected'
    assert verdict.before.exit_code == 0 and verdict.after.command.startswith('NOT_RUN')


@pytest.mark.parametrize('source', [
    'import nonexistent_rqa_dependency\n',
    'def test_runtime():\n    raise RuntimeError("not an assertion")\n',
])
def test_environment_and_runtime_errors_are_not_reproductions(setup, source):
    root, _, repro, _ = setup
    (root / repro.test_source_ref).write_text(source)
    verdict = run(setup)
    assert verdict.result == 'env_error'
    assert verdict.after.command.startswith('NOT_RUN')
    assert logs(root, verdict)[0]['reports']['errors'] > 0


def test_timeout_has_real_log_and_env_error(setup):
    root, _, repro, _ = setup
    (root / repro.test_source_ref).write_text('import time\ndef test_timeout():\n    time.sleep(10)\n')
    limits = json.loads((root / 'config/limits.json').read_text())
    limits['test_timeout_s'] = 0.1
    (root / 'config/limits.json').write_text(json.dumps(limits))
    verdict = run(setup)
    assert verdict.result == 'env_error'
    assert logs(root, verdict)[0]['timed_out'] is True
    assert verdict.after.exit_code == -1


@pytest.mark.parametrize('path', ['tests/test_checkout.py', '.github/workflows/ci.yml',
                                  'reproduction_custom.py', '.gitlab-ci.yml'])
def test_rejects_hidden_test_and_ci_changes_before_execution(setup, path):
    root, case, repro, make_patch = setup
    if path == 'reproduction_custom.py':
        repro = replace(repro, test_path=path)
        setup = root, case, repro, make_patch
    verdict = run(setup, make_patch(path=path))
    assert verdict.result == 'rejected'
    assert all(not log['executed'] for log in logs(root, verdict))
    assert verdict.base_revision == verdict.fix_revision


@pytest.mark.parametrize('flag', ['touches_tests', 'touches_ci'])
def test_declared_protected_changes_are_rejected(setup, flag):
    *_, make_patch = setup
    verdict = run(setup, replace(make_patch(), **{flag: True}))
    assert verdict.result == 'rejected'


def test_rejects_mismatched_metadata(setup):
    *_, make_patch = setup
    verdict = run(setup, replace(make_patch(), files_changed=('innocent.py',)))
    assert verdict.result == 'rejected'
    assert 'metadata' in verdict.reasons[0]


def test_enforces_configured_file_limit(setup):
    root, case, _, make_patch = setup
    patch = make_patch()
    second = root / case.repo_ref / 'extra.py'
    second.write_text('old = True\n')
    artifact = root / patch.diff_ref
    artifact.write_text(artifact.read_text() + ''.join(difflib.unified_diff(
        ['old = True\n'], ['new = True\n'], fromfile='a/extra.py', tofile='b/extra.py')))
    limits = json.loads((root / 'config/limits.json').read_text())
    limits['max_files_changed'] = 1
    (root / 'config/limits.json').write_text(json.dumps(limits))
    verdict = run(setup, replace(patch, files_changed=('checkout.py', 'extra.py')))
    assert verdict.result == 'rejected' and 'file count' in verdict.reasons[0]


def test_missing_diff_is_env_error_and_does_not_invent_results(setup):
    root, _, _, make_patch = setup
    patch = make_patch()
    (root / patch.diff_ref).unlink()
    verdict = run(setup, patch)
    assert verdict.result == 'env_error'
    assert all(log['executed'] is False and log['exit_code'] is None for log in logs(root, verdict))


def test_rejects_cross_case_artifact(setup):
    *_, make_patch = setup
    verdict = run(setup, replace(make_patch(), diff_ref='runs/other-case/evidence/fixture.diff'))
    assert verdict.result == 'rejected'


def test_patch_introducing_import_error_never_verifies(setup):
    *_, make_patch = setup
    verdict = run(setup, make_patch('return missing_symbol'))
    assert verdict.result == 'env_error'
    assert verdict.before.exit_code == 1 and verdict.after.exit_code == 1


def test_skipped_reproduction_never_verifies(setup):
    root, _, repro, _ = setup
    (root / repro.test_source_ref).write_text('import pytest\n@pytest.mark.skip\ndef test_skip():\n    pass\n')
    verdict = run(setup)
    assert verdict.result == 'rejected'
    assert verdict.after.command.startswith('NOT_RUN')


def test_existing_reproduction_must_match_recorded_evidence(setup):
    root, case, repro, _ = setup
    target = root / case.repo_ref / repro.test_path
    target.write_text('def test_unrelated():\n    assert False\n')
    verdict = run(setup)
    assert verdict.result == 'rejected'
    assert 'recorded test source' in verdict.reasons[0]
    assert all(not log['executed'] for log in logs(root, verdict))


def test_existing_matching_reproduction_is_verified(setup):
    root, case, repro, _ = setup
    target = root / case.repo_ref / repro.test_path
    target.write_bytes((root / repro.test_source_ref).read_bytes())
    verdict = run(setup)
    assert verdict.result == 'verified'
    assert target.read_bytes() == (root / repro.test_source_ref).read_bytes()
