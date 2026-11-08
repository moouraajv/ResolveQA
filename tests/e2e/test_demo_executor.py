"""Exercise the command against public stages, or its honest dependency diagnostic."""
import ast
import shutil
import urllib.request
import hashlib
import json
from pathlib import Path

import pytest

from resolveqa.contracts import ReportInput
from resolveqa.intake import Intake
from resolveqa.demo import COUPON_REPORT, VAGUE_REPORT, run_demo
from resolveqa.demo.__main__ import main
from resolveqa.demo.llm import create_demo_llm


@pytest.mark.parametrize('scenario,report,expected', [
    ('coupon', COUPON_REPORT, 'verified'),
    ('vague', VAGUE_REPORT, 'needs_info'),
])
def test_public_pipeline(scenario, report, expected, monkeypatch, tmp_path):
    def forbidden(*args, **kwargs):
        pytest.fail("default mock demo attempted network access")
    monkeypatch.setenv("FEATHERLESS_API_KEY", "synthetic-demo-value")
    monkeypatch.setattr(urllib.request.OpenerDirector, "open", forbidden)
    source = Path(__file__).resolve().parents[2]
    shutil.copytree(source / 'demo-target', tmp_path / 'demo-target')
    shutil.copytree(source / 'config', tmp_path / 'config')
    result = run_demo(scenario, root=tmp_path)
    assert result.run_dir.is_relative_to(tmp_path)
    assert result.case.report_text == report
    assert result.case.state.value == expected
    assert result.evidence_ids
    events = result.events
    assert [e.seq for e in events] == list(range(len(events)))
    states = [e.to_state.value for e in events if e.to_state]
    assert states[-1] == expected
    assert result.message
    assert [e.ts for e in events] == sorted(e.ts for e in events)
    if scenario == 'coupon':
        assert states == ['triaging', 'triaged', 'reproducing', 'reproduced',
                          'fixing', 'fixed', 'verifying', 'verified']
        assert result.verdict.before.exit_code == 1
        assert result.verdict.after.exit_code == result.verdict.suite.exit_code == 0
        assert result.verdict.base_revision != result.verdict.fix_revision
        assert 'total agora R$ 180,00' in result.message.text
        assert result.receipt_path.is_file()
        receipt = result.receipt_path.read_text()
        assert 'Antes: R$ 200,00. Agora: R$ 180,00.' in receipt
        assert result.verification_code in receipt
        for internal in ('checkout.py', 'calculate_total', 'AssertionError', 'pytest'):
            assert internal not in receipt
            assert internal not in result.tracking_path.read_text()
        package = Path(result.delivery.url_or_path)
        assert (package / 'MANIFEST.json').is_file()
        assert 'AssertionError' in (package / 'before.log').read_text()
        assert 'passed' in (package / 'after.log').read_text()
        assert result.message.sent_after_event_seq > next(
            e.seq for e in events if e.to_state and e.to_state.value == 'verified')
    else:
        assert states == ['triaging', 'needs_info']
        assert result.delivery is None and result.verdict is None
        assert '?' in result.message.text
        assert 'valor' in result.message.text
        assert result.message.text.endswith('?')
        assert not result.message.text.endswith('?.')
        assert not list(result.run_dir.glob('evidence/*.diff'))
        assert result.receipt_path is None
        assert not (result.run_dir / 'comprovante.txt').exists()
    assert result.tracking_path.is_file()
    html = result.tracking_path.read_text()
    assert 'demonstração com dados simulados' in html
    for event in events:
        if event.to_state and event.to_state.value in {'triaging', 'reproducing', 'fixing', 'verifying', 'verified', 'needs_info'}:
            assert f'datetime="{event.ts}"' in html
    from resolveqa.security import scan_paths_for_secrets
    assert not scan_paths_for_secrets([result.run_dir])
    descriptors = json.loads((result.run_dir / 'evidence-manifest.json').read_text())
    for item in descriptors:
        path = result.run_dir / item['path']
        assert path.is_file()
        assert hashlib.sha256(path.read_bytes()).hexdigest() == item['sha256']
    manifest = json.loads((result.run_dir / 'demo-result.json').read_text())
    assert manifest['mode'] == 'mock'
    assert manifest['evidence_ids'] == list(result.evidence_ids)


def test_real_mode_requires_key_without_printing_it(monkeypatch, capsys, tmp_path):
    monkeypatch.setenv('HOME', str(tmp_path))
    monkeypatch.setenv('FEATHERLESS_API_KEY', 'synthetic-environment-value')
    assert main(['--real-llm']) == 2
    assert 'FEATHERLESS_API_KEY' in capsys.readouterr().err


def test_missing_components_are_explicit(monkeypatch, capsys):
    import resolveqa.demo.runner as runner
    original = runner.import_module
    def missing(name):
        if name == 'resolveqa.triage.engine':
            raise ModuleNotFoundError(name=name)
        return original(name)
    monkeypatch.setattr(runner, 'import_module', missing)
    assert main(['--scenario', 'coupon']) == 2
    output = capsys.readouterr()
    assert 'modo mock' in output.out
    assert 'PR #49' in output.err
    assert 'resolveqa.triage.engine' in output.err


def test_real_transport_omits_provider_error(monkeypatch, tmp_path):
    from resolveqa.llm import LLMAdapter, LLMProviderError, build_delimited_messages
    from urllib.error import URLError
    monkeypatch.setenv('HOME', str(tmp_path))
    path = tmp_path / '.config/resolveqa/featherless.env'
    path.parent.mkdir(parents=True)
    path.write_text('FEATHERLESS_API_KEY=synthetic-demo-value\n')
    path.chmod(0o600)
    llm = create_demo_llm(real=True)
    assert isinstance(llm, LLMAdapter) and llm.use_real
    assert llm.transport is None and not hasattr(llm, '_credential')
    def unavailable(*args, **kwargs):
        raise URLError('synthetic-demo-value')
    llm.transport = unavailable
    with pytest.raises(LLMProviderError) as error:
        llm.complete('triage', build_delimited_messages('Triage', {'report_text': COUPON_REPORT}),
                     case=Intake().create(ReportInput(
                         'client-demo', 'demo-target', 'simulated_chat', COUPON_REPORT)))
    assert 'synthetic-demo-value' not in str(error.value)


def test_demo_has_no_custom_transport_or_pending_loader():
    root = Path(__file__).resolve().parents[2]
    package = root / 'src/resolveqa/demo'
    assert not (package / 'real_llm.py').exists()
    assert not (package / 'validate_pending.py').exists()
    for path in package.glob('*.py'):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                assert node.func.id != 'exec'
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                imports = [node.module or ''] if isinstance(node, ast.ImportFrom) else [n.name for n in node.names]
                assert not any('validate_pending' in name or name.startswith('urllib') for name in imports)
