#!/usr/bin/env python3
"""
每日健康计划邮件发送脚本
从 data/reviews/ 当日计划文件读取建议并发送邮件。
"""
import os
import sys
import json
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from pathlib import Path
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv

# 加载环境变量
PROJECT_ROOT = Path(__file__).resolve().parents[1]
BEIJING = timezone(timedelta(hours=8))
load_dotenv(PROJECT_ROOT / ".env")

def format_email_body(review_data, plan_date=None):
    """格式化邮件正文"""
    today = (plan_date or datetime.now(BEIJING).date()).strftime("%Y年%m月%d日")

    body = f"""
<html>
<head>
<meta charset="utf-8">
<style>
body {{ font-family: 'Microsoft YaHei', Arial, sans-serif; line-height: 1.6; color: #333; }}
.header {{ background: #4CAF50; color: white; padding: 20px; text-align: center; }}
.section {{ margin: 20px 0; padding: 15px; border-left: 4px solid #4CAF50; background: #f9f9f9; }}
.section h3 {{ margin-top: 0; color: #2E7D32; }}
.metric {{ display: inline-block; margin: 10px 15px 10px 0; padding: 8px 12px; background: white; border-radius: 4px; }}
.label {{ font-weight: bold; color: #555; }}
.value {{ color: #2E7D32; font-weight: bold; }}
.action {{ margin: 10px 0; padding: 10px; background: #E8F5E9; border-radius: 4px; }}
.footer {{ margin-top: 30px; padding: 15px; text-align: center; color: #777; font-size: 12px; border-top: 1px solid #ddd; }}
</style>
</head>
<body>
<div class="header">
<h2>🏃 每日健康计划</h2>
<p>{today}</p>
</div>

<div class="section">
<h3>📊 当前状态</h3>
"""

    # 体重数据
    if "weight" in review_data:
        weight_data = review_data["weight"]
        body += f'<div class="metric"><span class="label">体重：</span><span class="value">{weight_data.get("current", "待测量")} kg</span></div>'
        if "source_date" in weight_data:
            body += f'<div class="metric"><span class="label">数据日期：</span>{weight_data["source_date"]}</div>'

    # 睡眠数据
    if "sleep" in review_data:
        sleep_data = review_data["sleep"]
        if "duration_hours" in sleep_data:
            body += f'<div class="metric"><span class="label">昨夜睡眠：</span><span class="value">{sleep_data["duration_hours"]} 小时</span></div>'

    body += "</div>"

    # 今日运动计划
    if "exercise_plan" in review_data:
        exercise = review_data["exercise_plan"]
        body += """
<div class="section">
<h3>🏋️ 今日运动</h3>
"""
        if isinstance(exercise, dict):
            if "type" in exercise:
                body += f'<div class="action">类型：{exercise["type"]}</div>'
            if "duration" in exercise:
                body += f'<div class="action">时长：{exercise["duration"]}</div>'
            if "intensity" in exercise:
                body += f'<div class="action">强度：{exercise["intensity"]}</div>'
        elif isinstance(exercise, str):
            body += f'<div class="action">{exercise}</div>'
        body += "</div>"

    # 今日饮食建议
    if "diet_plan" in review_data:
        diet = review_data["diet_plan"]
        body += """
<div class="section">
<h3>🍽️ 今日饮食</h3>
"""
        if isinstance(diet, dict):
            for meal, content in diet.items():
                body += f'<div class="action"><strong>{meal}：</strong>{content}</div>'
        elif isinstance(diet, str):
            body += f'<div class="action">{diet}</div>'
        body += "</div>"

    # 重要提醒
    if "reminders" in review_data:
        reminders = review_data["reminders"]
        body += """
<div class="section">
<h3>⚠️ 重要提醒</h3>
"""
        if isinstance(reminders, list):
            for reminder in reminders:
                body += f'<div class="action">• {reminder}</div>'
        elif isinstance(reminders, str):
            body += f'<div class="action">{reminders}</div>'
        body += "</div>"

    # 页脚
    body += """
<div class="footer">
<p>本计划由健康顾问AI生成，基于你的历史数据和当前目标</p>
<p>如有疑问，请在Codex中与助手交流</p>
</div>
</body>
</html>
"""
    return body

def send_email(subject, body_html, to_email):
    """发送邮件"""
    smtp_server = os.getenv("SMTP_SERVER", "smtp.163.com")
    smtp_port = int(os.getenv("SMTP_PORT", "465"))
    smtp_user = os.getenv("SMTP_USER")
    smtp_password = os.getenv("SMTP_PASSWORD")
    from_email = os.getenv("FROM_EMAIL", smtp_user)

    if not smtp_user or not smtp_password:
        print("错误：未配置SMTP凭据", file=sys.stderr)
        return False

    # 创建邮件
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = from_email
    msg["To"] = to_email

    # 添加HTML正文
    html_part = MIMEText(body_html, "html", "utf-8")
    msg.attach(html_part)

    try:
        # 使用SSL连接
        with smtplib.SMTP_SSL(smtp_server, smtp_port, timeout=30) as server:
            server.login(smtp_user, smtp_password)
            server.send_message(msg)
        return True
    except Exception as e:
        print(f"邮件发送失败: {e}", file=sys.stderr)
        return False

def main():
    plan_date = datetime.now(BEIJING).date()
    plan_file = PROJECT_ROOT / "data" / "reviews" / f"{plan_date}-plan.json"

    # 读取数据
    try:
        with plan_file.open("r", encoding="utf-8") as f:
            review_data = json.load(f)
    except Exception as e:
        print(f"读取计划文件失败: {e}", file=sys.stderr)
        sys.exit(1)

    required_sections = ("exercise_plan", "diet_plan", "reminders")
    if not isinstance(review_data, dict) or any(
        not review_data.get(section) for section in required_sections
    ):
        print("当日计划缺少运动、饮食或作息安排", file=sys.stderr)
        sys.exit(1)

    subject = f"每日健康计划 {plan_date}"
    body_html = format_email_body(review_data, plan_date)

    # 发送邮件
    to_email = os.getenv("HEALTH_EMAIL_TO", "njshk@163.com")
    if to_email.strip().lower() != "njshk@163.com":
        print("收件地址与授权不符", file=sys.stderr)
        sys.exit(1)

    if send_email(subject, body_html, to_email):
        print(f"邮件已发送到 {to_email}")
        print(f"使用数据: {plan_file.name}")
        sys.exit(0)
    else:
        print("邮件发送失败", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
