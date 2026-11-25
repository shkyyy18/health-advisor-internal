import json

from fastapi.testclient import TestClient

from app import active_plan, main


def activate(text=None):
    folder = active_plan.plan_directory()
    folder.mkdir(parents=True)
    (folder / "state.json").write_text(
        text if text is not None else json.dumps({"status": "等待体检核验"}),
        encoding="utf-8",
    )
    (folder / "report.html").write_text(
        '<html lang="zh-CN"><h1>新的健康方案</h1></html>', encoding="utf-8"
    )


def test_active_plan_never_calls_retired_engine(monkeypatch):
    activate()

    def retired(*args, **kwargs):
        raise AssertionError("Retired engine must not be called")

    monkeypatch.setattr(main, "build_summary", retired)
    with TestClient(main.app) as client:
        response = client.get("/api/summary")
        assert response.status_code == 200
        assert response.json()["legacy_retired"] is True
        assert "workout" not in response.json()
        assert "stage_goal" not in response.json()["body_composition"]
        page = client.get("/")
        assert page.status_code == 410
        assert "网页看板已移除" in page.text
        assert page.headers["cache-control"] == "no-store"
        mobile = client.get("/mobile")
        assert mobile.status_code == 200
        assert "30秒手工记录" in mobile.text
        assert "今日联动教练" not in mobile.text
        assert "今天怎么吃" not in mobile.text


def test_corrupt_replacement_does_not_restore_old_advice(monkeypatch):
    activate("{")
    monkeypatch.setattr(main, "build_summary", lambda *args: (_ for _ in ()).throw(AssertionError()))
    with TestClient(main.app) as client:
        result = client.get("/api/summary")
        assert result.status_code == 200
        assert result.json()["status"] == "方案文件待修复"


def test_reviewed_medical_update_replaces_pending_nutrition_text():
    result = active_plan.reviewed_summary({}, {
        "status": "历史体检已核验",
        "nutrition": {"energy_target": "先记录实际摄入，不设置热量缺口"},
    })
    assert result["nutrition"]["energy_target"] == "先记录实际摄入，不设置热量缺口"
    assert result["nutrition"]["protein_target"]


def test_post_workout_retirement_prevents_old_notifications(tmp_path, monkeypatch):
    from scripts import post_workout_recovery as recovery
    folder = tmp_path / "current_plan"
    folder.mkdir()
    (folder / "state.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(recovery, "DB_PATH", tmp_path / "health.db")
    monkeypatch.setattr(recovery, "log", lambda message: None)
    monkeypatch.setattr(recovery, "todays_activities", lambda: (_ for _ in ()).throw(AssertionError()))
    assert recovery.main() == 0
