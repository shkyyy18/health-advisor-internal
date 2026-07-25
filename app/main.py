from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import hmac
import logging
import os
import re
import secrets
import time
from contextlib import asynccontextmanager
from datetime import datetime
from urllib.parse import urlparse

import httpx
from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from app.analytics import build_summary
from app.meal_analysis import (
    MAX_IMAGE_BYTES, MealAnalysisError, analyze_meal_photo, validate_meal_image,
)
from app.config import PROJECT_ROOT, settings
from app.db import (
    connect, init_db, latest_sync_time, list_activities, list_body, list_daily_metrics,
    list_nutrition, list_sleep, load_health_snapshot, record_sync,
    save_photo_nutrition, save_quick_nutrition,
)
from app.xiaomi_sync import XiaomiSyncError, sync_mi_fitness
from app.strava import (
    StravaConfigurationError,
    authorization_url,
    exchange_code,
    process_webhook_event,
    sync_activities,
)


_IDLE_TIMEOUT_SECONDS = int(os.getenv("HEALTH_IDLE_TIMEOUT_SECONDS", "300"))
_last_heartbeat = time.monotonic()
# 进行中的同步请求数。夜间小米云慢时单次同步可超过 300s 闲置阈值，
# 看门狗必须跳过这些时段，否则会把正在同步的服务强杀（os._exit）。
_active_syncs = 0

# 回环来源免令牌（本地脚本：daily_sync.py、open_dashboard.py、计划任务）；
# "testclient" 是 Starlette TestClient 的对端标识，测试视同本机。
_LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost", "testclient"}


async def _idle_watchdog() -> None:
    """Stop the service once no dashboard page has checked in for a while.

    看板页面打开时每 30 秒 POST 一次 /api/heartbeat；用户关闭标签页后，
    超过 HEALTH_IDLE_TIMEOUT_SECONDS（默认 300 秒）没有心跳就自动退出，
    配合"后端不常驻"模式。每日同步任务一两分钟内结束并自行停止服务；
    同步请求执行期间（_active_syncs > 0）看门狗暂停计时，避免夜间小米云
    响应慢、同步超过闲置阈值时被误杀。
    """
    while True:
        await asyncio.sleep(30)
        if _active_syncs:
            continue
        if time.monotonic() - _last_heartbeat > _IDLE_TIMEOUT_SECONDS:
            logger.info("No dashboard heartbeat for over %ss; shutting down.", _IDLE_TIMEOUT_SECONDS)
            os._exit(0)


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    watchdog = asyncio.create_task(_idle_watchdog())
    logger.info(
        "LAN access enabled. Phone dashboard URL: http://<本机局域网IP>:8000/?token=%s",
        settings.lan_token,
    )
    yield
    watchdog.cancel()


app = FastAPI(title="数据驱动减脂健康顾问", version="0.2.0", lifespan=lifespan)
templates = Jinja2Templates(directory=str(PROJECT_ROOT / "app" / "templates"))
templates.env.auto_reload = True
templates.env.cache_size = 0
app.mount("/static", StaticFiles(directory=str(PROJECT_ROOT / "app" / "static")), name="static")
logger = logging.getLogger(__name__)


@app.middleware("http")
async def protect_public_tunnel(request: Request, call_next):
    """Keep the webhook public and protect the phone page with HTTP Basic auth."""
    callback_host = urlparse(settings.strava_webhook_callback_url).netloc.lower()
    forwarded_host = request.headers.get("x-forwarded-host", "")
    request_host = (forwarded_host or request.headers.get("host", "")).lower()
    is_public_tunnel = callback_host and (request_host == callback_host or request.headers.get("x-forwarded-proto", "").lower() == "https")
    if not is_public_tunnel: return await call_next(request)
    if request.url.path.startswith("/webhooks/strava"): return await call_next(request)
    if request.url.path == "/mobile" or request.url.path.startswith("/api/meals/"):
        if not settings.mobile_access_password: return JSONResponse({"detail": "手机访问密码尚未配置"}, status_code=503)
        authorization = request.headers.get("authorization", "")
        authenticated = False
        if authorization.lower().startswith("basic "):
            try:
                raw = base64.b64decode(authorization.split(" ", 1)[1], validate=True).decode("utf-8")
                username, password = raw.split(":", 1)
                authenticated = hmac.compare_digest(username, "health") and hmac.compare_digest(password, settings.mobile_access_password)
            except (binascii.Error, ValueError, UnicodeDecodeError): authenticated = False
        if not authenticated:
            return JSONResponse({"detail": "需要手机访问密码"}, status_code=401, headers={"WWW-Authenticate": 'Basic realm="Health Assistant"'})
        return await call_next(request)
    return JSONResponse({"detail": "Not found"}, status_code=404)


