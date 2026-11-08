"""Safe, static customer documents derived from recorded events and hashed evidence."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
from html import escape
import json
from pathlib import Path
import re

from resolveqa.contracts import (
    CaseState, ContractValidationError, EventSource, EventType, Evidence, EvidenceKind, RunState, Verdict,
    VerdictResult, TERMINAL_STATES,
)
from resolveqa.store import EventStore


class CustomerArtifactError(ValueError):
    """Recorded data cannot support an honest customer document."""


@dataclass(frozen=True)
class CustomerArtifacts:
    tracking_path: Path
    receipt_path: Path | None = None
    verification_code: str | None = None


# Only these public labels cross the boundary into customer HTML.
STAGES = {
    CaseState.TRIAGING: ('investigando', 'Investigando'),
    CaseState.REPRODUCING: ('reproduzindo', 'Reproduzindo'),
    CaseState.FIXING: ('corrigindo', 'Corrigindo'),
    CaseState.VERIFYING: ('verificando', 'Verificando'),
    CaseState.VERIFIED: ('pronto', 'Pronto'),
    CaseState.NEEDS_INFO: ('aguardando', 'Precisamos de mais informações'),
    CaseState.BLOCKED: ('interrompido', 'Análise interrompida'),
    CaseState.INFRA_ERROR: ('interrompido', 'Análise interrompida'),
}
QUESTION = ('Qual foi o valor da compra, qual cupom você usou e quais foram os '
            'valores esperado e observado?')


def _read_json(path):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        raise CustomerArtifactError('Registro do caso indisponível ou inválido') from exc


def _time(ts):
    return datetime.fromisoformat(ts.replace('Z', '+00:00')).strftime('%d/%m/%Y às %H:%M:%S UTC')


def _amount(value):
    # Extract no free-form model or report text: accept only a complete BRL amount.
    if not isinstance(value, str) or not re.fullmatch(
        r'R\$\s*(?:\d{1,3}(?:\.\d{3})+|\d+),\d{2}', value.strip()
    ):
        raise CustomerArtifactError('Valores seguros de antes e depois indisponíveis')
    return 'R$ ' + value.strip()[2:].strip()


def _evidence(run_dir, case, events):
    manifest = _read_json(run_dir / 'evidence-manifest.json')
    if not isinstance(manifest, list) or not manifest:
        raise CustomerArtifactError('Evidências do caso indisponíveis')
    descriptors, payloads, identifiers = [], [], set()
    for entry in manifest:
        try:
            item = Evidence.from_dict(entry)
        except ContractValidationError:
            raise CustomerArtifactError('Registro de evidência inválido') from None
        path = run_dir / item.path
        if (item.case_id != case.case_id or item.evidence_id in identifiers
                or path.is_symlink() or not path.resolve().is_relative_to(run_dir)):
            raise CustomerArtifactError('Referência de evidência inválida')
        try:
            raw = path.read_bytes()
        except OSError as exc:
            raise CustomerArtifactError('Evidência indisponível') from exc
        if hashlib.sha256(raw).hexdigest() != item.sha256:
            raise CustomerArtifactError('Falha de integridade das evidências')
        identifiers.add(item.evidence_id)
        descriptors.append(item)
        try:
            payload = json.loads(raw)
        except (ValueError, UnicodeError):
            payload = None
        payloads.append((item, payload))
    referenced = {ref for event in events for ref in event.evidence_refs}
    if not referenced.issubset(identifiers):
        raise CustomerArtifactError('Evento referencia evidência ausente')
    return descriptors, payloads


def _verified_facts(case, events, payloads):
    approved = [event for event in events if event.type == EventType.STATE_CHANGED
                and event.to_state == CaseState.VERIFIED
                and event.source == EventSource.VERIFICATION]
    if not approved:
        raise CustomerArtifactError('Correção sem evento de verificação independente')
    try:
        verdicts = [Verdict.from_dict(data) for item, data in payloads
                    if item.kind == EvidenceKind.VERDICT and isinstance(data, dict)
                    and 'result' in data]
    except ContractValidationError:
        raise CustomerArtifactError('Evidência de aprovação inválida') from None
    if not verdicts or verdicts[-1].result != VerdictResult.VERIFIED:
        raise CustomerArtifactError('Correção sem evidência de aprovação')
    verdict = verdicts[-1]
    if (verdict.before.exit_code == 0 or verdict.after.exit_code != 0
            or verdict.suite.exit_code != 0 or not verdict.base_revision
            or not verdict.fix_revision or verdict.base_revision == verdict.fix_revision):
        raise CustomerArtifactError('Evidências insuficientes para comprovar a correção')
    records = [data for item, data in payloads if item.kind == EvidenceKind.TRIAGE_RECORD
               and isinstance(data, dict) and 'expected' in data and 'observed' in data]
    if not records:
        raise CustomerArtifactError('Valores de antes e depois indisponíveis')
    return approved[-1], _amount(records[-1]['observed']), _amount(records[-1]['expected'])


def _code(case_id, verified_at, descriptors):
    # Bind a deterministic checksum to the case, approval event and evidence hashes.
    canonical = json.dumps({
        'case_id': case_id, 'verified_at': verified_at,
        'evidence': sorted((item.evidence_id, item.sha256) for item in descriptors),
    }, ensure_ascii=True, sort_keys=True, separators=(',', ':'))
    digest = hashlib.sha256(canonical.encode('utf-8')).hexdigest()[:16].upper()
    return '-'.join(digest[i:i + 4] for i in range(0, 16, 4))


def _receipt(case, approval, before, after, code, *, mock):
    return '\n'.join((
        'COMPROVANTE DE CORREÇÃO', 'Correção verificada',
        *(['demonstração com dados simulados'] if mock else []), '',
        f'Id do caso: {case.case_id}', f'Data e hora: {_time(approval.ts)}', '',
        'O que você relatou:',
        f'O total da compra continuou em {before}, quando você esperava {after}.', '',
        'O que estava errado:', f'O total mostrado era diferente do valor esperado de {after}.', '',
        'O que ficou certo:', f'Antes: {before}. Agora: {after}.',
        'O total foi corrigido e o resultado foi conferido.', '',
        f'Código de verificação: {code}', '',
    ))


CSS = '''
:root{color-scheme:light;font-family:system-ui,sans-serif;color:#213b38;background:#f3f6f3}
*{box-sizing:border-box}body{margin:0;padding:40px 18px}main{max-width:680px;margin:auto}
header,section{background:#fff;border:1px solid #dce6e0;border-radius:20px;padding:28px;margin:18px 0}
header{display:flex;align-items:center;gap:22px}h1{font-size:1.75rem;line-height:1.2;margin:8px 0}
h2{font-size:1.1rem;margin:0 0 20px}p{line-height:1.65;margin:8px 0}.eyebrow{font-size:.78rem;letter-spacing:.12em;text-transform:uppercase}
.notice{padding:12px 18px;border:1px solid #c9ddd4;border-radius:12px;background:#e9f3ee}
.case{overflow-wrap:anywhere;color:#536a65;font-size:.9rem}ol{list-style:none;margin:0;padding:0}
li{display:grid;grid-template-columns:34px 1fr;gap:14px;padding-bottom:22px;position:relative}
li:last-child{padding-bottom:0}li:not(:last-child):before{content:"";position:absolute;left:15px;top:30px;bottom:0;width:2px;background:#dce6e0}
.dot{height:32px;width:32px;border-radius:50%;background:#e2f1e9;color:#25694f;display:grid;place-items:center;font-weight:650}
time{display:block;font-size:.85rem;color:#62766f;margin-top:5px}strong{font-weight:650}
.change{display:grid;grid-template-columns:1fr 1fr;gap:12px}.amount{border:1px solid #dce6e0;border-radius:12px;padding:18px}
.amount span{display:block;color:#62766f;font-size:.85rem}.amount b{display:block;font-size:1.4rem;margin-top:8px}
pre{font:inherit;white-space:pre-wrap;line-height:1.75;margin:0;overflow-wrap:anywhere}
.mascot{flex:none;width:92px;height:100px}.mascot .body{fill:#d9eee3;stroke:#36765c;stroke-width:2}
.mascot .face{fill:#254f40}.mascot .tool{stroke:#36765c;stroke-width:3;fill:none;stroke-linecap:round}
.mascot .scan,.mascot .repeat,.mascot .repair,.mascot .verify,.mascot .check,.mascot .pause{display:none}
.mascot[data-mood="investigando"] .scan,.mascot[data-mood="reproduzindo"] .repeat,.mascot[data-mood="corrigindo"] .repair,.mascot[data-mood="verificando"] .verify{display:block}
.mascot[data-mood="corrigindo"] .body{fill:#c5e5db}
.mascot[data-mood="pronto"] .check{display:block}
.mascot[data-mood="aguardando"] .pause,.mascot[data-mood="interrompido"] .pause{display:block}
.mascot[data-mood="interrompido"] .body{fill:#e9e9e1;stroke:#6e7565}
@media(max-width:480px){header,section{padding:20px}header{gap:12px}.mascot{width:68px}.change{grid-template-columns:1fr}h1{font-size:1.4rem}}
@media print{body{background:white;padding:0}header,section{break-inside:avoid}.notice{background:white}}
'''


def _mascot(mood):
    # All mood values come from STAGES, never from free-form model output.
    return f'''<svg class="mascot" data-mood="{mood}" viewBox="0 0 100 110" role="img" aria-label="Assistente acompanhando o caso">
<rect class="body" x="16" y="16" width="68" height="78" rx="24"/>
<circle class="face" cx="37" cy="47" r="3"/><circle class="face" cx="63" cy="47" r="3"/>
<path class="tool" d="M42 63h16"/>
<g class="scan tool"><circle cx="71" cy="79" r="10"/><path d="m79 87 9 9"/></g>
<path class="repeat tool" d="M35 78a16 16 0 0 1 28-2m0-7v8h-8m9 10a16 16 0 0 1-28-2m0 7v-8h8"/>
<path class="repair tool" d="m37 91 20-20m-1-5 9 2 2 9-7 5-9-9z"/>
<g class="verify tool"><rect x="36" y="71" width="28" height="27" rx="4"/><path d="m42 84 5 5 11-11"/></g>
<path class="check tool" d="m35 81 10 9 21-23"/>
<path class="pause tool" d="M43 77v11m14-11v11"/>
</svg>'''


def _page(case, steps, *, mock, receipt, before, after):
    mood = steps[-1][0]
    title = {'pronto': 'Sua correção foi verificada', 'aguardando': 'Precisamos da sua ajuda',
             'interrompido': 'O caso precisa de atenção'}.get(mood, 'Estamos cuidando do seu caso')
    notice = '<p class="notice">demonstração com dados simulados</p>' if mock else ''
    rows = []
    for index, (stage, label, ts) in enumerate(steps, 1):
        rows.append(f'<li data-stage="{stage}"><span class="dot">{index}</span><div>'
                    f'<strong>{label}</strong><time datetime="{escape(ts, quote=True)}">{escape(_time(ts))}</time>'
                    '</div></li>')
    details = ''
    if receipt is not None:
        details = (f'<section aria-label="Resultado"><h2>O que mudou</h2><div class="change">'
                   f'<div class="amount"><span>Antes</span><b>{escape(before)}</b></div>'
                   f'<div class="amount"><span>Agora</span><b>{escape(after)}</b></div></div></section>'
                   '<section aria-label="Comprovante de correção"><h2>Comprovante de correção</h2>'
                   f'<pre>{escape(receipt)}</pre></section>')
    elif case.state == CaseState.NEEDS_INFO:
        details = f'<section aria-label="Pergunta"><p>{QUESTION}</p></section>'
    elif case.state in {CaseState.BLOCKED, CaseState.INFRA_ERROR}:
        details = '<section><p>A análise foi interrompida. Ainda não há uma correção confirmada.</p></section>'
    return f'''<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'">
<title>Acompanhamento do caso</title><style>{CSS}</style></head>
<body><main>{notice}<header>{_mascot(mood)}<div><p class="eyebrow">Acompanhamento do caso</p>
<h1>{title}</h1><p class="case">Id do caso: {escape(case.case_id)}</p></div></header>
<section aria-label="Etapas registradas"><h2>Etapas registradas</h2><ol>{''.join(rows)}</ol></section>
{details}</main></body></html>'''


def generate_customer_artifacts(run_dir: Path | str) -> CustomerArtifacts:
    """Read recorded files; validate hashes; publish only allowlisted customer facts."""
    run_dir = Path(run_dir).resolve()
    result = _read_json(run_dir / 'demo-result.json')
    if not isinstance(result, dict) or not isinstance(result.get('case'), dict):
        raise CustomerArtifactError('Registro do caso inválido')
    case = RunState.from_dict(result['case'])
    if (run_dir.name != case.case_id
            or not re.fullmatch(r'case-[A-Za-z0-9-]{1,64}', case.case_id)
            or result.get('mode') not in {'mock', 'real'}):
        raise CustomerArtifactError('Identificação do caso inválida')
    events = EventStore(run_dir.parent).list_events(case.case_id)
    if not events or events[0].type != EventType.CASE_CREATED:
        raise CustomerArtifactError('Evento de recebimento ausente')
    if any(event.case_id != case.case_id or event.seq != index for index, event in enumerate(events)):
        raise CustomerArtifactError('Sequência de eventos inválida')
    previous = CaseState.CREATED
    steps = [('recebido', 'Recebido', events[0].ts)]
    for event in events:
        if event.type != EventType.STATE_CHANGED:
            continue
        if previous in TERMINAL_STATES or event.from_state != previous:
            raise CustomerArtifactError('Histórico de estados inconsistente')
        previous = event.to_state
        if event.to_state in STAGES:
            stage, label = STAGES[event.to_state]
            steps.append((stage, label, event.ts))
    if previous != case.state:
        raise CustomerArtifactError('Estado do caso não corresponde aos eventos')
    descriptors, payloads = _evidence(run_dir, case, events)
    receipt = code = before = after = None
    receipt_path = None
    if case.state == CaseState.VERIFIED:
        approval, before, after = _verified_facts(case, events, payloads)
        code = _code(case.case_id, approval.ts, descriptors)
        receipt = _receipt(case, approval, before, after, code, mock=result['mode'] == 'mock')
        receipt_path = run_dir / 'comprovante.txt'
    tracking_path = run_dir / 'acompanhamento.html'
    for path in (tracking_path, run_dir / 'comprovante.txt'):
        if path.is_symlink():
            raise CustomerArtifactError('Destino de documento inválido')
    if receipt is None and (run_dir / 'comprovante.txt').exists():
        raise CustomerArtifactError('Comprovante existente sem aprovação atual')
    page = _page(case, steps, mock=result['mode'] == 'mock', receipt=receipt, before=before, after=after)
    tracking_path.write_text(page, encoding='utf-8')
    if receipt_path is not None:
        receipt_path.write_text(receipt, encoding='utf-8')
    return CustomerArtifacts(tracking_path, receipt_path, code)
