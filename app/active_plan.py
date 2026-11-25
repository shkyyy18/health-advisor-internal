"""Local, explicitly reviewed advice supersedes legacy generated prescriptions."""
from __future__ import annotations

import json
from pathlib import Path

from app import db


def plan_directory() -> Path:
    return db.settings.database_path.parent / "current_plan"


def load_active_plan() -> dict | None:
    marker = plan_directory() / "state.json"
    if not marker.exists():
        return None
    try:
        value = json.loads(marker.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("Invalid plan state")
        return value
    except (OSError, ValueError):
        # A broken replacement must never silently restore a retired plan.
        return {"status": "方案文件待修复", "legacy_retired": True}


def reviewed_summary(snapshot: dict, plan: dict) -> dict:
    body = next(iter(snapshot.get("body") or []), {})
    return {
        "active_plan": True,
        "method_version": "health-first-2026-11-09",
        "status": plan.get("status", "待核验"),
        "reviewed_at": plan.get("reviewed_at"),
        "goal": "健康运动与日常生活",
        "legacy_retired": True,
        "body_composition": {
            "measured_at": body.get("measured_at"),
            "latest_weight_kg": body.get("weight_kg"),
            "latest_body_fat_pct": body.get("body_fat_pct"),
        },
        "readiness": {"status": "不自动评分：以症状及有效数据复核"},
        "sleep": {},
        "daily_coaching": {
            "status": plan.get("status", "待核验"),
            "headline": "旧方案已撤销，请查看重新评估报告。",
        },
        "nutrition": {
            **{
                "energy_target": "待体检及完整个人信息核验，不设置减脂热量缺口",
                "protein_target": "先采用普通均衡饮食，未设高蛋白目标",
                "data_note": "餐食记录与估算不是已经验证的实际摄入。",
            },
            **(plan.get("nutrition") if isinstance(plan.get("nutrition"), dict) else {}),
        },
        "data_gaps": plan.get("data_gaps", []),
    }