@app.middleware("http")
async def lan_token_guard(request: Request, call_next):
    """服务绑定 0.0.0.0 后，非回环来源（手机等局域网设备）必须携带有效令牌。

    令牌可用 ?token=… 查询参数（手机浏览器最方便）或 X-LAN-Token 头；
    回环请求（daily_sync.py、open_dashboard.py 等本地脚本）一律免令牌。
    """
    client_host = request.client.host if request.client else ""
    if client_host in _LOOPBACK_HOSTS:
        return await call_next(request)
    # 静态资源只是界面文件（CSS/JS/图标），不含健康数据，放行以保证
    # 手机端页面能正常加载样式与脚本；页面与 API 仍全部要求令牌。
    if request.url.path.startswith("/static/"):
        return await call_next(request)
    token = request.query_params.get("token") or request.headers.get("x-lan-token", "")
    if settings.lan_token and hmac.compare_digest(token, settings.lan_token):
        return await call_next(request)
    return JSONResponse(
        {"detail": "局域网访问需要有效令牌：URL 加 ?token=… 或发送 X-LAN-Token 头"},
        status_code=403,
    )


class BodyMeasurement(BaseModel):
    measured_at: datetime
    weight_kg: float = Field(gt=20, lt=400)
    body_fat_pct: float | None = Field(default=None, ge=0, le=80)
    muscle_kg: float | None = Field(default=None, ge=0, le=200)
    water_pct: float | None = Field(default=None, ge=0, le=100)
    visceral_fat: float | None = Field(default=None, ge=0, le=100)
    basal_metabolism: float | None = Field(default=None, ge=0, le=10000)
    source: str = "xiaomi_s800_manual"


class SleepSession(BaseModel):
    start_time: datetime
    end_time: datetime
    deep_minutes: int | None = Field(default=None, ge=0, le=1000)
    light_minutes: int | None = Field(default=None, ge=0, le=1000)
    rem_minutes: int | None = Field(default=None, ge=0, le=1000)
    awake_minutes: int | None = Field(default=None, ge=0, le=1000)
    average_hr: float | None = Field(default=None, ge=20, le=250)
    average_spo2: float | None = Field(default=None, ge=50, le=100)
    source: str = "xiaomi_band_10_nfc_manual"


class QuickMeal(BaseModel):
    eaten_at: datetime | None = None
    meal_type: str = Field(default="unknown", min_length=1, max_length=20)
    description: str = Field(min_length=1, max_length=500)
    estimated_kcal: float | None = Field(default=None, ge=0, le=10000)
    protein_g: float | None = Field(default=None, ge=0, le=1000)
    carb_g: float | None = Field(default=None, ge=0, le=2000)
    fat_g: float | None = Field(default=None, ge=0, le=1000)
    confidence: str = Field(default="manual", min_length=1, max_length=30)
    notes: str | None = Field(default=None, max_length=1000)


class StravaWebhookEvent(BaseModel):
    object_type: str
    object_id: int
    aspect_type: str
    owner_id: int
    subscription_id: int
    event_time: int
    updates: dict[str, object] = Field(default_factory=dict)


async def _handle_strava_webhook(event: dict[str, object]) -> None:
    try:
        result = await process_webhook_event(event)
        record_sync("strava")
        logger.info("Strava webhook handled: %s", result)
    except Exception:
        # The callback must acknowledge quickly; failures can be repaired by manual sync.
        logger.exception("Strava webhook processing failed")


def _state_signature(nonce: str) -> str:
    return hmac.new(
        settings.app_secret.encode(), nonce.encode(), hashlib.sha256
    ).hexdigest()


def _snapshot_time() -> str:
    """最近一次数据同步的本地时间；从未记录过同步时退化为数据库文件的修改时间。"""
    latest = latest_sync_time()
    if latest:
        moment = datetime.fromisoformat(latest).astimezone()
    else:
        moment = datetime.fromtimestamp(settings.database_path.stat().st_mtime).astimezone()
    return moment.strftime("%Y/%m/%d %H:%M:%S")


