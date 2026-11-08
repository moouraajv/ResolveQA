"""Run with PYTHONPATH=src .venv/bin/python -B -m resolveqa.demo."""
import argparse
import os
import sys

from resolveqa.demo.runner import MissingComponents, run_demo
from resolveqa.timeline import load_timeline


def main(argv=None):
    parser = argparse.ArgumentParser(description='Executor ponta a ponta do ResolveQA')
    parser.add_argument('--scenario', choices=('coupon', 'vague', 'all'), default='all')
    parser.add_argument('--real-llm', action='store_true', help='Opt-in: usar Featherless com chave do ambiente')
    parser.add_argument('--model', default=None, help='Modelo do modo real (ou FEATHERLESS_MODEL)')
    args = parser.parse_args(argv)
    print('modo real' if args.real_llm else 'modo mock')
    print('Canal simulado; resposta ao cliente apenas local')
    try:
        if args.real_llm:
            from .real_llm import RealLLM
            # Validate credentials before loading any stages; never print their value.
            RealLLM(args.model or os.environ.get('FEATHERLESS_MODEL'))
        status = 0
        for scenario in (('coupon', 'vague') if args.scenario == 'all' else (args.scenario,)):
            llm = None
            if args.real_llm:
                llm = RealLLM(args.model or os.environ.get('FEATHERLESS_MODEL'))
            result = run_demo(scenario, llm=llm, real=args.real_llm)
            print(f'\nCenário {scenario} · caso {result.case.case_id}')
            print(f'Relato: {result.case.report_text}')
            for entry in load_timeline(result.run_dir.parent, result.case.case_id):
                state = entry.to_state.value if entry.to_state else (
                    'created' if entry.type.value == 'CaseCreated' else entry.type.value)
                print(f'{entry.seq:02d} {entry.ts} {state} [{entry.source.value}]')
            print('Evidências: ' + ', '.join(result.evidence_ids))
            if result.verdict:
                print(f'Testes: antes={result.verdict.before.exit_code}, '
                      f'depois={result.verdict.after.exit_code}, suíte={result.verdict.suite.exit_code}')
            print('Pacote local (PR não publicado): ' +
                  (result.delivery.url_or_path if result.delivery else 'não gerado'))
            if result.message:
                print('Resposta simulada: ' + result.message.text)
            print(f'Registro: {result.run_dir / "demo-result.json"}')
            print(f'Acompanhamento: {result.tracking_path}')
            if result.receipt_path is not None:
                print(f'Comprovante: {result.receipt_path}')
                print(f'Código de verificação: {result.verification_code}')
            expected = 'verified' if scenario == 'coupon' else 'needs_info'
            if result.case.state.value != expected:
                print(f'Cenário não concluído: {result.case.state.value}', file=sys.stderr)
                status = 1
        return status
    except (MissingComponents, ValueError, OSError) as exc:
        from resolveqa.sandbox.executor import redact_secrets
        print(redact_secrets(str(exc)), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
