"""QR login tests use synthetic credentials and never contact Xiaomi."""
import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).absolute().parents[1]


@pytest.fixture
def login_script(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location(
        'synthetic_mijia_login', ROOT / 'scripts' / 'mijia_health_sync.py'
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, 'AUTH_DIR', tmp_path / 'auth')
    monkeypatch.setattr(module, 'AUTH_PATH', tmp_path / 'auth' / 'auth.json')
    monkeypatch.setattr(module, 'QR_PATH', tmp_path / 'auth' / 'login_qr.png')
    monkeypatch.setattr(module.socket, 'setdefaulttimeout', lambda value: None)
    return module


def test_reset_backs_up_only_login_and_preserves_data(login_script, tmp_path):
    m = login_script
    m.AUTH_DIR.mkdir()
    m.AUTH_PATH.write_text('{"synthetic": true}', encoding='utf-8')
    db = tmp_path / 'health.db'
    db.write_bytes(b'unchanged synthetic database')
    env = tmp_path / '.env'
    env.write_text('SYNTHETIC=unchanged', encoding='utf-8')
    backup = m.reset_login()
    assert backup.parent == m.AUTH_DIR
    assert backup.read_text(encoding='utf-8') == '{"synthetic": true}'
    assert not m.AUTH_PATH.exists()
    assert db.read_bytes() == b'unchanged synthetic database'
    assert env.read_text(encoding='utf-8') == 'SYNTHETIC=unchanged'
    assert m.reset_login() is None


def test_qr_is_opened_before_waiting_for_scan(login_script, monkeypatch):
    m = login_script
    events = []

    class API:
        def __init__(self, path):
            assert path == str(m.AUTH_PATH)

        def _get_qr_login_data(self):
            return {'loginUrl': 'https://example.invalid/synthetic-qr'}

        def _complete_qr_login(self, data):
            events.append('wait-for-scan')
            m.AUTH_PATH.write_text(json.dumps({
                'userId': 'synthetic-user', 'passToken': 'synthetic-token'
            }), encoding='utf-8')

    def save(path):
        Path(path).write_bytes(b'synthetic image')
        events.append('save')

    def show(path):
        assert path.exists()
        events.append('open')

    monkeypatch.setitem(sys.modules, 'mijiaAPI', SimpleNamespace(mijiaAPI=API))
    monkeypatch.setitem(sys.modules, 'qrcode', SimpleNamespace(make=lambda url: SimpleNamespace(save=save)))
    monkeypatch.setattr(m, 'show_qr', show)
    m.login()
    assert events == ['save', 'open', 'wait-for-scan']
    assert list(m.AUTH_DIR.iterdir()) == [m.QR_PATH, m.AUTH_PATH] or set(m.AUTH_DIR.iterdir()) == {m.QR_PATH, m.AUTH_PATH}


def test_image_viewer_failure_prints_fallback_path(login_script, monkeypatch, capsys):
    def fail(path):
        raise OSError('synthetic viewer failure')
    monkeypatch.setattr(login_script.os, 'startfile', fail, raising=False)
    login_script.show_qr(login_script.QR_PATH)
    output = capsys.readouterr().out
    assert str(login_script.QR_PATH) in output
    assert 'manually' in output


def test_reset_cli_rejects_sync_before_touching_credentials(login_script, monkeypatch):
    monkeypatch.setattr(sys, 'argv', ['mijia_health_sync.py', 'sync', '--reset-login'])
    monkeypatch.setattr(login_script, 'reset_login', lambda: pytest.fail('reset must not run'))
    with pytest.raises(SystemExit) as error:
        login_script.main()
    assert error.value.code == 2
