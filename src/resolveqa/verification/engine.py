"""Verify real pytest executions in LocalSandbox copies without using an LLM.

Artifact references are relative to base_root; Evidence paths are case-relative.
Revision identifiers are SHA-256 hashes of actual target trees, not invented Git
commits. A NOT_RUN TestRun has exit_code=-1 and an explicit non-execution log.
Only in-place regular text modifications are supported by this MVP verifier.
"""

from __future__ import annotations

import hashlib
import json
import re
import shlex
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from resolveqa.contracts import Evidence, EvidenceKind, Patch, ReproOutcome, ReproResult, RunState, TestRun, Verdict
from resolveqa.sandbox.executor import LocalSandbox, redact_secrets


# Trusted runner records assertion failures separately from collection/runtime
# errors and skips. Test paths remain argv data, never interpolated Python.
_RUNNER = '''import json, sys, pytest
class Reports:
    def __init__(self):
        self.data = dict(passed=0, assertions=0, errors=0, skipped=0)
    @pytest.hookimpl(hookwrapper=True)
    def pytest_runtest_makereport(self, item, call):
        report = (yield).get_result()
        if report.skipped:
            self.data['skipped'] += 1
        elif report.failed:
            key = 'assertions' if report.when == 'call' and call.excinfo and call.excinfo.errisinstance(AssertionError) else 'errors'
            self.data[key] += 1
        elif report.when == 'call' and report.passed:
            self.data['passed'] += 1
    def pytest_collectreport(self, report):
        if report.failed:
            self.data['errors'] += 1
plugin = Reports()
code = pytest.main(['-q', '-p', 'no:cacheprovider', '--', sys.argv[1]], plugins=[plugin])
print('RQA_RESULT=' + json.dumps(plugin.data), flush=True)
sys.exit(int(code))
'''


class _Rejected(ValueError):
    pass


def _relative(value: str) -> Path:
    path = Path(value)
    if (not value or path.is_absolute() or path == Path('.') or '..' in path.parts
            or '\\' in value or any(ord(c) < 32 for c in value)):
        raise _Rejected("Unsafe relative path")
    return path


def _snapshot(root: Path) -> dict[str, bytes]:
    result = {}
    for path in root.rglob('*'):
        if path.is_symlink():
            raise _Rejected("Symlink targets are unsupported")
        if path.is_file():
            result[path.relative_to(root).as_posix()] = path.read_bytes()
    return result


def _revision(files: dict[str, bytes]) -> str:
    digest = hashlib.sha256()
    for path, content in sorted(files.items()):
        digest.update(path.encode() + b'\0' + str(len(content)).encode() + b'\0' + content)
    return 'sha256:' + digest.hexdigest()


def _protected(path: str, repro_path: str) -> bool:
    parts = Path(path).parts
    name = parts[-1].lower()
    return (path == repro_path
            or any(p.lower() in {'test', 'tests', '__tests__', '.github', '.circleci', '.buildkite', 'ci'} for p in parts)
            or name.startswith(('test_', '.gitlab-ci'))
            or name.endswith(('_test.py', '.test.js', '.spec.js', '.test.ts', '.spec.ts'))
            or name in {'conftest.py', 'pytest.ini', 'tox.ini', 'pyproject.toml', 'setup.cfg',
                        'jenkinsfile', 'azure-pipelines.yml', '.travis.yml'})


