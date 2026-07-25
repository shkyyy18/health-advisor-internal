from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from math import ceil
from statistics import mean, median
from typing import Any


def _parse(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed


def _try_parse(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return _parse(str(value))
    except (TypeError, ValueError):
        return None


def _number(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _raw(item: dict[str, Any]) -> dict[str, Any]:
    value = item.get("raw_json")
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def _sleep_hours(item: dict[str, Any]) -> float | None:
    duration = _number(item.get("duration_minutes"))
    if duration is not None:
        hours = duration / 60
        return hours if 0 < hours <= 24 else None
    if item.get("start_time") and item.get("end_time"):
        start = _try_parse(item["start_time"])
        end = _try_parse(item["end_time"])
        if start is not None and end is not None:
            hours = (end - start).total_seconds() / 3600
            return hours if 0 < hours <= 24 else None
    return None


def _activity_load(
    activity: dict[str, Any], observed_max_hr: float | None, resting_hr: float | None
) -> tuple[float, str]:
    """Transparent load proxy; deliberately not Garmin EPOC or Training Load."""
    minutes = max(0.0, _number(activity.get("moving_time")) or 0) / 60
    avg_hr = _number(activity.get("average_heartrate"))
    if avg_hr and observed_max_hr and resting_hr and observed_max_hr > resting_hr + 20:
        hrr = (avg_hr - resting_hr) / (observed_max_hr - resting_hr)
        if hrr < 0.65:
            factor, bucket = 1.0, "低有氧"
        elif hrr < 0.78:
            factor, bucket = 1.4, "中高有氧"
        else:
            factor, bucket = 1.8, "高强度"
    else:
        factor, bucket = 1.2, "强度未校准"
    return minutes * factor, bucket


def _body_analysis(
    body: list[dict[str, Any]], profile: dict[str, Any], now: datetime
) -> dict[str, Any]:
    records = [item for item in body if _try_parse(item.get("measured_at")) is not None]
    records.sort(
        key=lambda item: _parse(str(item["measured_at"])),
        reverse=True,
    )
    weights = [_number(item.get("weight_kg")) for item in records]
    weights = [value for value in weights if value is not None]
    bf_records = [item for item in records if _number(item.get("body_fat_pct")) is not None]
    latest = records[0] if records else None
    latest_bf_record = bf_records[0] if bf_records else None
    recent_weights = weights[:7]
    recent_bf = [_number(item.get("body_fat_pct")) for item in bf_records[:7]]
    recent_bf = [value for value in recent_bf if value is not None]

    reference_tz = now.astimezone().tzinfo
    local_today = now.astimezone(reference_tz).date()
    this_week_start = local_today - timedelta(days=local_today.weekday())
    next_week_start = this_week_start + timedelta(days=7)
    last_week_start = this_week_start - timedelta(days=7)

    def values_between(field: str, start_date, end_date) -> list[float]:
        values: list[float] = []
        for item in records:
            measured_date = _parse(str(item["measured_at"])).astimezone(reference_tz).date()
            value = _number(item.get(field))
            if start_date <= measured_date < end_date and value is not None:
                values.append(value)
        return values

    this_week_weights = values_between("weight_kg", this_week_start, next_week_start)
    last_week_weights = values_between("weight_kg", last_week_start, this_week_start)
    this_week_bf = values_between("body_fat_pct", this_week_start, next_week_start)
    last_week_bf = values_between("body_fat_pct", last_week_start, this_week_start)
    recent_measurements = []
    for item in records:
        measured_at = _parse(str(item["measured_at"])).astimezone(reference_tz)
        weight_value = _number(item.get("weight_kg"))
        if weight_value is None:
            continue
        body_fat_value = _number(item.get("body_fat_pct"))
        lean_value = (
            round(weight_value * (1 - body_fat_value / 100), 1)
            if body_fat_value is not None and 0 <= body_fat_value < 80
            else None
        )
        recent_measurements.append(
            {
                "measured_at": measured_at.isoformat(),
                "measured_at_label": measured_at.strftime("%Y-%m-%d %H:%M"),
                "measured_at_short_label": measured_at.strftime("%m-%d %H:%M"),
                "weight_kg": round(weight_value, 1),
                "body_fat_pct": round(body_fat_value, 1) if body_fat_value is not None else None,
                "lean_mass_kg": lean_value,
            }
        )
    recent_measurements = recent_measurements[:5]

    # Use one measurement per calendar day for day-to-day and rolling-trend decisions.
    # Multiple same-day weigh-ins would otherwise make a short-term change look more certain.
    daily_records: list[dict[str, Any]] = []
    seen_dates = set()
    for item in records:
        measured_at = _parse(str(item["measured_at"])).astimezone(reference_tz)
        measured_date = measured_at.date()
        weight_value = _number(item.get("weight_kg"))
        if measured_date in seen_dates or weight_value is None:
            continue
        seen_dates.add(measured_date)
        daily_records.append(item)

    daily_weights = [_number(item.get("weight_kg")) for item in daily_records]
    daily_weights = [value for value in daily_weights if value is not None]
    latest_daily = daily_records[0] if daily_records else None
    previous_daily = daily_records[1] if len(daily_records) > 1 else None
    day_weight_change = (
        (_number(latest_daily.get("weight_kg")) or 0)
        - (_number(previous_daily.get("weight_kg")) or 0)
        if latest_daily and previous_daily
        else None
    )
    prior_weight_values = [
        value
        for item in daily_records[1:8]
        if (value := _number(item.get("weight_kg"))) is not None
    ]
    weight_vs_prior_median = (
        (_number(latest_daily.get("weight_kg")) or 0) - median(prior_weight_values)
        if latest_daily and prior_weight_values
        else None
    )
    current_rolling_weights = daily_weights[:7]
    previous_rolling_weights = daily_weights[7:14]
    rolling_weight_change = (
        mean(current_rolling_weights) - mean(previous_rolling_weights)
        if len(current_rolling_weights) >= 3 and len(previous_rolling_weights) >= 3
        else None
    )

    daily_bf_records = [
        item for item in daily_records if _number(item.get("body_fat_pct")) is not None
    ]
    day_body_fat_change = (
        (_number(daily_bf_records[0].get("body_fat_pct")) or 0)
        - (_number(daily_bf_records[1].get("body_fat_pct")) or 0)
        if len(daily_bf_records) > 1
        else None
    )
    current_rolling_bf = [
        value
        for item in daily_bf_records[:7]
        if (value := _number(item.get("body_fat_pct"))) is not None
    ]
    previous_rolling_bf = [
        value
        for item in daily_bf_records[7:14]
        if (value := _number(item.get("body_fat_pct"))) is not None
    ]
    rolling_body_fat_change = (
        mean(current_rolling_bf) - mean(previous_rolling_bf)
        if len(current_rolling_bf) >= 3 and len(previous_rolling_bf) >= 3
        else None
    )

    basal_values = [_number(item.get("basal_metabolism")) for item in records]
    basal_values = [value for value in basal_values if value and value > 500]

    def average(values: list[float]) -> float | None:
        return round(mean(values), 1) if values else None

    def change(current: list[float], previous: list[float]) -> float | None:
        return round(mean(current) - mean(previous), 1) if current and previous else None

    result: dict[str, Any] = {
        "status": "数据不足",
        "latest_weight_kg": round(_number(latest.get("weight_kg")) or 0, 1) if latest else None,
        "weight_average_kg": round(mean(recent_weights), 1) if recent_weights else None,
        "body_fat_pct": round(mean(recent_bf), 1) if recent_bf else None,
        "latest_body_fat_pct": None,
        "latest_body_fat_date": None,
        "this_week_label": f"{this_week_start:%m-%d}至{local_today:%m-%d}",
        "last_week_label": f"{last_week_start:%m-%d}至{(this_week_start - timedelta(days=1)):%m-%d}",
        "weight_this_week_avg_kg": average(this_week_weights),
        "weight_last_week_avg_kg": average(last_week_weights),
        "weight_week_change_kg": change(this_week_weights, last_week_weights),
        "weight_this_week_count": len(this_week_weights),
        "weight_last_week_count": len(last_week_weights),
        "body_fat_this_week_avg_pct": average(this_week_bf),
        "body_fat_last_week_avg_pct": average(last_week_bf),
        "body_fat_week_change_pct": change(this_week_bf, last_week_bf),
        "body_fat_this_week_count": len(this_week_bf),
        "body_fat_last_week_count": len(last_week_bf),
        "target_weight_range_kg": None,
        "recommended_loss_kg": None,
        "weekly_loss_kg": "0.2–0.4",
        "detail": "至少需要连续体重和体脂数据才能估算。",
        "caveat": "家用生物电阻抗体脂秤受水分、进食和运动影响，应看同一条件下的多日趋势。",
        "recent_measurements": recent_measurements,
    }
    result["weight_trend_kg"] = result["weight_week_change_kg"]
    result.update(
        {
            "latest_measurement_date": (
                _parse(str(latest_daily["measured_at"])).astimezone(reference_tz).strftime("%Y-%m-%d")
                if latest_daily
                else None
            ),
            "previous_weight_kg": (
                round(_number(previous_daily.get("weight_kg")) or 0, 1)
                if previous_daily
                else None
            ),
            "weight_day_change_kg": (round(day_weight_change, 1) if day_weight_change is not None else None),
            "weight_vs_prior_median_kg": (
                round(weight_vs_prior_median, 1) if weight_vs_prior_median is not None else None
            ),
            "weight_rolling_change_kg": (
                round(rolling_weight_change, 2) if rolling_weight_change is not None else None
            ),
            "weight_rolling_current_count": len(current_rolling_weights),
            "weight_rolling_previous_count": len(previous_rolling_weights),
            "body_fat_day_change_pct": (
                round(day_body_fat_change, 1) if day_body_fat_change is not None else None
            ),
            "body_fat_rolling_change_pct": (
                round(rolling_body_fat_change, 2) if rolling_body_fat_change is not None else None
            ),
            "basal_metabolism_kcal": round(basal_values[0]) if basal_values else None,
        }
    )

    if day_weight_change is not None and abs(day_weight_change) >= 1.0:
        direction = "上升" if day_weight_change > 0 else "下降"
        result["daily_weight_signal"] = (
            f"单日体重{direction}{abs(day_weight_change):.1f}公斤，幅度更像水分、糖原、盐分、"
            "进食时间或排便造成的短期波动，不能按同等脂肪变化处理。"
        )
        result["single_day_weight_spike"] = True
    elif day_weight_change is not None:
        result["daily_weight_signal"] = f"最近两次体重变化{day_weight_change:+.1f}公斤，仍需结合多日均值判断。"
        result["single_day_weight_spike"] = False
    else:
        result["daily_weight_signal"] = "缺少相邻两天称重，暂不能判断单日变化。"
        result["single_day_weight_spike"] = False

    if rolling_weight_change is None:
        result["rolling_weight_signal"] = "尚不足以比较最近7次与此前7次称重均值。"
    elif rolling_weight_change > 0.2:
        result["rolling_weight_signal"] = f"最近7次称重均值比此前一组高{rolling_weight_change:.2f}公斤。"
    elif rolling_weight_change < -0.5:
        result["rolling_weight_signal"] = f"最近7次称重均值下降{abs(rolling_weight_change):.2f}公斤，速度可能偏快。"
    elif rolling_weight_change <= -0.2:
        result["rolling_weight_signal"] = f"最近7次称重均值下降{abs(rolling_weight_change):.2f}公斤，处于当前温和目标附近。"
    else:
        result["rolling_weight_signal"] = f"最近7次称重均值变化{rolling_weight_change:+.2f}公斤，整体接近平台。"

    if not latest_bf_record:
        return result
    weight = _number(latest_bf_record.get("weight_kg"))
    body_fat = _number(latest_bf_record.get("body_fat_pct"))
    if (
        weight is None
        or body_fat is None
        or weight <= 0
        or not 0 <= body_fat < 80
    ):
        return result

    latest_bf_at = _parse(str(latest_bf_record["measured_at"])).astimezone(reference_tz)
    lean_mass = weight * (1 - body_fat / 100)
    sex = profile.get("sex")
    if sex == "男":
        result["status"] = "偏高" if body_fat >= 25 else ("需关注" if body_fat >= 20 else "常用健康区间")
    elif sex == "女":
        result["status"] = "偏高" if body_fat >= 32 else ("需关注" if body_fat >= 25 else "常用健康区间")
    else:
        result["status"] = "需结合性别判断"

    target_low = _number(profile.get("target_body_fat_low")) or (20 if sex == "男" else 25)
    target_high = _number(profile.get("target_body_fat_high")) or (24 if sex == "男" else 30)
    target_low = min(60.0, max(5.0, target_low))
    target_high = min(60.0, max(target_low, target_high))
    target_weight_low = lean_mass / (1 - target_low / 100)
    target_weight_high = lean_mass / (1 - target_high / 100)
    loss_low = max(0.0, weight - target_weight_high)
    loss_high = max(0.0, weight - target_weight_low)
    result.update({
        "measurement_weight_kg": round(weight, 1),
        "body_fat_pct": round(mean(recent_bf), 1) if recent_bf else round(body_fat, 1),
        "latest_body_fat_pct": round(body_fat, 1),
        "latest_body_fat_date": latest_bf_at.strftime("%Y-%m-%d"),
        "lean_mass_kg": round(lean_mass, 1),
        "target_body_fat_range": f"{target_low:.0f}%–{target_high:.0f}%",
        "target_weight_range_kg": f"{target_weight_low:.1f}–{target_weight_high:.1f}",
        "recommended_loss_kg": f"约{loss_low:.1f}公斤",
        "extended_loss_kg": f"{loss_low:.1f}–{loss_high:.1f}公斤",
        "detail": (
            f"按最近一次同时有体重和体脂的数据估算，去脂体重约{lean_mass:.1f}公斤。"
            f"先以体脂{target_high:.0f}%、体重约{target_weight_high:.1f}公斤为第一阶段；"
            f"达到后根据功率、睡眠和饥饿感，再决定是否继续到{target_low:.0f}%–{target_high:.0f}%。"
        ),
    })
    return result


def _sleep_context(sleep: list[dict[str, Any]]) -> dict[str, Any]:
    entries: list[tuple[datetime | None, int, float]] = []
    for index, item in enumerate(sleep):
        hours = _sleep_hours(item)
        if hours is None:
            continue
        moment = _try_parse(item.get("start_time"))
        if moment is None and item.get("sleep_date"):
            moment = _try_parse(f"{item['sleep_date']}T12:00:00+00:00")
        entries.append((moment, index, hours))
    entries.sort(key=lambda entry: (entry[0] is not None, entry[0] or datetime.min.replace(tzinfo=timezone.utc), -entry[1]), reverse=True)
    values = [entry[2] for entry in entries[:7]]
    latest_hours = entries[0][2] if entries else None
    average_hours = mean(values) if values else None
    debt = sum(max(0.0, 7.0 - value) for value in values)
    if latest_hours is None:
        severity, signal = "未知", "没有可用的最近一晚睡眠时长。"
    elif latest_hours < 3:
        severity, signal = "严重不足", f"最近一晚仅睡{latest_hours:.1f}小时，今天不应安排高强度训练。"
    elif latest_hours < 5:
        severity, signal = "明显不足", f"最近一晚睡{latest_hours:.1f}小时，恢复资源明显不足。"
    elif latest_hours < 6:
        severity, signal = "不足", f"最近一晚睡{latest_hours:.1f}小时，训练强度应下调。"
    elif average_hours is not None and average_hours < 6.5:
        severity, signal = "累积不足", f"最近一晚睡{latest_hours:.1f}小时，但近7次平均仅{average_hours:.1f}小时。"
    else:
        severity, signal = "基本充足", f"最近一晚睡{latest_hours:.1f}小时，未触发睡眠降级规则。"
    return {"values": values, "latest_hours": round(latest_hours, 1) if latest_hours is not None else None, "average_hours": round(average_hours, 1) if average_hours is not None else None, "sleep_debt_hours": round(debt, 1), "severity": severity, "signal": signal, "count": len(values)}


def _daily_metrics_context(metrics: list[dict[str, Any]]) -> dict[str, Any]:
    dated = [(moment, item) for item in metrics if (moment := _try_parse(item.get("metric_date"))) is not None]
    dated.sort(key=lambda pair: pair[0], reverse=True)
    ordered = [item for _, item in dated]
    latest = ordered[0] if ordered else {}
    recent = ordered[:7]
    steps = [value for item in recent if (value := _number(item.get("steps"))) is not None and value >= 0]
    active_minutes = [value for item in recent if (value := _number(item.get("active_minutes"))) is not None and value >= 0]
    active_calories = [value for item in recent if (value := _number(item.get("calories"))) is not None and value >= 0]
    latest_resting = _number(latest.get("heart_rate_min"))
    prior_resting = [value for item in ordered[1:8] if (value := _number(item.get("heart_rate_min"))) is not None and value >= 30]
    resting_baseline = median(prior_resting) if prior_resting else None
    resting_delta = latest_resting - resting_baseline if latest_resting is not None and resting_baseline is not None else None
    latest_stress = _number(latest.get("stress_avg"))
    latest_steps = _number(latest.get("steps"))
    return {"latest_date": latest.get("metric_date"), "latest_steps": round(latest_steps) if latest_steps is not None else None, "average_steps": round(mean(steps)) if steps else None, "average_active_minutes": round(mean(active_minutes)) if active_minutes else None, "average_active_calories": round(mean(active_calories)) if active_calories else None, "latest_resting_hr": round(latest_resting) if latest_resting is not None else None, "resting_baseline_hr": round(resting_baseline) if resting_baseline is not None else None, "resting_hr_delta": round(resting_delta) if resting_delta is not None else None, "latest_stress": round(latest_stress) if latest_stress is not None else None}


def _mifflin_bmr(weight: float | None, profile: dict[str, Any]) -> float | None:
    height = _number(profile.get("height_cm")); age = _number(profile.get("age")); sex = profile.get("sex")
    if weight is None or height is None or age is None or sex not in {"男", "女"}:
        return None
    return 10 * weight + 6.25 * height - 5 * age + (5 if sex == "男" else -161)


# Weekday-to-sport mapping gives variety while keeping a predictable weekly rhythm.
# 0=Mon bodyweight, 1=Tue swim, 2=Wed rest, 3=Thu run, 4=Fri bodyweight, 5=Sat ride, 6=Sun rest
_WEEKDAY_SPORT = ["bodyweight", "swim", "rest", "run", "bodyweight", "ride", "rest"]

_WORKOUT_LIBRARY: dict[str, dict[str, dict[str, Any]]] = {
    "swim": {
        "recovery": {
            "title": "轻松游泳恢复",
            "duration": "30–40分钟",
            "rationale": "恢复不足时用水中的低阻力活动促进血流，不冲击关节和神经系统。",
            "sources": [
                "Mayo Clinic（梅奥诊所）水中运动指引 mayoclinic.org/healthy-lifestyle/fitness/in-depth/aquatic-exercise/art-20546802",
                "Mayo Clinic（梅奥诊所）有氧运动如何热身与冷身 mayoclinic.org/healthy-lifestyle/fitness/in-depth/exercise/art-20045517",
                "Mayo Clinic（梅奥诊所）运动强度自测（说话测试） mayoclinic.org/healthy-lifestyle/fitness/in-depth/exercise-intensity/art-20046887",
            ],
            "warmup": [
                {"name": "岸上动态热身", "detail": "肩部摆动前后各10次、颈部侧向拉伸每侧15秒、躯干左右旋转各10次", "duration": "3分钟", "source": "AAOS",
                 "guide": "身体前倾、一手扶墙或池边栏杆，另一只手臂完全放松下垂，靠身体轻晃带动手臂像钟摆一样摆动：前后10次、左右10次，换边（AAOS肩部方案的标准热身摆臂）；颈部侧倾：耳朵慢慢倒向肩膀，每侧15秒，不后仰；躯干直立、左右缓慢转体各10次。要领：肩是球窝关节可以环绕，但动作要慢、幅度由小到大；所有摆动都不用力甩。"},
                {"name": "水中适应", "detail": "水中行走 + 呼吸练习，然后慢速自由泳或蛙泳", "duration": "5分钟", "source": "Mayo Clinic",
                 "guide": "先在齐腰深的水里来回走2分钟适应水温（Mayo水中运动指引建议从水中行走开始）；再扶池边练呼吸：脸埋入水中用口鼻缓慢均匀吐气，转头或抬头时快速吸气，重复20次；最后慢速游，专注“水下吐气、水上吸气”的节奏。要领：这个阶段不是训练，是让身体熟悉水和呼吸，越慢越好。"},
            ],
            "main": [
                {"name": "轻松连续游", "detail": "自由泳或蛙泳任选，RPE 3分，能完整说句子", "sets": 1, "reps": "400–600米", "rest": "无", "note": "不要计时，动作放松", "source": "Mayo Clinic",
                 "guide": "自由泳或蛙泳任选，连续游或分段游都可以。强度用“说话测试”控制（Mayo/ACSM：中等强度＝能完整说话、但没法唱歌）：游进中能轻松说完一整句话就是对的强度。要领：身体尽量水平伸展，水下持续吐气不憋气；累了就在池边站定休息30秒再继续。不要计时、不比速度——今天只求“游完更轻松”，任何疼痛即停。"},
            ],
            "cooldown": [
                {"name": "放松游", "detail": "任意泳姿，越慢越好", "duration": "5分钟", "source": "Mayo Clinic",
                 "guide": "越慢越好，也可以仰漂或扶板慢打腿。Mayo冷身原则：用远低于主项的强度继续活动几分钟，让心率和血压平缓回落，而不是突然停下。"},
                {"name": "肩部/背部拉伸", "detail": "交叉手臂拉伸每侧30秒，躯干侧伸展每侧15秒", "duration": "3分钟", "source": "AAOS",
                 "guide": "交叉手臂拉伸（AAOS肩部方案）：一只手臂横过胸前，另一只手托住它的上臂（不要压肘关节），轻轻拉向身体，感到肩后侧轻微牵拉，每侧保持30秒；再双手上举，分别向左右侧弯各15秒。要领：不耸肩、身体不扭转，拉伸不应疼痛。"},
            ],
            "fallback": "若精神很差或泳池人多，改为水中行走10分钟（Mayo水中运动指引：水中有天然阻力且关节零冲击）+ 池边拉伸；任何疼痛即停。",
        },
        "easy": {
            "title": "游泳技术 + 低强度耐力",
            "duration": "40–50分钟",
            "rationale": "在低强度下打磨动作效率，同时积累有氧时间。",
            "sources": [
                "Mayo Clinic（梅奥诊所）水中运动指引 mayoclinic.org/healthy-lifestyle/fitness/in-depth/aquatic-exercise/art-20546802",
                "Mayo Clinic（梅奥诊所）运动强度自测（说话测试） mayoclinic.org/healthy-lifestyle/fitness/in-depth/exercise-intensity/art-20046887",
                "ACSM（美国运动医学会）有氧运动强度指引 acsm.org/wp-content/uploads/2025/02/Exercise-intensity-infographic-PDF.pdf",
            ],
            "warmup": [
                {"name": "岸上动态热身", "detail": "肩部摆动、直臂下压、转体各10次", "duration": "3分钟", "source": "AAOS",
                 "guide": "先做AAOS肩部方案的钟摆式摆臂：前倾、一手扶稳、手臂放松下垂，前后、左右各摆动10次换边；再做直臂下压：双臂前平举，缓慢向下向后压到体侧再抬起，10次，感受肩后侧收紧；最后躯干直立左右转体各10次。要领：全程放松慢速，幅度由小到大。"},
                {"name": "水中适应", "detail": "100米慢速配合呼吸练习", "duration": "5分钟", "source": "Mayo Clinic",
                 "guide": "慢速游100米，每25米只关注呼吸：脸在水中用口鼻持续均匀吐气，转头（自由泳）或抬头（蛙泳）时快速吸气。要领：吐气不充分是新手喘不上气的最常见原因——水下一定把气吐干净，吸气自然来得及。"},
            ],
            "main": [
                {"name": "技术游", "detail": "25米专注一个技术点（如呼吸/身体位置），RPE 3分", "sets": 6, "reps": "25米", "rest": "15秒", "note": "质量优先，不计速度", "source": "Mayo Clinic",
                 "guide": "每25米只专注一个技术点：第1–2组练呼吸（水下持续吐气、转头快吸气）；第3–4组练身体位置（头顶朝前、髋部尽量贴近水面、身体像一根伸直的圆木）；第5–6组练划水节奏（一手入水另一手开始划，动作连贯不抢）。要领：25米很短，正好让新手在不累的前提下打磨动作——质量优先，不计速度，组间只休15秒。"},
                {"name": "轻松连续游", "detail": "自由泳或蛙泳，RPE 4分", "sets": 1, "reps": "400–600米", "rest": "无", "note": "保持呼吸规律", "source": "Mayo Clinic",
                 "guide": "用说话测试维持在“能说话、不能唱歌”的中等强度（Mayo/ACSM）。自由泳每2–3划转头吸气一次，水下一直吐气；蛙泳抬头吸气低头吐气，节奏一下是一下。如果喘到说不出完整句子，就减速或在池边休30秒——强度宁低不高。"},
            ],
            "cooldown": [
                {"name": "放松游", "detail": "100米任意泳姿", "duration": "3分钟", "source": "Mayo Clinic",
                 "guide": "100米任意泳姿，越慢越好，专注把呼吸放缓放长。Mayo冷身原则：用远低于主项的强度继续活动几分钟，让心率和血压平缓回落，而不是突然停下上岸。"},
                {"name": "拉伸", "detail": "交叉手臂拉伸 + 侧伸展 + 面墙小腿拉伸，每侧15秒", "duration": "3分钟", "source": "AAOS",
                 "guide": "交叉手臂拉伸（AAOS肩部方案）：手臂横过胸前，托住上臂轻拉，每侧15秒×2；躯干侧伸展每侧15秒；面墙小腿拉伸：前腿屈膝后腿伸直、后脚跟不离地，髋向墙推，每侧15秒×2。要领：轻微牵拉即可，疼痛就是拉过头了。"},
            ],
            "fallback": "减少技术游到4组，连续游改为200米；任何疼痛即停。",
        },
        "tempo": {
            "title": "游泳节奏训练",
            "duration": "50–60分钟",
            "rationale": "用可控的中等强度段落提高有氧节奏感。",
            "sources": [
                "Mayo Clinic（梅奥诊所）水中运动指引 mayoclinic.org/healthy-lifestyle/fitness/in-depth/aquatic-exercise/art-20546802",
                "Mayo Clinic（梅奥诊所）运动强度自测（说话测试） mayoclinic.org/healthy-lifestyle/fitness/in-depth/exercise-intensity/art-20046887",
                "ACSM（美国运动医学会）有氧运动强度指引 acsm.org/wp-content/uploads/2025/02/Exercise-intensity-infographic-PDF.pdf",
            ],
            "warmup": [
                {"name": "岸上动态热身", "detail": "肩部摆动、躯干转体、髋绕环各10次", "duration": "3分钟", "source": "AAOS",
                 "guide": "AAOS肩部方案钟摆式摆臂：前倾扶稳，手臂放松下垂，前后、左右、画小圈各10次换边；躯干直立左右转体各10次；双手叉腰做髋关节绕环，顺逆时针各5次换边。要领：肩和髋是球窝关节可以环绕，但膝盖不做绕环类动作。"},
                {"name": "水中热身", "detail": "200米慢速 + 4×25米逐渐加速", "duration": "8分钟", "source": "Mayo Clinic",
                 "guide": "200米慢速游让身体热起来（Mayo热身原则：用主项运动的低强度版本热身）；然后4×25米逐渐加速：每一趟从慢开始、到最后5米略提速，游完慢走回起点或休20秒。要领：加速是“预演”节奏段的感觉，不是冲刺。"},
            ],
            "main": [
                {"name": "节奏游", "detail": "RPE 6分，呼吸明显加深但可说短句", "sets": 4, "reps": "100米", "rest": "30秒", "note": "保持每100米时间波动不超过5秒", "source": "ACSM",
                 "guide": "RPE 6分≈Mayo描述的较大强度临界：呼吸明显加深、只能说短句。每100米保持均匀配速，组间只休30秒。要领：强度来自更连贯的划水节奏，不是更用力的挣扎——身体姿态保持伸展、打水幅度不变形；第3组开始如果动作明显变形，就降回轻松游完成剩余组数。"},
                {"name": "轻松恢复游", "detail": "RPE 3分", "sets": 1, "reps": "200米", "rest": "无", "note": "衔接主项", "source": "Mayo Clinic",
                 "guide": "200米轻松游衔接主项，用说话测试保持在能完整说话的强度。专注把呼吸节奏放慢放长：水下持续吐气、转头快吸气，作为节奏段和冷身之间的过渡，让心率先降一档。"},
            ],
            "cooldown": [
                {"name": "放松游", "detail": "200米", "duration": "5分钟", "source": "Mayo Clinic",
                 "guide": "200米任意泳姿，越慢越好，可以仰漂或扶板慢打腿交替进行。Mayo冷身原则：用远低于主项的强度继续活动几分钟，让心率和血压平缓回落，而不是突然停下上岸。"},
                {"name": "拉伸", "detail": "交叉手臂拉伸 + 侧伸展，每侧20秒", "duration": "3分钟", "source": "AAOS",
                 "guide": "交叉手臂拉伸（AAOS肩部方案）：手臂横过胸前、托住上臂轻拉，每侧20秒×2；双手上举向左右侧弯各20秒。要领：不耸肩、不扭转，拉伸不应疼痛。"},
            ],
            "fallback": "节奏游减到3组，或每组改为75米；任何疼痛即停。",
        },
    },
    "run": {
        "recovery": {
            "title": "轻松慢跑恢复",
            "duration": "25–35分钟",
            "rationale": "用最轻松的跑步节奏帮助身体排出代谢废物。",
            "sources": [
                "Mayo Clinic（梅奥诊所）新手5K七周计划（跑走结合原则） mayoclinic.org/healthy-lifestyle/fitness/in-depth/5k-run/art-20050962",
                "Mayo Clinic（梅奥诊所）运动强度自测（说话测试） mayoclinic.org/healthy-lifestyle/fitness/in-depth/exercise-intensity/art-20046887",
                "Mayo Clinic（梅奥诊所）有氧运动如何热身与冷身 mayoclinic.org/healthy-lifestyle/fitness/in-depth/exercise/art-20045517",
            ],
            "warmup": [
                {"name": "步行", "detail": "自然步速逐渐加快到微微发热", "duration": "3分钟", "source": "Mayo Clinic",
                 "guide": "自然步速出门，逐渐加快到身体微微发热。Mayo热身原则：热身就是把主项运动用更慢的节奏先做一遍——跑步的热身从走路开始，让心率、血流和关节温度逐步上升，而不是一出门就跑。"},
                {"name": "动态拉伸", "detail": "原地交替抬膝20次、慢速后踢腿20次、扶墙腿部前后摆动每侧10次", "duration": "5分钟", "source": "Mayo Clinic",
                 "guide": "原地交替抬膝（高抬腿的走路版）：站直，交替把膝盖抬向髋部高度，双臂配合摆动，共20次；慢速后踢腿：原地交替把脚跟向后勾向臀部，双膝保持朝下并拢，20次；扶墙腿部前后摆动：一手扶墙，一条腿像钟摆一样前后自然摆动10次换边。Mayo柔韧性指引建议热身后做与运动本身相似的动态动作（动态热身），不要在这时做静止压腿。"},
            ],
            "main": [
                {"name": "超轻松慢跑", "detail": "RPE 3分，比快走略快，能完整聊天", "sets": 1, "reps": "20–25分钟", "rest": "无", "note": "不要看配速", "source": "Mayo Clinic",
                 "guide": "速度只比快走快一点，全程能完整聊天（Mayo说话测试：中等强度＝能说话、不能唱歌）。姿势要领：身体正直微微前倾、目视前方约10米；步幅小、步频快，落地点在身体正下方而不是跨到身体前面；落地尽量轻。不要看配速——今天只求“动完更轻松”。要领：Mayo给新手的跑步计划核心就是跑走结合，任何时候觉得喘或膝盖不适，直接改成走，这是计划的一部分。"},
            ],
            "cooldown": [
                {"name": "步行", "detail": "逐渐降速", "duration": "3分钟", "source": "Mayo Clinic",
                 "guide": "跑完不要立刻停下，从慢跑逐渐降到走，慢走3分钟让心率平缓回落（Mayo冷身原则：冷身帮助心率和血压逐渐恢复到运动前水平）。要领：边走边把呼吸放慢，等不再喘了再停下来拉伸。"},
                {"name": "小腿/大腿拉伸", "detail": "站姿股四头肌拉伸 + 面墙小腿拉伸，每侧20秒", "duration": "3分钟", "source": "AAOS",
                 "guide": "站姿股四头肌拉伸（AAOS膝盖方案）：扶墙，一手抓同侧脚踝把脚跟拉向臀部，双膝并拢，每侧20秒；面墙小腿拉伸（AAOS）：前腿屈膝、后腿伸直脚跟踩实，髋向墙推，每侧20秒。要领：不弓腰不扭转，拉伸不应疼痛。"},
            ],
            "fallback": "若腿沉或膝盖不适，改为快走15分钟 + 拉伸；任何疼痛即停。",
        },
        "easy": {
            "title": "有氧基础跑",
            "duration": "35–45分钟",
            "rationale": "在能完整对话的轻松配速下积累有氧能力。",
            "sources": [
                "Mayo Clinic（梅奥诊所）新手5K七周计划（跑走结合原则） mayoclinic.org/healthy-lifestyle/fitness/in-depth/5k-run/art-20050962",
                "Mayo Clinic（梅奥诊所）运动强度自测（说话测试） mayoclinic.org/healthy-lifestyle/fitness/in-depth/exercise-intensity/art-20046887",
                "ACSM（美国运动医学会）身体活动指南常见问题（每周150–300分钟中等强度） acsm.org/physical-activity-guidelines-faqs/",
            ],
            "warmup": [
                {"name": "步行", "detail": "唤醒下肢", "duration": "3分钟", "source": "Mayo Clinic",
                 "guide": "自然步速出门，逐渐加快到身体微微发热。Mayo热身原则：用主项运动的低强度版本热身——跑步的热身从走路开始，让心率、血流和关节温度逐步上升，降低受伤风险，而不是一出门就跑。"},
                {"name": "动态热身", "detail": "原地交替抬膝30次、慢速后踢腿30次、扶墙腿部前后摆动每侧10次", "duration": "5分钟", "source": "Mayo Clinic",
                 "guide": "原地交替抬膝30次：站直交替抬膝到髋部高度，双臂配合摆动；慢速后踢腿30次：脚跟向后勾向臀部，双膝朝下并拢；扶墙腿部前后摆动每侧10次。要领：全部是“走路版”的温和动态动作（Mayo动态热身原则），用它们替代开合跳等跳跃动作，对膝盖更友好。"},
            ],
            "main": [
                {"name": "轻松跑", "detail": "RPE 4分，能完整说话", "sets": 1, "reps": "25–35分钟", "rest": "无", "note": "选择平坦路线", "source": "Mayo Clinic",
                 "guide": "选择平坦路线，全程用说话测试维持中等强度（Mayo/ACSM：能说话、不能唱歌）。Mayo新手5K计划的核心原则是跑走结合：如果喘到说不出完整句子，就走1分钟再跑——这不丢人，是计划的一部分。姿势要领：小步快频、落地点在身体正下方、落地轻、身体正直不前仰。ACSM建议成人每周积累150–300分钟中等强度有氧，今天的轻松跑就是主要积累。"},
            ],
            "cooldown": [
                {"name": "步行", "detail": "5分钟慢走", "duration": "5分钟", "source": "Mayo Clinic",
                 "guide": "慢走5分钟，让心率平缓回落再停下来拉伸（Mayo冷身原则：冷身帮助心率和血压逐渐恢复到运动前水平）。要领：边走边深呼吸，等呼吸完全平稳、不再出汗了再做静态拉伸。"},
                {"name": "拉伸", "detail": "髋屈肌、腘绳肌、小腿每侧20秒", "duration": "4分钟", "source": "Mayo Clinic",
                 "guide": "跪姿髋屈肌拉伸（Mayo基础拉伸指引）：单膝跪地（膝下垫毛巾），另一腿在前屈膝踩地，身体直立缓慢前移重心，感受跪地侧髋前方牵拉；仰卧腘绳肌拉伸：抱大腿后侧轻拉，手不要压在膝盖关节上；面墙小腿拉伸：后腿伸直脚跟不离地，髋向墙推。每个每侧20秒，轻微牵拉即可，疼痛就是拉过头了。"},
            ],
            "fallback": "改为跑走结合：跑3分钟 + 走1分钟，重复6–8次；任何疼痛即停。",
        },
        "tempo": {
            "title": "节奏跑",
            "duration": "45–55分钟",
            "rationale": "用略高于日常有氧的强度提升乳酸阈值。",
            "sources": [
                "Mayo Clinic（梅奥诊所）运动强度自测（说话测试） mayoclinic.org/healthy-lifestyle/fitness/in-depth/exercise-intensity/art-20046887",
                "Mayo Clinic（梅奥诊所）有氧运动如何热身与冷身 mayoclinic.org/healthy-lifestyle/fitness/in-depth/exercise/art-20045517",
                "ACSM（美国运动医学会）有氧运动强度指引 acsm.org/wp-content/uploads/2025/02/Exercise-intensity-infographic-PDF.pdf",
            ],
            "warmup": [
                {"name": "慢跑", "detail": "RPE 3分", "duration": "8分钟", "source": "Mayo Clinic",
                 "guide": "8分钟超轻松慢跑，能完整聊天的速度。Mayo热身原则：用主项运动的低强度版本让身体逐步进入状态——节奏跑强度更高，热身更不能省。"},
                {"name": "动态热身", "detail": "原地交替抬膝、后踢腿、加速跑4×50米", "duration": "5分钟", "source": "Mayo Clinic",
                 "guide": "原地交替抬膝20次、慢速后踢腿20次、扶墙腿部前后摆动每侧10次；然后4×50米逐渐加速跑：从慢跑开始每趟略提速、最后到约八成速度，慢走回来再做下一趟。要领：加速跑是让身体“预演”节奏段的速度，不是冲刺。"},
            ],
            "main": [
                {"name": "节奏跑", "detail": "RPE 6分，呼吸深但可控，说短句", "sets": 3, "reps": "6分钟", "rest": "2分钟轻松走/慢跑", "note": "保持配速稳定", "source": "Mayo Clinic",
                 "guide": "RPE 6分：呼吸明显加深、只能说短句，但节奏可控——Mayo把“说几个字就要换气”归为较大强度，你要控制在比那略低、能稳定输出6分钟的程度。要领：6分钟内配速尽量均匀，宁可前慢后稳、不要前快后崩；组间2分钟慢走或超轻松慢跑，不要停下站着。"},
                {"name": "轻松慢跑", "detail": "RPE 4分", "sets": 1, "reps": "5分钟", "rest": "无", "note": "衔接", "source": "Mayo Clinic",
                 "guide": "5分钟轻松慢跑衔接节奏段，回到能完整说话的强度（Mayo说话测试）。要领：小步快频、落地轻，让呼吸从节奏段的深度慢慢放缓，作为冷身前的过渡，不要直接停下来。"},
            ],
            "cooldown": [
                {"name": "慢跑", "detail": "RPE 3分", "duration": "5分钟", "source": "Mayo Clinic",
                 "guide": "5分钟超轻松慢跑，最后1分钟逐渐降到走，让心率平缓回落（Mayo冷身原则：冷身帮助心率和血压逐渐恢复到运动前水平）。要领：边走边把呼吸放慢，等不再喘了再拉伸。"},
                {"name": "拉伸", "detail": "下肢全套每侧20秒", "duration": "5分钟", "source": "AAOS",
                 "guide": "站姿股四头肌拉伸、仰卧腘绳肌拉伸、面墙小腿拉伸（均AAOS膝盖方案）加跪姿髋屈肌拉伸，每侧20秒。要领：手不要压在膝盖关节上，后脚脚跟全程不离地，拉伸不应疼痛。"},
            ],
            "fallback": "节奏段改为2×6分钟，或改为轻松跑；任何疼痛即停。",
        },
    },
    "bodyweight": {
        "recovery": {
            "title": "低冲击护膝恢复训练",
            "duration": "25–35分钟",
            "rationale": "按AAOS膝盖调理原则：强化膝盖周围肌肉，让肌肉替关节吸收冲击；全程低冲击、不负重，恢复日安全执行。",
            "sources": [
                "AAOS（美国骨科医师学会）膝盖调理方案 orthoinfo.aaos.org/en/recovery/knee-conditioning-program/",
                "Mayo Clinic（梅奥诊所）核心力量动作库 mayoclinic.org/healthy-lifestyle/fitness/multimedia/core-strength/sls-20076575",
            ],
            "warmup": [
                {"name": "轻松步行或原地踏步", "detail": "自然步速，身体微微发热即可", "duration": "5分钟", "source": "AAOS",
                 "guide": "在屋里来回走，或原地踏步：站直，交替抬膝，双臂自然摆动，前脚掌先落地、落地放轻。AAOS要求力量训练前做5–10分钟低冲击热身，目的是让关节和肌肉热起来，不是练强度。"},
            ],
            "main": [
                {"name": "仰卧直腿抬高", "detail": "一腿屈膝踩地，另一腿绷直慢抬慢放", "sets": 3, "reps": "10次每侧", "rest": "30秒", "note": "膝盖全程伸直", "source": "AAOS",
                 "guide": "仰卧，一条腿屈膝踩地，另一条腿伸直、脚尖勾起。收紧伸直腿的大腿前侧肌肉，缓慢抬到与另一侧大腿同高，停2秒，再用2–3秒慢慢放下。要领：膝盖全程绷直不弯，腰贴地，靠大腿发力而不是甩腿。这是对膝盖压力最小的股四头肌训练——膝盖全程不承重、不屈曲。"},
                {"name": "臀桥", "detail": "顶峰夹臀停2秒，慢放", "sets": 2, "reps": "12–15次", "rest": "30秒", "note": "用臀发力不用腰", "source": "Mayo Clinic",
                 "guide": "仰卧屈膝，双脚踩地与髋同宽，脚跟离臀部约一脚掌。收紧腹部和臀部把髋向上顶，到肩—髋—膝成一条直线，顶峰夹紧臀部停2秒，再慢放。要领：发力的是臀部；如果腰酸说明在用腰代偿，减小幅度重新夹臀；顶起时肋骨不要外翻。臀肌强了，走路爬楼时膝盖的负担就小。"},
                {"name": "侧卧髋外展", "detail": "上腿伸直慢抬，骨盆不后倒", "sets": 2, "reps": "10次每侧", "rest": "30秒", "note": "脚尖朝前", "source": "AAOS",
                 "guide": "侧卧，下方腿微屈，上方腿伸直、脚尖朝正前方。缓慢向上抬约30–40厘米，停2秒，慢放。要领：骨盆保持垂直不向后倒（可手扶髋部自查），动作慢、不甩。练臀中肌——这块肌肉是走路和单腿支撑时膝盖不内扣的关键。"},
                {"name": "扶椅半蹲", "detail": "只下蹲约20–25厘米，不深蹲", "sets": 3, "reps": "10次", "rest": "45秒", "note": "重心在脚跟", "source": "AAOS",
                 "guide": "双脚与肩同宽站在椅背后，双手轻扶椅背。胸口抬起，像坐椅子一样只下蹲约20–25厘米（四分之一蹲），重心放在脚后跟，停2–5秒，再推脚跟起身。要领：膝盖方向始终与脚尖一致、不内扣；蹲得浅是AAOS为控制髌骨压力的刻意选择，不要蹲到大腿水平。"},
                {"name": "站姿腘绳肌弯举", "detail": "脚跟向后上方抬起，双膝并拢", "sets": 3, "reps": "10次每侧", "rest": "30秒", "note": "停2秒慢放", "source": "AAOS",
                 "guide": "扶椅背站立，一侧膝盖弯曲，把脚跟向后上方抬起（像用脚跟去够屁股），抬到无痛的最大幅度停2秒，慢放。要领：两侧膝盖保持并拢，不要为了让脚跟抬得更高而把大腿向前抬；应该感觉大腿后侧在发力。"},
                {"name": "提踵", "detail": "缓慢踮脚尖到最高，停1秒慢放", "sets": 2, "reps": "10–15次", "rest": "30秒", "note": "扶椅保持平衡", "source": "AAOS",
                 "guide": "扶椅背站立，双脚与肩同宽，缓慢踮起脚尖到最高点，停1秒，再用2–3秒慢慢落下。要领：身体直上直下不前后晃，重量均匀落在前脚掌上。强化小腿，帮助日常行走时脚踝和膝盖的稳定。"},
                {"name": "跪姿平板支撑", "detail": "前臂+膝盖着地，身体成直线", "sets": 2, "reps": "3次深呼吸", "rest": "30秒", "note": "Mayo新手版", "source": "Mayo Clinic",
                 "guide": "俯卧，前臂撑地、手肘在肩膀正下方，双膝着地（不是脚尖），把身体撑起到膝盖—髋—肩成一条直线。收紧腹部，想象手肘和膝盖互相靠近（实际不动），保持3次深呼吸。要领：不塌腰、不撅臀；Mayo给新手的起始版本就是跪姿，不要急于做脚尖版。"},
                {"name": "鸟狗式", "detail": "四点跪姿，对侧手脚伸展", "sets": 2, "reps": "5–8次每侧", "rest": "30秒", "note": "骨盆不歪", "source": "Mayo Clinic",
                 "guide": "四点跪姿：手在肩正下方、膝在髋正下方，背部放平。收紧腹部，先只把一条手臂向前平举，保持3次深呼吸后换边；再只向后伸直一条腿后换边；熟练后做对侧手脚同时伸展。要领：腰不塌、骨盆不左右歪，头顶到尾椎成一条线，动作越慢越好。这是Mayo核心库中训练躯干稳定、对腰背最友好的动作之一。"},
            ],
            "cooldown": [
                {"name": "站姿股四头肌拉伸", "detail": "扶墙拉脚踝，脚跟靠近臀部", "duration": "每侧30秒 × 2次", "source": "AAOS",
                 "guide": "扶墙站立，一侧手抓住同侧脚踝，轻轻把脚跟拉向臀部，双膝并拢，感到大腿前侧轻微牵拉即可，保持30秒后换边。要领：不要弓腰或扭转身体，拉伸不应该疼。"},
                {"name": "仰卧腘绳肌拉伸", "detail": "抱大腿后侧轻拉", "duration": "每侧30秒 × 2次", "source": "AAOS",
                 "guide": "仰卧，一腿屈膝踩地，另一腿抬起，双手抱在大腿后侧（不要压在膝盖关节上），轻轻把腿拉向胸口方向，感到大腿后侧牵拉即可，保持30秒后换边。抱不到可以套条毛巾在大腿上拉着。"},
                {"name": "面墙小腿拉伸", "detail": "一腿后伸脚跟踩地，髋向墙推", "duration": "每侧30秒 × 2次", "source": "AAOS",
                 "guide": "面对墙站立，前腿屈膝、后腿伸直且脚跟踩实地面，脚尖朝前，双手推墙，髋部缓慢向墙的方向推，感到后侧小腿和跟腱牵拉即可，保持30秒后换边。要领：后脚脚跟全程不离地，腰背不弓。"},
            ],
            "fallback": "所有动作组数减半，去掉扶椅半蹲；任何动作引起疼痛立即停止（AAOS原则：运动中不应感到疼痛）。",
        },
        "lower": {
            "title": "无器械下肢 + 核心",
            "duration": "40–50分钟",
            "rationale": "增强跑步和骑行所需的下肢力量与核心稳定。",
            "sources": [
                "AAOS（美国骨科医师学会）膝盖调理方案 orthoinfo.aaos.org/en/recovery/knee-conditioning-program/",
                "Mayo Clinic（梅奥诊所）核心力量动作库 mayoclinic.org/healthy-lifestyle/fitness/multimedia/core-strength/sls-20076575",
                "Mayo Clinic（梅奥诊所）基础拉伸指引 mayoclinic.org/healthy-lifestyle/fitness/in-depth/stretching/art-20546848",
                "ACSM（美国运动医学会）抗阻训练指南 acsm.org/resistance-training-guidelines-update-2026/",
            ],
            "warmup": [
                {"name": "原地踏步", "detail": "轻松节奏，身体微微发热", "duration": "3分钟", "source": "AAOS",
                 "guide": "站直，交替抬膝，双臂自然摆动，落地放轻。AAOS膝盖方案要求力量训练前做5–10分钟低冲击热身（走路或固定单车），目的是让关节和肌肉热起来，不是练强度。"},
                {"name": "动态热身", "detail": "髋绕环10次、扶墙腿部前后摆动每侧10次、原地交替抬膝20次", "duration": "5分钟", "source": "Mayo Clinic",
                 "guide": "髋关节绕环：双手叉腰，抬起一腿用髋带动大腿画大圈，顺逆时针各5次换边——髋是球窝关节，可以安全环绕（注意：膝盖是铰链关节，全程不做膝绕环）；扶墙腿部前后摆动每侧10次；原地交替抬膝20次。Mayo柔韧性指引建议用与正式训练相似的动态动作完成热身。"},
            ],
            "main": [
                {"name": "扶椅半蹲", "detail": "只下蹲约20–25厘米，不深蹲", "sets": 4, "reps": "15次", "rest": "60秒", "note": "重心在脚跟", "source": "AAOS",
                 "guide": "双脚与肩同宽站在椅背后，双手轻扶椅背。胸口抬起，像坐椅子一样缓慢下蹲约20–25厘米（AAOS半蹲标准约10英寸），重心放在脚后跟，停2–5秒，再推脚跟起身。要领：膝盖方向始终与脚尖一致、不内扣；不要蹲到大腿与地面平行——AAOS刻意用浅蹲控制髌骨压力；可徒手或抱水瓶增加一点负荷（ACSM抗阻指南：新手先求动作质量再求负荷）。"},
                {"name": "俯卧直腿抬高", "detail": "收紧臀部把整条腿慢抬慢放", "sets": 3, "reps": "10次每侧", "rest": "60秒", "note": "骨盆贴地不翻髋", "source": "AAOS",
                 "guide": "俯卧，头枕在小臂上，双腿伸直。收紧一侧臀部和大腿后侧，把整条腿向天花板方向缓慢抬起约15–20厘米，停5秒，慢放，休息2秒再做下一次。要领：骨盆全程贴地（可在髋下垫个小枕头），不要为了让腿抬得更高而翻髋；发力的感觉是臀部和大腿后侧，不是腰。这个动作替代原来后脚抬高的保加利亚分腿蹲——单腿深屈膝对新手膝盖压力太大。"},
                {"name": "臀桥", "detail": "顶峰夹臀停2秒，慢放", "sets": 3, "reps": "15次", "rest": "45秒", "note": "用臀发力不用腰", "source": "Mayo Clinic",
                 "guide": "仰卧屈膝，双脚踩地与髋同宽，脚跟离臀部约一脚掌。收紧腹部和臀部把髋向上顶，到肩—髋—膝成一条直线，顶峰夹紧臀部停2秒，再慢放。要领：发力的是臀部；如果腰酸说明在用腰代偿，减小幅度重新夹臀；顶起时肋骨不要外翻。"},
                {"name": "跪姿平板支撑", "detail": "前臂+膝盖着地，身体成直线", "sets": 3, "reps": "累计1分钟", "rest": "45秒", "note": "分次完成也 OK", "source": "Mayo Clinic",
                 "guide": "俯卧，前臂撑地、手肘在肩膀正下方，双膝着地（不是脚尖），把身体撑起到膝盖—髋—肩成一条直线，收紧腹部保持。累计1分钟可以分成2–3段完成（比如30秒+30秒）。要领：不塌腰、不撅臀；Mayo给新手的起始版本就是跪姿，核心力量上来后再考虑脚尖版。"},
                {"name": "超人式", "detail": "俯卧交替抬臂抬腿，慢速控制", "sets": 3, "reps": "5–8次每侧", "rest": "45秒", "note": "髋下垫枕护腰", "source": "Mayo Clinic",
                 "guide": "俯卧，髋下垫个小枕头或卷起的毛巾支撑腰部，额头可以垫叠起的毛巾。收紧腹部，先把一条手臂抬离地面，保持3次深呼吸，放下换边；再换成抬腿：一条腿抬离地面，保持3次深呼吸，换边。要领：动作慢、幅度小，只抬到不塌腰的高度。这是Mayo核心库中强化下背的动作，替代登山跑——对膝盖零冲击，也不会因为追求速度而塌腰。"},
            ],
            "cooldown": [
                {"name": "大腿前侧/后侧拉伸", "detail": "站姿股四头肌拉伸 + 仰卧腘绳肌拉伸，每侧30秒", "duration": "3分钟", "source": "AAOS",
                 "guide": "站姿股四头肌拉伸（AAOS膝盖方案）：扶墙，一手抓同侧脚踝把脚跟拉向臀部，双膝并拢不弓腰，每侧30秒；仰卧腘绳肌拉伸（AAOS）：仰卧抱大腿后侧轻拉，手不要压在膝盖关节上，每侧30秒。轻微牵拉即可，拉伸不应疼痛。"},
                {"name": "髋屈肌拉伸", "detail": "单膝跪姿前移重心", "duration": "2分钟", "source": "Mayo Clinic",
                 "guide": "单膝跪地（膝下垫毛巾），另一腿在前屈膝踩地，身体直立、收紧臀部，缓慢把重心向前移，感受跪地侧髋部前方的牵拉，每侧30秒×2（Mayo基础拉伸指引）。要领：不前倾弓腰，拉伸感轻到中度即可。"},
            ],
            "fallback": "扶椅半蹲组数减半，俯卧直腿抬高改为仰卧直腿抬高，跪姿平板每段20秒；任何动作引起疼痛立即停止（AAOS原则：运动中不应感到疼痛）。",
        },
        "upper": {
            "title": "无器械上肢 + 核心",
            "duration": "35–45分钟",
            "rationale": "改善上肢力量与躯干抗旋转稳定，帮助骑行姿势保持。",
            "sources": [
                "AAOS（美国骨科医师学会）肩袖与肩部调理方案 orthoinfo.aaos.org/en/recovery/rotator-cuff-and-shoulder-conditioning-program/",
                "Mayo Clinic（梅奥诊所）改良俯卧撑教学 mayoclinic.org/healthy-lifestyle/fitness/multimedia/modified-pushup/vid-20084674",
                "Mayo Clinic（梅奥诊所）弹力带俯身划船教学 mayoclinic.org/healthy-lifestyle/fitness/multimedia/bent-over-row/vid-20084668",
                "Mayo Clinic（梅奥诊所）核心力量动作库 mayoclinic.org/healthy-lifestyle/fitness/multimedia/core-strength/sls-20076575",
            ],
            "warmup": [
                {"name": "肩部钟摆摆动", "detail": "前倾扶稳，手臂放松下垂摆动", "duration": "3分钟", "source": "AAOS",
                 "guide": "身体前倾，一手扶桌或椅背，另一只手臂完全放松自然下垂，靠身体轻微晃动带动手臂摆动：前后10次、左右10次、画小圈10次，换边。要领：手臂像挂着的钟摆，不用力甩，背保持平不弓——这是AAOS肩部方案的标准热身动作，替代原来的手臂画圈，更放松、不会耸肩借力。"},
                {"name": "四点跪姿热身", "detail": "鸟狗式单臂、单腿交替伸展", "duration": "4分钟", "source": "Mayo Clinic",
                 "guide": "四点跪姿：手在肩正下方、膝在髋正下方，背部放平，收紧腹部。先只向前平举一条手臂，保持3次呼吸换边，各做3次；再只向后伸直一条腿，各做3次（Mayo核心库鸟狗式的分解版本）。要领：骨盆不歪、腰不塌，动作越慢越好——既唤醒核心，也让肩关节在承重下温和热身。"},
            ],
            "main": [
                {"name": "墙壁/跪姿俯卧撑", "detail": "身体成一直线，慢下快上", "sets": 4, "reps": "8–12次", "rest": "60秒", "note": "做不到就退回更直立的版本", "source": "Mayo Clinic",
                 "guide": "墙壁版（新手起步）：面对墙站立约一臂距离，双手撑墙与肩同宽同高，身体保持一条直线，屈肘让胸口缓慢靠近墙面，再推回；进阶跪姿版：双膝着地，双手撑地略宽于肩，身体从膝到肩一条直线，屈肘下放再推起。要领（Mayo改良俯卧撑教学）：全程收紧腹部不塌腰，肘部向后斜约45°，不贴身体也不横张；做不到8次就退回更直立的版本，动作质量优先。"},
                {"name": "弹力带俯身划船", "detail": "肘贴身体向后拉，肩胛骨互挤", "sets": 3, "reps": "10次", "rest": "60秒", "note": "没有弹力带可用装满水的水瓶", "source": "Mayo Clinic",
                 "guide": "双脚与肩同宽踩在弹力带中段，双手握两端、掌心相对，膝盖微屈、背部平直地前倾。缓慢把双肘向后拉，肘部贴着身体，感受两侧肩胛骨向中间挤（想象夹住一支笔），再缓慢放回。要领（Mayo弹力带划船教学）：不耸肩、不弓腰，拉的时候呼气。练上背——很多人只练胸前侧，Mayo强调肩部前后力量要平衡。"},
                {"name": "超人式", "detail": "俯卧交替抬臂抬腿", "sets": 3, "reps": "5–8次每侧", "rest": "60秒", "note": "髋下垫枕护腰", "source": "Mayo Clinic",
                 "guide": "俯卧，髋下垫小枕头支撑腰部，收紧腹部，先交替抬单臂、再交替抬单腿，每次保持3次深呼吸（Mayo核心库）。练下背耐力——长时间骑行握把需要下背持续发力。这个动作替代椅上臂屈伸：臂屈伸对肩关节前侧压力大，新手容易耸肩借力，对肩颈不友好。"},
                {"name": "侧平板支撑", "detail": "前臂撑地，髋部不塌陷", "sets": 3, "reps": "30秒每侧", "rest": "45秒", "note": "新手屈膝版", "source": "Mayo Clinic",
                 "guide": "侧卧，下方前臂撑地、手肘在肩膀正下方，双膝弯曲叠放（新手屈膝版），把髋部抬离地面到肩—髋—膝成一条直线，保持30秒换边。要领（Mayo核心库侧平板）：髋不向后倒、不塌陷，上方手臂叉腰；做不到30秒就从15秒开始分两次完成。"},
                {"name": "鸟狗式", "detail": "四点跪姿，对侧手脚同时伸展", "sets": 3, "reps": "5–8次每侧", "rest": "45秒", "note": "骨盆不歪", "source": "Mayo Clinic",
                 "guide": "四点跪姿：手在肩正下方、膝在髋正下方，背部放平，收紧腹部，同时向前伸右臂、向后伸左腿，保持3次深呼吸，收回换边。要领：想象背上放了一杯水不能洒——骨盆不歪、腰不塌。Mayo核心库强调先练好单臂、单腿版本再做对侧同时伸展；替代死虫式，与恢复日模板保持同一权威来源。"},
            ],
            "cooldown": [
                {"name": "交叉手臂拉伸", "detail": "手臂横过胸前轻拉", "duration": "3分钟", "source": "AAOS",
                 "guide": "一只手臂横过胸前，另一只手托住它的上臂（不要压肘关节），轻轻拉向身体，感到肩后侧轻微牵拉，保持30秒、放松30秒，换边（AAOS肩部方案）。要领：不耸肩、身体不跟着扭转。"},
                {"name": "毛巾辅助肩部拉伸", "detail": "背后拉毛巾，轻柔牵拉肩前侧", "duration": "2分钟", "source": "AAOS",
                 "guide": "一只手从背后上方抓住毛巾一端，另一只手从腰部后方抓住另一端，用上方的手轻轻拉动毛巾，让下方肩膀前侧感到轻柔牵拉，每侧30秒×2（AAOS肩部方案被动内旋拉伸的毛巾版）。要领：只拉到轻微牵拉感，拉伸不应疼痛。"},
            ],
            "fallback": "俯卧撑全部改墙壁版，划船次数减半，侧平板改15秒起步；任何动作引起疼痛立即停止（AAOS原则：运动中不应感到疼痛）。",
        },
    },
    "ride": {
        "recovery": {
            "title": "轻松骑行恢复",
            "duration": "35–50分钟",
            "rationale": "用低强度骑行促进下肢血流恢复，不增加神经疲劳。",
            "sources": [
                "Mayo Clinic（梅奥诊所）运动强度自测（说话测试） mayoclinic.org/healthy-lifestyle/fitness/in-depth/exercise-intensity/art-20046887",
                "Mayo Clinic（梅奥诊所）有氧运动如何热身与冷身 mayoclinic.org/healthy-lifestyle/fitness/in-depth/exercise/art-20045517",
                "ACSM（美国运动医学会）有氧运动强度指引 acsm.org/wp-content/uploads/2025/02/Exercise-intensity-infographic-PDF.pdf",
            ],
            "warmup": [
                {"name": "原地踏步 + 髋绕环", "detail": "原地踏步1分钟，髋绕环、腿部前后摆动各10次", "duration": "2分钟", "source": "AAOS",
                 "guide": "原地踏步1分钟让身体热起来；然后双手叉腰做髋关节绕环，顺逆时针各5次；再扶墙做腿部前后摆动每侧10次。要领：髋是球窝关节可以环绕；膝盖是铰链关节只能屈伸，不做任何膝绕环/膝环绕类旋转动作（旧版热身里的膝绕环已删除）。"},
                {"name": "轻松骑", "detail": "RPE 2分，轻齿比高踏频", "duration": "8分钟", "source": "Mayo Clinic",
                 "guide": "用轻齿比（踩起来不费力的档位）保持偏高的踏频（每分钟80圈左右），RPE 2分＝毫不费力。Mayo热身原则：用主项运动的低强度版本热身——骑行的热身就是慢慢骑，让腿部血流和关节温度逐步上来。"},
            ],
            "main": [
                {"name": "恢复骑", "detail": "平坦路，RPE 3分，踏频80–90，能完整聊天", "sets": 1, "reps": "25–35分钟", "rest": "无", "note": "不爬坡、不冲刺", "source": "Mayo Clinic",
                 "guide": "平坦路线，踏频80–90（看起来“踩得勤但不费劲”），用说话测试控制强度：能完整聊天就对了（Mayo/ACSM：中等强度＝能说话、不能唱歌）。姿势要领：坐垫高度调到脚踏在最低点时膝盖接近伸直但不锁死；手臂微屈、肩膀放松不耸肩；核心轻轻收住，体重不要全压在手把上。不爬坡、不冲刺，任何疼痛即停。"},
            ],
            "cooldown": [
                {"name": "轻松骑", "detail": "RPE 2分", "duration": "5分钟", "source": "Mayo Clinic",
                 "guide": "轻齿比慢骑5分钟，让心率平缓回落再下车（Mayo冷身原则：冷身帮助心率和血压逐渐恢复到运动前水平）。要领：踏频保持轻快、阻力放到最轻，等呼吸完全平稳再下车拉伸。"},
                {"name": "下肢拉伸", "detail": "股四头肌、腘绳肌、小腿每侧20秒", "duration": "3分钟", "source": "AAOS",
                 "guide": "站姿股四头肌拉伸（扶墙抓脚踝拉向臀部、双膝并拢）、仰卧腘绳肌拉伸（抱大腿后侧轻拉、手不压膝盖）、面墙小腿拉伸（后腿伸直脚跟不离地、髋向墙推），每侧20秒——均为AAOS膝盖方案动作。轻微牵拉即可，拉伸不应疼痛。"},
            ],
            "fallback": "改为室内骑行台20分钟或完全休息；任何疼痛即停。",
        },
        "easy": {
            "title": "有氧耐力骑行",
            "duration": "60–90分钟",
            "rationale": "积累低强度有氧时间，这是骑行能力的基础。",
            "sources": [
                "Mayo Clinic（梅奥诊所）运动强度自测（说话测试） mayoclinic.org/healthy-lifestyle/fitness/in-depth/exercise-intensity/art-20046887",
                "ACSM（美国运动医学会）身体活动指南常见问题（每周150–300分钟中等强度） acsm.org/physical-activity-guidelines-faqs/",
                "Mayo Clinic（梅奥诊所）有氧运动如何热身与冷身 mayoclinic.org/healthy-lifestyle/fitness/in-depth/exercise/art-20045517",
            ],
            "warmup": [
                {"name": "轻松骑", "detail": "RPE 2分", "duration": "10分钟", "source": "Mayo Clinic",
                 "guide": "轻齿比慢骑10分钟，毫不费力的强度（RPE 2分）。Mayo热身原则：用主项运动的低强度版本热身，让心率、血流和关节温度逐步上升。要领：踏频保持80圈左右，阻力宁轻勿重。"},
                {"name": "渐进加速", "detail": "每2分钟加一档，最后1分钟到RPE 4分", "duration": "5分钟", "source": "ACSM",
                 "guide": "每2分钟加一档齿比，让身体逐步接近今天的主项强度，最后1分钟达到RPE 4分（能说话不能唱歌）。要领：加的是齿比不是猛踩——踏频保持在80–90，用阻力调节强度，膝盖才不受冲击。"},
            ],
            "main": [
                {"name": "稳定有氧骑", "detail": "RPE 4分，踏频80–90，选择平坦或缓坡路线", "sets": 1, "reps": "45–75分钟", "rest": "无", "note": "全程能说话", "source": "ACSM",
                 "guide": "全程用说话测试维持中等强度（Mayo/ACSM：能说话、不能唱歌）。ACSM建议成人每周积累150–300分钟中等强度有氧——今天这一骑就是最大的积累来源。踏频80–90，选平坦或缓坡路线。每20分钟自检一次：肩膀有没有耸起来（放松下沉）？手指有没有麻（有就换一个握把位置）？膝盖有没有不适（有就减速收尾回家）？"},
            ],
            "cooldown": [
                {"name": "轻松骑", "detail": "RPE 2分", "duration": "10分钟", "source": "Mayo Clinic",
                 "guide": "轻齿比慢骑10分钟，让心率平缓回落再下车（Mayo冷身原则：冷身帮助心率和血压逐渐恢复到运动前水平）。要领：阻力放到最轻、踏频轻快，等呼吸完全平稳、腿部不再发烫再下车拉伸。"},
                {"name": "拉伸", "detail": "下肢全套", "duration": "5分钟", "source": "AAOS",
                 "guide": "站姿股四头肌拉伸、仰卧腘绳肌拉伸、面墙小腿拉伸（均AAOS膝盖方案）加跪姿髋屈肌拉伸，每侧20–30秒。要领：手不压膝盖关节、后脚跟不离地，拉伸不应疼痛。"},
            ],
            "fallback": "时间减半，改为45分钟轻松骑；任何疼痛即停。",
        },
        "tempo": {
            "title": "骑行节奏训练",
            "duration": "70–90分钟",
            "rationale": "用可控的中等强度提高有氧输出能力。",
            "sources": [
                "Mayo Clinic（梅奥诊所）运动强度自测（说话测试） mayoclinic.org/healthy-lifestyle/fitness/in-depth/exercise-intensity/art-20046887",
                "ACSM（美国运动医学会）有氧运动强度指引 acsm.org/wp-content/uploads/2025/02/Exercise-intensity-infographic-PDF.pdf",
                "Mayo Clinic（梅奥诊所）有氧运动如何热身与冷身 mayoclinic.org/healthy-lifestyle/fitness/in-depth/exercise/art-20045517",
            ],
            "warmup": [
                {"name": "轻松骑", "detail": "RPE 2分", "duration": "10分钟", "source": "Mayo Clinic",
                 "guide": "轻齿比慢骑10分钟，毫不费力的强度。Mayo热身原则：强度越高的训练，热身越不能省——用主项运动的低强度版本让身体逐步进入状态。要领：踏频保持80圈左右，身体微微出汗再进入渐进热身。"},
                {"name": "渐进热身", "detail": "2×3分钟 RPE 4–5分，组间2分钟轻松", "duration": "10分钟", "source": "ACSM",
                 "guide": "做2组3分钟的偏快节奏骑（RPE 4–5分：说话开始费劲），组间2分钟轻松骑。要领：这是让身体“预演”节奏段的强度，齿比逐步加重、踏频保持80–90，不要猛踩冲刺。"},
            ],
            "main": [
                {"name": "节奏骑", "detail": "RPE 6分，呼吸深但可控，选择平坦或缓上坡", "sets": 3, "reps": "8分钟", "rest": "4分钟轻松骑", "note": "保持踏频稳定", "source": "Mayo Clinic",
                 "guide": "RPE 6分：呼吸明显加深、只能说短句，但8分钟内节奏稳定可控（Mayo把“说几个字就要换气”归为较大强度，你要控制在比那略低一点）。保持踏频80–90，强度靠齿比调节，不靠猛踩猛冲；每组最后1分钟自检姿势：核心收紧、肩膀放松。如果第2组就维持不住踏频，说明强度高了，降一档。"},
                {"name": "稳定骑", "detail": "RPE 4分", "sets": 1, "reps": "15分钟", "rest": "无", "note": "衔接", "source": "ACSM",
                 "guide": "15分钟稳定骑衔接节奏段，用说话测试回到“能说话不能唱歌”的中等强度（Mayo/ACSM）。要领：踏频保持80–90、阻力放轻，让呼吸从节奏段的深度慢慢放缓，作为冷身前的过渡。"},
            ],
            "cooldown": [
                {"name": "轻松骑", "detail": "RPE 2分", "duration": "10分钟", "source": "Mayo Clinic",
                 "guide": "轻齿比慢骑10分钟，让心率平缓回落再下车（Mayo冷身原则：冷身帮助心率和血压逐渐恢复到运动前水平）。要领：阻力放到最轻、踏频轻快，等呼吸完全平稳、腿部不再发烫再下车拉伸。"},
                {"name": "拉伸", "detail": "下肢全套", "duration": "5分钟", "source": "AAOS",
                 "guide": "站姿股四头肌拉伸、仰卧腘绳肌拉伸、面墙小腿拉伸（均AAOS膝盖方案）加跪姿髋屈肌拉伸，每侧20–30秒。要领：手不压膝盖关节、后脚跟不离地，拉伸不应疼痛。"},
            ],
            "fallback": "节奏段改为2×6分钟，或改为有氧耐力骑；任何疼痛即停。",
        },
    },
    "rest": {
        "rest": {
            "title": "完全休息或主动恢复",
            "duration": "0–30分钟",
            "rationale": "每周至少一天完全休息，让身体真正恢复。",
            "sources": [
                "Mayo Clinic（梅奥诊所）步行健康指引 mayoclinic.org/healthy-lifestyle/fitness/in-depth/walking/art-20046261",
                "Mayo Clinic（梅奥诊所）柔韧性与拉伸指引（含泡沫轴） mayoclinic.org/healthy-lifestyle/fitness/in-depth/stretching/art-20047931",
                "Mayo Clinic（梅奥诊所）放松技术（深呼吸） mayoclinic.org/healthy-lifestyle/stress-management/basics/relaxation-techniques/hlv-20049495",
            ],
            "warmup": [
                {"name": "全身舒展", "detail": "原地踏步，然后肩、髋、踝依次活动", "duration": "2分钟", "source": "Mayo Clinic",
                 "guide": "先原地踏步30秒；然后肩膀前后各绕环5次（肩是球窝关节，可以环绕）；双手叉腰做髋关节绕环，顺逆各5次；坐姿或扶椅，脚尖离地做踝绕环每侧10次。注意：膝盖不做绕环——膝盖是铰链关节，只能前后屈伸，旋转类动作会给韧带和半月板带来剪切力。"},
            ],
            "main": [
                {"name": "散步", "detail": "户外慢走，RPE 1–2分", "sets": 1, "reps": "10–15分钟", "rest": "无", "note": "可选，不做也行", "source": "Mayo Clinic",
                 "guide": "户外慢走，抬头目视前方、肩膀放松、手臂自然摆动，落地从脚跟滚到前脚掌。Mayo步行指引：不必追求步数和速度，10分钟起步就有健康收益；今天唯一的目的是让身体“动起来但不出力”。"},
                {"name": "泡沫轴/拉伸", "detail": "大腿前侧、外侧、小腿各1分钟", "sets": 1, "reps": "10分钟", "rest": "无", "note": "可选", "source": "Mayo Clinic",
                 "guide": "有泡沫轴：把大腿前侧、外侧、小腿先后压在轴上，用体重缓慢来回滚动各1分钟，在特别紧的点停20–30秒（Mayo柔韧性指引把泡沫轴列为可选的放松方式）。没有泡沫轴就做三个静态拉伸替代：站姿股四头肌拉伸、仰卧腘绳肌拉伸、面墙小腿拉伸，每侧30秒。要领：滚动和拉伸都应该是“酸胀但舒服”，疼就减轻压力或停下。"},
            ],
            "cooldown": [
                {"name": "深呼吸放松", "detail": "腹式深呼吸 4 轮", "duration": "3分钟", "source": "Mayo Clinic",
                 "guide": "坐下或躺下，一只手放在腹部。用鼻子缓慢吸气4拍，感觉腹部把手顶起来（而不是胸口起伏），再用嘴缓慢呼气6拍，像吹凉一杯热茶，做4轮。Mayo放松技术：深慢的腹式呼吸能减慢心率、帮助身体从紧张状态切换到恢复状态，是主动恢复的一部分。"},
            ],
            "fallback": "如果今天特别累，直接躺平，不要有任何运动；任何疼痛即停。",
        },
    },
}


def _build_workout(
    *,
    readiness: str,
    sleep_severity: str,
    weekday: int,
    profile: dict[str, Any],
    recent_sport_types: list[str] | None = None,
) -> dict[str, Any]:
    """Pick a concrete, coach-style workout for today."""
    sport = _WEEKDAY_SPORT[weekday % 7]
    recent_sport_types = recent_sport_types or []

    severe_sleep = sleep_severity in {"严重不足", "明显不足"}

    if readiness == "恢复不足" and severe_sleep:
        # Sleep is critically low: prioritize rest above all else.
        sport = "rest"
        template_key = "rest"
        intensity_override = "恢复"
    elif readiness == "恢复不足":
        # Moderate sleep debt: active recovery within the scheduled sport.
        template_key = "recovery" if sport != "rest" else "rest"
        intensity_override = None
    elif readiness == "一般":
        # Still conservative: use easy template for the scheduled sport.
        if sport == "rest":
            template_key = "rest"
        else:
            template_key = "easy" if sport in {"swim", "run", "ride"} else "lower"
        intensity_override = None
    else:
        # Ready: follow the weekly plan with quality sessions.
        if sport == "rest":
            template_key = "rest"
        elif sport == "bodyweight":
            # Alternate lower/upper emphasis across the two bodyweight days.
            template_key = "upper" if weekday == 4 else "lower"
        else:
            # Swim/run/ride: mix easy and tempo across the week.
            # Mon swim=easy, Thu run=tempo, Sat ride=tempo (when ready)
            template_key = "tempo" if (sport, weekday) in {("run", 3), ("ride", 5)} else "easy"
        intensity_override = None

    library = _WORKOUT_LIBRARY.get(sport, _WORKOUT_LIBRARY["rest"])
    template = library.get(template_key, library.get("rest", {}))

    # Determine intensity label.
    if intensity_override:
        intensity = intensity_override
    elif template_key in {"recovery", "rest"}:
        intensity = "恢复"
    elif template_key == "tempo":
        intensity = "节奏"
    else:
        intensity = "低强度耐力"

    # Build human-readable steps for backwards compatibility and quick scanning.
    steps: list[str] = []
    for item in template.get("warmup", []):
        steps.append(f"热身 · {item['name']}：{item['detail']}（{item['duration']}）")
    for item in template.get("main", []):
        detail = f"{item['sets']}组 × {item['reps']}"
        if item.get("rest"):
            detail += f"，组间休息{item['rest']}"
        steps.append(f"主训练 · {item['name']}：{item['detail']}（{detail}）")
    for item in template.get("cooldown", []):
        steps.append(f"冷身 · {item['name']}：{item['detail']}（{item['duration']}）")

    return {
        "title": template.get("title", "休息"),
        "intensity": intensity,
        "duration": template.get("duration", "0分钟"),
        "readiness": readiness,
        "sport": sport,
        "template": template_key,
        "warmup": template.get("warmup", []),
        "main": template.get("main", []),
        "cooldown": template.get("cooldown", []),
        "fallback": template.get("fallback", ""),
        "steps": steps,
        "rationale": template.get("rationale", ""),
        "sources": template.get("sources", []),
        "stop_rule": "出现胸痛、异常气短、眩晕、心悸或明显不适应立即停止；持续异常应寻求医疗评估。",
    }


def _rotating_daily_menu(*, today: Any, protein_low: int | None, protein_target: str, carb_mode: str) -> dict[str, Any]:
    """Create a date-stable rotating menu, then adjust carbohydrate portions for today's workout."""
    variants = [
        # Week 1: classic combinations
        {"name":"鸡胸鱼虾搭配","breakfast":"鸡蛋3个 + 纯牛奶250毫升 + 干燕麦50克 + 苹果1个","breakfast_main":27.5,"breakfast_protein":"鸡蛋3个、纯牛奶250毫升","lunch":"去皮熟鸡胸肉","density":0.30,"minimum":100,"snack":"无糖高蛋白酸奶200克 + 蓝莓或草莓1份","snack_main":17.0,"snack_protein":"无糖高蛋白酸奶200克","dinner":"熟鱼虾160克","dinner_main":35.2,"carb":"rice","extra":" + 香蕉1根"},
        {"name":"牛肉鲜虾搭配","breakfast":"鸡蛋2个 + 无糖豆浆300毫升 + 全麦面包80克 + 橙子1个","breakfast_main":22.0,"breakfast_protein":"鸡蛋2个、无糖豆浆300毫升","lunch":"熟瘦牛肉","density":0.26,"minimum":120,"snack":"无糖高蛋白酸奶200克 + 苹果1个","snack_main":17.0,"snack_protein":"无糖高蛋白酸奶200克","dinner":"熟虾仁180克","dinner_main":39.6,"carb":"sweet_potato","extra":" + 香蕉1根"},
        {"name":"瘦猪肉豆腐搭配","breakfast":"无糖高蛋白酸奶250克 + 鸡蛋2个 + 干燕麦40克 + 蓝莓1份","breakfast_main":35.0,"breakfast_protein":"无糖高蛋白酸奶250克、鸡蛋2个","lunch":"熟瘦猪里脊","density":0.25,"minimum":110,"snack":"纯牛奶250毫升 + 猕猴桃1个","snack_main":8.0,"snack_protein":"纯牛奶250毫升","dinner":"北豆腐250克 + 熟虾仁100克","dinner_main":47.0,"carb":"mixed","extra":" + 香蕉1根"},
        {"name":"鱼肉鸡腿搭配","breakfast":"鸡蛋2个 + 纯牛奶250毫升 + 玉米1根 + 猕猴桃1个","breakfast_main":21.0,"breakfast_protein":"鸡蛋2个、纯牛奶250毫升","lunch":"熟鱼肉","density":0.22,"minimum":150,"snack":"无糖豆浆300毫升 + 香蕉1根","snack_main":9.0,"snack_protein":"无糖豆浆300毫升","dinner":"去皮熟鸡腿肉180克","dinner_main":45.0,"carb":"noodle_potato","extra":" + 全麦面包2片"},
        {"name":"鸡肉牛肉搭配","breakfast":"无糖高蛋白酸奶250克 + 干燕麦50克 + 香蕉1根","breakfast_main":22.0,"breakfast_protein":"无糖高蛋白酸奶250克","lunch":"去皮熟鸡胸肉","density":0.30,"minimum":110,"snack":"鸡蛋2个 + 橙子1个","snack_main":13.0,"snack_protein":"鸡蛋2个","dinner":"熟瘦牛肉170克","dinner_main":44.2,"carb":"rice_pumpkin","extra":" + 纯牛奶250毫升"},
        {"name":"猪里脊鱼肉搭配","breakfast":"鸡蛋2个 + 无糖豆浆300毫升 + 蒸红薯250克","breakfast_main":22.0,"breakfast_protein":"鸡蛋2个、无糖豆浆300毫升","lunch":"熟瘦猪里脊","density":0.25,"minimum":130,"snack":"纯牛奶250毫升 + 苹果1个","snack_main":8.0,"snack_protein":"纯牛奶250毫升","dinner":"熟鱼肉180克","dinner_main":39.6,"carb":"rice_corn","extra":" + 香蕉1根"},
        {"name":"鸡肉豆腐鲜虾搭配","breakfast":"鸡蛋3个 + 纯牛奶250毫升 + 全麦馒头100克 + 苹果1个","breakfast_main":27.5,"breakfast_protein":"鸡蛋3个、纯牛奶250毫升","lunch":"去皮熟鸡胸肉","density":0.30,"minimum":100,"snack":"无糖高蛋白酸奶200克 + 草莓1份","snack_main":17.0,"snack_protein":"无糖高蛋白酸奶200克","dinner":"北豆腐250克 + 熟虾仁100克","dinner_main":47.0,"carb":"mixed_potato","extra":" + 香蕉1根"},
        # Week 2: Sichuan-friendly and quick options
        {"name":"辣炒鸡胸搭配","breakfast":"鸡蛋2个 + 无糖豆浆300毫升 + 全麦馒头100克 + 小番茄1份","breakfast_main":22.0,"breakfast_protein":"鸡蛋2个、无糖豆浆300毫升","lunch":"去皮鸡胸肉（可青椒/洋葱快炒）","density":0.30,"minimum":110,"snack":"纯牛奶250毫升 + 核桃2个","snack_main":8.0,"snack_protein":"纯牛奶250毫升","dinner":"清蒸鱼180克（可淋少量花椒油）","dinner_main":39.6,"carb":"rice","extra":" + 香蕉1根"},
        {"name":"番茄牛肉搭配","breakfast":"无糖高蛋白酸奶250克 + 干燕麦40克 + 鸡蛋1个","breakfast_main":29.0,"breakfast_protein":"无糖高蛋白酸奶250克、鸡蛋1个","lunch":"番茄炖瘦牛肉","density":0.26,"minimum":130,"snack":"鸡蛋1个 + 苹果1个","snack_main":6.5,"snack_protein":"鸡蛋1个","dinner":"白灼虾200克 + 蒜泥醋汁","dinner_main":44.0,"carb":"sweet_potato","extra":" + 纯牛奶250毫升"},
        {"name":"快手鸡胸搭配","breakfast":"鸡蛋3个 + 纯牛奶250毫升 + 全麦面包80克","breakfast_main":27.5,"breakfast_protein":"鸡蛋3个、纯牛奶250毫升","lunch":"即食鸡胸150克 + 生菜","density":0.30,"minimum":100,"snack":"无糖高蛋白酸奶200克","snack_main":17.0,"snack_protein":"无糖高蛋白酸奶200克","dinner":"煎三文鱼160克","dinner_main":35.2,"carb":"mixed","extra":" + 香蕉1根"},
        {"name":"周末牛肉搭配","breakfast":"鸡蛋2个 + 无糖豆浆300毫升 + 蒸南瓜200克","breakfast_main":22.0,"breakfast_protein":"鸡蛋2个、无糖豆浆300毫升","lunch":"卤牛肉（少油）150克","density":0.26,"minimum":130,"snack":"纯牛奶250毫升 + 橙子1个","snack_main":8.0,"snack_protein":"纯牛奶250毫升","dinner":"烤鸡腿去皮180克","dinner_main":45.0,"carb":"rice_corn","extra":" + 香蕉1根"},
        {"name":"清淡鱼虾搭配","breakfast":"无糖高蛋白酸奶250克 + 干燕麦40克 + 猕猴桃1个","breakfast_main":22.0,"breakfast_protein":"无糖高蛋白酸奶250克","lunch":"清蒸鱼（鲈鱼/鳜鱼）180克","density":0.22,"minimum":160,"snack":"鸡蛋2个 + 小番茄1份","snack_main":13.0,"snack_protein":"鸡蛋2个","dinner":"熟虾仁200克 + 醋汁","dinner_main":44.0,"carb":"noodle_potato","extra":" + 纯牛奶250毫升"},
        {"name":"豆腐鸡蛋搭配","breakfast":"鸡蛋3个 + 纯牛奶250毫升 + 蒸红薯200克","breakfast_main":27.5,"breakfast_protein":"鸡蛋3个、纯牛奶250毫升","lunch":"北豆腐300克（可少量辣椒炒）","density":0.10,"minimum":300,"snack":"无糖高蛋白酸奶200克 + 蓝莓1份","snack_main":17.0,"snack_protein":"无糖高蛋白酸奶200克","dinner":"熟鸡胸150克","dinner_main":45.0,"carb":"mixed_potato","extra":" + 香蕉1根"},
        {"name":"猪里脊虾仁搭配","breakfast":"鸡蛋2个 + 无糖豆浆300毫升 + 全麦面包80克 + 苹果1个","breakfast_main":22.0,"breakfast_protein":"鸡蛋2个、无糖豆浆300毫升","lunch":"熟瘦猪里脊","density":0.25,"minimum":130,"snack":"纯牛奶250毫升 + 猕猴桃1个","snack_main":8.0,"snack_protein":"纯牛奶250毫升","dinner":"熟虾仁200克","dinner_main":44.0,"carb":"rice_pumpkin","extra":" + 香蕉1根"},
        {"name":"鸡腿牛肉搭配","breakfast":"无糖高蛋白酸奶250克 + 干燕麦50克 + 香蕉1根","breakfast_main":22.0,"breakfast_protein":"无糖高蛋白酸奶250克","lunch":"去皮熟鸡腿肉","density":0.25,"minimum":130,"snack":"鸡蛋2个 + 橙子1个","snack_main":13.0,"snack_protein":"鸡蛋2个","dinner":"熟瘦牛肉170克","dinner_main":44.2,"carb":"rice","extra":" + 纯牛奶250毫升"},
    ]
    carbs = {
        "rice":{"lunch":{"恢复/休息日":"熟米饭150克","轻松训练日":"熟米饭200克","质量训练日":"熟米饭250克"},"dinner":{"恢复/休息日":"熟米饭120克","轻松训练日":"熟米饭150克","质量训练日":"熟米饭250克"}},
        "sweet_potato":{"lunch":{"恢复/休息日":"蒸红薯250克","轻松训练日":"蒸红薯300克","质量训练日":"蒸红薯400克"},"dinner":{"恢复/休息日":"熟米饭120克","轻松训练日":"熟米饭170克","质量训练日":"熟米饭250克"}},
        "mixed":{"lunch":{"恢复/休息日":"熟杂粮饭150克","轻松训练日":"熟杂粮饭200克","质量训练日":"熟杂粮饭260克"},"dinner":{"恢复/休息日":"玉米1根","轻松训练日":"玉米1根 + 南瓜150克","质量训练日":"玉米1根 + 熟米饭150克"}},
        "noodle_potato":{"lunch":{"恢复/休息日":"熟荞麦面180克","轻松训练日":"熟荞麦面250克","质量训练日":"熟荞麦面320克"},"dinner":{"恢复/休息日":"蒸土豆200克","轻松训练日":"蒸土豆300克","质量训练日":"蒸土豆400克"}},
        "rice_pumpkin":{"lunch":{"恢复/休息日":"熟米饭150克","轻松训练日":"熟米饭200克","质量训练日":"熟米饭260克"},"dinner":{"恢复/休息日":"蒸南瓜300克","轻松训练日":"蒸红薯250克","质量训练日":"蒸红薯350克"}},
        "rice_corn":{"lunch":{"恢复/休息日":"熟米饭150克","轻松训练日":"熟米饭210克","质量训练日":"熟米饭270克"},"dinner":{"恢复/休息日":"玉米1根","轻松训练日":"玉米1根 + 南瓜150克","质量训练日":"玉米1根 + 熟米饭150克"}},
        "mixed_potato":{"lunch":{"恢复/休息日":"熟杂粮饭150克","轻松训练日":"熟杂粮饭200克","质量训练日":"熟杂粮饭260克"},"dinner":{"恢复/休息日":"蒸土豆200克","轻松训练日":"蒸土豆300克","质量训练日":"蒸土豆400克"}},
    }
    variant=variants[today.toordinal()%len(variants)]
    fixed=variant["breakfast_main"]+variant["snack_main"]+variant["dinner_main"]
    required=max(0.0,float(protein_low or 0)-fixed)
    lunch_g=max(variant["minimum"],ceil(required/variant["density"]/10)*10)
    lunch_protein=round(lunch_g*variant["density"])
    main_protein=round(fixed+lunch_g*variant["density"])
    portions=carbs[variant["carb"]]
    snack=variant["snack"]+(variant["extra"] if carb_mode=="质量训练日" else "")
    lunch_energy={"恢复/休息日":"约550–700千卡","轻松训练日":"约650–800千卡","质量训练日":"约750–900千卡"}[carb_mode]
    dinner_energy={"恢复/休息日":"约500–650千卡","轻松训练日":"约600–750千卡","质量训练日":"约750–950千卡"}[carb_mode]
    carb_reason={
        "恢复/休息日":"降低主食份量但保留蛋白质和蔬菜，避免恢复日变成跳餐日。",
        "轻松训练日":"用中等主食份量支持活动，同时维持温和热量缺口。",
        "质量训练日":"把更多碳水放在训练前后，优先保障输出和恢复。",
    }[carb_mode]
    daily_menu=[
        {"meal":"早餐","foods":variant["breakfast"],"estimate":"约450–620千卡；蛋白质约25–40克","why":"早餐先补蛋白质和高纤维主食，降低上午饥饿。"},
        {"meal":"午餐","foods":f"{portions['lunch'][carb_mode]} + {variant['lunch']}{lunch_g}克 + 蔬菜300克（约2拳） + 烹调油10克","estimate":f"{lunch_energy}；主要蛋白质约{lunch_protein}克","why":carb_reason},
        {"meal":"加餐","foods":snack,"estimate":("约180–290千卡" if carb_mode!="质量训练日" else "约260–380千卡；训练前后使用"),"why":("用于两餐间控制饥饿，不因为休息而省掉蛋白质。" if carb_mode!="质量训练日" else "训练前后补充易执行的碳水和蛋白质。")},
        {"meal":"晚餐","foods":f"{portions['dinner'][carb_mode]} + {variant['dinner']} + 蔬菜300克（约2拳） + 烹调油10克","estimate":f"{dinner_energy}；主要蛋白质约{round(variant['dinner_main'])}克","why":"补足全天蛋白质和蔬菜，主食份量继续跟随训练需求。"},
    ]
    protein_foods="、".join([variant["breakfast_protein"],f"{variant['lunch']}{lunch_g}克",variant["snack_protein"],variant["dinner"]])
    goal=(f"今日轮换为“{variant['name']}”：{protein_foods}。主要蛋白质食物合计约{main_protein}克蛋白质，覆盖{protein_target}的下限。" if protein_low else f"今日轮换为“{variant['name']}”。需要体重数据后才能校准具体蛋白质份量。")
    return {"menu_date":today.isoformat(),"menu_variant":variant["name"],"menu_mode":carb_mode,"today_food_goal":goal,"main_food_protein_g":main_protein if protein_low else None,"daily_menu":daily_menu}


def _nutrition_plan(body_result: dict[str, Any], nutrition: list[dict[str, Any]], workout: dict[str, Any], *, now: datetime, profile: dict[str, Any], sleep_context: dict[str, Any], metrics_context: dict[str, Any]) -> dict[str, Any]:
    weight = body_result.get("weight_average_kg") or body_result.get("latest_weight_kg")
    weight = float(weight) if weight else None
    protein_low = round(weight * 1.6) if weight else None; protein_high = round(weight * 2.0) if weight else None
    easy_carb_low = round(weight * 2.5) if weight else None; easy_carb_high = round(weight * 3.5) if weight else None
    hard_carb_low = round(weight * 4.0) if weight else None; hard_carb_high = round(weight * 6.0) if weight else None
    local_tz = now.astimezone().tzinfo; today = now.astimezone(local_tz).date(); window_start = today - timedelta(days=6)
    recent_nutrition: list[dict[str, Any]] = []; logged_dates: set[str] = set(); totals_by_date: dict[str, dict[str, float]] = {}; counts_by_date: dict[str, int] = {}
    for item in nutrition:
        eaten_at = _try_parse(item.get("eaten_at"))
        if eaten_at is None:
            try: logged_date = datetime.fromisoformat(str(item.get("eaten_at", ""))[:10]).date()
            except ValueError: continue
        else: logged_date = eaten_at.astimezone(local_tz).date()
        if not window_start <= logged_date <= today: continue
        recent_nutrition.append(item); date_key = logged_date.isoformat(); logged_dates.add(date_key); counts_by_date[date_key] = counts_by_date.get(date_key, 0) + 1
        totals = totals_by_date.setdefault(date_key, {"kcal": 0.0, "protein": 0.0, "carb": 0.0, "fat": 0.0})
        for output_key, input_key in (("kcal", "total_kcal"), ("protein", "protein_g"), ("carb", "carb_g"), ("fat", "fat_g")):
            value = _number(item.get(input_key))
            if value is not None and value >= 0: totals[output_key] += value
    logged_days = len(logged_dates); record_count = len(recent_nutrition); coverage_pct = round(logged_days / 7 * 100)
    if logged_days >= 5:
        logging_confidence = "高"; data_note = f"近7天饮食记录覆盖{logged_days}天，共{record_count}条；可以观察摄入与体重、恢复和训练的关系，但估算仍有误差。"
    elif logged_days >= 2:
        logging_confidence = "中"; data_note = f"近7天饮食记录覆盖{logged_days}天，共{record_count}条；可初步看餐次模式，尚不足以把体重变化归因于真实摄入。"
    else:
        logging_confidence = "低"; data_note = "近7天尚无连续饮食记录，只能制定起始目标，不能评价实际摄入。"
    kcal_days = [totals["kcal"] for key, totals in totals_by_date.items() if totals["kcal"] > 0 and counts_by_date.get(key, 0) >= 2]
    protein_days = [totals["protein"] for totals in totals_by_date.values() if totals["protein"] > 0]
    observed_intake = "没有足够的整日热量记录，暂不把已记录热量当成全天摄入。"
    if kcal_days: observed_intake = f"有{len(kcal_days)}天至少记录2餐，记录到的日均热量约{round(mean(kcal_days))}千卡；仍可能漏餐，只用于和体重趋势交叉核对。"
    if protein_days: observed_intake += f" 已记录日的蛋白质平均约{round(mean(protein_days))}克。"
    severe_sleep = sleep_context.get("severity") in {"严重不足", "明显不足"}
    rolling_change = body_result.get("weight_rolling_change_kg")
    trend_sufficient = body_result.get("weight_rolling_current_count", 0) >= 3 and body_result.get("weight_rolling_previous_count", 0) >= 3 and rolling_change is not None
    adjustment_reasons: list[str] = []
    if body_result.get("single_day_weight_spike") and severe_sleep:
        adjustment = "不因单日体重突变削减主食或跳餐；同时因睡眠明显不足，把今天热量缺口缩小到约0–200千卡。"
        adjustment_reasons.extend([body_result["daily_weight_signal"], sleep_context["signal"]])
    elif body_result.get("single_day_weight_spike"):
        adjustment = "保持原计划，不因单日体重突变削减主食或跳餐。"; adjustment_reasons.append(body_result["daily_weight_signal"])
    elif severe_sleep:
        adjustment = "今天把热量缺口缩小到约0–200千卡，优先规律吃饭、补水和恢复睡眠。"; adjustment_reasons.append(sleep_context["signal"])
    elif trend_sufficient and rolling_change < -0.5:
        adjustment = "减重速度可能偏快：今天比原计划加回约100–200千卡，优先放在蛋白质和训练前后碳水。"; adjustment_reasons.append(body_result["rolling_weight_signal"])
    elif trend_sufficient and rolling_change > 0.2 and logged_days >= 3:
        adjustment = "多日均值持续上升：未来7天只下调一个变量，每天减少约100–150千卡，不同时增加高强度训练。"; adjustment_reasons.extend([body_result["rolling_weight_signal"], f"饮食记录已覆盖{logged_days}天，可进行小幅、可复盘的调整。"])
    elif trend_sufficient and rolling_change > -0.15 and logged_days >= 5:
        adjustment = "多日均值接近平台：未来7天每天减少约100–150千卡，其他训练安排保持不变。"; adjustment_reasons.append(body_result["rolling_weight_signal"])
    elif trend_sufficient and -0.5 <= rolling_change <= -0.15:
        adjustment = "当前多日减重速度处于可接受范围，继续现有热量和训练安排，不追着单日数字调整。"; adjustment_reasons.append(body_result["rolling_weight_signal"])
    elif trend_sufficient and rolling_change >= -0.15 and logged_days < 3:
        adjustment = "先把饮食连续记录提高到至少3–5天，再决定减热量还是增加低强度活动。"; adjustment_reasons.append("体重趋势需要与实际饮食记录交叉验证，当前记录覆盖不足。")
    else:
        if trend_sufficient:
            adjustment = "体重多日趋势在可接受区间，保持现有热量和训练安排，继续观察7天。"; adjustment_reasons.append(body_result["rolling_weight_signal"])
        else:
            adjustment = "先执行温和热量缺口并连续观察7天；数据不足时不做激进调整。"; adjustment_reasons.append(body_result.get("rolling_weight_signal", "体重趋势数据不足。"))

    if workout.get("intensity") == "节奏": carb_mode, planned_training_kcal = "质量训练日", 200
    elif workout.get("intensity") == "低强度耐力": carb_mode, planned_training_kcal = "轻松训练日", 75
    else: carb_mode, planned_training_kcal = "恢复/休息日", 0
    bmr = _number(body_result.get("basal_metabolism_kcal")) or _mifflin_bmr(weight, profile)
    average_steps = _number(metrics_context.get("average_steps"))
    if average_steps is None: activity_factor = 1.4
    elif average_steps < 4000: activity_factor = 1.3
    elif average_steps < 7000: activity_factor = 1.4
    elif average_steps < 10000: activity_factor = 1.5
    else: activity_factor = 1.6
    if severe_sleep: deficit_low, deficit_high = 0, 200
    elif trend_sufficient and rolling_change < -0.5: deficit_low, deficit_high = 0, 150
    else: deficit_low, deficit_high = 250, 400
    energy_target = "需基础代谢或完整的性别、年龄、身高数据"; energy_target_detail = "当前不提供伪精确热量；先记录饮食和体重趋势。"
    if bmr is not None:
        estimated_tdee = bmr * activity_factor + planned_training_kcal
        target_low = max(1200, round((estimated_tdee - deficit_high) / 50) * 50)
        target_high = max(target_low, round((estimated_tdee - deficit_low) / 50) * 50)
        energy_target = f"约{target_low}–{target_high}千卡"
        energy_target_detail = f"起始估算使用基础代谢约{round(bmr)}千卡、近期活动系数{activity_factor:.1f}、今日{carb_mode}修正和{deficit_low}–{deficit_high}千卡缺口；最终仍以连续7–14天体重、睡眠、饥饿感和训练表现校准。"
    today_easy = workout.get("intensity") in {"恢复", "低强度耐力"}
    protein_target = f"{protein_low}–{protein_high}克/天" if protein_low else "需体重数据"
    protein_plain = (f"这里的{protein_target}指食物中所含的‘蛋白质营养素’，不是称{protein_low}–{protein_high}克食物。例如1个鸡蛋约含6–7克蛋白质；如果只靠鸡蛋达到{protein_low}克，约需{round(protein_low / 6.5)}个，不现实也不均衡，所以应由蛋、奶、鱼虾、瘦肉和豆制品共同完成。" if protein_low else "蛋白质目标指食物中所含的蛋白质营养素，不等于食物本身的重量。")
    if severe_sleep or workout.get("intensity") == "恢复":
        menu_carb_mode = "恢复/休息日"
    elif workout.get("intensity") == "低强度耐力":
        menu_carb_mode = "轻松训练日"
    else:
        menu_carb_mode = "质量训练日"
    menu_plan = _rotating_daily_menu(today=today, protein_low=protein_low, protein_target=protein_target, carb_mode=menu_carb_mode)
    today_food_goal = menu_plan["today_food_goal"]
    daily_menu = menu_plan["daily_menu"]
    if menu_carb_mode == "质量训练日":
        carb_target_today = f"{hard_carb_low}–{hard_carb_high}克/天" if hard_carb_low else "需体重数据"
        carb_target_today_label = "质量训练日碳水"
    else:
        carb_target_today = f"{easy_carb_low}–{easy_carb_high}克/天" if easy_carb_low else "需体重数据"
        carb_target_today_label = "今日碳水" if menu_carb_mode == "轻松训练日" else "休息日碳水"
    today_actions: list[str] = []
    if severe_sleep: today_actions.append(f"昨夜睡眠级别为{sleep_context.get('severity')}，今天取消高强度，按恢复/休息日份量吃")
    elif today_easy: today_actions.append("今天按轻松/恢复日安排主食，保持蛋白质，不用为减脂完全戒碳水")
    else: today_actions.append("今天有质量训练，训练前后增加主食以保障输出和恢复")
    if body_result.get("single_day_weight_spike"): today_actions.append("单日体重突变先按水分波动处理，不跳餐、不突然砍热量")
    today_actions.append(adjustment)
    return {
        "energy_strategy": "热量缺口、碳水和训练强度每天联动；蛋白质相对稳定，热量只根据多日趋势小幅调整。",
        "energy_reason": "单日体重会受水分、糖原、盐分、进食时间和排便影响。真正的调整依据是7–14天体重/体脂趋势、睡眠恢复、训练负荷、饥饿与表现，以及饮食记录覆盖度。",
        "energy_target": energy_target, "energy_target_detail": energy_target_detail, "adjustment": adjustment, "adjustment_reasons": adjustment_reasons, "observed_intake": observed_intake,
        "deficit_actions": ["先控制烹调油和含糖饮料，再考虑减少正餐；不要用跳餐补偿某一天体重上升。", "休息/轻松日用较小主食份量；质量课/长骑日把更多碳水放在训练前后。", "每次只改变一个变量并维持7天：每天少100–150千卡，或增加15–20分钟低强度活动，避免同时改变后无法判断原因。", "若睡眠明显不足、体重下降过快、持续饥饿或训练表现下降，优先缩小缺口而不是硬撑。"],
        "protein_target": protein_target, "protein_explanation": protein_plain, "protein_distribution": "分3–4餐完成，每餐约25–40克蛋白质；睡眠差或休息日也不应大幅削减蛋白质。",
        "protein_portions": ["鸡蛋1个：约6–7克蛋白质；3个约19–20克。", "熟鸡胸肉100克：约30克蛋白质；熟瘦牛肉100克：约25–27克。", "熟鱼虾100克：约20–24克蛋白质。", "纯牛奶250毫升：约8克蛋白质；无糖高蛋白酸奶200克通常约15–20克。", "北豆腐200克：约16–24克蛋白质。"],
        "carb_target_easy": f"{easy_carb_low}–{easy_carb_high}克/天" if easy_carb_low else "需体重数据", "carb_target_hard": f"{hard_carb_low}–{hard_carb_high}克/天" if hard_carb_low else "需体重数据",
        "carb_target_today": carb_target_today, "carb_target_today_label": carb_target_today_label,
        "carb_explanation": "碳水随当天训练和恢复变化：睡眠严重不足或休息日减少训练型加餐，但不因单日体重上升完全戒主食；质量课和长骑日前后增加。",
        "today": "；".join(today_actions), "today_food_goal": today_food_goal, "sample_day_total": f"{energy_target}；蛋白质{protein_target}", "daily_menu": daily_menu,
        "menu_date": menu_plan["menu_date"], "menu_variant": menu_plan["menu_variant"], "menu_mode": menu_plan["menu_mode"], "main_food_protein_g": menu_plan["main_food_protein_g"],
        "during_ride": ["60分钟以内轻松骑：通常喝水即可。", "60–150分钟：每小时补30–60克碳水化合物。", "超过150分钟：先从每小时60克开始练肠胃耐受。", "饮水先以每小时500–750毫升为起点；炎热、大汗时按个体出汗补电解质。"],
        "food_pattern": "保留喜欢的口味，优先量化烹调油、高脂配料、甜饮和主食份量；调整的是总量与训练时机，不是把某类食物永久禁掉。",
        "logged_days": logged_days, "record_count": record_count, "coverage_pct": coverage_pct, "logging_confidence": logging_confidence, "data_note": data_note,
    }


def _integrated_coaching(*, body_result: dict[str, Any], sleep_context: dict[str, Any], metrics_context: dict[str, Any], training: dict[str, Any], workout: dict[str, Any], nutrition_plan: dict[str, Any]) -> dict[str, Any]:
    severe_sleep = sleep_context.get("severity") in {"严重不足", "明显不足"}; rolling_change = body_result.get("weight_rolling_change_kg")
    if severe_sleep: status, headline = "恢复优先", "睡眠恢复不足，今天先降低训练强度，同时缩小热量缺口，而不是靠少吃和硬练补偿。"
    elif body_result.get("single_day_weight_spike"): status, headline = "观察波动", "体重单日大幅变化，今天保持计划并观察水分与多日均值，不做激进饮食调整。"
    elif rolling_change is not None and rolling_change < -0.5: status, headline = "防止减重过快", "体重趋势下降偏快，训练和饮食都应给恢复留余地。"
    elif rolling_change is not None and rolling_change > -0.1: status, headline = "小幅校准", "多日趋势接近平台或上升，只改变一个变量并观察7天。"
    else: status, headline = "稳步减脂", "当前按恢复状态决定训练、按训练决定碳水、按多日体重趋势决定热量微调。"
    body_signal = body_result.get("daily_weight_signal", "缺少体重数据。")
    if rolling_change is not None: body_signal += " " + body_result.get("rolling_weight_signal", "")
    activity_signal = f"近7天{training['minutes']}分钟运动，负荷比{training['load_ratio'] if training['load_ratio'] is not None else '暂无'}。"
    if metrics_context.get("average_steps") is not None: activity_signal += f" 近7日平均约{metrics_context['average_steps']}步。"
    inputs = [
        {"area": "睡眠", "signal": sleep_context["signal"], "impact": "决定今天是否允许质量训练，并影响热量缺口是否需要缩小。"},
        {"area": "体重与体脂", "signal": body_signal, "impact": "单日变化只作观察；连续7–14天趋势才触发热量调整。"},
        {"area": "运动与日常活动", "signal": activity_signal, "impact": "训练负荷决定今天训练刺激和碳水放置，而不是简单把运动热量全部吃回。"},
        {"area": "饮食记录", "signal": nutrition_plan["data_note"], "impact": "记录覆盖越完整，越能判断平台来自摄入、活动还是水分波动。"},
    ]
    recovery_action = ("今晚优先保证完整睡眠窗口，白天规律补水；若困倦明显可完全休息。" if severe_sleep else "保持规律睡眠窗口；若静息心率、精神状态或腿部感觉异常，临时把课表降为恢复。")
    linked_actions = [
        {"area": "运动", "action": f"{workout['title']}，{workout['duration']}。", "because": workout["rationale"]},
        {"area": "饮食", "action": nutrition_plan["today"], "because": "由睡眠恢复、今日训练类型、体重多日趋势和饮食记录覆盖度共同决定。"},
        {"area": "恢复", "action": recovery_action, "because": "恢复不足时继续加训练并扩大热量缺口，会同时影响训练质量、饥饿控制和次日体重波动。"},
        {"area": "测量", "action": "明早在相近时间、起床排空后、进食饮水前称重；继续记录睡眠、饮食和训练主观用力程度。", "because": "固定测量条件可以减少水分噪声，让后续调整基于趋势而不是偶然数字。"},
    ]
    if severe_sleep: experiment = "今天不是增加训练量或扩大热量缺口的实验日。唯一变量是恢复：取消高强度、正常吃蛋白质和三餐，今晚争取恢复睡眠。"
    elif body_result.get("single_day_weight_spike"): experiment = "未来3天保持热量和训练框架不变，只观察晨重、盐分/碳水、排便和睡眠；若均值仍上升，再做100–150千卡的小调整。"
    elif rolling_change is not None and rolling_change > -0.1:
        experiment = ("未来7天只执行一个变量：每天减少约100–150千卡，不同时增加高强度；第8天比较7日均重、睡眠和训练表现。" if nutrition_plan["logged_days"] >= 5 else "未来7天先提高饮食记录覆盖度，不同时改变热量和训练量；拿到至少3–5个完整日后再选择一个变量测试。")
    elif rolling_change is not None and rolling_change < -0.5: experiment = "未来7天每天加回约100–200千卡，并保持训练强度不增加；观察晨重均值、饥饿、睡眠和训练输出是否恢复。"
    else: experiment = "未来7天保持当前框架，只根据每天睡眠决定课表降级；第8天用7日均重、体脂趋势、饮食覆盖和训练完成度一起复盘。"
    available_domains = sum([sleep_context.get("count", 0) > 0, body_result.get("latest_weight_kg") is not None, training.get("activity_count", 0) > 0 or metrics_context.get("average_steps") is not None, nutrition_plan.get("logged_days", 0) >= 3])
    return {"status": status, "headline": headline, "confidence": "高" if available_domains == 4 else ("中" if available_domains >= 2 else "低"), "inputs": inputs, "linked_actions": linked_actions, "experiment": experiment, "next_review": "下次刷新时同时复核：昨夜睡眠、晨重及7日均值、体脂多日趋势、昨日/今日运动负荷、饮食记录覆盖和训练主观感受。", "connections": ["睡眠 → 训练：睡得越差，越先取消高强度。", "训练 → 饮食：质量课前后增加碳水，恢复日减少训练型加餐但保持蛋白质。", "体重趋势 → 热量：单日波动不改计划，多日平台才小幅减100–150千卡。", "饮食记录 → 决策置信度：记录不足时不武断归因，也不做大幅调整。"]}


def build_summary(
    activities: list[dict[str, Any]],
    sleep: list[dict[str, Any]],
    body: list[dict[str, Any]],
    daily_metrics: list[dict[str, Any]] | None = None,
    profile: dict[str, Any] | None = None,
    nutrition: list[dict[str, Any]] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    profile = profile or {}
    metrics = daily_metrics or []
    nutrition = nutrition or []
    week_start = now - timedelta(days=7)
    month_start = now - timedelta(days=28)

    dated_activities = [
        (started_at, item)
        for item in activities
        if (started_at := _try_parse(item.get("start_date"))) is not None
        and started_at <= now
    ]
    dated_activities.sort(key=lambda pair: pair[0], reverse=True)
    recent = [item for started_at, item in dated_activities if started_at >= week_start]
    month = [item for started_at, item in dated_activities if started_at >= month_start]

    total_minutes = round(sum(max(0.0, _number(item.get("moving_time")) or 0) for item in recent) / 60)
    total_distance_km = round(sum(max(0.0, _number(item.get("distance")) or 0) for item in recent) / 1000, 1)
    total_elevation = round(sum(max(0.0, _number(item.get("total_elevation_gain")) or 0) for item in recent))
    total_kj = round(sum(max(0.0, _number(item.get("kilojoules")) or 0) for item in recent))

    sleep_context = _sleep_context(sleep)
    metrics_context = _daily_metrics_context(metrics)
    observed_max_hr_values = [value for item in month if (value := _number(item.get("max_heartrate"))) is not None and value > 0]
    observed_max_hr = max(observed_max_hr_values) if observed_max_hr_values else None
    resting_values = [value for item in metrics[:14] if (value := _number(item.get("heart_rate_min"))) is not None and value >= 30]
    resting_hr = median(resting_values) if resting_values else None

    acute_load = 0.0
    month_load = 0.0
    buckets = {"低有氧": 0, "中高有氧": 0, "高强度": 0, "强度未校准": 0}
    for item in month:
        load, bucket = _activity_load(item, observed_max_hr, resting_hr)
        month_load += load
        if item in recent:
            acute_load += load
            buckets[bucket] += 1
    chronic_weekly = month_load / 4 if month else 0
    load_ratio = acute_load / chronic_weekly if chronic_weekly > 0 else None
    latest_activity_at = dated_activities[0][0] if dated_activities else None
    days_since = (now - latest_activity_at).total_seconds() / 86400 if latest_activity_at else None

    severe_sleep = sleep_context["severity"] in {"严重不足", "明显不足"}
    ordinary_sleep_debt = sleep_context["severity"] in {"不足", "累积不足"}
    high_load = load_ratio is not None and load_ratio > 1.5
    elevated_resting = (metrics_context.get("resting_hr_delta") or 0) >= 8
    high_stress = (metrics_context.get("latest_stress") or 0) >= 75
    low_recovery_reasons: list[str] = []
    if sleep_context.get("latest_hours") is not None and sleep_context["severity"] != "基本充足":
        low_recovery_reasons.append(sleep_context["signal"])
    if high_load:
        low_recovery_reasons.append("近7天训练负荷明显高于近4周周均")
    if elevated_resting:
        low_recovery_reasons.append(f"最新最低心率较近期基线高约{metrics_context['resting_hr_delta']}次/分")
    if high_stress:
        low_recovery_reasons.append(f"最新压力值{metrics_context['latest_stress']}，触发恢复降级")

    if severe_sleep:
        readiness = "恢复不足"
    elif ordinary_sleep_debt:
        readiness = "恢复不足"
    elif high_load or elevated_resting or high_stress or (days_since is not None and days_since < 2 and load_ratio is not None and load_ratio >= 1.1):
        readiness = "一般"
    else:
        readiness = "可训练"

    local_tz = now.astimezone().tzinfo
    weekday = now.astimezone(local_tz).weekday()
    recent_sport_types = [item.get("sport_type") for item in recent if item.get("sport_type")]
    workout = _build_workout(
        readiness=readiness,
        sleep_severity=sleep_context["severity"],
        weekday=weekday,
        profile=profile,
        recent_sport_types=recent_sport_types,
    )
    intensity = workout["intensity"]
    workout_title = workout["title"]
    duration = workout["duration"]
    workout_steps = workout["steps"]
    rationale = workout["rationale"]
    known_signals = low_recovery_reasons or ["睡眠、训练负荷、最低心率和压力数据未触发必须降级的规则"]
    decision_explanation = [
        "数据：" + "；".join(s.rstrip("。") for s in known_signals) + "。",
        f"判断：今日准备状态为{readiness}，因此训练定为{intensity}。",
        f"安排：{workout_title}，{duration}。",
        "联动：训练强度决定今天的碳水安排；睡眠和恢复状态决定热量缺口；体重只按多日趋势调整。",
    ]

    body_result = _body_analysis(body, profile, now)
    training_result = {
        "activity_count": len(recent),
        "minutes": total_minutes,
        "distance_km": total_distance_km,
        "elevation_m": total_elevation,
        "kilojoules": total_kj,
        "acute_load": round(acute_load),
        "chronic_weekly_load": round(chronic_weekly),
        "load_ratio": round(load_ratio, 2) if load_ratio is not None else None,
        "intensity_distribution": buckets,
    }
    nutrition_plan = _nutrition_plan(
        body_result,
        nutrition,
        workout,
        now=now,
        profile=profile,
        sleep_context=sleep_context,
        metrics_context=metrics_context,
    )
    daily_coaching = _integrated_coaching(
        body_result=body_result,
        sleep_context=sleep_context,
        metrics_context=metrics_context,
        training=training_result,
        workout=workout,
        nutrition_plan=nutrition_plan,
    )

    observations = [f"过去7天记录{len(recent)}段活动，共{total_minutes}分钟、{total_distance_km}公里、爬升{total_elevation}米。"]
    if total_kj:
        observations.append(f"功率计记录的机械功约{total_kj}千焦，仅用于比较骑行负荷，不直接等同于应吃回的热量。")
    observations.append(sleep_context["signal"])
    observations.append(body_result.get("daily_weight_signal", "缺少体重数据。"))
    if body_result.get("weight_rolling_change_kg") is not None:
        observations.append(body_result.get("rolling_weight_signal", ""))

    suggestions = [f"今日课表：{workout_title}，{duration}；{rationale}", nutrition_plan["today"]]
    if readiness == "恢复不足":
        suggestions.insert(0, "近期睡眠或恢复指标不足，今天不建议安排高强度训练。")

    gaps: list[str] = []
    if not profile.get("sex") or not profile.get("height_cm") or not profile.get("age"):
        gaps.append("用户档案不完整：性别、年龄、身高会影响体脂解释和能量估算。")
    if observed_max_hr is None:
        gaps.append("缺少可靠最大心率；当前不会生成心率区间。")
    else:
        gaps.append(f"最高记录心率{observed_max_hr:.0f}仅为历史观测值，不视为实验室测得最大心率。")
    gaps.append("缺少FTP（功能性阈值功率）/阈值功率测试，因此课表使用RPE（主观用力程度）和说话测试，不伪造功率区间。")
    if nutrition_plan["logged_days"] < 3:
        gaps.append("近7天饮食日志不足3天，无法可靠评价真实能量和营养摄入。")

    return {
        "period": "最近7天",
        "method_version": "本地数据驱动减脂顾问 v2（联动决策）",
        "training": training_result,
        "sleep": sleep_context,
        "daily_metrics": metrics_context,
        "readiness": {
            "status": readiness,
            "reasons": low_recovery_reasons or ["睡眠与近期训练负荷未触发降级规则"],
            "confidence": "中" if sleep_context["count"] and (activities or metrics) else "低",
        },
        "workout": workout,
        "decision_explanation": decision_explanation,
        "body_composition": body_result,
        "nutrition": nutrition_plan,
        "daily_coaching": daily_coaching,
        "weekly_framework": [
            "每周最多1次质量课，前提是昨夜睡眠、近期负荷、最低心率和主观状态均允许。",
            "每周2次低强度耐力或恢复活动，承担大部分训练时间。",
            "训练量通常每周只增加5%–10%；疲劳、睡眠差或表现下降时不增加。",
            "至少1天完全休息；每次实验只改一个变量并维持7天后复盘。",
        ],
        "observations": observations,
        "suggestions": suggestions,
        "data_gaps": gaps,
        "method_note": "综合睡眠、身体指标、运动与日常活动、饮食记录生成可解释建议；单日体重只作观察，多日趋势才触发小幅调整。",
        "glossary": [
            "RPE（主观用力程度）：用0–10分描述自己感觉有多累，0分为休息，10分为极限。",
            "FTP（功能性阈值功率）：约代表可持续接近1小时的最高平均骑行功率，需要专门测试，当前没有就不编造。",
            "肌糖原：储存在肌肉里的碳水化合物能量，训练时间长或强度高时会大量使用。",
            "热量缺口：一天摄入热量低于身体消耗；恢复不足时应缩小，而不是机械维持。",
        ],
        "disclaimer": "内容用于个人运动与体重管理，不作医疗诊断，也不替代医生、注册营养师或持证教练的个体化评估。",
    }