def _current_health_data() -> tuple[dict, dict]:
    snapshot = load_health_snapshot()
    summary = build_summary(
        snapshot["activities"],
        snapshot["sleep"],
        snapshot["body"],
        snapshot["daily_metrics"],
        snapshot["profile"],
        snapshot["nutrition"],
    )
    return snapshot, summary


def _template_response_no_cache(request: Request, name: str, context: dict[str, object]):
    response = templates.TemplateResponse(request=request, name=name, context=context)
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    snapshot, summary = _current_health_data()
    return _template_response_no_cache(
        request=request,
        name="index.html",
        context={
            "connected": snapshot["strava_connected"],
            "activities": snapshot["activities"][:10],
            "summary": summary,
            "dashboard_data": _build_dashboard_data(),
            "snapshot_time": _snapshot_time(),
        },
    )


@app.get("/mobile", response_class=HTMLResponse)
def mobile_dashboard(request: Request):
    _, summary = _current_health_data()
    return _template_response_no_cache(
        request=request,
        name="mobile.html",
        context={
            "summary": summary,
            "openai_ready": bool(settings.openai_api_key),
            "vision_model": settings.openai_vision_model,
            "snapshot_time": _snapshot_time(),
        },
    )


def _range_midpoint(value: object) -> float | None:
    numbers = [float(item) for item in re.findall(r"\d+(?:\.\d+)?", str(value or ""))]
    if not numbers: return None
    return sum(numbers[:2]) / min(2, len(numbers))


@app.post("/api/meals/quick")
def save_quick_meal(item: QuickMeal):
    if item.eaten_at is not None:
        eaten_dt = item.eaten_at
        if eaten_dt.tzinfo is None:
            # datetime-local submits a naive timestamp; interpret it as local time.
            eaten_dt = eaten_dt.replace(tzinfo=datetime.now().astimezone().tzinfo)
    else:
        eaten_dt = datetime.now().astimezone()
    eaten_at = eaten_dt.isoformat()
    meal_type = item.meal_type.strip() or "unknown"
    description = item.description.strip()
    if not description:
        raise HTTPException(status_code=422, detail="Meal description cannot be blank.")
    save_quick_nutrition(
        eaten_at,
        meal_type,
        description,
        total_kcal=item.estimated_kcal,
        protein_g=item.protein_g,
        carb_g=item.carb_g,
        fat_g=item.fat_g,
        confidence=item.confidence.strip() or "manual",
        notes=item.notes.strip() if item.notes else None,
    )
    return {
        "status": "saved",
        "source": "quick_manual",
        "eaten_at": eaten_at,
        "meal_type": meal_type,
        "description": description,
    }


@app.post("/api/meals/analyze")
async def analyze_meal(
    image: UploadFile = File(...), meal_type: str = Form(default="午餐")
):
    content_type = (image.content_type or "").lower()
    data = await image.read(MAX_IMAGE_BYTES + 1)
    normalized_meal_type = meal_type.strip()[:20] or "未知餐次"
    try:
        # Reject bad uploads before opening the database or calling an external API.
        validate_meal_image(data, content_type)
        _, summary = _current_health_data()
        analysis = await analyze_meal_photo(
            data, content_type, normalized_meal_type, summary["nutrition"]
        )
    except MealAnalysisError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    meal_total = analysis.get("meal_total", {})
    totals = {
        "total_kcal": _range_midpoint(meal_total.get("kcal_range")),
        "protein_g": _range_midpoint(meal_total.get("protein_g_range")),
        "carb_g": _range_midpoint(meal_total.get("carb_g_range")),
        "fat_g": _range_midpoint(meal_total.get("fat_g_range")),
    }
    eaten_at = datetime.now().astimezone().isoformat()
    save_photo_nutrition(eaten_at, normalized_meal_type, analysis, totals)
    return {
        "status": "saved",
        "eaten_at": eaten_at,
        "analysis": analysis,
        "privacy": "原始照片只发送给图片分析接口，本应用不在本地保存照片；仅保存文字分析和营养估算。",
    }


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/api/heartbeat")
def heartbeat():
    """看板页面的保活心跳；时间戳供闲置看门狗判断用户是否还在看。"""
    global _last_heartbeat
    _last_heartbeat = time.monotonic()
    return {"ok": True}


@app.get("/connect/strava")
def connect_strava():
    nonce = secrets.token_urlsafe(24)
    state = f"{nonce}.{_state_signature(nonce)}"
    try:
        return RedirectResponse(authorization_url(state))
    except StravaConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/oauth/strava/callback")