class VerificationStage:
    """Run independent before/after reproduction and the complete target suite.

    Reproduction source must exist at repro.test_path in the target or at a
    case-local test_source_ref artifact (relative to base_root). No source is
    generated here. All commands use LocalSandbox's clean environment and
    timeout; a new execution copy is made for each test invocation.
    """

    def __init__(self, base_root: Path | str | None = None) -> None:
        self.sandbox = LocalSandbox(base_root=base_root)
        self.base_root = self.sandbox.base_root

    def _artifact(self, reference: str, case: RunState) -> Path:
        path = self.base_root / _relative(reference)
        allowed = self.base_root / 'runs' / case.case_id / 'evidence'
        if not path.resolve().is_relative_to(allowed.resolve()):
            raise _Rejected("Artifact must belong to this case's evidence directory")
        current = self.base_root
        for part in path.relative_to(self.base_root).parts:
            current = current / part
            if current.is_symlink():
                raise _Rejected("Artifact symlinks are forbidden")
        return path

    def _save(self, case: RunState, kind: EvidenceKind, text: str, revision: str | None) -> str:
        directory = self.base_root / 'runs' / case.case_id / 'evidence'
        current = self.base_root
        for part in directory.relative_to(self.base_root).parts:
            current = current / part
            if current.is_symlink():
                raise OSError("Evidence directory contains a symlink")
            current.mkdir(exist_ok=True)
        evidence_id = 'verification_' + uuid4().hex
        path = directory / (evidence_id + '.json')
        raw = redact_secrets(text).encode('utf-8')
        evidence = Evidence(evidence_id=evidence_id, case_id=case.case_id, kind=kind,
                            path='evidence/' + path.name, sha256=hashlib.sha256(raw).hexdigest(),
                            created_at=datetime.now(timezone.utc).isoformat(), revision=revision)
        with path.open('xb') as stream:
            stream.write(raw)
        with path.with_suffix('.meta.json').open('x', encoding='utf-8') as stream:
            stream.write(evidence.to_json())
        return path.relative_to(self.base_root).as_posix()

    def _execute(self, workspace: Path, target: str, timeout: float, output_limit: int,
                 case: RunState, revision: str) -> tuple[TestRun, dict]:
        command = shlex.join(['python3', '-c', _RUNNER, target])
        sandbox = LocalSandbox(workspace.parent, max_output_bytes=output_limit)
        started = time.monotonic()
        result = sandbox.exec(workspace.name, command, timeout_s=timeout)
        duration = time.monotonic() - started
        data = {}
        for line in result.stdout_ref.splitlines():
            if line.startswith('RQA_RESULT='):
                try:
                    data = json.loads(line.removeprefix('RQA_RESULT='))
                except ValueError:
                    data = {}
        required = {'passed', 'assertions', 'errors', 'skipped'}
        valid = (isinstance(data, dict) and set(data) == required
                 and all(type(v) is int and v >= 0 for v in data.values()))
        env_error = (result.timed_out or getattr(result, 'truncated', False)
                     or result.exit_code not in (0, 1) or not valid
                     or (valid and (data['errors'] > 0 or sum(data.values()) == 0)))
        if not valid:
            data = {}
        log_ref = self._save(case, EvidenceKind.TEST_LOG, json.dumps({
            'executed': True, 'command': command, 'exit_code': result.exit_code,
            'duration_s': duration, 'stdout': result.stdout_ref, 'stderr': result.stderr_ref,
            'timed_out': result.timed_out, 'truncated': getattr(result, 'truncated', False),
            'reports': data, 'env_error': env_error,
        }), revision)
        return TestRun(command, result.exit_code, duration, log_ref), {'env_error': env_error, **data}

    @staticmethod
    def _apply(workspace: Path, diff: bytes, patch: Patch, repro_path: str, limit: int) -> None:
        if patch.touches_tests or patch.touches_ci:
            raise _Rejected("Patch declares test or CI changes")
        text = diff.decode('utf-8')
        # Restrict accepted format before git can write anything. No renames,
        # file creation/deletion, binary patches or file mode/symlink changes.
        if any(line.startswith(('rename ', 'copy ', 'old mode ', 'new mode ', 'new file mode ',
                                 'deleted file mode ', 'GIT binary patch', 'Binary files '))
               for line in text.splitlines()):
            raise _Rejected("Unsupported patch operation")
        old = [line[6:].split('\t')[0] for line in text.splitlines() if line.startswith('--- a/')]
        new = [line[6:].split('\t')[0] for line in text.splitlines() if line.startswith('+++ b/')]
        if not old or old != new or len(set(old)) != len(old):
            raise _Rejected("Patch must modify existing regular files in place")
        paths = tuple(sorted(_relative(p).as_posix() for p in old))
        if len(paths) > limit or set(paths) != set(patch.files_changed):
            raise _Rejected("Actual patch paths violate file count or metadata")
        if any(_protected(p, repro_path) or '.git' in Path(p).parts for p in paths):
            raise _Rejected("Patch changes reproduction, tests or CI")
        env = LocalSandbox.build_clean_env(workspace)
        for args in (['git', 'apply', '--check', '-'], ['git', 'apply', '-']):
            result = subprocess.run(args, input=diff, cwd=workspace, env=env,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10)
            if result.returncode:
                raise _Rejected("Diff does not apply cleanly")

    def run(self, case: RunState, repro: ReproResult, patch: Patch) -> Verdict:
        if not re.fullmatch(r'[A-Za-z0-9_-]+', case.case_id):
            raise ValueError("Unsafe case_id")
        records = [TestRun('NOT_RUN: ' + name, -1, 0.0, '') for name in ('before', 'after', 'suite')]
        base = fixed = ''
        result, reasons = 'env_error', ('Verification did not complete',)
        try:
            limits = json.loads((self.base_root / 'config/limits.json').read_text())
            limit = limits['max_files_changed']
            timeout = limits['test_timeout_s']
            output_limit = limits['max_output_bytes']
            if type(limit) is not int or limit <= 0 or type(timeout) not in (int, float) or timeout <= 0:
                raise OSError("Invalid verification limits")
            with self.sandbox.isolated_copy(case.repo_ref) as workspace:
                initial = _snapshot(workspace)
                base = fixed = _revision(initial)
                test_path = repro.test_path
                prefix = case.repo_ref.rstrip('/') + '/'
                if test_path.startswith(prefix):
                    test_path = test_path[len(prefix):]
                target = workspace / _relative(test_path)
                # When Reproduction provides a filesystem artifact, bind both
                # executions to those exact bytes even if a test already exists.
                if repro.test_source_ref.startswith('runs/'):
                    recorded_source = self._artifact(repro.test_source_ref, case).read_bytes()
                    if target.is_file() and target.read_bytes() != recorded_source:
                        raise _Rejected("Target reproduction differs from recorded test source")
                if not target.is_file():
                    source = self._artifact(repro.test_source_ref, case).read_bytes()
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(source)
                test_source = target.read_bytes()
                diff_path = self._artifact(patch.diff_ref, case)
                if diff_path.stat().st_size > 1024 * 1024:
                    raise _Rejected("Diff exceeds supported size")
                diff = diff_path.read_bytes()
                # Validate patch in a separate copy before spending test time.
                with LocalSandbox(workspace.parent).isolated_copy(workspace.name) as candidate:
                    self._apply(candidate, diff, patch, test_path, limit)
                    changed = _snapshot(candidate)
                    expected = _snapshot(workspace)
                    actual = {p for p in expected.keys() | changed.keys() if expected.get(p) != changed.get(p)}
                    if actual != set(patch.files_changed):
                        raise _Rejected("Actual changed files differ from patch metadata")
                if repro.outcome != ReproOutcome.RED_ON_ASSERTION or repro.exit_code == 0:
                    raise _Rejected("Reproduction input is not red_on_assertion")
                records[0], before = self._execute(workspace, test_path, timeout, output_limit, case, base)
                if before['env_error']:
                    raise OSError("Before reproduction has an environment/runtime error")
                if records[0].exit_code != 1 or before['assertions'] != 1 or before['skipped']:
                    raise _Rejected("Before reproduction must fail on exactly one assertion without skips")
                self._apply(workspace, diff, patch, test_path, limit)
                if target.read_bytes() != test_source:
                    raise _Rejected("Reproduction source changed")
                repaired = _snapshot(workspace)
                # Exclude an evidence-sourced reproduction from target revision hashes.
                if test_path not in initial:
                    repaired.pop(test_path, None)
                fixed = _revision(repaired)
                records[1], after = self._execute(workspace, test_path, timeout, output_limit, case, fixed)
                if after['env_error']:
                    raise OSError("After reproduction has an environment/runtime error")
                if records[1].exit_code != 0 or after['passed'] == 0 or after['skipped']:
                    raise _Rejected("Reproduction does not pass after patch")
                records[2], suite = self._execute(workspace, '.', timeout, output_limit, case, fixed)
                if suite['env_error']:
                    raise OSError("Suite has an environment/runtime error")
                if records[2].exit_code != 0 or suite['passed'] == 0 or suite['skipped']:
                    raise _Rejected("Target suite is not fully green")
                result, reasons = 'verified', ()
        except _Rejected as error:
            result, reasons = ('rejected' if base else 'env_error'), (str(error),)
        except (OSError, ValueError, KeyError, subprocess.TimeoutExpired) as error:
            result, reasons = 'env_error', (redact_secrets(str(error)),)
        for i, record in enumerate(records):
            if not record.log_ref:
                reference = self._save(case, EvidenceKind.TEST_LOG, json.dumps({
                    'executed': False, 'status': 'NOT_RUN', 'stage': record.command,
                    'reason': reasons, 'exit_code': None,
                }), base or None)
                records[i] = TestRun(record.command, -1, 0.0, reference)
        verdict = Verdict(*records, base, fixed, result, reasons)
        self._save(case, EvidenceKind.VERDICT, verdict.to_json(), fixed or base or None)
        return verdict
