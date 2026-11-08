"""Changelog and technical note writers for the evidence package (#26)."""

from __future__ import annotations

import hashlib
from pathlib import Path

from resolveqa.contracts import RunState, Verdict
from resolveqa.playbook import Playbook

from .package import DeliveryError, _write_text


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def _changed_files_from_diff(diff_text: str) -> list[str]:
    files: list[str] = []
    for line in diff_text.splitlines():
        if line.startswith("+++ b/"):
            files.append(line[6:].strip())
        elif line.startswith("diff --git "):
            parts = line.split(" b/", 1)
            if len(parts) == 2:
                files.append(parts[1].strip())
    # stable unique
    seen: set[str] = set()
    ordered: list[str] = []
    for name in files:
        if name and name not in seen:
            seen.add(name)
            ordered.append(name)
    return ordered


def write_package_docs(
    package_dir: Path,
    *,
    case: RunState,
    verdict: Verdict,
    cause: str,
    diff_text: str,
    before_log: Path,
    after_log: Path,
    playbook: Playbook | None,
    corrected_behavior: str,
    test_id: str = "test_checkout",
) -> list[str]:
    """Write changelog + technical note only under playbook docs paths. Returns relative paths."""
    book = playbook or Playbook()
    changelog_rel = book.changelog_path
    notes_rel = f"{book.technical_notes_dir.rstrip('/')}/{case.case_id}.md"

    # Docs may only touch configured documentation paths.
    for rel in (changelog_rel, notes_rel):
        if rel.startswith("/") or ".." in Path(rel).parts:
            raise DeliveryError(f"Documentation path escapes package docs roots: {rel}")

    changelog_path = package_dir / changelog_rel
    notes_path = package_dir / notes_rel
    changelog_path.parent.mkdir(parents=True, exist_ok=True)
    notes_path.parent.mkdir(parents=True, exist_ok=True)

    entry = (
        f"## Fixed\n\n"
        f"- [{case.case_id}] {corrected_behavior.strip()}\n"
    )
    if changelog_path.exists():
        existing = changelog_path.read_text(encoding="utf-8")
        if "## Fixed" in existing:
            updated = existing.replace("## Fixed", "## Fixed\n\n" + entry.split("\n\n", 1)[1], 1)
        else:
            updated = existing.rstrip() + "\n\n" + entry
        _write_text(changelog_path, updated if updated.endswith("\n") else updated + "\n")
    else:
        _write_text(changelog_path, "# Changelog\n\n" + entry)

    before_sha = _sha256_file(before_log)
    after_sha = _sha256_file(after_log)
    changed = _changed_files_from_diff(diff_text)
    note_header = [
        f"# Nota técnica — {case.case_id}",
        "",
        "## Relato resumido",
        case.report_text.strip(),
        "",
        "## Causa",
        cause.strip(),
        "",
        "## Arquivos alterados",
    ]
    file_lines = [f"- `{name}`" for name in changed] or ["- (não detectados no diff)"]
    reason_lines = [f"- {reason}" for reason in verdict.reasons]
    note = "\n".join(
        [
            *note_header,
            *file_lines,
            "",
            "## test_id",
            f"`{test_id}`",
            "",
            "## Evidência RED/GREEN",
            f"- RED: `before.log` sha256=`{before_sha}`",
            f"- GREEN: `after.log` sha256=`{after_sha}`",
            "",
            "## Revisões",
            f"- base_revision: `{verdict.base_revision}`",
            f"- fix_revision: `{verdict.fix_revision}`",
            "",
            "## Regras do veredito",
            f"- result: `{verdict.result.value}`",
            *reason_lines,
            "",
        ]
    )
    _write_text(notes_path, note)

    # Verify evidence links exist inside the package.
    for required in ("before.log", "after.log"):
        if not (package_dir / required).is_file():
            raise DeliveryError(f"Technical note evidence missing in package: {required}")

    return [changelog_rel.replace("\\", "/"), notes_rel.replace("\\", "/")]
