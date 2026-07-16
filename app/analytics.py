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

    reference_tz = _parse(str(latest["measured_at"])).tzinfo if latest else timezone.utc
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
    return {"latest_date": latest.get("metric_date"), "latest_steps": round(_number(latest.get("steps")) or 0) if latest else None, "average_steps": round(mean(steps)) if steps else None, "average_active_minutes": round(mean(active_minutes)) if active_minutes else None, "average_active_calories": round(mean(active_calories)) if active_calories else None, "latest_resting_hr": round(latest_resting) if latest_resting is not None else None, "resting_baseline_hr": round(resting_baseline) if resting_baseline is not None else None, "resting_hr_delta": round(resting_delta) if resting_delta is not None else None, "latest_stress": round(latest_stress) if latest_stress is not None else None}


def _mifflin_bmr(weight: float | None, profile: dict[str, Any]) -> float | None:
    height = _number(profile.get("height_cm")); age = _number(profile.get("age")); sex = profile.get("sex")
    if weight is None or height is None or age is None or sex not in {"男", "女"}:
        return None
    return 10 * weight + 6.25 * height - 5 * age + (5 if sex == "男" else -161)


def _rotating_daily_menu(*, today: Any, protein_low: int | None, protein_target: str, carb_mode: str) -> dict[str, Any]:
    """Create a date-stable rotating menu, then adjust carbohydrate portions for today's workout."""
    variants = [
        {"name":"鸡胸鱼虾搭配","breakfast":"鸡蛋3个 + 纯牛奶250毫升 + 干燕麦50克 + 苹果1个","breakfast_main":27.5,"breakfast_protein":"鸡蛋3个、纯牛奶250毫升","lunch":"去皮熟鸡胸肉","density":0.30,"minimum":100,"snack":"无糖高蛋白酸奶200克 + 蓝莓或草莓1份","snack_main":17.0,"snack_protein":"无糖高蛋白酸奶200克","dinner":"熟鱼虾160克","dinner_main":35.2,"carb":"rice","extra":" + 香蕉1根"},
        {"name":"牛肉鲜虾搭配","breakfast":"鸡蛋2个 + 无糖豆浆300毫升 + 全麦面包80克 + 橙子1个","breakfast_main":22.0,"breakfast_protein":"鸡蛋2个、无糖豆浆300毫升","lunch":"熟瘦牛肉","density":0.26,"minimum":120,"snack":"无糖高蛋白酸奶200克 + 苹果1个","snack_main":17.0,"snack_protein":"无糖高蛋白酸奶200克","dinner":"熟虾仁180克","dinner_main":39.6,"carb":"sweet_potato","extra":" + 香蕉1根"},
        {"name":"瘦猪肉豆腐搭配","breakfast":"无糖高蛋白酸奶250克 + 鸡蛋2个 + 干燕麦40克 + 蓝莓1份","breakfast_main":35.0,"breakfast_protein":"无糖高蛋白酸奶250克、鸡蛋2个","lunch":"熟瘦猪里脊","density":0.25,"minimum":110,"snack":"纯牛奶250毫升 + 猕猴桃1个","snack_main":8.0,"snack_protein":"纯牛奶250毫升","dinner":"北豆腐250克 + 熟虾仁100克","dinner_main":47.0,"carb":"mixed","extra":" + 香蕉1根"},
        {"name":"鱼肉鸡腿搭配","breakfast":"鸡蛋2个 + 纯牛奶250毫升 + 玉米1根 + 猕猴桃1个","breakfast_main":21.0,"breakfast_protein":"鸡蛋2个、纯牛奶250毫升","lunch":"熟鱼肉","density":0.22,"minimum":150,"snack":"无糖豆浆300毫升 + 香蕉1根","snack_main":9.0,"snack_protein":"无糖豆浆300毫升","dinner":"去皮熟鸡腿肉180克","dinner_main":45.0,"carb":"noodle_potato","extra":" + 全麦面包2片"},
        {"name":"鸡肉牛肉搭配","breakfast":"无糖高蛋白酸奶250克 + 干燕麦50克 + 香蕉1根","breakfast_main":22.0,"breakfast_protein":"无糖高蛋白酸奶250克","lunch":"去皮熟鸡胸肉","density":0.30,"minimum":110,"snack":"鸡蛋2个 + 橙子1个","snack_main":13.0,"snack_protein":"鸡蛋2个","dinner":"熟瘦牛肉170克","dinner_main":44.2,"carb":"rice_pumpkin","extra":" + 纯牛奶250毫升"},
        {"name":"猪里脊鱼肉搭配","breakfast":"鸡蛋2个 + 无糖豆浆300毫升 + 蒸红薯250克","breakfast_main":22.0,"breakfast_protein":"鸡蛋2个、无糖豆浆300毫升","lunch":"熟瘦猪里脊","density":0.25,"minimum":130,"snack":"纯牛奶250毫升 + 苹果1个","snack_main":8.0,"snack_protein":"纯牛奶250毫升","dinner":"熟鱼肉180克","dinner_main":39.6,"carb":"rice_corn","extra":" + 香蕉1根"},
        {"name":"鸡肉豆腐鲜虾搭配","breakfast":"鸡蛋3个 + 纯牛奶250毫升 + 全麦馒头100克 + 苹果1个","breakfast_main":27.5,"breakfast_protein":"鸡蛋3个、纯牛奶250毫升","lunch":"去皮熟鸡胸肉","density":0.30,"minimum":100,"snack":"无糖高蛋白酸奶200克 + 草莓1份","snack_main":17.0,"snack_protein":"无糖高蛋白酸奶200克","dinner":"北豆腐250克 + 熟虾仁100克","dinner_main":47.0,"carb":"mixed_potato","extra":" + 香蕉1根"},
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
    elif trend_sufficient and rolling_change > -0.1 and logged_days >= 5:
        adjustment = "多日均值接近平台：未来7天每天减少约100–150千卡，其他训练安排保持不变。"; adjustment_reasons.append(body_result["rolling_weight_signal"])
    elif trend_sufficient and -0.5 <= rolling_change <= -0.15:
        adjustment = "当前多日减重速度处于可接受范围，继续现有热量和训练安排，不追着单日数字调整。"; adjustment_reasons.append(body_result["rolling_weight_signal"])
    elif trend_sufficient and rolling_change >= -0.1 and logged_days < 3:
        adjustment = "先把饮食连续记录提高到至少3–5天，再决定减热量还是增加低强度活动。"; adjustment_reasons.append("体重趋势需要与实际饮食记录交叉验证，当前记录覆盖不足。")
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
        intensity = "恢复"
        workout_title = "补觉优先：完全休息或轻松散步"
        duration = "0–30分钟"
        workout_steps = [
            "首选完全休息并补足睡眠，不用训练补偿进度。",
            "若白天精神尚可，仅做10–30分钟轻松散步或舒缓活动，RPE 1–2分。",
            "取消间歇、节奏、长距离和大重量力量训练；不要用咖啡因硬顶高强度。",
        ]
        rationale = "昨夜睡眠严重不足时，训练、饮食和恢复必须一起降级：保留正常三餐与蛋白质，缩小热量缺口，把恢复放在首位。"
    elif ordinary_sleep_debt:
        readiness = "恢复不足"
        intensity = "低强度耐力"
        workout_title = "低强度耐力 + 技术练习"
        duration = "30–60分钟"
        workout_steps = [
            "热身10分钟，RPE 2–3分。",
            "主训练20–40分钟，RPE 3–4分，全程能完整说句子，不追速度或爬坡输出。",
            "冷身5–10分钟；若困倦、腿沉或心率异常，提前结束并休息。",
        ]
        rationale = "睡眠不足但未到极端程度，今天只保留低强度活动，避免高强度继续放大恢复压力。"
    elif high_load or elevated_resting or high_stress or (days_since is not None and days_since < 2 and load_ratio is not None and load_ratio >= 1.1):
        readiness = "一般"
        intensity = "恢复"
        workout_title = "恢复骑、轻松散步或完全休息"
        duration = "0–45分钟"
        workout_steps = [
            "任选20–45分钟非常轻松活动，RPE 2分，全程可自然交谈。",
            "避免爬坡发力、冲刺、节奏段和大重量力量训练。",
            "若精神疲惫、静息心率仍偏高或双腿沉重，直接休息。",
        ]
        rationale = "训练负荷、静息心率或压力信号提示恢复需求，今天不继续叠加刺激。"
    else:
        readiness = "可训练"
        intensity = "节奏"
        workout_title = "有氧节奏能力"
        duration = "50–70分钟"
        workout_steps = [
            "热身15分钟，最后加入3×30秒高踏频，组间轻松60秒。",
            "主训练3×8分钟，RPE 6分、呼吸加深但可说短句，组间轻松4分钟。",
            "随后10–20分钟轻松耐力活动并冷身；若第二组已无法稳定完成，取消第三组。",
        ]
        rationale = "当前睡眠、近期负荷和恢复代理指标未触发降级，可安排一次受控的中等偏上有氧刺激。"

    workout = {
        "title": workout_title,
        "intensity": intensity,
        "duration": duration,
        "readiness": readiness,
        "steps": workout_steps,
        "rationale": rationale,
        "stop_rule": "出现胸痛、异常气短、眩晕、心悸或明显不适应立即停止；持续异常应寻求医疗评估。",
    }
    known_signals = low_recovery_reasons or ["睡眠、训练负荷、最低心率和压力数据未触发必须降级的规则"]
    decision_explanation = [
        "数据：" + "；".join(known_signals) + "。",
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
