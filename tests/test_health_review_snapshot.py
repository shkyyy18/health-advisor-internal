import json
from datetime import datetime
from pathlib import Path

from scripts.health_review_snapshot import assess_sleep, build_snapshot
from app import db

NOW = datetime.fromisoformat("2026-11-09T21:05:00+08:00")


def record(start="2026-11-08T23:40:00+08:00", end="2026-11-09T06:40:00+08:00", stages=None):
    return {"sleep_date": "2026-11-09", "duration_minutes": 420,
            "raw_json": json.dumps({"start_at": start, "end_at": end,
                                    "stages": stages if stages is not None else [{"stage": "light", "minutes": 420}]})}


def test_all_light_does_not_become_zero_deep_sleep_advice():
    result = assess_sleep(record(), NOW)
    assert result["candidate_main_night"]
    assert not result["stage_analysis_available"]
    assert result["stage_issues"] == ["no_deep_or_rem_mapping_unverified"]
    assert result["sleep_latency"] is None


def test_sleep_stages_with_inconsistent_duration_are_flagged():
    result = assess_sleep(record(stages=[{"stage": "deep", "minutes": 90}, {"stage": "light", "minutes": 100}]), NOW)
    assert "stage_duration_inconsistent" in result["stage_issues"]
    assert not result["stage_analysis_available"]


def test_daytime_and_unfinished_records_do_not_replace_night():
    assert not assess_sleep(record(start="2026-11-09T09:00:00+08:00", end="2026-11-09T16:00:00+08:00"), NOW)["candidate_main_night"]
    assert not assess_sleep(record(start="2026-11-09T23:00:00+08:00", end="2026-11-10T06:00:00+08:00"), NOW)["candidate_main_night"]


def test_real_stage_detail_can_be_used_as_estimates():
    r = assess_sleep(record(stages=[{"stage": "light", "minutes": 260}, {"stage": "deep", "minutes": 80}, {"stage": "rem", "minutes": 80}]), NOW)
    assert r["stage_analysis_available"]


def test_snapshot_is_read_only_and_keeps_missing_sleep_unknown():
    db.init_db()
    path = db.settings.database_path
    before = path.read_bytes()
    data = build_snapshot(path, NOW)
    assert data["sleep"]["windows"]["7"]["mean_asleep_minutes"] is None
    assert data["sleep"]["windows"]["7"]["uncovered_days"] == 7
    assert data["body"]["latest"] is None
    assert before == path.read_bytes()


def test_multiple_weights_in_one_day_are_not_multiple_baseline_days():
    db.init_db()
    with db.connect() as connection:
        for time in ["07:00:00", "07:01:00"]:
            connection.execute("INSERT INTO body_measurements(source, measured_at, weight_kg) VALUES (?, ?, ?)", ("synthetic", f"2026-11-09T{time}+08:00", 74.0))
    data = build_snapshot(db.settings.database_path, NOW)
    assert data["body"]["distinct_measurement_days"] == 1
