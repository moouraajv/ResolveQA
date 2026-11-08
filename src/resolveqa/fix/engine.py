"""Deterministic repair for the MVP's single supported defect; no LLM or mock.

FixStage never edits the source repository. It returns a portable unified diff
relative to the target root. ``diff_ref`` is relative to ``base_root``; the diff
and an Evidence JSON sidecar live in runs/<case_id>/evidence/. Verification must
apply that diff in its own isolated copy and independently run the tests.
Unsupported source shapes are rejected instead of claiming a successful fix.
"""

from __future__ import annotations

import ast
import difflib
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from resolveqa.contracts import (
    ContractValidationError,
    Evidence,
    EvidenceKind,
    Patch,
    ReproOutcome,
    ReproResult,
    RunState,
    TriageRecord,
)
from resolveqa.sandbox.executor import LocalSandbox, redact_secrets


class PatchRejected(ContractValidationError):
    """No admissible patch can be proposed for this case.

    Subclasses ContractValidationError so the orchestrator terminalizes as
    blocked / patch_rejected instead of infra_error.
    """


class FixStage:
    """Repair the known missing subtraction, constrained by config/limits.json.

    ``base_root`` holds the target repo_ref, config and runs directories. Suspect
    paths are relative to the target, optionally prefixed by case.repo_ref.
    """

    def __init__(self, base_root: Path | str | None = None) -> None:
        self.sandbox = LocalSandbox(base_root=base_root)
        self.base_root = self.sandbox.base_root

    @staticmethod
    def _snapshot(root: Path) -> dict[str, bytes]:
        result = {}
        for path in root.rglob("*"):
            if path.is_symlink():
                raise PatchRejected("Symlinks are unsupported in repair targets")
            if path.is_file():
                result[path.relative_to(root).as_posix()] = path.read_bytes()
        return result

    @staticmethod
    def _repair(workspace: Path) -> None:
        path = workspace / "checkout.py"
        # Decode raw bytes (no universal-newline translation) so CRLF targets
        # keep unrelated line endings; only the expression bytes are replaced.
        raw = path.read_bytes()
        source = raw.decode("utf-8")
        tree = ast.parse(source)
        functions = [node for node in tree.body if isinstance(node, ast.FunctionDef)
                     and node.name == "calculate_total"]
        if len(functions) != 1:
            raise PatchRejected("Unsupported calculate_total definition")
        body = functions[0].body
        # Match the known cause structurally and preserve every other source byte.
        expected_discount = ast.parse("discount = round(float(subtotal) * (pct / 100.0), 2)").body[0]
        expected_return = ast.parse("return round(float(subtotal), 2)").body[0]
        if (len(body) < 2
                or ast.dump(body[-2]) != ast.dump(expected_discount)
                or ast.dump(body[-1]) != ast.dump(expected_return)):
            raise PatchRejected("Known missing-discount cause not found")
        node = body[-1].value.args[0]
        # AST offsets are UTF-8 byte offsets into the decoded source string.
        lines = source.encode("utf-8").splitlines(keepends=True)
        start = sum(map(len, lines[:node.lineno - 1])) + node.col_offset
        end = sum(map(len, lines[:node.end_lineno - 1])) + node.end_col_offset
        path.write_bytes(raw[:start] + b"float(subtotal) - discount" + raw[end:])

    @staticmethod
    def _target_path(value: str, repo_ref: str) -> str:
        path = Path(value)
        if path.is_absolute() or ".." in path.parts or "\\" in value:
            raise PatchRejected("Target paths must be relative without traversal")
        prefix = repo_ref.rstrip("/") + "/"
        return value[len(prefix):] if value.startswith(prefix) else path.as_posix()

    @staticmethod
    def _protected(path: str, repro_path: str) -> bool:
        parts = Path(path).parts
        name = parts[-1].lower()
        return (path == repro_path
                or any(part.lower() in {"test", "tests", "__tests__", ".github", ".circleci", ".buildkite"} for part in parts)
                or name.startswith(("test_", ".gitlab-ci"))
                or name.endswith(("_test.py", ".test.js", ".spec.js", ".test.ts", ".spec.ts"))
                or name in {"conftest.py", "pytest.ini", "tox.ini", "pyproject.toml", "setup.cfg", "jenkinsfile", "azure-pipelines.yml", ".travis.yml"})

    def run(self, case: RunState, triage: TriageRecord, repro: ReproResult) -> Patch:
        if (
            repro.outcome != ReproOutcome.RED_ON_ASSERTION
            or repro.exit_code == 0
            or not (repro.failing_assertion or "").strip()
        ):
            raise PatchRejected("Fix requires a reproduction failing on the reported assertion")
        if not re.fullmatch(r"[A-Za-z0-9_-]+", case.case_id):
            raise PatchRejected("Unsafe case_id")
        suspects = {self._target_path(p, case.repo_ref) for p in triage.suspect_files}
        if "checkout.py" not in suspects:
            raise PatchRejected("Triage must identify checkout.py as a suspect")
        repro_path = self._target_path(repro.test_path, case.repo_ref)
        config = json.loads((self.base_root / "config/limits.json").read_text(encoding="utf-8"))
        limit = config["max_files_changed"]
        if type(limit) is not int or limit <= 0:
            raise PatchRejected("max_files_changed must be a positive integer")
        with self.sandbox.isolated_copy(case.repo_ref) as workspace:
            before = self._snapshot(workspace)
            self._repair(workspace)
            after = self._snapshot(workspace)
            changed = tuple(sorted(p for p in before.keys() | after.keys() if before.get(p) != after.get(p)))
            if not changed or len(changed) > limit:
                raise PatchRejected("Patch is empty or exceeds max_files_changed")
            if any(self._protected(p, repro_path) for p in changed):
                raise PatchRejected("Patch touches tests or CI")
            if not set(changed) <= suspects:
                raise PatchRejected("Patch exceeds triage suspect files")
            diff = "".join("".join(difflib.unified_diff(
                before.get(p, b"").decode("utf-8").splitlines(keepends=True),
                after.get(p, b"").decode("utf-8").splitlines(keepends=True),
                fromfile=f"a/{p}" if p in before else "/dev/null",
                tofile=f"b/{p}" if p in after else "/dev/null",
            )) for p in changed)
        if redact_secrets(diff) != diff:
            raise PatchRejected("Patch contains a recognizable secret")
        evidence_id = "diff_" + uuid4().hex
        relative = Path("runs") / case.case_id / "evidence" / (evidence_id + ".diff")
        destination = self.base_root / relative
        # Refuse pre-existing symlink ancestors, including runs and the case dir.
        current = self.base_root
        for part in relative.parts[:-1]:
            current = current / part
            if current.is_symlink():
                raise PatchRejected("Evidence directory cannot contain symlinks")
            current.mkdir(exist_ok=True)
        payload = diff.encode("utf-8")
        evidence = Evidence(
            evidence_id=evidence_id, case_id=case.case_id, kind=EvidenceKind.DIFF,
            path=f"evidence/{evidence_id}.diff", sha256=hashlib.sha256(payload).hexdigest(),
            created_at=datetime.now(timezone.utc).isoformat(), revision=case.base_revision,
            simulated=False,
        )
        with destination.open("xb") as stream:
            stream.write(payload)
        with destination.with_suffix(".json").open("x", encoding="utf-8") as stream:
            stream.write(evidence.to_json())
        return Patch(diff_ref=relative.as_posix(), files_changed=changed,
                     touches_tests=False, touches_ci=False)
