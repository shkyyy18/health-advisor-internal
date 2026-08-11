# 导出健康数据摘要，供云端 Kimi 健康顾问使用。
# 由计划任务每周自动运行，输出到桌面「健康顾问-云端复刻」文件夹。
# 手动运行：python scripts/export_cloud_digest.py
import os
import re
import sqlite3
import sys
from datetime import date

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(BASE, "data", "health.db")
DEST = os.path.join(
    os.environ["USERPROFILE"], "Desktop", "健康顾问-云端复刻", "健康数据摘要.md"
)


def main() -> None:
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    out = []
    A = out.append

    A("# 健康数据摘要（供云端健康顾问使用）")
    A(f"\n导出日期：{date.today()}　来源：本地健康看板 health.db\n")

    p = con.execute(
        "select * from user_profile order by updated_at desc limit 1"
    ).fetchone()
    if p:
        A("## 用户档案")
        A(f"- 性别：{p['sex']}　年龄：{p['age']}　身高：{p['height_cm']} cm")
        A(f"- 训练目标：{p['training_goal']}")
        A(f"- 目标体脂率：{p['target_body_fat_low']}%~{p['target_body_fat_high']}%")
        if p["food_preferences"]:
            A(f"- 饮食偏好：{p['food_preferences']}")
        A("")

    rows = con.execute(
        "select measured_at, weight_kg, body_fat_pct, muscle_kg "
        "from body_measurements where weight_kg is not null order by measured_at"
    ).fetchall()
    if rows:
        A(f"## 体重与体脂（共 {len(rows)} 次测量）")
        first, last = rows[0], rows[-1]
        A(
            f"- 最早：{first['measured_at'][:10]}　{first['weight_kg']} kg"
            + (f"，体脂 {first['body_fat_pct']}%" if first["body_fat_pct"] else "")
        )
        A(
            f"- 最新：{last['measured_at'][:10]}　{last['weight_kg']} kg"
            + (f"，体脂 {last['body_fat_pct']}%" if last["body_fat_pct"] else "")
        )
        recent = rows[-30:]
        ws = [r["weight_kg"] for r in recent]
        A(f"- 近 {len(recent)} 次均值：{sum(ws)/len(ws):.1f} kg（区间 {min(ws)}~{max(ws)}）")
        A("- 最近 10 次明细：")
        for r in rows[-10:]:
            line = f"  - {r['measured_at'][:10]}：{r['weight_kg']} kg"
            if r["body_fat_pct"]:
                line += f"，体脂 {r['body_fat_pct']}%"
            if r["muscle_kg"]:
                line += f"，肌肉 {r['muscle_kg']} kg"
            A(line)
        A("")

    dm = con.execute(
        "select metric_date, steps, calories, active_minutes, heart_rate_avg "
        "from daily_metrics order by metric_date desc limit 30"
    ).fetchall()
    if dm:
        A(f"## 日常活动（最近 {len(dm)} 天）")
        steps = [r["steps"] for r in dm if r["steps"]]
        if steps:
            A(f"- 日均步数：{int(sum(steps)/len(steps))}（最高 {max(steps)}，最低 {min(steps)}）")
        hr = [r["heart_rate_avg"] for r in dm if r["heart_rate_avg"]]
        if hr:
            A(f"- 平均心率：{int(sum(hr)/len(hr))} bpm")
        A("- 最近 7 天明细：")
        for r in dm[:7]:
            kcal = f"{r['calories']:.0f}" if r["calories"] else "-"
            A(
                f"  - {r['metric_date']}：{r['steps'] or '-'} 步，{kcal} kcal，"
                f"活动 {r['active_minutes'] or '-'} 分钟"
            )
        A("")

    sl = con.execute(
        "select sleep_date, duration_minutes, deep_minutes, rem_minutes "
        "from sleep_summaries order by sleep_date desc limit 30"
    ).fetchall()
    if sl:
        A(f"## 睡眠（最近 {len(sl)} 晚）")
        dur = [r["duration_minutes"] for r in sl if r["duration_minutes"]]
        if dur:
            A(f"- 平均时长：{sum(dur)/len(dur)/60:.1f} 小时")
        deep = [r["deep_minutes"] for r in sl if r["deep_minutes"]]
        if deep:
            A(f"- 平均深睡：{int(sum(deep)/len(deep))} 分钟")
        A("- 最近 7 晚明细：")
        for r in sl[:7]:
            h = f"{r['duration_minutes']/60:.1f}h" if r["duration_minutes"] else "-"
            A(f"  - {r['sleep_date']}：{h}（深睡 {r['deep_minutes'] or '-'} 分，REM {r['rem_minutes'] or '-'} 分）")
        A("")

    acts = con.execute(
        "select start_date, name, sport_type, distance, moving_time, average_heartrate "
        "from activities order by start_date desc limit 15"
    ).fetchall()
    if acts:
        total = con.execute("select count(*) c from activities").fetchone()["c"]
        A(f"## 运动记录（共 {total} 条，列最近 15 条）")
        for r in acts:
            km = f"{r['distance']/1000:.1f}km" if r["distance"] else "-"
            mins = f"{int(r['moving_time']/60)}分" if r["moving_time"] else "-"
            hr = int(r["average_heartrate"]) if r["average_heartrate"] else "-"
            A(f"- {r['start_date'][:10]}｜{r['name'] or r['sport_type']}｜{km}｜{mins}｜均心率 {hr}")
        A("")

    nu = con.execute(
        "select * from nutrition_logs order by eaten_at desc limit 10"
    ).fetchall()
    if nu:
        A("## 饮食记录")
        for r in nu:
            A(
                f"- {r['eaten_at'][:16]}｜{r['meal_type']}｜{r['total_kcal']:.0f} kcal"
                f"（蛋白 {r['protein_g']}g / 碳水 {r['carb_g']}g / 脂肪 {r['fat_g']}g）"
            )

    text = "\n".join(out)
    text = re.sub(r"(\d+)\.\d+ kcal", r"\1 kcal", text)
    os.makedirs(os.path.dirname(DEST), exist_ok=True)
    with open(DEST, "w", encoding="utf-8") as f:
        f.write(text)
    print(f"exported -> {DEST} ({len(text)} chars)")


if __name__ == "__main__":
    sys.exit(main())
