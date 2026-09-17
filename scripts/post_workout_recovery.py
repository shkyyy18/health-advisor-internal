"""每日运动后放松提醒（Hypervolt 手搓引导页的配套机制）。

运行时机：计划任务 HealthAssistantPostWorkoutRelax，每天 21:55（在 21:40 每日同步之后）。
逻辑：查 health.db 里今天的 Strava 活动；有运动 -> 生成放松指导 md + Windows 通知；
没有运动 -> 静默退出（只记日志）。
"""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "data" / "health.db"
OUT_DIR = PROJECT_ROOT / "output" / "recovery"
LOG_DIR = PROJECT_ROOT / "logs"
TOAST_PS1 = PROJECT_ROOT / "scripts" / "show_toast.ps1"
PAGE_URL = os.getenv("HEALTH_RECOVERY_PAGE_URL", "http://127.0.0.1:8000/static/hypervolt.html")

# sport_type -> (页面流程 key, 流程名, 重点)
ROUTINE_MAP = {
    "ride": ("ride", "骑行后放松（约 10 分钟）", "股四头肌、臀部、小腿"),
    "run": ("run", "跑步后放松（约 9 分钟）", "小腿、股四头肌、足底"),
    "walk": ("run", "跑步/步行后放松（约 9 分钟）", "小腿、股四头肌、足底"),
    "swim": ("full", "全身通用放松（约 8 分钟）", "肩背、臀腿大肌群"),
    "weight": ("full", "全身通用放松（约 8 分钟）", "当天训练涉及的大肌群"),
    "workout": ("full", "全身通用放松（约 8 分钟）", "当天训练涉及的大肌群"),
    "full": ("full", "全身通用放松（约 8 分钟）", "大肌群轮一遍"),
}


def log(msg: str) -> None:
    LOG_DIR.mkdir(exist_ok=True)
    line = f"{datetime.now().isoformat(timespec='seconds')} {msg}\n"
    with open(LOG_DIR / "post_workout_recovery.log", "a", encoding="utf-8") as f:
        f.write(line)


def classify(sport_type: str) -> str:
    s = (sport_type or "").lower()
    if "ride" in s or "cycl" in s or "bike" in s:
        return "ride"
    if "run" in s or "trail" in s:
        return "run"
    if "walk" in s or "hike" in s:
        return "walk"
    if "swim" in s:
        return "swim"
    if "weight" in s or "strength" in s:
        return "weight"
    return "full"


def todays_activities() -> list[dict]:
    if not DB_PATH.exists():
        return []
    today = datetime.now().date().isoformat()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT name, sport_type, start_date, moving_time, distance, raw_json "
            "FROM activities ORDER BY start_date DESC LIMIT 50"
        ).fetchall()
    finally:
        conn.close()
    result = []
    for r in rows:
        # Strava raw_json 里 start_date_local 才是本地日期
        local = None
        try:
            local = json.loads(r["raw_json"]).get("start_date_local")
        except (json.JSONDecodeError, TypeError):
            pass
        date_str = (local or r["start_date"] or "")[:10]
        if date_str == today:
            result.append(dict(r))
    return result


def build_guide(acts: list[dict]) -> tuple[str, str]:
    """返回 (通知短文本, 指导 md 全文)。"""
    lines = [
        f"# {datetime.now().date().isoformat()} 运动后放松指导",
        "",
        "## 今日运动",
    ]
    keys = []
    for a in acts:
        minutes = round((a.get("moving_time") or 0) / 60)
        km = (a.get("distance") or 0) / 1000
        dist = f"、{km:.1f}km" if km >= 0.1 else ""
        lines.append(f"- {a['name']}（{a.get('sport_type') or '?'}，{minutes} 分钟{dist}）")
        keys.append(classify(a.get("sport_type") or ""))
    primary = max(set(keys), key=keys.count) if keys else "full"
    _, routine_name, focus = ROUTINE_MAP[primary]

    lines += [
        "",
        f"## 推荐流程：{routine_name}",
        "",
        f"- 重点部位：{focus}",
        f"- 打开放松引导页跟着做（手机 Chrome）：{PAGE_URL}",
        "- 蓝牙连接后可自动调档；连不上就用手动模式，按页面提示自己调档。",
        "",
        "## 安全提醒（每次都看）",
        "",
        "- 疼痛即停：出现任何尖锐疼痛立即停止。",
        "- 只打肌肉，避开骨头、关节、脊柱、颈前侧、膝盖正反面。",
        "- 每部位不超过 2 分钟，缓慢移动不要定点死压。",
        "- 有伤病或处于康复期时，请先咨询医疗专业人员；通用流程不能替代个体化康复方案。",
        "- 出处：Hyperice 官方使用指引 + ACSM 冷身原则 + Mayo Clinic 恢复指南。",
    ]
    total_min = sum(round((a.get("moving_time") or 0) / 60) for a in acts)
    toast = (
        f"今日运动 {total_min} 分钟。建议做「{routine_name}」，重点：{focus}。"
        f"打开 {PAGE_URL} 跟着引导做。"
    )
    return toast, "\n".join(lines) + "\n"


def notify(text: str) -> None:
    if not TOAST_PS1.exists():
        log(f"toast script missing: {TOAST_PS1}")
        return
    msg_file = LOG_DIR / "toast_message.txt"
    LOG_DIR.mkdir(exist_ok=True)
    msg_file.write_text(text, encoding="utf-8")
    subprocess.run(
        [
            "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
            "-WindowStyle", "Hidden", "-File", str(TOAST_PS1),
            "-MessageFile", str(msg_file),
        ],
        check=False,
        timeout=30,
    )


def main() -> int:
    acts = todays_activities()
    if not acts:
        log("no activity today, skip")
        return 0
    toast, guide = build_guide(acts)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"{datetime.now().date().isoformat()}_放松指导.md"
    out.write_text(guide, encoding="utf-8")
    log(f"guide written: {out} ({len(acts)} activities)")
    notify(toast)
    return 0


if __name__ == "__main__":
    sys.exit(main())
