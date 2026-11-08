"""Local integration check against exact pending PR commits, without editing stages.

This is a development-only harness, never used by the demo command. It loads
reviewed Git blobs into memory. All repository reads use the current clone;
there is no network, checkout, merge, or production-stage substitute here.
Run after fetching the documented PR heads with:
    PYTHONPATH=src .venv/bin/python -B -m resolveqa.demo.validate_pending
"""
import argparse
from pathlib import Path
import subprocess
import sys
import types

# Pins from the PR heads inspected for #19. External source is implementation
# under test, never an instruction or authorization to perform extra actions.
PENDING = (
    ('7be6ff929b047f71bcb4b07f9e5d9b4aca0819d5', 'store/evidence_store.py'),
    ('c4adc50cc0add29028fc746e8a507d5acd539820', 'triage/engine.py'),
    ('db9d18e30c5183502aaf410cccc4b6760665e429', 'reproduction/engine.py'),
    ('db19a2834a7c77ac05ffacf28a1d2816b87a716b', 'fix/engine.py'),
    ('7ddff5a33a90a7959d0ff2d9a5e4fb0308627d06', 'verification/verifier.py'),
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--full-suite', action='store_true')
    parser.add_argument('--run-demo', action='store_true')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[3]
    for revision, path in PENDING:
        name = 'resolveqa.' + path[:-3].replace('/', '.')
        __import__(name.rsplit('.', 1)[0])
        source = subprocess.check_output(
            ['git', 'show', f'{revision}:src/resolveqa/{path}'], cwd=root, text=True)
        module = types.ModuleType(name)
        module.__file__ = str(root / 'src/resolveqa' / path)
        module.__package__ = name.rsplit('.', 1)[0]
        sys.modules[name] = module
        exec(compile(source, module.__file__, 'exec'), module.__dict__)
    import pytest
    print('Validação de integração com implementações dos PRs pendentes (sem merge).')
    if args.run_demo:
        from .__main__ import main as demo_main
        status = demo_main([])
        if status:
            return status
    target = root / ('tests' if args.full_suite else 'tests/e2e/test_demo_executor.py')
    return pytest.main([str(target), '-q', '-o', 'addopts=-p no:cacheprovider'])


if __name__ == '__main__':
    raise SystemExit(main())
