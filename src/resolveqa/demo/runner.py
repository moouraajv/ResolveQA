"""Compose the public pipeline without substituting missing production stages."""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from importlib import import_module
import json
from pathlib import Path
from uuid import uuid4

from resolveqa.contracts import (
    CaseState, ChannelType, CustomerMessage, DeliveryResult, Event, EventSource,
    EventType, EvidenceKind, RunState, Verdict,
    ReportInput,
)
from resolveqa.delivery import DeliveryBuilder
from resolveqa.intake import Intake
from resolveqa.llm import DeterministicMockLLM
from resolveqa.orchestrator import Orchestrator
from resolveqa.reply import ReplyComposer, ReplyOutcome
from resolveqa.store import EventStore

from .customer import generate_customer_artifacts

COUPON_REPORT = ('Comprei R$ 200,00 no site, apliquei o cupom DESC10 de 10% e o total '
                 'continuou R$ 200,00. Deveria ser R$ 180,00.')
VAGUE_REPORT = 'O checkout está estranho, o valor não bate.'
ROOT = Path(__file__).resolve().parents[3]


class MissingComponents(RuntimeError):
    """Required public implementation has not landed yet."""


def load_components():
    """Import known APIs explicitly; list every missing dependency in one diagnostic."""
    required = (
        ('resolveqa.store.evidence_store', 'EvidenceStore', 47),
        ('resolveqa.triage.engine', 'TriageEngine', 49),
        ('resolveqa.reproduction.engine', 'ReproductionEngine', 50),
        ('resolveqa.fix.engine', 'FixStage', 52),
        ('resolveqa.verification.verifier', 'Verification', 53),
    )
    loaded, missing = {}, []
    for module, symbol, pr in required:
        try:
            loaded[symbol] = getattr(import_module(module), symbol)
        except (ImportError, AttributeError):
            missing.append(f'{module}.{symbol} (PR #{pr})')
    if missing:
        raise MissingComponents('Fluxo indisponível; faltam implementações compatíveis na main: '
                                + '; '.join(missing))
    return loaded


@dataclass(frozen=True)
class DemoResult:
    case: RunState
    run_dir: Path
    events: tuple[Event, ...]
    evidence_ids: tuple[str, ...]
    verdict: Verdict | None = None
    delivery: DeliveryResult | None = None
    message: CustomerMessage | None = None
    receipt_path: Path | None = None
    tracking_path: Path | None = None
    verification_code: str | None = None


class _RecordedStage:
    """Observe a real stage result; only the main orchestrator changes case state."""
    def __init__(self, stage, record):
        self.stage, self.record, self.result = stage, record, None

    def run(self, *args):
        self.result = self.stage.run(*args)
        self.record(self.result)
        return self.result


