from __future__ import annotations
import asyncio
import json
from datetime import datetime, timedelta, timezone
from dataclasses import replace
from fastapi.testclient import TestClient
from app import db, main
from app.analytics import build_summary
from app.meal_analysis import _json_from_text

def test_concrete_nutrition_plan_explains_food_weight():
    body=[{"measured_at":"2026-07-07T08:00:00+08:00","weight_kg":74,"body_fat_pct":27}]
    nutrition=build_summary([],[],body,profile={"sex":"男"})["nutrition"]
    assert nutrition["protein_target"] == "118–148克/天"
    assert "鸡蛋" in nutrition["protein_explanation"]
    assert "约需18个" in nutrition["protein_explanation"]
    assert len(nutrition["daily_menu"]) == 4
    assert any("熟米饭200克" in item["foods"] for item in nutrition["daily_menu"])
    assert "鸡蛋3个" in nutrition["today_food_goal"]
    assert "达到118–148克/天的最低目标" in nutrition["today_food_goal"]
    assert "热量缺口" in nutrition["energy_strategy"]

def test_decision_explanation_is_data_to_reason_chain():
    result=build_summary([],[],[])
    assert len(result["decision_explanation"]) == 4
    assert result["decision_explanation"][0].startswith("数据：")
    assert result["decision_explanation"][1].startswith("判断：")
    assert any("RPE（" in item for item in result["glossary"])

def test_mobile_public_route_requires_basic_auth(monkeypatch):
    monkeypatch.setattr(main,"settings",replace(main.settings,strava_webhook_callback_url="https://health.example/webhooks/strava",mobile_access_password="secret"))
    client=TestClient(main.app)
    denied=client.get("/mobile",headers={"host":"health.example"})
    assert denied.status_code == 401
    allowed=client.get("/mobile",headers={"host":"health.example"},auth=("health","secret"))
    assert allowed.status_code == 200
    assert "拍照记录饮食" in allowed.text

def test_meal_upload_saves_ai_result(monkeypatch):
    fake={"summary":"一餐","foods":[],"meal_total":{"kcal_range":"500–600千卡","protein_g_range":"30–40克","carb_g_range":"50–60克","fat_g_range":"10–20克"},"good_points":[],"improvements":[],"science_reason":[],"next_meal":"鸡蛋2个","uncertainty":[],"confidence":"中"}
    async def analyze(*args,**kwargs): return fake
    saved=[]
    monkeypatch.setattr(main,"analyze_meal_photo",analyze)
    monkeypatch.setattr(main,"save_photo_nutrition",lambda *args: saved.append(args))
    client=TestClient(main.app)
    response=client.post("/api/meals/analyze",files={"image":("meal.jpg",b"abc","image/jpeg")},data={"meal_type":"午餐"})
    assert response.status_code == 200
    assert response.json()["analysis"]["next_meal"] == "鸡蛋2个"
    assert saved and saved[0][3]["total_kcal"] == 550

def test_json_fence_parser():
    assert _json_from_text('```json\n{"confidence":"中"}\n```')["confidence"] == "中"


def test_dashboard_renders_week_comparison_and_concrete_food_plan():
    body = [
        {"measured_at": "2026-07-10T08:00:00+08:00", "weight_kg": 74, "body_fat_pct": 27}
    ]
    summary = build_summary([], [], body, profile={"sex": "男"})
    html = main.templates.env.get_template("index.html").render(
        summary=summary, activities=[], connected=False
    )
    assert "最近一次体脂" in html
    assert "本周体重均值" in html
    assert "上周体脂均值" in html
    assert "近5次称重表" in html
    assert "<th>时间</th>" in html
    assert "<th>体脂率 (%)</th>" in html
    assert "<th>体重 (kg)</th>" in html
    assert "<th>去脂体重 (kg)</th>" in html
    assert "07-10 08:00" in html

def test_meal_upload_uses_lunch_when_meal_type_is_omitted(monkeypatch):
    fake = {
        "summary": "meal",
        "foods": [],
        "meal_total": {},
        "good_points": [],
        "improvements": [],
        "science_reason": [],
        "next_meal": "",
        "uncertainty": [],
        "confidence": "medium",
    }

    async def analyze(*args, **kwargs):
        return fake

    saved = []
    monkeypatch.setattr(main, "analyze_meal_photo", analyze)
    monkeypatch.setattr(main, "save_photo_nutrition", lambda *args: saved.append(args))
    response = TestClient(main.app).post(
        "/api/meals/analyze",
        files={"image": ("meal.jpg", b"abc", "image/jpeg")},
    )
    assert response.status_code == 200
    assert saved[0][1] == "午餐"


def test_quick_manual_meal_endpoint_saves_without_openai():
    eaten_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    response = TestClient(main.app).post(
        "/api/meals/quick",
        json={
            "eaten_at": eaten_at,
            "meal_type": "\u665a\u9910",
            "description": "\u719f\u7c73\u996d150\u514b\uff0c\u9c7c\u867e160\u514b\uff0c\u852c\u83dc300\u514b",
            "estimated_kcal": 680,
            "protein_g": 42,
            "confidence": "rough_estimate",
            "notes": "\u5916\u5356\u5c11\u6cb9",
        },
    )

    assert response.status_code == 200
    assert response.json()["source"] == "quick_manual"
    with db.connect() as connection:
        row = connection.execute(
            "SELECT * FROM nutrition_logs WHERE source='quick_manual'"
        ).fetchone()
    assert row["meal_type"] == "\u665a\u9910"
    assert row["total_kcal"] == 680
    metadata = json.loads(row["raw_json"])
    assert metadata["confidence"] == "rough_estimate"
    assert "\u9c7c\u867e" in metadata["description"]


def test_nutrition_summary_exposes_recent_logging_coverage():
    now = datetime.now(timezone.utc)
    nutrition = [
        {"eaten_at": now.isoformat(), "source": "quick_manual"},
        {"eaten_at": (now - timedelta(days=1)).isoformat(), "source": "photo_ai"},
        {"eaten_at": (now - timedelta(days=1, hours=2)).isoformat(), "source": "quick_manual"},
        {"eaten_at": (now - timedelta(days=10)).isoformat(), "source": "quick_manual"},
    ]

    result = build_summary([], [], [], nutrition=nutrition)["nutrition"]

    assert result["logged_days"] == 2
    assert result["record_count"] == 3
    assert result["coverage_pct"] == 29
    assert result["logging_confidence"] == "\u4e2d"
