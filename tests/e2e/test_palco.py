"""Stage output and saved real execution replay remain explicit and offline."""
import hashlib
import json
import shutil
import socket
import urllib.request

import pytest

from resolveqa.demo import palco


def _no_network(*args, **kwargs):
    pytest.fail('stage mock/replay must not contact a provider')


def test_stage_mock_runs_both_scenarios_and_records_replay(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(urllib.request.OpenerDirector, 'open', _no_network)
    monkeypatch.setattr(socket, 'create_connection', _no_network)
    destination = tmp_path / 'recording'
    try:
        palco.load_components()
    except palco.MissingComponents:
        pending_expected = True
    else:
        pending_expected = bool(palco._pending_sources())
    assert palco.main(['--record-replay', str(destination)]) == 0
    out = capsys.readouterr().out
    assert out.startswith('modo mock\n')
    assert ('PRs pendentes' if pending_expected else 'APIs públicas disponíveis') in out
    assert 'Comprei R$ 200,00' in out
    assert 'O checkout está estranho' in out
    assert 'RED: observado R$ 200,00; esperado R$ 180,00' in out
    assert 'PATCH: 1 arquivo' in out
    assert 'GREEN: reprodução=0; suíte=0' in out
    assert 'VEREDITO: verified' in out
    assert 'VEREDITO: needs_info' in out
    assert 'Pergunta: Qual foi o valor da compra' in out
    assert 'Comprovante:' in out and 'Página:' in out
    assert 'PR não publicado' in out
    assert len(out.splitlines()) <= 24
    manifest = json.loads((destination / 'index.json').read_text())
    assert manifest['mode'] == 'mock'
    assert set(manifest['scenarios']) == {'coupon', 'vague'}
    assert any(name.endswith('events.jsonl') for name in manifest['files'])
    assert any(name.endswith('comprovante.txt') for name in manifest['files'])


def test_bundled_replay_is_explicit_read_only_and_never_runs_pipeline(monkeypatch, capsys):
    monkeypatch.setattr(palco, 'run_demo', _no_network)
    monkeypatch.setattr(palco, 'load_pending_components', _no_network)
    monkeypatch.setattr(urllib.request.OpenerDirector, 'open', _no_network)
    monkeypatch.setattr(socket, 'create_connection', _no_network)
    index = json.loads((palco.DEFAULT_REPLAY / 'index.json').read_text())
    before = {name: hashlib.sha256((palco.DEFAULT_REPLAY / name).read_bytes()).hexdigest()
              for name in index['files']}
    assert palco.main(['--replay']) == 0
    out = capsys.readouterr().out
    assert out.startswith('modo mock\n')
    assert f"REPLAY de uma execução gravada em {index['recorded_at']}" in out
    assert 'NÃO É AO VIVO' in out
    assert 'VEREDITO: verified' in out and 'VEREDITO: needs_info' in out
    after = {name: hashlib.sha256((palco.DEFAULT_REPLAY / name).read_bytes()).hexdigest()
             for name in index['files']}
    assert before == after == index['files']


def test_replay_page_flag_opens_only_a_local_page_with_replay_notice(monkeypatch, capsys):
    opened = []
    monkeypatch.setattr(palco.webbrowser, 'open', lambda uri: opened.append(uri) or True)
    assert palco.main(['--replay', '--open-page']) == 0
    assert len(opened) == 1 and opened[0].startswith('file://')
    index = json.loads((palco.DEFAULT_REPLAY / 'index.json').read_text())
    page = palco.DEFAULT_REPLAY / index['scenarios']['coupon'] / 'acompanhamento-replay.html'
    assert page.as_uri() == opened[0]
    assert 'REPLAY de uma execução gravada em' in page.read_text()
    assert 'NÃO É AO VIVO' in page.read_text()


def test_replay_refuses_changed_events(monkeypatch, capsys, tmp_path):
    destination = tmp_path / 'recording'
    shutil.copytree(palco.DEFAULT_REPLAY, destination)
    index = json.loads((destination / 'index.json').read_text())
    events = destination / index['scenarios']['coupon'] / 'events.jsonl'
    events.write_text(events.read_text() + '{}\n')
    monkeypatch.setattr(palco, 'run_demo', _no_network)
    assert palco.main(['--replay', str(destination)]) == 2
    out = capsys.readouterr()
    assert 'integridade' in out.err
    assert 'VEREDITO: verified' not in out.out


def test_replay_never_fetches_missing_modules(monkeypatch, capsys):
    import subprocess
    monkeypatch.setattr(subprocess, 'check_output', _no_network)
    assert palco.main(['--replay']) == 0
    assert 'REPLAY' in capsys.readouterr().out


@pytest.mark.parametrize('field,value', [('recorded_at', '2000-01-01T00:00:00Z'), ('mode', 'real')])
def test_replay_metadata_must_match_recorded_case(capsys, tmp_path, field, value):
    destination = tmp_path / 'recording'
    shutil.copytree(palco.DEFAULT_REPLAY, destination)
    path = destination / 'index.json'
    index = json.loads(path.read_text())
    index[field] = value
    path.write_text(json.dumps(index))
    assert palco.main(['--replay', str(destination)]) == 2
    assert 'divergem' in capsys.readouterr().err


def test_recording_is_not_overwritten_or_rerun(monkeypatch, capsys):
    monkeypatch.setattr(palco, 'run_demo', _no_network)
    assert palco.main(['--record-replay', str(palco.DEFAULT_REPLAY)]) == 2
    assert 'já existe' in capsys.readouterr().err


def test_real_stage_requires_explicit_credential_without_network(monkeypatch, capsys):
    monkeypatch.delenv('FEATHERLESS_API_KEY', raising=False)
    monkeypatch.setattr(urllib.request.OpenerDirector, 'open', _no_network)
    assert palco.main(['--real-llm']) == 2
    result = capsys.readouterr()
    assert result.out.startswith('modo real (Featherless)\n')
    assert 'FEATHERLESS_API_KEY' in result.err