def run_demo(scenario='coupon', *, root=ROOT, llm=None, real=False):
    """Run a fresh synthetic case, persisting actual events, outputs and delivery."""
    if scenario not in {'coupon', 'vague'}:
        raise ValueError('scenario must be coupon or vague')
    components = load_components()  # Fail before creating a case or any artefact.
    root = Path(root).resolve()
    runs = root / 'runs'
    case = Intake().create(ReportInput(
        client_id='client-demo', repo_ref='demo-target',
        channel=ChannelType.SIMULATED_CHAT,
        report_text=COUPON_REPORT if scenario == 'coupon' else VAGUE_REPORT,
    ))
    mode = 'real' if real else 'mock'
    llm = llm if llm is not None else DeterministicMockLLM(case=case)
    if real and not getattr(llm, 'use_real', False):
        raise ValueError('Modo real exige adaptador real explícito')
    if not real and getattr(llm, 'use_real', False):
        raise ValueError('Adaptador real exige a flag explícita de modo real')
    llm.bind_case(case)
    events = EventStore(runs)
    evidence = components['EvidenceStore'](runs_root=runs)
    run_dir = runs / case.case_id
    ids = []
    descriptors = []

    def append_event(source, kind, refs=()):
        events.append(Event(
            event_id=uuid4().hex, case_id=case.case_id,
            seq=events.next_seq(case.case_id), ts=datetime.now(timezone.utc).isoformat(),
            source=source, type=kind, evidence_refs=tuple(refs),
        ))

    def save(kind, content, source, extension='json', evidence_id=None):
        item = evidence.save_evidence(
            case_id=case.case_id, kind=kind, content=content,
            extension=extension, evidence_id=evidence_id,
            simulated=(not real or kind in {EvidenceKind.REPORT, EvidenceKind.PR_PACKAGE}),
        )
        ids.append(item.evidence_id)
        descriptors.append(item.to_dict())
        append_event(source, EventType.EVIDENCE_ADDED, (item.evidence_id,))
        return item

    def read_ref(ref):
        # Stages return paths relative to the case or repository root.
        for base in (run_dir, root):
            path = (base / ref).resolve()
            if path.is_relative_to(run_dir.resolve()) and path.is_file():
                return path.read_text(encoding='utf-8')
        raise FileNotFoundError('Artefato da etapa ausente dentro do diretório do caso')

    def record_triage(result):
        save(EvidenceKind.TRIAGE_RECORD, result.to_json(), EventSource.TRIAGE)

    def record_repro(result):
        save(EvidenceKind.TEST_SOURCE, read_ref(result.test_source_ref),
             EventSource.REPRODUCTION, 'py')
        save(EvidenceKind.TEST_LOG, read_ref(result.log_ref), EventSource.REPRODUCTION, 'log')
        save(EvidenceKind.EXIT_CODE, result.to_json(), EventSource.REPRODUCTION)

    def record_patch(result):
        save(EvidenceKind.DIFF, result.to_json(), EventSource.FIX)
        save(EvidenceKind.DIFF, read_ref(result.diff_ref), EventSource.FIX,
             'patch')

    def record_verdict(result):
        save(EvidenceKind.VERDICT, result.to_json(), EventSource.VERIFICATION)
        # Verification's public TestRun currently exposes captured log text.
        for name, test_run in (('before', result.before), ('after', result.after),
                               ('suite', result.suite)):
            save(EvidenceKind.TEST_LOG, test_run.log_ref, EventSource.VERIFICATION,
                 'log')

    append_event(EventSource.INTAKE, EventType.CASE_CREATED)
    save(EvidenceKind.REPORT, case.report_text, EventSource.INTAKE, 'txt')

    triage = _RecordedStage(components['TriageEngine'](llm=llm, store=evidence, base_root=root), record_triage)
    repro = _RecordedStage(components['ReproductionEngine'](llm=llm, store=evidence, base_root=root), record_repro)
    fix = _RecordedStage(components['FixStage'](base_root=root), record_patch)
    verifier = _RecordedStage(components['Verification'](base_root=root), record_verdict)
    # Intake history and report already exist; the orchestrator owns all transitions.
    final = Orchestrator(
        triage=triage, reproduction=repro, fix=fix, verification=verifier,
        store=events, limits_path=root / 'config/limits.json',
        llm_calls_getter=llm.get_llm_calls,
        clock=lambda: datetime.now(timezone.utc).isoformat(),
    ).run(case)
    delivery = message = None
    verdict = verifier.result
    if final.state == CaseState.VERIFIED:
        # Delivery's public file convention; data comes only from real stage outputs.
        record = triage.result
        save(EvidenceKind.DIFF, read_ref(fix.result.diff_ref), EventSource.DELIVERY,
             'patch', 'diff')
        for name, test_run in (('before', verdict.before), ('after', verdict.after),
                               ('suite', verdict.suite)):
            save(EvidenceKind.TEST_LOG, test_run.log_ref, EventSource.DELIVERY, 'log', name)
        cause = (f'Esperado: {record.expected}; observado: {record.observed}. '
                 f'Arquivos suspeitos: {", ".join(record.suspect_files)}. '
                 f'Correção proposta no diff; aprovação independente: {verdict.result.value}.')
        save(EvidenceKind.REPORT, cause, EventSource.DELIVERY, 'txt', 'cause')
        save(EvidenceKind.VERDICT, 'total agora R$ 180,00', EventSource.DELIVERY,
             'txt', 'corrected_behavior')
        final = replace(final, evidence_ids=tuple(ids))
        delivery = DeliveryBuilder(runs_root=runs, limits_path=root / 'config/limits.json').build(final, verdict)
        save(EvidenceKind.PR_PACKAGE, delivery.to_json(), EventSource.DELIVERY)
    if final.state in {CaseState.VERIFIED, CaseState.NEEDS_INFO, CaseState.BLOCKED}:
        seq = events.next_seq(case.case_id)
        message = ReplyComposer().compose(
            final, ReplyOutcome(corrected_behavior='total agora R$ 180,00'
                                if final.state == CaseState.VERIFIED else None),
            events=events.list_events(case.case_id), sent_after_event_seq=seq,
        )
        # The channel is simulated. Record the message at its actual sequence.
        item = evidence.save_evidence(case_id=case.case_id, kind=EvidenceKind.CUSTOMER_MESSAGE,
                                     content=message.to_json(), extension='json', simulated=True)
        ids.append(item.evidence_id)
        descriptors.append(item.to_dict())
        append_event(EventSource.REPLY, EventType.MESSAGE_SENT, (item.evidence_id,))
    final = replace(final, evidence_ids=tuple(ids))
    result = DemoResult(final, run_dir, tuple(events.list_events(case.case_id)),
                        tuple(ids), verdict, delivery, message)
    (run_dir / 'evidence-manifest.json').write_text(
        json.dumps(descriptors, ensure_ascii=False, indent=2), encoding='utf-8')
    summary = {
        'mode': mode, 'channel': 'Canal simulado', 'case': final.to_dict(),
        'evidence_ids': ids, 'delivery': delivery.to_dict() if delivery else None,
        'message': message.to_dict() if message else None,
    }
    summary_path = run_dir / 'demo-result.json'
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    customer = generate_customer_artifacts(run_dir)
    summary['customer_artifacts'] = {
        'tracking': customer.tracking_path.name,
        'receipt': customer.receipt_path.name if customer.receipt_path else None,
        'verification_code': customer.verification_code,
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    return replace(result, tracking_path=customer.tracking_path,
                   receipt_path=customer.receipt_path, verification_code=customer.verification_code)
