"""Customer documents must reflect evidence, preserve chronology and hide internals."""
import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

from resolveqa.contracts import (
    BlockedReason, BlockedTerminalReason, CaseState, ChannelType, Event, EventSource,
    EventType, Evidence, EvidenceKind, InfraErrorTerminalReason,
    NeedsInfoTerminalReason, RunState,
)
from resolveqa.demo.customer import CustomerArtifactError, generate_customer_artifacts


@pytest.fixture
def recorded_case(tmp_path):
    """Explicit recorded-data fixture, independent of pending pipeline stage PRs."""
    def create(states=('triaging', 'triaged', 'reproducing', 'reproduced',
                       'fixing', 'fixed', 'verifying', 'verified'), *, mock=True):
        case_id = 'case-customer-proof'
        run = tmp_path / case_id
        (run / 'evidence').mkdir(parents=True)
        terminal = CaseState(states[-1])
        reason = {
            CaseState.NEEDS_INFO: NeedsInfoTerminalReason(question_to_support='private-secret checkout.py'),
            CaseState.BLOCKED: BlockedTerminalReason(code=BlockedReason.NOT_REPRODUCED, detail='private-secret'),
            CaseState.INFRA_ERROR: InfraErrorTerminalReason(detail='private-secret'),
        }.get(terminal)
        final = RunState(
            case_id=case_id, client_id='synthetic', repo_ref='private-repository',
            channel=ChannelType.SIMULATED_CHAT, report_text='checkout.py assert False private-secret',
            state=terminal, created_at='2026-11-08T11:00:00Z',
            updated_at='2026-11-08T11:09:00Z',
            terminal_reason=reason,
        )
        descriptors = []
        for identifier, kind, data in [
            ('triage', EvidenceKind.TRIAGE_RECORD, {'input': 'subtotal=200', 'expected': 'R$ 180,00',
             'observed': 'R$ 200,00', 'suspect_files': ['checkout.py'], 'confidence': .95}),
            ('verdict', EvidenceKind.VERDICT, {
                'before': {'command': 'pytest checkout.py', 'exit_code': 1, 'duration_s': .1, 'log_ref': 'AssertionError private-secret'},
                'after': {'command': 'pytest checkout.py', 'exit_code': 0, 'duration_s': .1, 'log_ref': '1 passed'},
                'suite': {'command': 'pytest', 'exit_code': 0, 'duration_s': .1, 'log_ref': '5 passed'},
                'base_revision': 'before-revision', 'fix_revision': 'after-revision',
                'result': 'verified', 'reasons': [],
            }),
        ]:
            content = json.dumps(data).encode()
            path = f'evidence/{identifier}.json'
            (run / path).write_bytes(content)
            descriptors.append(Evidence(
                identifier, case_id, kind, path, hashlib.sha256(content).hexdigest(),
                '2026-11-08T11:00:00Z', simulated=mock,
            ).to_dict())
        events = [Event('created', case_id, 0, final.created_at, EventSource.INTAKE,
                        EventType.CASE_CREATED)]
        previous = CaseState.CREATED
        for seq, state in enumerate(states, 1):
            events.append(Event(str(seq), case_id, seq, f'2026-11-08T11:{seq:02d}:00Z',
                EventSource.VERIFICATION if state == 'verified' else EventSource.ORCHESTRATOR,
                EventType.STATE_CHANGED, previous, CaseState(state)))
            previous = CaseState(state)
        events.append(Event('evidence', case_id, len(events), '2026-11-08T11:10:00Z',
                            EventSource.VERIFICATION, EventType.EVIDENCE_ADDED,
                            evidence_refs=tuple(item['evidence_id'] for item in descriptors)))
        (run / 'events.jsonl').write_text(''.join(e.to_json() + '\n' for e in events))
        (run / 'evidence-manifest.json').write_text(json.dumps(descriptors))
        (run / 'demo-result.json').write_text(json.dumps({
            'mode': 'mock' if mock else 'real', 'case': final.to_dict()}))
        return run, events
    return create


def test_receipt_and_tracking_use_only_safe_recorded_facts(recorded_case):
    run, events = recorded_case()
    artifacts = generate_customer_artifacts(run)
    receipt = artifacts.receipt_path.read_text()
    html = artifacts.tracking_path.read_text()
    assert 'Correção verificada' in receipt
    assert 'Antes: R$ 200,00. Agora: R$ 180,00.' in receipt
    assert 'case-customer-proof' in receipt
    assert '08/11/2026' in receipt
    assert artifacts.verification_code in receipt
    assert artifacts.verification_code in html
    assert 'demonstração com dados simulados' in html
    for forbidden in ('checkout.py', 'assert False', 'private-secret', 'private-repository',
                      'AssertionError', 'pytest', '<script', 'https://', 'http://'):
        assert forbidden not in receipt and forbidden not in html
    expected = [('recebido', events[0].ts), ('investigando', events[1].ts),
                ('reproduzindo', events[3].ts), ('corrigindo', events[5].ts),
                ('verificando', events[7].ts), ('pronto', events[8].ts)]
    positions = []
    for stage, timestamp in expected:
        positions.append(html.index(f'data-stage="{stage}"'))
        assert f'datetime="{timestamp}"' in html
    assert positions == sorted(positions)
    assert '<svg' in html and 'data-mood="pronto"' in html
    assert generate_customer_artifacts(run).verification_code == artifacts.verification_code


