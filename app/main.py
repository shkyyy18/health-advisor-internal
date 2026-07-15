from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import logging
import re
import secrets
from contextlib import asynccontextmanager
from datetime import datetime
from urllib.parse import urlparse

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from app.analytics import build_summary
from app.meal_analysis import (
    MAX_IMAGE_BYTES, MealAnalysisError, analyze_meal_photo, validate_meal_image,
)
from app.config import PROJECT_ROOT, settings
from app.db import (
    connect, init_db, list_activities, load_health_snapshot, save_photo_nutrition,
)
from app.xiaomi_sync import XiaomiSyncError, sync_mi_fitness
from app.strava import (
    StravaConfigurationError,
    authorization_url,
    exchange_code,
    process_webhook_event,
    sync_activities,
)


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(title="健康助手", version="0.2.0", lifespan=lifespan)
templates = Jinja2Templates(directory=str(PROJECT_ROOT / "app" / "templates"))
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
        logger.info("Strava webhook handled: %s", result)
    except Exception:
        # The callback must acknowledge quickly; failures can be repaired by manual sync.
        logger.exception("Strava webhook processing failed")


def _state_signature(nonce: str) -> str:
    return hmac.new(
        settings.app_secret.encode(), nonce.encode(), hashlib.sha256
    ).hexdigest()


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
        },
    )


def _range_midpoint(value: object) -> float | None:
    numbers = [float(item) for item in re.findall(r"\d+(?:\.\d+)?", str(value or ""))]
    if not numbers: return None
    return sum(numbers[:2]) / min(2, len(numbers))


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
    await exchange_code(code)
    await sync_activities()
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


@app.post("/api/sync/xiaomi")
async def sync_xiaomi():
    try:
        return await sync_mi_fitness()
    except XiaomiSyncError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# Compatibility for the previous dashboard button. The old directory importer is gone;
# this endpoint now performs a direct public-path Mi Fitness sync.
@app.post("/api/sync/legacy")
async def sync_legacy_compat():
    return await sync_xiaomi()


@app.post("/api/sync/strava")
async def sync_strava():
    try:
        count = await sync_activities()
    except (RuntimeError, StravaConfigurationError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"synced": count}


@app.get("/api/activities")
def activities(limit: int = Query(default=30, ge=1, le=500)):
    return list_activities(limit)


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
