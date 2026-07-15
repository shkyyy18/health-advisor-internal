from app import db


def test_connect_initializes_parent_and_schema(tmp_path):
    path = tmp_path / "nested" / "health.db"
    with db.connect(path) as connection:
        connection.execute(
            "INSERT INTO body_measurements (source, measured_at, weight_kg) VALUES (?, ?, ?)",
            ("test", "2026-07-14T08:00:00+08:00", 70.0),
        )
    assert path.exists()
    with db.connect(path) as connection:
        count = connection.execute("SELECT COUNT(*) FROM body_measurements").fetchone()[0]
    assert count == 1


def test_health_snapshot_reads_all_sections_in_one_database(tmp_path):
    path = tmp_path / "health.db"
    db.init_db(path)
    with db.connect(path) as connection:
        connection.execute(
            "INSERT INTO daily_metrics (metric_date, source, steps) VALUES (?, ?, ?)",
            ("2026-07-14", "test", 8000),
        )
    original = db.settings
    db.settings = type(original)(**{**original.__dict__, "database_path": path})
    try:
        snapshot = db.load_health_snapshot()
    finally:
        db.settings = original
    assert snapshot["daily_metrics"][0]["steps"] == 8000
    assert snapshot["profile"] == {}
    assert snapshot["strava_connected"] is False