def test_needs_info_has_only_a_question_and_no_success_receipt(recorded_case):
    run, events = recorded_case(('triaging', 'needs_info'))
    artifacts = generate_customer_artifacts(run)
    assert artifacts.receipt_path is None and artifacts.verification_code is None
    assert not (run / 'comprovante.txt').exists()
    html = artifacts.tracking_path.read_text()
    assert 'Qual foi o valor da compra' in html and '?' in html
    assert 'Correção verificada' not in html
    assert 'data-stage="pronto"' not in html
    assert 'data-stage="corrigindo"' not in html
    assert 'private-secret' not in html
    assert f'datetime="{events[2].ts}"' in html


def test_modified_evidence_cannot_receive_a_receipt(recorded_case):
    run, _ = recorded_case()
    (run / 'evidence/triage.json').write_text('{}')
    with pytest.raises(CustomerArtifactError, match='integridade'):
        generate_customer_artifacts(run)
    assert not (run / 'comprovante.txt').exists()


def test_verified_state_without_real_event_is_rejected(recorded_case):
    run, events = recorded_case()
    events = [e for e in events if e.to_state != CaseState.VERIFIED]
    (run / 'events.jsonl').write_text(''.join(replace(e, seq=i).to_json() + '\n'
                                           for i, e in enumerate(events)))
    with pytest.raises(CustomerArtifactError):
        generate_customer_artifacts(run)
    assert not (run / 'comprovante.txt').exists()


def test_retries_are_kept_in_event_order(recorded_case):
    run, events = recorded_case(('triaging', 'triaged', 'reproducing', 'reproduced',
                                'fixing', 'fixed', 'verifying', 'fixing', 'fixed',
                                'verifying', 'verified'), mock=False)
    html = generate_customer_artifacts(run).tracking_path.read_text()
    assert html.count('data-stage="corrigindo"') == 2
    assert html.count('data-stage="verificando"') == 2
    assert 'demonstração com dados simulados' not in html
    assert html.index(f'datetime="{events[7].ts}"') < html.index(f'datetime="{events[8].ts}"')


@pytest.mark.parametrize('state', ['blocked', 'infra_error'])
def test_failure_page_is_calm_and_never_claims_success(recorded_case, state):
    run, _ = recorded_case(('triaging', state))
    artifacts = generate_customer_artifacts(run)
    assert artifacts.receipt_path is None
    html = artifacts.tracking_path.read_text()
    assert 'data-mood="interrompido"' in html
    assert 'Ainda não há uma correção confirmada' in html
    assert 'data-stage="pronto"' not in html
    assert 'Correção verificada' not in html
    assert 'private-secret' not in html


def test_code_changes_if_evidence_changes_with_its_hash(recorded_case):
    run, _ = recorded_case()
    previous = generate_customer_artifacts(run).verification_code
    path = run / 'evidence/verdict.json'
    verdict = json.loads(path.read_text())
    verdict['before']['log_ref'] += ' extra evidence'
    path.write_text(json.dumps(verdict))
    manifest_path = run / 'evidence-manifest.json'
    manifest = json.loads(manifest_path.read_text())
    manifest[1]['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest))
    current = generate_customer_artifacts(run).verification_code
    assert current != previous
    assert current in (run / 'comprovante.txt').read_text()


def test_rejected_verdict_cannot_support_verified_receipt(recorded_case):
    run, _ = recorded_case()
    path = run / 'evidence/verdict.json'
    verdict = json.loads(path.read_text())
    verdict['result'] = 'rejected'
    verdict['reasons'] = ['not_approved']
    path.write_text(json.dumps(verdict))
    manifest_path = run / 'evidence-manifest.json'
    manifest = json.loads(manifest_path.read_text())
    manifest[1]['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(CustomerArtifactError, match='aprovação'):
        generate_customer_artifacts(run)
    assert not (run / 'comprovante.txt').exists()


def test_in_progress_page_never_invents_future_steps(recorded_case):
    run, events = recorded_case(('triaging', 'triaged', 'reproducing'))
    artifacts = generate_customer_artifacts(run)
    html = artifacts.tracking_path.read_text()
    assert 'data-mood="reproduzindo"' in html
    assert f'datetime="{events[3].ts}"' in html
    assert 'data-stage="corrigindo"' not in html
    assert 'data-stage="verificando"' not in html
    assert 'data-stage="pronto"' not in html
    assert artifacts.receipt_path is None
