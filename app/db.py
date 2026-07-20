from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from app.config import settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS oauth_tokens (
    provider TEXT PRIMARY KEY,
    athlete_id INTEGER,
    access_token TEXT NOT NULL,
    refresh_token TEXT NOT NULL,
    expires_at INTEGER NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS activities (
    id INTEGER PRIMARY KEY,
    source TEXT NOT NULL,
    name TEXT NOT NULL,
    sport_type TEXT,
    start_date TEXT NOT NULL,
    elapsed_time INTEGER,
    moving_time INTEGER,
    distance REAL,
    total_elevation_gain REAL,
    average_heartrate REAL,
    max_heartrate REAL,
    average_cadence REAL,
    average_watts REAL,
    kilojoules REAL,
    raw_json TEXT NOT NULL,
    synced_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sleep_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    start_time TEXT NOT NULL,
    end_time TEXT NOT NULL,
    deep_minutes INTEGER,
    light_minutes INTEGER,
    rem_minutes INTEGER,
    awake_minutes INTEGER,
    average_hr REAL,
    average_spo2 REAL,
    raw_json TEXT,
    UNIQUE(source, start_time, end_time)
);

CREATE TABLE IF NOT EXISTS body_measurements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    measured_at TEXT NOT NULL,
    weight_kg REAL NOT NULL,
    body_fat_pct REAL,
    muscle_kg REAL,
    water_pct REAL,
    visceral_fat REAL,
    basal_metabolism REAL,
    raw_json TEXT,
    UNIQUE(source, measured_at)
);

CREATE TABLE IF NOT EXISTS sleep_summaries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sleep_date TEXT NOT NULL,
    source TEXT NOT NULL,
    duration_minutes INTEGER NOT NULL,
    deep_minutes INTEGER,
    light_minutes INTEGER,
    rem_minutes INTEGER,
    awake_minutes INTEGER,
    average_hr REAL,
    average_spo2 REAL,
    raw_json TEXT,
    UNIQUE(sleep_date, source)
);

CREATE TABLE IF NOT EXISTS daily_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    metric_date TEXT NOT NULL,
    source TEXT NOT NULL,
    steps INTEGER,
    calories REAL,
    distance_m REAL,
    active_minutes INTEGER,
    heart_rate_avg REAL,
    heart_rate_min REAL,
    heart_rate_max REAL,
    spo2_avg REAL,
    stress_avg REAL,
    raw_json TEXT,
    UNIQUE(metric_date, source)
);

CREATE TABLE IF NOT EXISTS user_profile (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    sex TEXT,
    age INTEGER,
    height_cm REAL,
    training_goal TEXT,
    food_preferences TEXT,
    target_body_fat_low REAL,
    target_body_fat_high REAL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS nutrition_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    eaten_at TEXT NOT NULL,
    meal_type TEXT,
    total_kcal REAL,
    protein_g REAL,
    carb_g REAL,
    fat_g REAL,
    sodium_mg REAL,
    source TEXT NOT NULL,
    raw_json TEXT,
    UNIQUE(eaten_at, source)
);