async def strava_callback(code: str, state: str, error: str | None = None):
    if error:
        raise HTTPException(status_code=400, detail=f"Strava授权失败：{error}")
    try:
        nonce, signature = state.split(".", 1)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="无效的OAuth state") from exc
    if not hmac.compare_digest(signature, _state_signature(nonce)):
        raise HTTPException(status_code=400, detail="OAuth state校验失败")
    try:
        await exchange_code(code)
        await sync_activities()
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="无法连接 Strava，请稍后重试。") from exc
    record_sync("strava")
    return RedirectResponse("/", status_code=303)


@app.get("/webhooks/strava")
def verify_strava_webhook(
    mode: str = Query(alias="hub.mode"),
    verify_token: str = Query(alias="hub.verify_token"),
    challenge: str = Query(alias="hub.challenge"),
):
    expected = settings.strava_webhook_verify_token
    if not expected or mode != "subscribe" or not hmac.compare_digest(verify_token, expected):
        raise HTTPException(status_code=403, detail="Strava webhook 验证失败。")
    return {"hub.challenge": challenge}


@app.post("/webhooks/strava", status_code=200)
def receive_strava_webhook(
    event: StravaWebhookEvent, background_tasks: BackgroundTasks
):
    background_tasks.add_task(_handle_strava_webhook, event.model_dump())
    return {"status": "accepted"}


_xiaomi_sync_lock = asyncio.Lock()


@app.post("/api/sync/xiaomi")
async def sync_xiaomi():
    # 客户端超时重试时，上一轮同步可能仍在服务端执行；加锁串行化，
    # 避免两个同步任务并发抓取小米云/写 SQLite（upsert 幂等，重复执行无害）。
    global _active_syncs
    _active_syncs += 1
    try:
        async with _xiaomi_sync_lock:
            try:
                result = await sync_mi_fitness()
            except XiaomiSyncError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            record_sync("xiaomi")
            return result
    finally:
        _active_syncs -= 1


# Compatibility for the previous dashboard button. The old directory importer is gone;
# this endpoint now performs a direct public-path Mi Fitness sync.
@app.post("/api/sync/legacy")
async def sync_legacy_compat():
    return await sync_xiaomi()


@app.post("/api/sync/strava")
async def sync_strava():
    global _active_syncs
    _active_syncs += 1
    try:
        try:
            count = await sync_activities()
        except (RuntimeError, StravaConfigurationError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail="无法连接 Strava，请稍后重试。") from exc
        record_sync("strava")
        return {"synced": count}
    finally:
        _active_syncs -= 1


@app.get("/api/activities")
def activities(limit: int = Query(default=30, ge=1, le=500)):
    return list_activities(limit)


@app.get("/api/sleep")
def sleep_records(limit: int = Query(default=30, ge=1, le=500)):
    return list_sleep(limit)


@app.get("/api/daily-metrics")
def daily_metrics(limit: int = Query(default=30, ge=1, le=500)):
    return list_daily_metrics(limit)


@app.get("/api/body")
def body_records(limit: int = Query(default=30, ge=1, le=500)):
    return list_body(limit)


@app.get("/api/nutrition")
def nutrition_records(limit: int = Query(default=30, ge=1, le=500)):
    return list_nutrition(limit)


@app.post("/api/body")
def add_body(item: BodyMeasurement):
    with connect() as db:
        db.execute(
            """
            INSERT INTO body_measurements
              (source, measured_at, weight_kg, body_fat_pct, muscle_kg,
               water_pct, visceral_fat, basal_metabolism)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(source, measured_at) DO UPDATE SET
              weight_kg=excluded.weight_kg, body_fat_pct=excluded.body_fat_pct,
              muscle_kg=excluded.muscle_kg, water_pct=excluded.water_pct,
              visceral_fat=excluded.visceral_fat,
              basal_metabolism=excluded.basal_metabolism
            """,
            (
                item.source, item.measured_at.isoformat(), item.weight_kg,
                item.body_fat_pct, item.muscle_kg, item.water_pct,
                item.visceral_fat, item.basal_metabolism,
            ),
        )
    return {"status": "saved"}


