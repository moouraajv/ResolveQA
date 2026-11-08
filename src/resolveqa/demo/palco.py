"""Two-minute stage demo and an explicitly labeled, offline recording replay."""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
from html import escape
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
import webbrowser

from resolveqa.contracts import CaseState, EventType, EvidenceKind, Patch, RunState, Verdict
from resolveqa.sandbox.executor import redact_secrets
from resolveqa.store import EventStore

from .customer import QUESTION, _evidence, _read_json, _verified_facts
from .runner import ROOT, MissingComponents, load_components, run_demo
from .llm import create_demo_llm

# Pending PR snapshots moved to scripts/dev_validate_pending.py (#65).
# On main all public stages are available; keep empty PENDING for replay metadata.
PENDING = ()

def load_pending_components(root, *, only_missing=True):
    """Compatibility no-op: stages must already be merged on main."""
    raise ModuleNotFoundError('pending snapshots moved to scripts/dev_validate_pending.py')

DEFAULT_REPLAY = Path(__file__).resolve().parent / 'replay'
SCENARIOS = ('coupon', 'vague')


def _module_name(path):
    return 'resolveqa.' + path[:-3].replace('/', '.')


def _pending_sources():
    return [(getattr(sys.modules.get(_module_name(path)), '__resolveqa_pending_revision__'), path)
            for _, path in PENDING
            if getattr(sys.modules.get(_module_name(path)), '__resolveqa_pending_revision__', None)]


def _display_path(path):
    path = Path(path).resolve()
    return str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path)


def _record(run_dir):
    """Read evidence without executing any archived code or rewriting documents."""
    summary = _read_json(run_dir / 'demo-result.json')
    case = RunState.from_dict(summary['case'])
    if run_dir.name != case.case_id:
        raise ValueError('Id da gravação diverge da pasta do caso')
    events = EventStore(run_dir.parent).list_events(case.case_id)
    states = [(CaseState.CREATED.value, events[0].ts)] if events else []
    states.extend((event.to_state.value, event.ts) for event in events
                  if event.type == EventType.STATE_CHANGED and event.to_state is not None)
    if not states or states[-1][0] != case.state.value:
        raise ValueError('Estado da gravação diverge dos eventos')
    descriptors, payloads = _evidence(run_dir, case, events)
    facts = verdict = patch = None
    if case.state == CaseState.VERIFIED:
        _, before, after = _verified_facts(case, events, payloads, run_dir)
        facts = (before, after)
        verdict = next(Verdict.from_dict(data) for item, data in reversed(payloads)
                       if item.kind == EvidenceKind.VERDICT and isinstance(data, dict) and 'result' in data)
        patch = next(Patch.from_dict(data) for item, data in reversed(payloads)
                     if item.kind == EvidenceKind.DIFF and isinstance(data, dict) and 'diff_ref' in data)
    return summary, case, states, facts, verdict, patch


def _show_case(scenario, run_dir, *, replay=False):
    _, case, states, facts, verdict, patch = _record(run_dir)
    print(f'\n{"1/2 · Cupom" if scenario == "coupon" else "2/2 · Relato vago"}')
    print('Relato: ' + redact_secrets(case.report_text).replace('\n', ' ').replace('\r', ' '))
    timeline = ' → '.join(f'{state} {datetime.fromisoformat(ts.replace("Z", "+00:00")).strftime("%H:%M:%S")}'
                          for state, ts in states)
    print('Estados (UTC): ' + timeline)
    if verdict is not None:
        if (patch.touches_tests or patch.touches_ci
                or not (run_dir / 'comprovante.txt').is_file()
                or not (run_dir / 'delivery/pr-nao-publicado/MANIFEST.json').is_file()):
            raise ValueError('Artefatos da correção verificada indisponíveis ou inconsistentes')
        print(f'RED: observado {facts[0]}; esperado {facts[1]} (exit={verdict.before.exit_code})')
        print(f'PATCH: {len(patch.files_changed)} arquivo alterado; testes e CI preservados')
        print(f'GREEN: reprodução={verdict.after.exit_code}; suíte={verdict.suite.exit_code}')
        print('VEREDITO: verified — RED antes, GREEN depois e suíte verde; revisões registradas')
        print('Comprovante: ' + _display_path(run_dir / 'comprovante.txt'))
        print('Pacote: PR não publicado — ' + _display_path(run_dir / 'delivery/pr-nao-publicado'))
    elif case.state == CaseState.NEEDS_INFO:
        print('VEREDITO: needs_info — relato insuficiente; sem patch nem comprovante')
        print('Pergunta: ' + QUESTION)
    else:
        print(f'VEREDITO: {case.state.value} — correção não confirmada')
    page = run_dir / ('acompanhamento-replay.html' if replay else 'acompanhamento.html')
    if not page.is_file():
        raise ValueError('Página de acompanhamento indisponível')
    print('Página: ' + _display_path(page))
    expected = CaseState.VERIFIED if scenario == 'coupon' else CaseState.NEEDS_INFO
    return page, 0 if case.state == expected else 1


