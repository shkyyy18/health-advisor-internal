from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app import db, main
from app.config import _int_from_env
from app.xiaomi_sync import XiaomiSyncError, sync_mi_fitness


class Record(SimpleNamespace):
    def model_dump(self, mode="python"):
        def convert(value):
            if isinstance(value, datetime):
                return value.isoformat()
            if isinstance(value, list):
                return [convert(item) for item in value]
            if isinstance(value, dict):
                return {key: convert(item) for key, item in value.items()}
            if hasattr(value, "__dict__"):
                return {key: convert(item) for key, item in vars(value).items()}
            return value

        return convert(vars(self))


class FakeAdapter:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.closed = False

    async def connect(self):
        return True

    async def close(self):
        self.closed = True

    async def iter_daily_activity(self, start, end):
        yield Record(date="2026-07-14", steps=8234, active_kcal=421, distance_m=6100, active_minutes=64)

    async def iter_sleep_sessions(self, start, end):
        yield Record(
            end_at=datetime(2026, 7, 14, 7, 0, tzinfo=timezone.utc),
            start_at=datetime(2026, 7, 13, 23, 0, tzinfo=timezone.utc),
            duration_minutes=480,
            time_asleep_minutes=450,
            time_awake_minutes=30,
            stages=[
                {"stage": "deep", "minutes": 90},
                {"stage": "light", "minutes": 250},
                {"stage": "rem", "minutes": 110},
                {"stage": "awake", "minutes": 30},
            ],
        )

    async def iter_body_measurements(self, start, end):
        yield Record(
            timestamp=datetime(2026, 7, 14, 7, 5, tzinfo=timezone.utc),
            weight_kg=73.2,
            body_fat_pct=26.1,
            muscle_mass_kg=51.0,
            water_pct=53.2,
            visceral_fat_score=9,
            basal_metabolism_kcal=1620,
        )

    async def iter_heart_rate(self, start, end):
        for bpm in (50, 60, 70):
            yield Record(timestamp=datetime(2026, 7, 14, 12, bpm % 60, tzinfo=timezone.utc), bpm=bpm)

    async def iter_spo2(self, start, end):
        for value in (96, 98):
            yield Record(timestamp=datetime(2026, 7, 14, 13, value % 60, tzinfo=timezone.utc), spo2_pct=value)

    async def iter_stress(self, start, end):
        for value in (20, 40):
            yield Record(timestamp=datetime(2026, 7, 14, 14, value, tzinfo=timezone.utc), stress_score=value)


def test_sync_mi_fitness_upserts_all_supported_health_data(tmp_path):
    auth = tmp_path / "auth.json"
    auth.write_text(json.dumps({"userId": "user", "passToken": "token"}), encoding="utf-8")

    result = asyncio.run(
        sync_mi_fitness(days=1, credentials_path=auth, adapter_factory=FakeAdapter)
    )

    assert result["body"] == 1
    assert result["sleep"] == 1
    assert result["daily_metrics"] == 1
    with db.connect() as connection:
        body = connection.execute("SELECT * FROM body_measurements").fetchone()
        sleep = connection.execute("SELECT * FROM sleep_summaries").fetchone()
        metrics = connection.execute("SELECT * FROM daily_metrics").fetchone()
    assert body["weight_kg"] == 73.2
    assert sleep["duration_minutes"] == 450
    assert sleep["deep_minutes"] == 90
    assert metrics["steps"] == 8234
    assert metrics["heart_rate_avg"] == 60
    assert metrics["heart_rate_min"] == 50
    assert metrics["heart_rate_max"] == 70
    assert metrics["spo2_avg"] == 97
    assert metrics["stress_avg"] == 30


def test_xiaomi_endpoint_returns_actionable_configuration_error(monkeypatch):
    async def fail():
        raise XiaomiSyncError("请先扫码登录")

    monkeypatch.setattr(main, "sync_mi_fitness", fail)
    response = TestClient(main.app).post("/api/sync/xiaomi")
    assert response.status_code == 400
    assert response.json()["detail"] == "请先扫码登录"


def test_dashboard_uses_public_xiaomi_sync_endpoint():
    response = TestClient(main.app).get("/")
    assert response.status_code == 200
    assert "/api/sync/xiaomi" in response.text
    assert "syncLegacy" not in response.text
    assert response.headers["cache-control"] == "no-store, no-cache, must-revalidate, max-age=0"
    assert response.headers["pragma"] == "no-cache"
    assert response.headers["expires"] == "0"


def test_mobile_dashboard_disables_cache_headers():
    response = TestClient(main.app).get("/mobile")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store, no-cache, must-revalidate, max-age=0"
    assert response.headers["pragma"] == "no-cache"
    assert response.headers["expires"] == "0"


def test_invalid_sync_days_falls_back_to_default(monkeypatch):
    monkeypatch.setenv("MI_FITNESS_SYNC_DAYS", "not-a-number")
    assert _int_from_env("MI_FITNESS_SYNC_DAYS", 14, 1, 90) == 14


def test_sync_days_is_clamped(monkeypatch):
    monkeypatch.setenv("MI_FITNESS_SYNC_DAYS", "999")
    assert _int_from_env("MI_FITNESS_SYNC_DAYS", 14, 1, 90) == 90
