from datetime import date, datetime, timedelta

from fastapi.testclient import TestClient

from app import main
from app.analytics import _build_workout, _rotating_daily_menu


def test_rest_day_with_fair_readiness_gets_recovery_label():
    # Wednesday is a scheduled rest day; it must not be tagged as endurance training.
    workout = _build_workout(readiness="一般", sleep_severity="基本充足", weekday=2, profile={})
    assert workout["sport"] == "rest"
    assert workout["template"] == "rest"
    assert workout["intensity"] == "恢复"


def test_low_readiness_keeps_recovery_label_and_nutrition_mode():
    workout = _build_workout(readiness="恢复不足", sleep_severity="不足", weekday=1, profile={})
    assert workout["sport"] == "swim"
    assert workout["template"] == "recovery"
    assert workout["intensity"] == "恢复"


def test_quick_meal_naive_eaten_at_is_saved_as_local_time():
    # The dashboard's datetime-local input submits a naive timestamp;
    # it must be interpreted as local time, not UTC.
    response = TestClient(main.app).post(
        "/api/meals/quick",
        json={"eaten_at": "2026-07-19T20:30:00", "meal_type": "晚餐", "description": "测试餐"},
    )
    assert response.status_code == 200
    saved = datetime.fromisoformat(response.json()["eaten_at"])
    assert saved.tzinfo is not None
    assert saved.utcoffset() == datetime.now().astimezone().utcoffset()
    assert (saved.hour, saved.minute) == (20, 30)


def test_tofu_egg_variant_meets_protein_floor():
    menu = None
    for offset in range(16):
        candidate = date(2026, 7, 1) + timedelta(days=offset)
        result = _rotating_daily_menu(
            today=candidate,
            protein_low=118,
            protein_target="118–148克/天",
            carb_mode="轻松训练日",
        )
        if result["menu_variant"] == "豆腐鸡蛋搭配":
            menu = result
            break
    assert menu is not None
    assert menu["main_food_protein_g"] >= 118
