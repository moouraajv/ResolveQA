"""Support knowledge-base draft article (#27)."""

from __future__ import annotations

from pathlib import Path

from resolveqa.contracts import RunState, Verdict
from resolveqa.playbook import Playbook

from .package import DeliveryError, _write_text


def write_kb_draft(
    package_dir: Path,
    *,
    case: RunState,
    verdict: Verdict,
    cause: str,
    playbook: Playbook | None,
    corrected_behavior: str,
    technical_note_rel: str,
) -> str:
    """Write kb draft under docs.kb_drafts_dir. Returns relative path inside package."""
    book = playbook or Playbook()
    rel = f"{book.kb_drafts_dir.rstrip('/')}/{case.case_id}.md"
    if rel.startswith("/") or ".." in Path(rel).parts:
        raise DeliveryError(f"KB draft path escapes configured docs root: {rel}")

    path = package_dir / rel
    path.parent.mkdir(parents=True, exist_ok=True)

    # Simple language, synthetic data only; no source code dumps.
    body = "\n".join(
        [
            "Rascunho — requer revisão humana",
            "",
            f"# Artigo de suporte — {case.case_id}",
            "",
            "## Sintoma",
            case.report_text.strip(),
            "",
            "## Causa resumida",
            cause.strip(),
            "",
            "## Situação",
            (
                f"A correção entrou na revisão `{verdict.fix_revision}` "
                f"(base `{verdict.base_revision}`). "
                f"Comportamento esperado: {corrected_behavior.strip()}."
            ),
            "",
            "## Como confirmar",
            (
                "Confira a nota técnica e as evidências RED/GREEN no pacote: "
                f"`{technical_note_rel}`, `before.log`, `after.log`."
            ),
            "",
            "Este rascunho **não** é publicado automaticamente.",
            "",
        ]
    )
    _write_text(path, body)
    return rel.replace("\\", "/")
