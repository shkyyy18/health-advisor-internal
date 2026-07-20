from datetime import datetime, timedelta, timezone

from app.analytics import _body_analysis, build_summary


def test_summary_uses_recent_activity():
    now = datetime.now(timezone.utc)
    activities = [{
        "start_date": (now - timedelta(days=1)).isoformat(),
        "moving_time": 3600,
        "distance": 25000,
        "average_heartrate": 135,
    }]
    result = build_summary(activities, [], [])
    assert result["training"]["activity_count"] == 1
    assert result["training"]["minutes"] == 60
    assert result["training"]["distance_km"] == 25.0


def test_low_sleep_reduces_intensity():
    now = datetime.now(timezone.utc)
    sleep = [{
        "start_time": (now - timedelta(hours=6)).isoformat(),
        "end_time": now.isoformat(),
    }]
    result = build_summary([], sleep, [])
    assert any("不建议安排高强度" in text for text in result["suggestions"])
    assert result["readiness"]["status"] == "恢复不足"
    assert result["workout"]["intensity"] == "恢复"


def test_body_fat_produces_transparent_staged_target():
    body = [
        {"measured_at": "2026-07-07T08:00:00+08:00", "weight_kg": 74.15, "body_fat_pct": 27.4},
        {"measured_at": "2026-07-06T08:00:00+08:00", "weight_kg": 73.6, "body_fat_pct": 27.3},
    ]
    profile = {
        "sex": "男", "age": 38, "height_cm": 173,
        "target_body_fat_low": 20, "target_body_fat_high": 24,
    }
    result = build_summary([], [], body, profile=profile)
    analysis = result["body_composition"]
    assert analysis["status"] == "偏高"
    assert analysis["lean_mass_kg"] == 53.8
    assert analysis["target_weight_range_kg"] == "67.3–70.8"
    assert analysis["recommended_loss_kg"] == "约3.3公斤"
    assert "第一阶段" in analysis["detail"]


def test_nutrition_targets_scale_with_weight_and_do_not_claim_logged_intake():
    body = [{"measured_at": "2026-07-07T08:00:00+08:00", "weight_kg": 74, "body_fat_pct": 27}]
    result = build_summary([], [], body, profile={"sex": "男"}, nutrition=[])
    nutrition = result["nutrition"]
    assert nutrition["protein_target"] == "118–148克/天"
    assert "尚无连续饮食记录" in nutrition["data_note"]
    assert any("30–60克" in item for item in nutrition["during_ride"])


def test_no_ftp_means_no_invented_power_zone():
    result = build_summary([], [], [])
    assert any("缺少FTP" in item for item in result["data_gaps"])
    assert all("FTP" not in step and "瓦" not in step for step in result["workout"]["steps"])


def test_body_analysis_compares_calendar_weeks_and_reports_latest_body_fat():
    now = datetime(2026, 7, 11, 4, 0, tzinfo=timezone.utc)
    body = [
        {"measured_at": "2026-07-05T08:00:00+08:00", "weight_kg": 74, "body_fat_pct": 27},
        {"measured_at": "2026-07-10T08:00:00+08:00", "weight_kg": 73, "body_fat_pct": 26},
        {"measured_at": "2026-07-01T08:00:00+08:00", "weight_kg": 75, "body_fat_pct": 28},
        {"measured_at": "2026-07-06T08:00:00+08:00", "weight_kg": 74, "body_fat_pct": 27},
    ]
    analysis = _body_analysis(body, {"sex": "男"}, now)
    assert analysis["latest_body_fat_date"] == "2026-07-10"
    assert analysis["latest_body_fat_pct"] == 26.0
    assert analysis["weight_this_week_avg_kg"] == 73.5
    assert analysis["weight_last_week_avg_kg"] == 74.5
    assert analysis["weight_week_change_kg"] == -1.0
    assert analysis["body_fat_this_week_avg_pct"] == 26.5
    assert analysis["body_fat_last_week_avg_pct"] == 27.5
    assert analysis["body_fat_week_change_pct"] == -1.0
    assert len(analysis["recent_measurements"]) == 4
    assert analysis["recent_measurements"][0]["measured_at_label"] == "2026-07-10 08:00"
    assert analysis["recent_measurements"][0]["measured_at_short_label"] == "07-10 08:00"
    assert analysis["recent_measurements"][0]["body_fat_pct"] == 26.0
    assert analysis["recent_measurements"][0]["weight_kg"] == 73.0
    assert analysis["recent_measurements"][0]["lean_mass_kg"] == 54.0


def test_summary_ignores_invalid_and_future_activities_and_sorts_latest():
    now = datetime.now(timezone.utc)
    activities = [
        {"start_date": "not-a-date", "moving_time": 99999},
        {
            "start_date": (now + timedelta(days=1)).isoformat(),
            "moving_time": 99999,
        },
        {
            "start_date": (now - timedelta(days=5)).isoformat(),
            "moving_time": 1800,
            "distance": 10000,
        },
        {
            "start_date": (now - timedelta(days=1)).isoformat(),
            "moving_time": 3600,
            "distance": 20000,
        },
    ]
    result = build_summary(activities, [], [])
    assert result["training"]["activity_count"] == 2
    assert result["training"]["minutes"] == 90
    assert result["training"]["distance_km"] == 30.0


