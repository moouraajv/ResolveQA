"""LLM-based defect repair stage with AST-based Plan B fallback (RFC-0001 §3.3, RF-05)."""

from __future__ import annotations

import difflib
import json
import re
from pathlib import Path
from typing import Optional

from resolveqa.contracts import (
    EvidenceKind,
    FixStage as FixStageProtocol,
    Patch,
    ReproOutcome,
    ReproResult,
    RunState,
    TriageRecord,
)
from resolveqa.fix.engine import FixStage as DeterministicFixStage, PatchRejected
from resolveqa.llm import LLMAdapter, LLMOutputError, build_delimited_messages
from resolveqa.sandbox.executor import LocalSandbox, redact_secrets
from resolveqa.store.evidence_store import EvidenceStore

REPO_ROOT = Path(__file__).resolve().parents[3]


def _is_protected_file(path_str: str, repro_test_path: Optional[str] = None) -> bool:
    """Return True if path_str targets tests, CI, or test-runner configuration files."""
    posix_path = path_str.replace("\\", "/").strip().lstrip("/")
    parts = Path(posix_path).parts
    if not parts:
        return True
    name = parts[-1].lower()
    if repro_test_path:
        clean_repro = repro_test_path.replace("\\", "/").strip().lstrip("/")
        if posix_path == clean_repro or posix_path.endswith("/" + clean_repro):
            return True
    if any(
        part.lower() in {"test", "tests", "__tests__", ".github", ".circleci", ".buildkite", ".gitlab"}
        for part in parts
    ):
        return True
    if name.startswith(("test_", ".gitlab-ci")):
        return True
    if name.endswith(("_test.py", ".test.js", ".spec.js", ".test.ts", ".spec.ts")):
        return True
    if name in {
        "conftest.py",
        "pytest.ini",
        ".pytest.ini",
        "pytest.toml",
        "tox.ini",
        "noxfile.py",
        "pyproject.toml",
        "setup.cfg",
        "setup.py",
        "jenkinsfile",
        "azure-pipelines.yml",
        ".travis.yml",
        "makefile",
        "requirements.txt",
        ".pre-commit-config.yaml",
    }:
        return True
    return False


def _target_path(value: str, repo_ref: str) -> str:
    path = Path(value)
    if path.is_absolute() or ".." in path.parts or "\\" in value:
        raise PatchRejected(f"Target paths must be relative without traversal: {value!r}")
    prefix = repo_ref.rstrip("/") + "/"
    return value[len(prefix):] if value.startswith(prefix) else path.as_posix()


def _snapshot(root: Path) -> dict[str, bytes]:
    result = {}
    for path in root.rglob("*"):
        if path.is_symlink():
            raise PatchRejected("Symlinks are unsupported in repair targets")
        if path.is_file():
            result[path.relative_to(root).as_posix()] = path.read_bytes()
    return result


