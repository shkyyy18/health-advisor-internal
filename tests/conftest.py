from dataclasses import replace

import pytest

from app import db


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
