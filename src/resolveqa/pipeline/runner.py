"""Run the full agent pipeline for an existing case (demo CLI + cloud worker)."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from importlib import import_module
from pathlib import Path
from typing import Any, Callable, Optional
from uuid import uuid4

from resolveqa.contracts import (
    CaseState,
    CustomerMessage,
    DeliveryResult,
    Event,
    EventSource,
    EventType,
    EvidenceKind,
    RunState,
    Verdict,
)
from resolveqa.delivery import DeliveryBuilder
from resolveqa.orchestrator import Orchestrator
from resolveqa.pipeline.gates import PlaybookGatedFix, PlaybookGatedTriage
from resolveqa.playbook import load_playbook
from resolveqa.reply import ReplyComposer, ReplyOutcome
from resolveqa.store import EventStore
from resolveqa.store.syncing import SyncingEventStore

ROOT = Path(__file__).resolve().parents[3]


class MissingComponents(RuntimeError):
    """Required public implementation has not landed yet."""


def agent_mode() -> str:
    """Return ``general`` (LLM fix + playbook gates) or ``dogfood`` (deterministic fix)."""
    raw = (os.environ.get("RESOLVEQA_AGENT_MODE") or "general").strip().lower()
    return "dogfood" if raw in {"dogfood", "deterministic", "coupon"} else "general"


def load_components(*, mode: str | None = None) -> dict[str, Any]:
    """Import known stage APIs; list every missing dependency in one diagnostic."""
    mode = mode or agent_mode()
    fix_spec = (
        ("resolveqa.fix.llm_fix", "LLMFixStage", 52)
        if mode == "general"
        else ("resolveqa.fix.engine", "FixStage", 52)
    )
    required = (
        ("resolveqa.store.evidence_store", "EvidenceStore", 47),
        ("resolveqa.triage.engine", "TriageEngine", 49),
        ("resolveqa.reproduction.engine", "ReproductionEngine", 50),
        fix_spec,
        ("resolveqa.verification.verifier", "Verification", 53),
    )
    loaded: dict[str, Any] = {}
    missing: list[str] = []
    for module, symbol, pr in required:
        try:
            loaded[symbol] = getattr(import_module(module), symbol)
        except (ImportError, AttributeError):
            missing.append(f"{module}.{symbol} (PR #{pr})")
    if missing:
        raise MissingComponents(
            "Fluxo indisponível; faltam implementações compatíveis na main: "
            + "; ".join(missing)
        )
    # Normalize fix key for callers.
    if "LLMFixStage" in loaded and "FixStage" not in loaded:
        loaded["FixStage"] = loaded["LLMFixStage"]
    return loaded


@dataclass(frozen=True)
class PipelineResult:
    case: RunState
    run_dir: Path
    events: tuple[Event, ...]
    evidence_ids: tuple[str, ...]
    verdict: Verdict | None = None
    delivery: DeliveryResult | None = None
    message: CustomerMessage | None = None


class _RecordedStage:
    """Observe a real stage result; only the orchestrator changes case state."""

    def __init__(self, stage: Any, record: Callable[[Any], None]) -> None:
        self.stage = stage
        self.record = record
        self.result = None

    def run(self, *args: Any) -> Any:
        self.result = self.stage.run(*args)
        self.record(self.result)
        return self.result


def run_pipeline(
    case: RunState,
    *,
    root: Path | str = ROOT,
    llm: Any,
    real: bool = False,
    on_case: Optional[Callable[[RunState], None]] = None,
    mode: str | None = None,
) -> PipelineResult:
    """Drive an existing `created` case through triage → verify (+ delivery/reply)."""
    if bool(getattr(llm, "use_real", False)) != real:
        raise ValueError("O modo do adaptador deve corresponder à flag explícita do pipeline")
    mode = mode or agent_mode()
    components = load_components(mode=mode)
    root = Path(root).resolve()
    runs = root / "runs"
    llm.bind_case(case)
    events = EventStore(runs)
    if on_case is not None:
        on_case(case)
        events = SyncingEventStore(events, seed=case, on_case=on_case)  # type: ignore[assignment]
    evidence = components["EvidenceStore"](runs_root=runs)
    playbook = load_playbook(root / case.repo_ref)
    run_dir = runs / case.case_id
    ids: list[str] = []
    descriptors: list[dict[str, Any]] = []

    def append_event(source: EventSource, kind: EventType, refs: tuple[str, ...] = ()) -> None:
        events.append(
            Event(
                event_id=uuid4().hex,
                case_id=case.case_id,
                seq=events.next_seq(case.case_id),
                ts=datetime.now(timezone.utc).isoformat(),
                source=source,
                type=kind,
                evidence_refs=tuple(refs),
            )
        )

    def save(kind: EvidenceKind, content: str, source: EventSource, extension: str = "json", evidence_id: str | None = None):
        item = evidence.save_evidence(
            case_id=case.case_id,
            kind=kind,
            content=content,
            extension=extension,
            evidence_id=evidence_id,
            simulated=(not real or kind in {EvidenceKind.REPORT, EvidenceKind.PR_PACKAGE}),
        )
        ids.append(item.evidence_id)
        descriptors.append(item.to_dict())
        append_event(source, EventType.EVIDENCE_ADDED, (item.evidence_id,))
        return item

    def read_ref(ref: str) -> str:
        for base in (run_dir, root):
            path = (base / ref).resolve()
            if path.is_relative_to(run_dir.resolve()) and path.is_file():
                return path.read_text(encoding="utf-8")
        raise FileNotFoundError("Artefato da etapa ausente dentro do diretório do caso")

    def record_triage(result: Any) -> None:
        save(EvidenceKind.TRIAGE_RECORD, result.to_json(), EventSource.TRIAGE)

    def record_repro(result: Any) -> None:
        save(EvidenceKind.TEST_SOURCE, read_ref(result.test_source_ref), EventSource.REPRODUCTION, "py")
        save(EvidenceKind.TEST_LOG, read_ref(result.log_ref), EventSource.REPRODUCTION, "log")
        save(EvidenceKind.EXIT_CODE, result.to_json(), EventSource.REPRODUCTION)

    def record_patch(result: Any) -> None:
        save(EvidenceKind.DIFF, result.to_json(), EventSource.FIX)
        save(EvidenceKind.DIFF, read_ref(result.diff_ref), EventSource.FIX, "patch")

    def record_verdict(result: Any) -> None:
        save(EvidenceKind.VERDICT, result.to_json(), EventSource.VERIFICATION)
        for _name, test_run in (("before", result.before), ("after", result.after), ("suite", result.suite)):
            save(EvidenceKind.TEST_LOG, test_run.log_ref, EventSource.VERIFICATION, "log")

    existing = events.list_events(case.case_id)
    if not any(e.type == EventType.CASE_CREATED for e in existing):
        append_event(EventSource.INTAKE, EventType.CASE_CREATED)
    if not any(e.type == EventType.EVIDENCE_ADDED for e in existing):
        save(EvidenceKind.REPORT, case.report_text, EventSource.INTAKE, "txt")

    triage_engine: Any = components["TriageEngine"](llm=llm, store=evidence, base_root=root)
    fix_engine: Any
    if mode == "general":
        triage_engine = PlaybookGatedTriage(triage_engine, playbook)
        fix_engine = components["FixStage"](
            base_root=root,
            llm=llm,
            store=evidence,
            allow_fallback=True,
            fallback_on_rejected=False,
        )
        fix_engine = PlaybookGatedFix(fix_engine, playbook)
    else:
        fix_engine = components["FixStage"](base_root=root)

    triage = _RecordedStage(triage_engine, record_triage)
    repro = _RecordedStage(
        components["ReproductionEngine"](llm=llm, store=evidence, base_root=root),
        record_repro,
    )
    fix = _RecordedStage(fix_engine, record_patch)
    verifier = _RecordedStage(components["Verification"](base_root=root), record_verdict)

    final = Orchestrator(
        triage=triage,
        reproduction=repro,
        fix=fix,
        verification=verifier,
        store=events,
        limits_path=root / "config/limits.json",
        llm_calls_getter=llm.get_llm_calls,
        clock=lambda: datetime.now(timezone.utc).isoformat(),
    ).run(case)

    delivery = None
    message = None
    corrected_behavior = None
    verdict = verifier.result
    if final.state == CaseState.VERIFIED:
        record = triage.result
        save(EvidenceKind.DIFF, read_ref(fix.result.diff_ref), EventSource.DELIVERY, "patch", "diff")
        for name, test_run in (("before", verdict.before), ("after", verdict.after), ("suite", verdict.suite)):
            save(EvidenceKind.TEST_LOG, test_run.log_ref, EventSource.DELIVERY, "log", name)
        cause = (
            f"Esperado: {record.expected}; observado: {record.observed}. "
            f"Arquivos suspeitos: {', '.join(record.suspect_files)}. "
            f"Correção proposta no diff; aprovação independente: {verdict.result.value}."
        )
        save(EvidenceKind.REPORT, cause, EventSource.DELIVERY, "txt", "cause")
        corrected_behavior = f"total agora {record.expected}"
        save(EvidenceKind.VERDICT, corrected_behavior, EventSource.DELIVERY, "txt", "corrected_behavior")
        final = replace(final, evidence_ids=tuple(ids))
        delivery = DeliveryBuilder(runs_root=runs, limits_path=root / "config/limits.json").build(final, verdict)
        save(EvidenceKind.PR_PACKAGE, delivery.to_json(), EventSource.DELIVERY)
        if on_case is not None:
            on_case(final)

    if final.state in {CaseState.VERIFIED, CaseState.NEEDS_INFO, CaseState.BLOCKED}:
        seq = events.next_seq(case.case_id)
        message = ReplyComposer().compose(
            final,
            ReplyOutcome(corrected_behavior=corrected_behavior),
            events=events.list_events(case.case_id),
            sent_after_event_seq=seq,
        )
        if message.text.endswith("?."):
            message = replace(message, text=message.text[:-1])
        item = evidence.save_evidence(
            case_id=case.case_id,
            kind=EvidenceKind.CUSTOMER_MESSAGE,
            content=message.to_json(),
            extension="json",
            simulated=True,
        )
        ids.append(item.evidence_id)
        descriptors.append(item.to_dict())
        append_event(EventSource.REPLY, EventType.MESSAGE_SENT, (item.evidence_id,))

    final = replace(final, evidence_ids=tuple(ids))
    if on_case is not None:
        on_case(final)
    (run_dir / "evidence-manifest.json").write_text(
        json.dumps(descriptors, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return PipelineResult(
        case=final,
        run_dir=run_dir,
        events=tuple(events.list_events(case.case_id)),
        evidence_ids=tuple(ids),
        verdict=verdict,
        delivery=delivery,
        message=message,
    )