CREATE TABLE IF NOT EXISTS sync_state (
    source TEXT PRIMARY KEY,
    synced_at TEXT NOT NULL
);
"""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


_SCHEMA_LOCK = threading.Lock()
_INITIALIZED_DATABASES: set[Path] = set()


def _database_path(path: Path | None = None) -> Path:
    return (path or settings.database_path).expanduser().absolute()


def init_db(path: Path | None = None) -> None:
    db_path = _database_path(path)
    if db_path in _INITIALIZED_DATABASES and db_path.exists():
        return
    with _SCHEMA_LOCK:
        if db_path in _INITIALIZED_DATABASES and db_path.exists():
            return
        db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(db_path, timeout=30) as connection:
            connection.execute("PRAGMA busy_timeout=30000")
            connection.executescript(SCHEMA)
        _INITIALIZED_DATABASES.add(db_path)


@contextmanager
def connect(path: Path | None = None) -> Iterator[sqlite3.Connection]:
    db_path = _database_path(path)
    # Lifespan normally initializes the database. This fallback also keeps CLI,
    # tests, and direct ASGI calls safe when lifespan is not entered explicitly.
    init_db(db_path)
    connection = sqlite3.connect(db_path, timeout=30)
    connection.execute("PRAGMA busy_timeout=30000")
    connection.row_factory = sqlite3.Row
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def save_token(token: dict[str, Any]) -> None:
    with connect() as db:
        db.execute(
            """
            INSERT INTO oauth_tokens
              (provider, athlete_id, access_token, refresh_token, expires_at, updated_at)
            VALUES ('strava', ?, ?, ?, ?, ?)
            ON CONFLICT(provider) DO UPDATE SET
              athlete_id=excluded.athlete_id,
              access_token=excluded.access_token,
              refresh_token=excluded.refresh_token,
              expires_at=excluded.expires_at,
              updated_at=excluded.updated_at
            """,
            (
                token.get("athlete", {}).get("id"),
                token["access_token"],
                token["refresh_token"],
                token["expires_at"],
                utc_now(),
            ),
        )


def get_token() -> dict[str, Any] | None:
    with connect() as db:
        row = db.execute(
            "SELECT * FROM oauth_tokens WHERE provider='strava'"
        ).fetchone()
    return dict(row) if row else None


def delete_token() -> None:
    with connect() as db:
        db.execute("DELETE FROM oauth_tokens WHERE provider='strava'")


def save_activity(activity: dict[str, Any]) -> None:
    with connect() as db:
        db.execute(
            """
            INSERT INTO activities (
              id, source, name, sport_type, start_date, elapsed_time, moving_time,
              distance, total_elevation_gain, average_heartrate, max_heartrate,
              average_cadence, average_watts, kilojoules, raw_json, synced_at
            ) VALUES (?, 'strava', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
              name=excluded.name, sport_type=excluded.sport_type,
              elapsed_time=excluded.elapsed_time, moving_time=excluded.moving_time,
              distance=excluded.distance,
              total_elevation_gain=excluded.total_elevation_gain,
              average_heartrate=excluded.average_heartrate,
              max_heartrate=excluded.max_heartrate,
              average_cadence=excluded.average_cadence,
              average_watts=excluded.average_watts,
              kilojoules=excluded.kilojoules,
              raw_json=excluded.raw_json, synced_at=excluded.synced_at
            """,
            (
                activity["id"], activity.get("name", "未命名运动"),
                activity.get("sport_type") or activity.get("type"),
                activity["start_date"], activity.get("elapsed_time"),
                activity.get("moving_time"), activity.get("distance"),
                activity.get("total_elevation_gain"),
                activity.get("average_heartrate"), activity.get("max_heartrate"),
                activity.get("average_cadence"), activity.get("average_watts"),
                activity.get("kilojoules"), json.dumps(activity, ensure_ascii=False),
                utc_now(),
            ),
        )


def delete_activity(activity_id: int) -> None:
    with connect() as db:
        db.execute(
            "DELETE FROM activities WHERE source='strava' AND id=?",
            (activity_id,),
        )


def list_activities(limit: int = 30) -> list[dict[str, Any]]:
    with connect() as db:
        rows = db.execute(
            "SELECT * FROM activities ORDER BY start_date DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(row) for row in rows]


def list_sleep(limit: int = 30) -> list[dict[str, Any]]:
    with connect() as db:
        rows = db.execute(
            """
            SELECT sleep_date, source, duration_minutes, deep_minutes, light_minutes,
                   rem_minutes, awake_minutes, average_hr, average_spo2
            FROM sleep_summaries
            ORDER BY sleep_date DESC LIMIT ?
            """,
            (limit,),
        ).fetchall()
        if rows:
            return [dict(row) for row in rows]
        session_rows = db.execute(
            "SELECT * FROM sleep_sessions ORDER BY start_time DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(row) for row in session_rows]


def list_daily_metrics(limit: int = 30) -> list[dict[str, Any]]:
    with connect() as db:
        rows = db.execute(
            "SELECT * FROM daily_metrics ORDER BY metric_date DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(row) for row in rows]


def list_body(limit: int = 30) -> list[dict[str, Any]]:
    with connect() as db:
        rows = db.execute(
            "SELECT * FROM body_measurements ORDER BY measured_at DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(row) for row in rows]


def get_profile() -> dict[str, Any]:
    with connect() as db:
        row = db.execute("SELECT * FROM user_profile WHERE id=1").fetchone()
    return dict(row) if row else {}


def list_nutrition(limit: int = 30) -> list[dict[str, Any]]:
    with connect() as db:
        rows = db.execute(
            "SELECT * FROM nutrition_logs ORDER BY eaten_at DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(row) for row in rows]


def record_sync(source: str) -> None:
    """Stamp the moment a data source finished syncing, for the dashboard snapshot time."""
    with connect() as db:
        db.execute(
            """
            INSERT INTO sync_state (source, synced_at) VALUES (?, ?)
            ON CONFLICT(source) DO UPDATE SET synced_at=excluded.synced_at
            """,
            (source, utc_now()),
        )


def latest_sync_time() -> str | None:
    """Return the most recent sync timestamp across sources, or None if never synced."""
    with connect() as db:
        row = db.execute("SELECT MAX(synced_at) AS latest FROM sync_state").fetchone()
    return row["latest"] if row else None


def save_photo_nutrition(eaten_at: str, meal_type: str, analysis: dict[str, Any], totals: dict[str, float | None]) -> None:
    with connect() as db:
        db.execute(
            """INSERT INTO nutrition_logs
              (eaten_at, meal_type, total_kcal, protein_g, carb_g, fat_g, source, raw_json)
              VALUES (?, ?, ?, ?, ?, ?, 'photo_ai', ?)""",
            (eaten_at, meal_type, totals.get("total_kcal"), totals.get("protein_g"), totals.get("carb_g"), totals.get("fat_g"), json.dumps(analysis, ensure_ascii=False)),
        )


def save_quick_nutrition(
    eaten_at: str,
    meal_type: str,
    description: str,
    *,
    total_kcal: float | None = None,
    protein_g: float | None = None,
    carb_g: float | None = None,
    fat_g: float | None = None,
    confidence: str = "manual",
    notes: str | None = None,
) -> None:
    metadata = {
        "description": description,
        "confidence": confidence,
        "notes": notes,
    }
    with connect() as db:
        db.execute(
            """INSERT INTO nutrition_logs
              (eaten_at, meal_type, total_kcal, protein_g, carb_g, fat_g, source, raw_json)
              VALUES (?, ?, ?, ?, ?, ?, 'quick_manual', ?)
              ON CONFLICT(eaten_at, source) DO UPDATE SET
                meal_type=excluded.meal_type,
                total_kcal=excluded.total_kcal,
                protein_g=excluded.protein_g,
                carb_g=excluded.carb_g,
                fat_g=excluded.fat_g,
                raw_json=excluded.raw_json""",
            (
                eaten_at,
                meal_type,
                total_kcal,
                protein_g,
                carb_g,
                fat_g,
                json.dumps(metadata, ensure_ascii=False),
            ),
        )


def load_health_snapshot(activity_limit: int = 500, other_limit: int = 30) -> dict[str, Any]:
    """Read all dashboard inputs in one consistent transaction."""
    with connect() as db:
        db.execute("BEGIN")
        activities = [
            dict(row)
            for row in db.execute(
                "SELECT * FROM activities ORDER BY start_date DESC LIMIT ?",
                (activity_limit,),
            ).fetchall()
        ]
        sleep_rows = db.execute(
            """
            SELECT sleep_date, source, duration_minutes, deep_minutes, light_minutes,
                   rem_minutes, awake_minutes, average_hr, average_spo2
            FROM sleep_summaries
            ORDER BY sleep_date DESC LIMIT ?
            """,
            (other_limit,),
        ).fetchall()
        if not sleep_rows:
            sleep_rows = db.execute(
                "SELECT * FROM sleep_sessions ORDER BY start_time DESC LIMIT ?",
                (other_limit,),
            ).fetchall()
        body = [
            dict(row)
            for row in db.execute(
                "SELECT * FROM body_measurements ORDER BY measured_at DESC LIMIT ?",
                (other_limit,),
            ).fetchall()
        ]
        daily_metrics = [
            dict(row)
            for row in db.execute(
                "SELECT * FROM daily_metrics ORDER BY metric_date DESC LIMIT ?",
                (other_limit,),
            ).fetchall()
        ]
        nutrition = [
            dict(row)
            for row in db.execute(
                "SELECT * FROM nutrition_logs ORDER BY eaten_at DESC LIMIT ?",
                (max(other_limit, 100),),
            ).fetchall()
        ]
        profile_row = db.execute("SELECT * FROM user_profile WHERE id=1").fetchone()
        token_row = db.execute(
            "SELECT 1 FROM oauth_tokens WHERE provider='strava'"
        ).fetchone()
    return {
        "activities": activities,
        "sleep": [dict(row) for row in sleep_rows],
        "body": body,
        "daily_metrics": daily_metrics,
        "nutrition": nutrition,
        "profile": dict(profile_row) if profile_row else {},
        "strava_connected": token_row is not None,
    }
