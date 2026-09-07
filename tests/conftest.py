import tempfile
from dataclasses import replace
from pathlib import Path

import pytest

# Isolate import-time settings too: the DB fixture alone does not prevent .env
# and persisted LAN credentials from being read during test collection.
_test_config_dir = tempfile.TemporaryDirectory(prefix="health-advisor-tests-")
_test_env = pytest.MonkeyPatch()
_test_env.setenv("HEALTH_ENV_FILE", str(Path(_test_config_dir.name) / ".env"))
for _key in (
    "STRAVA_CLIENT_ID",
    "STRAVA_CLIENT_SECRET",
    "STRAVA_WEBHOOK_CALLBACK_URL",
    "STRAVA_WEBHOOK_VERIFY_TOKEN",
    "MOBILE_ACCESS_PASSWORD",
    "MEAL_LLM_API_KEY",
    "MEAL_LLM_BASE_URL",
    "MEAL_LLM_MODEL",
    "DATABASE_PATH",
    "MI_FITNESS_AUTH_PATH",
):
    _test_env.setenv(_key, "")
_test_env.setenv("HEALTH_LAN_TOKEN", "synthetic-test-lan-token")
_test_env.setenv("APP_SECRET", "synthetic-test-app-secret")
_test_env.setenv("STRAVA_REDIRECT_URI", "http://127.0.0.1:8000/oauth/strava/callback")

from app import db  # noqa: E402


def pytest_unconfigure(config):
    _test_env.undo()
    _test_config_dir.cleanup()


@pytest.fixture(autouse=True)
def isolated_database(tmp_path, monkeypatch):
    """Never let tests read or write the user's real health database."""
    monkeypatch.setattr(
        db,
        "settings",
        replace(db.settings, database_path=tmp_path / "health.db"),
    )
    db._INITIALIZED_DATABASES.clear()
    yield
    db._INITIALIZED_DATABASES.clear()