class LLMFixStage:
    """Repairs bugs by requesting search/replace patches from the LLM adapter with deterministic Plan B fallback."""

    def __init__(
        self,
        base_root: Path | str | None = None,
        llm: Optional[LLMAdapter] = None,
        store: Optional[EvidenceStore] = None,
        *,
        allow_fallback: bool = True,
        fallback_on_rejected: bool = False,
    ) -> None:
        self.sandbox = LocalSandbox(base_root=base_root)
        self.base_root = self.sandbox.base_root
        self.llm = llm if llm is not None else LLMAdapter()
        self.store = store if store is not None else EvidenceStore(runs_root=self.base_root / "runs")
        self.allow_fallback = bool(allow_fallback)
        self.fallback_on_rejected = bool(fallback_on_rejected)

    def get_llm_calls(self, case: RunState) -> int:
        """Return total LLM calls tracked for this case without mutating RunState."""
        if hasattr(self.llm, "get_llm_calls"):
            return int(self.llm.get_llm_calls(case))
        return int(case.attempts.llm_calls)

    def _load_max_files_changed(self) -> int:
        limits_file = self.base_root / "config" / "limits.json"
        if limits_file.is_file():
            try:
                cfg = json.loads(limits_file.read_text(encoding="utf-8"))
                val = cfg.get("max_files_changed", 3)
                if isinstance(val, int) and val > 0:
                    return val
            except Exception:
                pass
        return 3

    def _read_suspect_sources(self, case: RunState, suspect_files: list[str]) -> dict[str, str]:
        repo_dir = (self.base_root / case.repo_ref).resolve()
        if not repo_dir.is_relative_to(self.base_root) or not repo_dir.is_dir():
            return {}
        sources: dict[str, str] = {}
        for rel_file in suspect_files:
            candidate = (repo_dir / rel_file).resolve()
            if candidate.is_relative_to(repo_dir) and candidate.is_file() and not candidate.is_symlink():
                try:
                    sources[f"source_{Path(rel_file).stem}"] = candidate.read_text(encoding="utf-8")[:4000]
                except OSError:
                    continue
        return sources

    def _run_deterministic_plan_b(
        self,
        case: RunState,
        triage: TriageRecord,
        repro: ReproResult,
        reason: str = "",
    ) -> Patch:
        """Run Plan B deterministic AST repair from #52, labeling the evidence as simulated=True."""
        deterministic_fixer = DeterministicFixStage(base_root=self.base_root)
        patch = deterministic_fixer.run(case, triage, repro)

        diff_path = self.base_root / patch.diff_ref
        diff_content = diff_path.read_text(encoding="utf-8") if diff_path.is_file() else ""

        ev = self.store.save_evidence(
            case_id=case.case_id,
            evidence_id=None,
            kind=EvidenceKind.DIFF,
            content=diff_content,
            extension="diff",
            revision=case.base_revision,
            simulated=True,
        )

        diff_ref = f"runs/{case.case_id}/{ev.path}"
        destination = self.base_root / diff_ref
        with destination.with_suffix(".json").open("w", encoding="utf-8") as stream:
            stream.write(ev.to_json())

        return Patch(
            diff_ref=diff_ref,
            files_changed=patch.files_changed,
            touches_tests=patch.touches_tests,
            touches_ci=patch.touches_ci,
        )

    def _apply_llm_patch(
        self,
        case: RunState,
        triage: TriageRecord,
        repro: ReproResult,
        llm_content: str,
        suspect_files: list[str],
        is_simulated: bool,
    ) -> Patch:
        try:
            payload = json.loads(llm_content)
        except Exception as json_err:
            raise PatchRejected(f"Invalid JSON from LLM: {json_err}") from json_err

        if isinstance(payload, dict) and "file" in payload:
            edits = [payload]
        elif isinstance(payload, list):
            edits = payload
        else:
            raise PatchRejected("LLM output must be a JSON object or list of edits with 'file', 'search', 'replace'")

        repro_path = _target_path(repro.test_path, case.repo_ref)
        for ed in edits:
            if not isinstance(ed, dict) or not all(k in ed for k in ("file", "search", "replace")):
                raise PatchRejected("Each edit must contain 'file', 'search', and 'replace'")
            target_rel = _target_path(ed["file"], case.repo_ref)
            if _is_protected_file(target_rel, repro_path):
                raise PatchRejected(f"Patch touches protected file: {target_rel}")

        limit = self._load_max_files_changed()

        with self.sandbox.isolated_copy(case.repo_ref) as workspace:
            before = _snapshot(workspace)

            for ed in edits:
                target_rel = _target_path(ed["file"], case.repo_ref)
                target_path = (workspace / target_rel).resolve()
                if not target_path.is_relative_to(workspace.resolve()) or not target_path.is_file():
                    raise PatchRejected(f"Target file not found in repository: {target_rel}")
                if target_path.is_symlink():
                    raise PatchRejected("Symlinks are unsupported in repair targets")

                current_src = target_path.read_text(encoding="utf-8")
                search_str = ed["search"]
                replace_str = ed["replace"]
                if search_str not in current_src:
                    raise PatchRejected(f"Search block not found in {target_rel}")

                new_src = current_src.replace(search_str, replace_str, 1)
                target_path.write_text(new_src, encoding="utf-8")

            after = _snapshot(workspace)
            changed = tuple(sorted(p for p in before if before.get(p) != after.get(p)))

            if not changed:
                raise PatchRejected("Patch is empty (no changes made)")

            if len(changed) > limit:
                raise PatchRejected(f"Patch changes {len(changed)} files, exceeding max_files_changed limit of {limit}")

            if any(_is_protected_file(p, repro_path) for p in changed):
                raise PatchRejected("Patch touches tests, CI, or runner configuration")

            if not set(changed).issubset(set(suspect_files)):
                raise PatchRejected(f"Patch touches files outside suspect_files: {set(changed) - set(suspect_files)}")

            diff = "".join(
                "".join(
                    difflib.unified_diff(
                        before.get(p, b"").decode("utf-8").splitlines(keepends=True),
                        after.get(p, b"").decode("utf-8").splitlines(keepends=True),
                        fromfile=f"a/{p}" if p in before else "/dev/null",
                        tofile=f"b/{p}" if p in after else "/dev/null",
                    )
                )
                for p in changed
            )

        if redact_secrets(diff) != diff:
            raise PatchRejected("Patch contains a recognizable secret")

        ev = self.store.save_evidence(
            case_id=case.case_id,
            evidence_id=None,
            kind=EvidenceKind.DIFF,
            content=diff,
            extension="diff",
            revision=case.base_revision,
            simulated=is_simulated,
        )

        diff_ref = f"runs/{case.case_id}/{ev.path}"
        destination = self.base_root / diff_ref
        with destination.with_suffix(".json").open("w", encoding="utf-8") as stream:
            stream.write(ev.to_json())

        return Patch(
            diff_ref=diff_ref,
            files_changed=changed,
            touches_tests=False,
            touches_ci=False,
        )

    def run(self, case: RunState, triage: TriageRecord, repro: ReproResult) -> Patch:
        """Propose a fix patch via LLM, falling back to Plan B deterministic repair when needed."""
        if repro.outcome != ReproOutcome.RED_ON_ASSERTION or repro.exit_code == 0:
            raise PatchRejected("Fix requires a reproduction failing on the reported assertion")
        if not re.fullmatch(r"[A-Za-z0-9_-]+", case.case_id):
            raise PatchRejected(f"Unsafe case_id: {case.case_id!r}")

        suspect_files = [_target_path(p, case.repo_ref) for p in triage.suspect_files]
        if not suspect_files:
            raise PatchRejected("Triage record contains no suspect files")

        suspect_sources = self._read_suspect_sources(case, suspect_files)

        untrusted_blocks: dict[str, str] = {
            "report_text": case.report_text,
            "triage_input": triage.input,
            "triage_expected": triage.expected,
            "triage_observed": triage.observed,
            "repro_assertion": repro.failing_assertion or "",
            "suspect_files": ", ".join(suspect_files),
        }
        untrusted_blocks.update(suspect_sources)

        messages = build_delimited_messages(
            system_instruction=(
                "Generate a minimal fix for the reported defect. Return a JSON object with 'file', 'search', and 'replace'. "
                "Only propose edits to the allowed suspect files. Never modify tests or CI."
            ),
            untrusted_blocks=untrusted_blocks,
        )

        schema = {"allowed_files": suspect_files}
        try:
            llm_res = self.llm.complete("fix", messages, schema=schema, case=case)
        except LLMOutputError as out_err:
            if self.fallback_on_rejected:
                return self._run_deterministic_plan_b(case, triage, repro, reason=str(out_err))
            raise PatchRejected(f"Patch rejected by validation: {out_err}") from out_err
        except Exception as llm_exc:
            if self.allow_fallback:
                return self._run_deterministic_plan_b(case, triage, repro, reason=f"LLM failure: {llm_exc}")
            raise PatchRejected(f"LLM fix generation failed: {llm_exc}") from llm_exc

        is_simulated = bool(getattr(llm_res, "mock", False))
        try:
            return self._apply_llm_patch(
                case=case,
                triage=triage,
                repro=repro,
                llm_content=llm_res.content,
                suspect_files=suspect_files,
                is_simulated=is_simulated,
            )
        except PatchRejected as rej_exc:
            if self.fallback_on_rejected:
                return self._run_deterministic_plan_b(case, triage, repro, reason=str(rej_exc))
            raise


LLMFix = LLMFixStage
