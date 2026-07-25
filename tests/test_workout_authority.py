"""Workout library authority requirements (project memory section 1).

Every exercise in every template must carry a detailed guide and an
authoritative source (AAOS / Mayo Clinic / ACSM), every template must list
its sources, and knee-circling moves are banned (knee is a hinge joint).
"""
from __future__ import annotations

from app.analytics import _WORKOUT_LIBRARY

_ALLOWED_SOURCES = {"AAOS", "Mayo Clinic", "ACSM"}
_BANNED_TERMS = ("膝绕环", "膝环绕", "膝关节环绕")


def test_every_exercise_has_guide_and_authoritative_source():
    checked = 0
    for sport, templates in _WORKOUT_LIBRARY.items():
        for key, template in templates.items():
            assert template.get("sources"), f"{sport}/{key} 缺 sources 列表"
            for section in ("warmup", "main", "cooldown"):
                for item in template.get(section, []):
                    label = f"{sport}/{key}/{section}/{item['name']}"
                    assert item.get("guide"), f"{label} 缺 guide"
                    assert len(item["guide"]) >= 60, f"{label} guide 过短"
                    assert item.get("source") in _ALLOWED_SOURCES, (
                        f"{label} source 不是权威机构: {item.get('source')}"
                    )
                    checked += 1
    # 七个模板全部覆盖（含已迁移的 bodyweight/recovery）
    assert checked >= 60


def test_no_knee_circling_anywhere():
    """动作名称与 detail（处方字段）不得包含膝绕环类动作；guide 中允许以
    “膝盖是铰链关节、不做膝绕环”的告诫形式出现。"""
    for sport, templates in _WORKOUT_LIBRARY.items():
        for key, template in templates.items():
            for section in ("warmup", "main", "cooldown"):
                for item in template.get(section, []):
                    label = f"{sport}/{key}/{section}/{item['name']}"
                    for field in ("name", "detail", "note"):
                        text = item.get(field) or ""
                        for term in _BANNED_TERMS:
                            assert term not in text, f"{label} {field} 含禁用动作: {term}"


def test_cardio_prescription_unchanged():
    """swim/run/ride 各级别的时长处方不得因权威化迁移而改变。"""
    expected_durations = {
        ("swim", "recovery"): "30–40分钟",
        ("swim", "easy"): "40–50分钟",
        ("swim", "tempo"): "50–60分钟",
        ("run", "recovery"): "25–35分钟",
        ("run", "easy"): "35–45分钟",
        ("run", "tempo"): "45–55分钟",
        ("ride", "recovery"): "35–50分钟",
        ("ride", "easy"): "60–90分钟",
        ("ride", "tempo"): "70–90分钟",
        ("rest", "rest"): "0–30分钟",
    }
    for (sport, key), duration in expected_durations.items():
        assert _WORKOUT_LIBRARY[sport][key]["duration"] == duration
    # 主项组数与次数保持原处方
    assert _WORKOUT_LIBRARY["ride"]["recovery"]["main"][0]["reps"] == "25–35分钟"
    assert _WORKOUT_LIBRARY["run"]["tempo"]["main"][0]["reps"] == "6分钟"
    assert _WORKOUT_LIBRARY["swim"]["tempo"]["main"][0]["reps"] == "100米"
