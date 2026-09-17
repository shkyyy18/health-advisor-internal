from pathlib import Path

from app import config
from scripts import start_health_services


def test_project_root_preserves_the_public_entry_path():
    expected = Path(config.__file__).absolute().parents[1]
    assert config.PROJECT_ROOT == expected
    assert config.settings.database_path == expected / "data" / "health.db"
    assert config.settings.mi_fitness_auth_path == expected / "data" / ".mijia" / "auth.json"


def test_startup_env_reader_tolerates_missing_dotenv(tmp_path, monkeypatch):
    monkeypatch.setattr(start_health_services, "PROJECT", tmp_path)
    assert start_health_services.env_values() == {}


def test_ngrok_is_disabled_by_default():
    assert start_health_services.ngrok_enabled({}) is False
    assert start_health_services.ngrok_enabled({"STRAVA_WEBHOOK_CALLBACK_URL": "https://example.invalid"}) is False


def test_ngrok_requires_explicit_true_value():
    assert start_health_services.ngrok_enabled({"HEALTH_ENABLE_NGROK": "true"}) is True
    assert start_health_services.ngrok_enabled({"HEALTH_ENABLE_NGROK": " ON "}) is True
    assert start_health_services.ngrok_enabled({"HEALTH_ENABLE_NGROK": "false"}) is False


def test_callback_url_alone_never_launches_ngrok(monkeypatch):
    launched = []
    monkeypatch.setattr(start_health_services, "port_open", lambda port: port == 8000)
    monkeypatch.setattr(
        start_health_services,
        "env_values",
        lambda: {"STRAVA_WEBHOOK_CALLBACK_URL": "https://example.invalid/webhook"},
    )
    monkeypatch.setattr(start_health_services, "launch", lambda *args: launched.append(args))
    monkeypatch.setattr(start_health_services, "log", lambda message: None)

    start_health_services.main()

    assert launched == []