def test_summary_ignores_invalid_sleep_durations():
    result = build_summary(
        [],
        [
            {"duration_minutes": -60},
            {"start_time": "bad", "end_time": "also-bad"},
        ],
        [],
    )
    assert result["readiness"]["confidence"] == "低"


def test_body_analysis_limits_recent_measurements_to_five_rows():
    now = datetime(2026, 7, 11, 4, 0, tzinfo=timezone.utc)
    body = [
        {"measured_at": f"2026-07-{day:02d}T08:00:00+08:00", "weight_kg": 70 + day / 10, "body_fat_pct": 20 + day / 10}
        for day in range(1, 8)
    ]
    analysis = _body_analysis(body, {"sex": "男"}, now)
    assert len(analysis["recent_measurements"]) == 5
    assert analysis["recent_measurements"][0]["measured_at_label"] == "2026-07-07 08:00"
    assert analysis["recent_measurements"][-1]["measured_at_label"] == "2026-07-03 08:00"


def test_one_hour_sleep_links_recovery_training_and_nutrition():
    now = datetime(2026, 7, 16, 8, 0, tzinfo=timezone.utc)
    sleep = [{
        "start_time": (now - timedelta(hours=2)).isoformat(),
        "end_time": (now - timedelta(hours=1)).isoformat(),
    }]

    body = [
        {"measured_at": "2026-07-16T07:00:00+00:00", "weight_kg": 74},
        {"measured_at": "2026-07-15T07:00:00+00:00", "weight_kg": 72},
    ]
    result = build_summary([], sleep, body, now=now)

    assert result["readiness"]["status"] == "恢复不足"
    assert result["workout"]["intensity"] == "恢复"
    assert "补觉" in result["workout"]["title"] or "休息" in result["workout"]["title"]
    assert result["workout"]["duration"] == "0–30分钟"
    assert "0–200千卡" in result["nutrition"]["adjustment"]
    assert "不因单日体重" in result["nutrition"]["adjustment"]
    coaching_text = str(result["daily_coaching"])
    assert "取消高强度" in coaching_text
    assert "睡眠" in coaching_text and "饮食" in coaching_text


def test_single_day_weight_jump_does_not_trigger_crash_diet():
    now = datetime(2026, 7, 16, 8, 0, tzinfo=timezone.utc)
    body = [
        {"measured_at": "2026-07-16T07:00:00+00:00", "weight_kg": 74, "body_fat_pct": 27},
        {"measured_at": "2026-07-15T07:00:00+00:00", "weight_kg": 72, "body_fat_pct": 26.8},
    ]

    result = build_summary([], [], body, profile={"sex": "男"}, now=now)

    assert result["body_composition"]["single_day_weight_spike"] is True
    assert "不因单日体重" in result["nutrition"]["adjustment"]
    assert "跳餐" in result["nutrition"]["adjustment"]
    assert "未来3天" in result["daily_coaching"]["experiment"]
    assert "盐分" in result["daily_coaching"]["experiment"]


def test_rolling_weight_gain_with_food_logs_changes_only_one_variable():
    now = datetime(2026, 7, 16, 8, 0, tzinfo=timezone.utc)
    body = []
    for offset in range(14):
        weight = 74.0 if offset < 7 else 73.4
        body.append({
            "measured_at": (now - timedelta(days=offset)).isoformat(),
            "weight_kg": weight,
            "body_fat_pct": 27.0,
        })
    nutrition = [
        {
            "eaten_at": (now - timedelta(days=offset)).isoformat(),
            "total_kcal": 2000,
            "protein_g": 120,
        }
        for offset in range(5)
    ]

    result = build_summary([], [], body, profile={"sex": "男"}, nutrition=nutrition, now=now)

    assert result["body_composition"]["weight_rolling_change_kg"] > 0.2
    assert "100–150千卡" in result["nutrition"]["adjustment"]
    assert "只" in result["daily_coaching"]["experiment"]
    assert "一个变量" in result["daily_coaching"]["experiment"]
    assert "不同时增加高强度" in result["daily_coaching"]["experiment"]


def test_integrated_coaching_contains_all_linked_domains():
    now = datetime(2026, 7, 16, 8, 0, tzinfo=timezone.utc)
    result = build_summary([], [], [], now=now)

    assert {item["area"] for item in result["daily_coaching"]["inputs"]} == {
        "睡眠", "体重与体脂", "运动与日常活动", "饮食记录"
    }
    assert {item["area"] for item in result["daily_coaching"]["linked_actions"]} == {
        "运动", "饮食", "恢复", "测量"
    }
    assert len(result["daily_coaching"]["connections"]) == 4
