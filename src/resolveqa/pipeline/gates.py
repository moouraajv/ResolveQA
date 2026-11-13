"""Playbook gates wrapping triage/fix for the general agent mode."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from resolveqa.contracts import NeedsInfo, Patch, ReproResult, RunState, TriageRecord
from resolveqa.fix.engine import PatchRejected
from resolveqa.playbook.schema import Playbook


class PlaybookGatedTriage:
    """Filter triage suspects through playbook allow/forbid lists."""

    def __init__(self, inner: Any, playbook: Playbook) -> None:
        self.inner = inner
        self.playbook = playbook

    def run(self, case: RunState) -> TriageRecord | NeedsInfo:
        result = self.inner.run(case)
        if isinstance(result, NeedsInfo):
            return result
        if not isinstance(result, TriageRecord):
            return result
        allowed = [p for p in result.suspect_files if self.playbook.is_path_allowed(p)]
        forbidden_hits = [p for p in result.suspect_files if self.playbook.is_path_forbidden(p)]
        if forbidden_hits and not allowed:
            return NeedsInfo(
                missing_fields=("suspect_files",),
                question_to_support=(
                    "Os arquivos apontados pela triagem estão fora do playbook permitido. "
                    "Informe um caminho de código dentro da allowlist do projeto."
                ),
            )
        if not allowed:
            return NeedsInfo(
                missing_fields=("suspect_files",),
                question_to_support=(
                    "Não identificamos arquivos permitidos pelo playbook para investigar. "
                    "Pode indicar o módulo afetado?"
                ),
            )
        return replace(result, suspect_files=allowed)


class PlaybookGatedFix:
    """Reject patches that touch forbidden or non-allowed paths."""

    def __init__(self, inner: Any, playbook: Playbook) -> None:
        self.inner = inner
        self.playbook = playbook

    def run(self, case: RunState, triage: TriageRecord, repro: ReproResult) -> Patch:
        for path in triage.suspect_files:
            if not self.playbook.is_path_allowed(path):
                raise PatchRejected(f"Suspect file outside playbook allowlist: {path}")
            if self.playbook.is_test_protected(path):
                raise PatchRejected(f"Suspect file is playbook-protected: {path}")
        patch = self.inner.run(case, triage, repro)
        for path in patch.files_changed:
            if not self.playbook.is_path_allowed(path):
                raise PatchRejected(f"Patch touches path outside playbook allowlist: {path}")
            if self.playbook.is_test_protected(path) or self.playbook.is_path_forbidden(path):
                raise PatchRejected(f"Patch touches forbidden/protected path: {path}")
        return patch