def record_replay(results, destination, pending):
    """Copy actual completed runs, preserving original bytes; refuse overwriting recordings."""
    destination = Path(destination).resolve()
    if destination.exists():
        raise ValueError('Destino da gravação já existe; escolha uma pasta nova')
    if len(results) != 2 or results[0].case.state != CaseState.VERIFIED or results[1].case.state != CaseState.NEEDS_INFO:
        raise ValueError('Só é possível gravar os dois cenários concluídos')
    recorded_at = results[0].case.created_at
    destination.mkdir(parents=True)
    try:
        scenarios = {}
        for scenario, result in zip(SCENARIOS, results):
            if any(path.is_symlink() for path in result.run_dir.rglob('*')):
                raise ValueError('Gravação não aceita referências simbólicas')
            target = destination / result.case.case_id
            shutil.copytree(result.run_dir, target)
            notice = (f'REPLAY de uma execução gravada em {result.case.created_at} — NÃO É AO VIVO')
            original_page = (target / 'acompanhamento.html').read_text(encoding='utf-8')
            if '<body>' not in original_page:
                raise ValueError('Página original sem ponto seguro para o aviso de replay')
            labeled = original_page.replace('<body>',
                '<body><aside class="notice" role="note" style="max-width:680px;margin:0 auto">'
                + escape(notice) + '</aside>', 1)
            (target / 'acompanhamento-replay.html').write_text(labeled, encoding='utf-8')
            scenarios[scenario] = result.case.case_id
        inventory = {path.relative_to(destination).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                     for path in sorted(destination.rglob('*')) if path.is_file()}
        index = {'format_version': 1, 'recorded_at': recorded_at,
                 'mode': 'mock' if all(_read_json(result.run_dir / 'demo-result.json')['mode'] == 'mock'
                                       for result in results) else 'real',
                 'pending': list(pending), 'scenarios': scenarios, 'files': inventory}
        (destination / 'index.json').write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding='utf-8')
    except BaseException:
        shutil.rmtree(destination)
        raise
    return destination