@app.post("/api/sleep")
def add_sleep(item: SleepSession):
    if item.end_time <= item.start_time:
        raise HTTPException(status_code=422, detail="睡眠结束时间必须晚于开始时间")
    with connect() as db:
        db.execute(
            """
            INSERT INTO sleep_sessions
              (source, start_time, end_time, deep_minutes, light_minutes,
               rem_minutes, awake_minutes, average_hr, average_spo2)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(source, start_time, end_time) DO UPDATE SET
              deep_minutes=excluded.deep_minutes,
              light_minutes=excluded.light_minutes,
              rem_minutes=excluded.rem_minutes,
              awake_minutes=excluded.awake_minutes,
              average_hr=excluded.average_hr,
              average_spo2=excluded.average_spo2
            """,
            (
                item.source, item.start_time.isoformat(), item.end_time.isoformat(),
                item.deep_minutes, item.light_minutes, item.rem_minutes,
                item.awake_minutes, item.average_hr, item.average_spo2,
            ),
        )
    return {"status": "saved"}


@app.get("/api/summary")
def summary():
    _, result = _current_health_data()
    return result


def _iso_to_local_date(iso_string: str) -> str:
    """Extract YYYY-MM-DD from an ISO timestamp in the local timezone."""
    if not iso_string:
        return ""
    # Handles both '+08:00' and 'Z' suffixes; localizes to the date portion.
    try:
        parsed = datetime.fromisoformat(iso_string.replace("Z", "+00:00"))
    except ValueError:
        return iso_string[:10]
    return parsed.astimezone().date().isoformat()


def _build_dashboard_data() -> dict:
    snapshot, summary = _current_health_data()

    body_points = []
    for row in sorted(snapshot.get("body") or [], key=lambda r: r.get("measured_at", "")):
        measured_at = row.get("measured_at") or ""
        date = _iso_to_local_date(measured_at)
        if not date:
            continue
        weight = row.get("weight_kg")
        body_fat = row.get("body_fat_pct")
        lean = None
        if weight is not None and body_fat is not None:
            lean = round(weight * (1 - body_fat / 100), 2)
        body_points.append({
            "date": date,
            "weight": weight,
            "body_fat": body_fat,
            "lean_mass": lean,
        })

    sleep_points = []
    for row in sorted(snapshot.get("sleep") or [], key=lambda r: r.get("sleep_date") or r.get("start_time") or ""):
        sleep_date = row.get("sleep_date") or _iso_to_local_date(row.get("start_time") or "")
        if not sleep_date:
            continue
        duration = row.get("duration_minutes") or 0
        if duration < 30:  # skip naps
            continue
        sleep_points.append({
            "date": sleep_date,
            "hours": round(duration / 60, 1),
            "deep_hours": round((row.get("deep_minutes") or 0) / 60, 1),
            "rem_hours": round((row.get("rem_minutes") or 0) / 60, 1),
        })

    activity_points = []
    for row in sorted(snapshot.get("activities") or [], key=lambda r: r.get("start_date", "")):
        start = row.get("start_date") or ""
        date = _iso_to_local_date(start)
        if not date:
            continue
        moving = row.get("moving_time") or 0
        distance = row.get("distance") or 0
        activity_points.append({
            "date": date,
            "minutes": int(moving / 60),
            "distance_km": round(distance / 1000, 1),
            "type": row.get("sport_type") or "活动",
            "avg_hr": row.get("average_heartrate"),
        })

    nutrition_points = []
    for row in sorted(snapshot.get("nutrition") or [], key=lambda r: r.get("eaten_at") or ""):
        eaten_at = row.get("eaten_at") or ""
        date = _iso_to_local_date(eaten_at)
        if not date:
            continue
        nutrition_points.append({
            "date": date,
            "meal": row.get("meal_type"),
            "kcal": row.get("total_kcal"),
            "protein": row.get("protein_g"),
            "carb": row.get("carb_g"),
            "fat": row.get("fat_g"),
        })

    return {
        "period_days": 30,
        "body": body_points[-60:],
        "sleep": sleep_points[-60:],
        "activities": activity_points[-60:],
        "nutrition": nutrition_points[-60:],
        "summary": {
            "latest_weight_kg": summary.get("body_composition", {}).get("latest_weight_kg"),
            "latest_body_fat_pct": summary.get("body_composition", {}).get("latest_body_fat_pct"),
            "latest_sleep_hours": summary.get("sleep", {}).get("latest_hours"),
            "readiness_status": summary.get("readiness", {}).get("status"),
            "coaching_status": summary.get("daily_coaching", {}).get("status"),
            "coaching_headline": summary.get("daily_coaching", {}).get("headline"),
        },
    }


@app.get("/api/dashboard-data")
def dashboard_data():
    return _build_dashboard_data()
