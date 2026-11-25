"""Read-only, dated health evidence for the advisor; never generates a diagnosis."""
from __future__ import annotations

import argparse
import json
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import mean

LOCAL = timezone(timedelta(hours=8))


def moment(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.astimezone(LOCAL) if parsed.tzinfo else None
    except (ValueError, TypeError):
        return None


def assess_sleep(row: dict, as_of: datetime) -> dict:
    try:
        raw = json.loads(row.get("raw_json") or "{}")
        if not isinstance(raw, dict):
            raw = {}
    except (ValueError, TypeError):
        raw = {}
    start, end = moment(raw.get("start_at")), moment(raw.get("end_at"))
    minutes = row.get("duration_minutes")
    issues = []
    if not start or not end or end <= start:
        issues.append("missing_or_invalid_interval")
    elif end > as_of:
        issues.append("not_finished_by_cutoff")
    elif 8 <= start.hour < 18:
        issues.append("daytime_record_not_main_night")
    if not isinstance(minutes, (int, float)) or not 0 < minutes <= 960:
        issues.append("invalid_duration")
    elif minutes < 180:
        # A short record may be true short sleep or incomplete coverage: do not
        # silently substitute it for a full night, or call missing sleep zero.
        issues.append("short_record_completeness_unknown")
    if start and end and isinstance(minutes, (int, float)):
        if minutes > (end - start).total_seconds() / 60 + 5:
            issues.append("sleep_longer_than_recorded_interval")
    stages = raw.get("stages") or []
    totals = {key: 0 for key in ["deep", "light", "rem", "awake"]}
    stage_issues = []
    if not isinstance(stages, list) or not stages:
        stages = []
        stage_issues.append("stage_detail_missing")
    for item in stages:
        if not isinstance(item, dict):
            stage_issues.append("invalid_stage_segment")
            continue
        name, duration = item.get("stage"), item.get("minutes")
        if name not in totals or not isinstance(duration, (int, float)) or duration < 0:
            stage_issues.append("unknown_stage_segment")
        else:
            totals[name] += duration
    if stages and totals["light"] and not any(totals[k] for k in ["deep", "rem"]):
        # Upstream defaults unrecognized stage codes to light. The normalized
        # payload cannot recover those codes, so even all-light records with
        # awake segments cannot establish zero deep/REM sleep.
        stage_issues.append("no_deep_or_rem_mapping_unverified")
    if stages and isinstance(minutes, (int, float)):
        asleep_sum = sum(totals[k] for k in ["deep", "light", "rem"])
        if abs(asleep_sum - minutes) > max(5, minutes * .05):
            stage_issues.append("stage_duration_inconsistent")
    return {
        "date": row.get("sleep_date"), "start_at": start.isoformat() if start else None,
        "end_at": end.isoformat() if end else None, "reported_asleep_minutes": minutes,
        "candidate_main_night": not issues, "coverage_issues": issues,
        "observed_stage_totals_minutes": totals if stages else None,
        "stage_analysis_available": bool(stages) and not issues and not stage_issues,
        "stage_issues": sorted(set(stage_issues)),
        "sleep_hr": row.get("average_hr"), "sleep_spo2": row.get("average_spo2"),
        "time_in_bed": None, "sleep_latency": None,
        "note": "Wearable interval is not a verified lights-out time; missing stages are not zero.",
    }


def build_snapshot(database: Path, as_of: datetime) -> dict:
    if as_of.tzinfo is None:
        raise ValueError("as_of must include a timezone")
    as_of = as_of.astimezone(LOCAL)
    today = as_of.date()
    uri = database.resolve().as_uri() + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as connection:
        connection.row_factory = sqlite3.Row
        sleeps = [assess_sleep(dict(x), as_of) for x in connection.execute(
            "SELECT * FROM sleep_summaries ORDER BY sleep_date")]
        body = [dict(x) for x in connection.execute(
            "SELECT measured_at,weight_kg,body_fat_pct FROM body_measurements ORDER BY measured_at")]
        activities = [dict(x) for x in connection.execute(
            "SELECT start_date,sport_type,moving_time,distance FROM activities ORDER BY start_date")]
        sync = [dict(x) for x in connection.execute("SELECT source,synced_at FROM sync_state")]
        food_count = connection.execute("SELECT COUNT(*) FROM nutrition_logs").fetchone()[0]
    windows = {}
    for days in [7, 28, 30]:
        start = today - timedelta(days=days - 1)
        samples = [r for r in sleeps if r["candidate_main_night"] and r["end_at"]
                   and start <= moment(r["end_at"]).date() <= today]
        windows[str(days)] = {
            "calendar_days": days, "candidate_nights": len(samples),
            "uncovered_days": days - len({r["date"] for r in samples}),
            "mean_asleep_minutes": round(mean(r["reported_asleep_minutes"] for r in samples), 1) if samples else None,
            "nights_at_least_7h": sum(r["reported_asleep_minutes"] >= 420 for r in samples),
            "nights_with_usable_stages": sum(r["stage_analysis_available"] for r in samples),
        }
    body = [r for r in body if moment(r["measured_at"]) and moment(r["measured_at"]) <= as_of]
    # Do not treat repeat weigh-ins as independent baseline days.
    by_day = {moment(r["measured_at"]).date().isoformat(): r for r in body}
    latest = body[-1] if body else None
    week_start = today - timedelta(days=today.weekday())
    current_week = [r for r in activities if moment(r["start_date"]) and
                    week_start <= moment(r["start_date"]).date() <= today and moment(r["start_date"]) <= as_of]
    completed_sleeps = [r for r in sleeps if r["end_at"] and moment(r["end_at"]) <= as_of]
    return {
        "as_of": as_of.isoformat(), "timezone": "Asia/Shanghai", "sync_state": sync,
        "sleep": {"latest_completed_record": completed_sleeps[-1] if completed_sleeps else None,
                  "windows": windows,
                  "recent_records": [r for r in sleeps if r["date"] and (today - timedelta(days=29)).isoformat() <= r["date"] <= today.isoformat()],
                  "limitations": ["Stages are device estimates, not a clinical sleep study.", "No causal conclusion from one night.", "No verified lights-out, sleep latency or sleep efficiency."]},
        "body": {"latest": latest, "distinct_measurement_days": len(by_day),
                 "latest_age_days": (today - moment(latest["measured_at"]).date()).days if latest else None,
                 "bmi_using_172cm": round(latest["weight_kg"] / 1.72 ** 2, 2) if latest else None,
                 "historical_start_is_provisional": True, "history": list(by_day.values())},
        "activity_this_week": {"start": week_start.isoformat(), "through": today.isoformat(),
                               "records": current_week, "moving_minutes": round(sum(r["moving_time"] or 0 for r in current_week) / 60, 2)},
        "food_records": food_count,
        "subjective_pain_fatigue_hunger": "unknown unless supplied by the user",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, default=Path(__file__).resolve().parents[1] / "data/health.db")
    parser.add_argument("--as-of", help="ISO timestamp including timezone")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    cutoff = datetime.fromisoformat(args.as_of) if args.as_of else datetime.now(LOCAL)
    result = build_snapshot(args.database, cutoff)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"snapshot_written": str(args.output), "as_of": result["as_of"]}, ensure_ascii=True))


if __name__ == "__main__":
    main()
