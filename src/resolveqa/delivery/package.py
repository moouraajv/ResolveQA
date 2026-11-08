"""Build a local evidence package labeled "PR não publicado" (RF-08, RNF-05, D4).

MVP default (RFC §9 D4): always produce a local package. Never opens or merges a
real PR. Draft-PR against an authorized remote remains a future extension behind
the same DeliveryStage interface.

`Delivery.build(case, verdict)` reads cause/diff/logs from
`runs/<case_id>/evidence/` so the frozen DeliveryStage signature stays intact.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from resolveqa.contracts import (
    DeliveryKind,
    DeliveryResult,
    DeliveryStage,
    RunState,
    Verdict,
    VerdictResult,
)
from resolveqa.security import scan_paths_for_secrets

UNPUBLISHED_LABEL = "PR não publicado"


class DeliveryError(ValueError):
    """Raised when delivery cannot build an honest evidence package."""


def _read_limits(limits_path: Path) -> dict[str, object]:
    if not limits_path.is_file():
        return {
            "max_fix_attempts": 2,
            "max_llm_calls": 12,
            "test_timeout_s": 600,
            "max_files_changed": 3,
        }
    return json.loads(limits_path.read_text(encoding="utf-8"))


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")


def _require_evidence_file(evidence_dir: Path, name: str) -> Path:
    path = evidence_dir / name
    if not path.is_file():
        raise DeliveryError(
            f"Delivery requires evidence file runs/<case_id>/evidence/{name}"
        )
    return path


def _copy_file(src: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dest)


class DeliveryBuilder:
    """Implements DeliveryStage.build for the local unpublished package path."""

    def __init__(
        self,
        *,
        runs_root: Path | str = "runs",
        limits_path: Path | str = "config/limits.json",
        authorized_remote: bool = False,
    ) -> None:
        self.runs_root = Path(runs_root)
        self.limits_path = Path(limits_path)
        # MVP: authorized_remote stays False (D4-a). Never auto-merge.
        self.authorized_remote = bool(authorized_remote)

    def build(self, case: RunState, verdict: Verdict) -> DeliveryResult:
        if not isinstance(case, RunState):
            raise DeliveryError(f"Delivery.build expects RunState, got {type(case).__name__}.")
        if not isinstance(verdict, Verdict):
            raise DeliveryError(f"Delivery.build expects Verdict, got {type(verdict).__name__}.")
        if verdict.result != VerdictResult.VERIFIED:
            raise DeliveryError(
                f"Delivery only packages verified cases; got verdict.result={verdict.result.value}."
            )
        if case.state.value != "verified":
            raise DeliveryError(
                f"Delivery requires case.state=verified; got {case.state.value}."
            )

        # D4-a: local package only. Never merge.
        if self.authorized_remote:
            raise DeliveryError(
                "Draft PR remote delivery is not enabled in the MVP; "
                "use the local unpublished package path."
            )

        evidence_dir = self.runs_root / case.case_id / "evidence"
        cause_path = _require_evidence_file(evidence_dir, "cause.txt")
        diff_path = _require_evidence_file(evidence_dir, "diff.patch")
        before_path = _require_evidence_file(evidence_dir, "before.log")
        after_path = _require_evidence_file(evidence_dir, "after.log")
        suite_path = _require_evidence_file(evidence_dir, "suite.log")

        cause_text = cause_path.read_text(encoding="utf-8").strip()
        diff_text = diff_path.read_text(encoding="utf-8").strip()
        if not cause_text:
            raise DeliveryError("Delivery package requires a non-empty cause.txt.")
        if not diff_text:
            raise DeliveryError("Delivery package requires a non-empty diff.patch.")

        package_dir = self.runs_root / case.case_id / "delivery" / "pr-nao-publicado"
        if package_dir.exists():
            shutil.rmtree(package_dir)
        package_dir.mkdir(parents=True, exist_ok=True)

        _write_text(
            package_dir / "README.md",
            "\n".join(
                [
                    f"# {UNPUBLISHED_LABEL}",
                    "",
                    f"case_id: `{case.case_id}`",
                    f"client_id: `{case.client_id}`",
                    f"repo_ref: `{case.repo_ref}`",
                    f"channel: `{case.channel.value}`",
                    f"base_revision: `{verdict.base_revision}`",
                    f"fix_revision: `{verdict.fix_revision}`",
                    "",
                    "Este pacote **não** publica nem faz merge automático de PR.",
                    "",
                ]
            ),
        )
        _write_text(
            package_dir / "report.md",
            "# Relato\n\n" + case.report_text.strip() + "\n",
        )
        _write_text(package_dir / "cause.md", "# Causa\n\n" + cause_text + "\n")
        _copy_file(diff_path, package_dir / "diff.patch")
        _copy_file(before_path, package_dir / "before.log")
        _copy_file(after_path, package_dir / "after.log")
        _copy_file(suite_path, package_dir / "suite.log")
        limits = _read_limits(self.limits_path)
        _write_text(
            package_dir / "limits.json",
            json.dumps(limits, indent=2, sort_keys=True) + "\n",
        )
        _write_text(
            package_dir / "verdict.json",
            verdict.to_json(indent=2) + "\n",
        )

        relative_names = [
            "README.md",
            "report.md",
            "cause.md",
            "diff.patch",
            "before.log",
            "after.log",
            "suite.log",
            "limits.json",
            "verdict.json",
        ]
        for name in relative_names:
            path = package_dir / name
            if not path.is_file():
                raise DeliveryError(f"Delivery package missing required file: {name}")

        findings = scan_paths_for_secrets([package_dir])
        if findings:
            raise DeliveryError(
                "Secret scan found credentials in delivery package: "
                + ", ".join(f"{f.kind}@{Path(f.path).name}" for f in findings)
            )

        manifest = {
            "case_id": case.case_id,
            "label": UNPUBLISHED_LABEL,
            "kind": DeliveryKind.LOCAL_PACKAGE.value,
            "auto_merge": False,
            "files": relative_names,
        }
        _write_text(package_dir / "MANIFEST.json", json.dumps(manifest, indent=2) + "\n")

        evidence_refs = tuple(f"delivery/pr-nao-publicado/{name}" for name in relative_names)
        return DeliveryResult(
            kind=DeliveryKind.LOCAL_PACKAGE,
            url_or_path=str(package_dir.resolve()),
            label=UNPUBLISHED_LABEL,
            evidence_refs=evidence_refs,
        )


# Structural check against the frozen contracts protocol.
def _assert_delivery_stage(builder: DeliveryStage) -> None:
    assert callable(builder.build)


_assert_delivery_stage(DeliveryBuilder())
