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