def load_replay(destination):
    destination = Path(destination).resolve()
    index = _read_json(destination / 'index.json')
    if (not isinstance(index, dict) or index.get('format_version') != 1 or index.get('mode') not in {'mock', 'real'}
            or not isinstance(index.get('scenarios'), dict)
            or set(index['scenarios']) != set(SCENARIOS)
            or not isinstance(index.get('files'), dict) or not index['files']):
        raise ValueError('Índice de replay inválido')
    datetime.fromisoformat(index['recorded_at'].replace('Z', '+00:00'))
    actual_files = {path.relative_to(destination).as_posix() for path in destination.rglob('*')
                    if path.is_file() and path != destination / 'index.json'}
    if actual_files != set(index['files']):
        raise ValueError('Inventário de integridade do replay incompleto')
    for relative, digest in index['files'].items():
        rel = PurePosixPath(relative)
        path = destination / relative
        if rel.is_absolute() or '..' in rel.parts or path.is_symlink() or not path.resolve().is_relative_to(destination):
            raise ValueError('Referência de replay inválida')
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError('Falha de integridade da gravação de replay')
    runs = []
    for scenario in SCENARIOS:
        case_id = index['scenarios'][scenario]
        if not isinstance(case_id, str) or not case_id.startswith('case-') or PurePosixPath(case_id).name != case_id:
            raise ValueError('Id de caso do replay inválido')
        run_dir = destination / case_id
        if not run_dir.resolve().is_relative_to(destination):
            raise ValueError('Caso de replay fora da gravação')
        summary, case, *_ = _record(run_dir)
        if (summary['mode'] != index['mode']
                or (scenario == 'coupon' and case.created_at != index['recorded_at'])):
            raise ValueError('Metadados do replay divergem da execução gravada')
        expected = CaseState.VERIFIED if scenario == 'coupon' else CaseState.NEEDS_INFO
        if case.state != expected:
            raise ValueError('Cenário de replay não corresponde ao resultado gravado')
        runs.append(run_dir)
    return index, runs


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--replay', nargs='?', const=DEFAULT_REPLAY, type=Path, metavar='DIR')
    mode.add_argument('--real-llm', action='store_true', help='Opt-in explícito para Featherless')
    parser.add_argument('--model', help='Modelo real ou FEATHERLESS_MODEL')
    parser.add_argument('--record-replay', type=Path, metavar='DIR', help='Salvar esta execução numa pasta nova')
    parser.add_argument('--open-page', action='store_true', help='Abrir a página local do cupom; todos os caminhos são impressos')
    args = parser.parse_args(argv)
    if args.replay and args.record_replay:
        parser.error('--replay e --record-replay são modos distintos')
    saved_modules = {_module_name(path): sys.modules.get(_module_name(path)) for _, path in PENDING}
    try:
        if args.replay:
            index, runs = load_replay(args.replay)
            print('modo mock' if index['mode'] == 'mock' else 'modo real (Featherless)')
            print(f'REPLAY de uma execução gravada em {index["recorded_at"]} — NÃO É AO VIVO')
            if index['pending']:
                print('Gravação com implementações reais de PRs pendentes; nenhum pipeline é executado no replay')
            pages, statuses = zip(*(_show_case(scenario, run_dir, replay=True)
                                    for scenario, run_dir in zip(SCENARIOS, runs)))
        else:
            print('modo real (Featherless)' if args.real_llm else 'modo mock', flush=True)
            if args.record_replay and args.record_replay.exists():
                raise ValueError('Destino da gravação já existe; escolha uma pasta nova')
            llm_factory = None
            if args.real_llm:
                create_demo_llm(real=True)  # Validate opt-in credentials before loading stages.
                llm_factory = lambda: create_demo_llm(real=True)
            try:
                load_components()
            except MissingComponents:
                # Dev-only fallback lives outside src/; presentation path requires merged APIs.
                load_pending_components(ROOT, only_missing=True)
                load_components()
            pending = _pending_sources()
            print('Composição: implementações reais de PRs pendentes (Git local, sem merge)'
                  if pending else 'Composição: APIs públicas disponíveis na branch')
            results, pages, statuses = [], [], []
            for scenario in SCENARIOS:
                result = run_demo(scenario, llm=llm_factory() if llm_factory else None, real=args.real_llm)
                results.append(result)
                page, status = _show_case(scenario, result.run_dir)
                pages.append(page)
                statuses.append(status)
            if args.record_replay:
                path = record_replay(results, args.record_replay, pending)
                print('Replay gravado: ' + _display_path(path))
        if args.open_page and not webbrowser.open(pages[0].resolve().as_uri()):
            print('Navegador indisponível; use o caminho da página indicado acima', file=sys.stderr)
        return max(statuses)
    except (OSError, ValueError, MissingComponents, subprocess.CalledProcessError, ImportError, KeyError, StopIteration) as exc:
        print('Palco indisponível: ' + redact_secrets(str(exc)), file=sys.stderr)
        return 2
    finally:
        # Do not leave stage-only imports installed in the caller's process.
        for name, original in saved_modules.items():
            if original is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = original


if __name__ == '__main__':
    raise SystemExit(main())
