"""DEVELOPMENT ONLY: validate fixed PR implementations locally; never import from src/.

This script imports code from local Git objects for development experiments only.
Live demos use merged public APIs. Replay is the offline presentation fallback.
No fetch/merge/network is performed. Source snapshots live in a temporary folder;
module.__file__ points to the actual snapshot file for the whole validation run.
"""
import argparse
from importlib import import_module, util
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
PENDING = (
    ('db9d18e30c5183502aaf410cccc4b6760665e429', 'reproduction/engine.py'),
    ('db19a2834a7c77ac05ffacf28a1d2816b87a716b', 'fix/engine.py'),
    ('7ddff5a33a90a7959d0ff2d9a5e4fb0308627d06', 'verification/verifier.py'),
)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--full-suite', action='store_true')
    parser.add_argument('--run-demo', action='store_true')
    args = parser.parse_args(argv)
    sys.path.insert(0, str(ROOT / 'src'))
    print('SOMENTE DESENVOLVIMENTO: snapshots locais de PRs pendentes; não é demo na main.', flush=True)
    with tempfile.TemporaryDirectory(prefix='resolveqa-dev-snapshots-') as directory:
        snapshots = Path(directory) / 'src/resolveqa'
        for revision, path in PENDING:
            name = 'resolveqa.' + path[:-3].replace('/', '.')
            try:
                import_module(name)
            except ModuleNotFoundError as exc:
                if exc.name != name:
                    raise
            else:
                continue
            file = snapshots / path
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_bytes(subprocess.check_output(
                ['git', 'show', f'{revision}:src/resolveqa/{path}'], cwd=ROOT))
            spec = util.spec_from_file_location(name, file)
            module = util.module_from_spec(spec)
            sys.modules[name] = module
            spec.loader.exec_module(module)
            print(f'{name}: {revision[:7]} → {module.__file__}', flush=True)
        if args.run_demo:
            from resolveqa.demo.__main__ import main as demo_main
            status = demo_main([])
            if status:
                return status
        import pytest
        target = ROOT / ('tests' if args.full_suite else 'tests/e2e/test_demo_executor.py')
        return pytest.main([str(target), '-q', '-o', 'addopts=-p no:cacheprovider'])


if __name__ == '__main__':
    raise SystemExit(main())
