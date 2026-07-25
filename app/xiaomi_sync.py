from __future__ import annotations

import asyncio
import json
import os
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable

from app.config import settings
from app.db import connect


SOURCE = "mi_fitness_data_bridge"


class XiaomiSyncError(RuntimeError):
    """Raised when the Mi Fitness connector cannot be configured or synced."""


def _adapter_class():
    try:
        from mi_fitness_mcp.adapters.mi_fitness_cloud import MiFitnessCloudAdapter
    except ModuleNotFoundError as exc:
        raise XiaomiSyncError(
            "Mi Fitness Data Bridge is not installed. In this workspace run: "
            "pip install -e ../mi_fitness_data_bridge. After release, install "
            "mi-fitness-data-bridge from the package index."
        ) from exc
    return MiFitnessCloudAdapter


def load_credentials(path: Path | None = None) -> tuple[str, str]:
    env_user_id = os.getenv("MI_FITNESS_USER_ID", "").strip()
    env_pass_token = os.getenv("MI_FITNESS_PASS_TOKEN", "").strip()
    if env_user_id and env_pass_token:
        return env_user_id, env_pass_token

    auth_path = (path or settings.mi_fitness_auth_path).expanduser().absolute()
    if not auth_path.exists():
        raise XiaomiSyncError(
            "\u5c0f\u7c73\u767b\u5f55\u51ed\u636e\u5c1a\u672a\u914d\u7f6e\u3002\u8bf7\u5728\u516c\u5171\u9879\u76ee\u76ee\u5f55\u8fd0\u884c\uff1a"
            "python scripts/mijia_health_sync.py login\uff0c\u626b\u7801\u767b\u5f55\u540e\u518d\u5237\u65b0\u3002"
        )
    try:
        payload = json.loads(auth_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise XiaomiSyncError(f"Cannot read Mi Fitness credentials: {auth_path}") from exc
    user_id = str(payload.get("userId") or payload.get("user_id") or "").strip()
    pass_token = str(payload.get("passToken") or payload.get("pass_token") or "").strip()
    if not user_id or not pass_token:
        raise XiaomiSyncError(
            f"Mi Fitness credentials are missing userId/passToken: {auth_path}. Run login again."
        )
    return user_id, pass_token


def _dump(record: Any) -> dict[str, Any]:
    if hasattr(record, "model_dump"):
        return record.model_dump(mode="json")
    if isinstance(record, dict):
        return record
    return dict(vars(record))


async def _collect(iterator: Any) -> list[Any]:
    return [item async for item in iterator]


def _mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 2) if values else None


def _sleep_stage_minutes(stages: list[Any]) -> dict[str, int]:
    totals = {"deep": 0, "light": 0, "rem": 0, "awake": 0}
    for stage in stages:
        name = stage.stage if hasattr(stage, "stage") else stage.get("stage")
        minutes = stage.minutes if hasattr(stage, "minutes") else stage.get("minutes", 0)
        if name in totals:
            totals[name] += int(minutes or 0)
    return totals


CONNECT_ATTEMPTS = 3
CONNECT_RETRY_SECONDS = 3

# adapter.connect() 把登录鉴权失败和网络波动都吞成 False，具体原因留在
# adapter.last_error。网络类错误不应提示用户重新扫码。
_TRANSIENT_ERROR_MARKERS = (
    "ConnectError",
    "ConnectTimeout",
    "ReadTimeout",
    "WriteTimeout",
    "PoolTimeout",
    "TimeoutException",
    "NetworkError",
    "ReadError",
    "RemoteProtocolError",
    "SSLError",
)


async def _connect_with_retry(adapter: Any) -> bool:
    for attempt in range(CONNECT_ATTEMPTS):
        if await adapter.connect():
            return True
        if attempt < CONNECT_ATTEMPTS - 1:
            await asyncio.sleep(CONNECT_RETRY_SECONDS)
    return False


def _connect_error(adapter: Any) -> XiaomiSyncError:
    detail = str(getattr(adapter, "last_error", "") or "").strip() or "未知原因"
    if any(marker in detail for marker in _TRANSIENT_ERROR_MARKERS):
        return XiaomiSyncError(
            f"小米云暂时连接失败（{detail}）。这是网络或小米服务器波动，"
            "不是登录过期，无需重新扫码，稍后点刷新或等下一次自动同步即可。"
        )
    return XiaomiSyncError(f"小米云连接失败（{detail}），passToken 可能已过期，请重新扫码登录。")


async def _collect_all(
    adapter: Any, start_text: str, end_text: str
) -> tuple[list[Any], list[Any], list[Any], list[Any], list[Any], list[Any]]:
    """Fetch every data type; retry the whole pass once on transient failures.

    小米云偶发在采集中途返回空原因的错误（2026-07-20 实录："Mi Fitness
    request failed: "），整轮重试一次通常即可成功。
    """
    last_exc: Exception | None = None
    for attempt in range(2):
        try:
            daily = await _collect(adapter.iter_daily_activity(start_text, end_text))
            sleep = await _collect(adapter.iter_sleep_sessions(start_text, end_text))
            body = await _collect(adapter.iter_body_measurements(start_text, end_text))
            heart = await _collect(adapter.iter_heart_rate(start_text, end_text))
            spo2 = await _collect(adapter.iter_spo2(start_text, end_text))
            stress = await _collect(adapter.iter_stress(start_text, end_text))
            return daily, sleep, body, heart, spo2, stress
        except Exception as exc:
            last_exc = exc
            if attempt == 0:
                await asyncio.sleep(CONNECT_RETRY_SECONDS)
    raise XiaomiSyncError(f"小米健康数据同步失败：{last_exc}") from last_exc


async def sync_mi_fitness(
    *,
    days: int | None = None,
    credentials_path: Path | None = None,
    adapter_factory: Callable[..., Any] | None = None,
) -> dict[str, int | str]:
    """Fetch recent Mi Fitness cloud data and upsert it into the health database."""
    user_id, pass_token = load_credentials(credentials_path)
    lookback = max(1, min(90, days or settings.mi_fitness_sync_days))
    end = date.today()
    start = end - timedelta(days=lookback - 1)
    start_text, end_text = start.isoformat(), end.isoformat()

    factory = adapter_factory or _adapter_class()
    adapter = factory(user_id=user_id, pass_token=pass_token, region="cn")
    try:
        if not await _connect_with_retry(adapter):
            raise _connect_error(adapter)
        daily, sleep, body, heart, spo2, stress = await _collect_all(adapter, start_text, end_text)
    except XiaomiSyncError:
        raise
    except Exception as exc:
        raise XiaomiSyncError(f"小米健康数据同步失败：{exc}") from exc
    finally:
        try:
            await adapter.close()
        except Exception:
            pass

    metrics: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "steps": None,
            "calories": None,
            "distance_m": None,
            "active_minutes": None,
            "heart": [],
            "spo2": [],
            "stress": [],
            "raw": defaultdict(list),
        }
    )
    for item in daily:
        row = metrics[str(item.date)]
        row.update(
            steps=int(item.steps),
            calories=float(item.active_kcal),
            distance_m=float(item.distance_m),
            active_minutes=item.active_minutes,
        )
        row["raw"]["daily_activity"].append(_dump(item))
    for item in heart:
        key = item.timestamp.date().isoformat()
        metrics[key]["heart"].append(float(item.bpm))
        metrics[key]["raw"]["heart_rate"].append(_dump(item))
    for item in spo2:
        key = item.timestamp.date().isoformat()
        metrics[key]["spo2"].append(float(item.spo2_pct))
        metrics[key]["raw"]["spo2"].append(_dump(item))
    for item in stress:
        key = item.timestamp.date().isoformat()
        metrics[key]["stress"].append(float(item.stress_score))
        metrics[key]["raw"]["stress"].append(_dump(item))

    with connect() as db:
        for item in body:
            db.execute(
                """
                INSERT INTO body_measurements
                  (source, measured_at, weight_kg, body_fat_pct, muscle_kg,
                   water_pct, visceral_fat, basal_metabolism, raw_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(source, measured_at) DO UPDATE SET
                  weight_kg=excluded.weight_kg, body_fat_pct=excluded.body_fat_pct,
                  muscle_kg=excluded.muscle_kg, water_pct=excluded.water_pct,
                  visceral_fat=excluded.visceral_fat,
                  basal_metabolism=excluded.basal_metabolism,
                  raw_json=excluded.raw_json
                """,
                (
                    SOURCE,
                    item.timestamp.isoformat(),
                    float(item.weight_kg),
                    item.body_fat_pct,
                    item.muscle_mass_kg,
                    item.water_pct,
                    item.visceral_fat_score,
                    item.basal_metabolism_kcal,
                    json.dumps(_dump(item), ensure_ascii=False),
                ),
            )
        for item in sleep:
            stages = _sleep_stage_minutes(item.stages)
            sleep_date = item.end_at.date().isoformat()
            db.execute(
                """
                INSERT INTO sleep_summaries
                  (sleep_date, source, duration_minutes, deep_minutes,
                   light_minutes, rem_minutes, awake_minutes, raw_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(sleep_date, source) DO UPDATE SET
                  duration_minutes=excluded.duration_minutes,
                  deep_minutes=excluded.deep_minutes,
                  light_minutes=excluded.light_minutes,
                  rem_minutes=excluded.rem_minutes,
                  awake_minutes=excluded.awake_minutes,
                  raw_json=excluded.raw_json
                """,
                (
                    sleep_date,
                    SOURCE,
                    int(item.time_asleep_minutes or item.duration_minutes),
                    stages["deep"],
                    stages["light"],
                    stages["rem"],
                    int(item.time_awake_minutes or stages["awake"]),
                    json.dumps(_dump(item), ensure_ascii=False),
                ),
            )
        for metric_date, row in metrics.items():
            heart_values = row["heart"]
            db.execute(
                """
                INSERT INTO daily_metrics
                  (metric_date, source, steps, calories, distance_m,
                   active_minutes, heart_rate_avg, heart_rate_min,
                   heart_rate_max, spo2_avg, stress_avg, raw_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(metric_date, source) DO UPDATE SET
                  steps=COALESCE(excluded.steps, daily_metrics.steps),
                  calories=COALESCE(excluded.calories, daily_metrics.calories),
                  distance_m=COALESCE(excluded.distance_m, daily_metrics.distance_m),
                  active_minutes=COALESCE(excluded.active_minutes, daily_metrics.active_minutes),
                  heart_rate_avg=COALESCE(excluded.heart_rate_avg, daily_metrics.heart_rate_avg),
                  heart_rate_min=COALESCE(excluded.heart_rate_min, daily_metrics.heart_rate_min),
                  heart_rate_max=COALESCE(excluded.heart_rate_max, daily_metrics.heart_rate_max),
                  spo2_avg=COALESCE(excluded.spo2_avg, daily_metrics.spo2_avg),
                  stress_avg=COALESCE(excluded.stress_avg, daily_metrics.stress_avg),
                  raw_json=excluded.raw_json
                """,
                (
                    metric_date,
                    SOURCE,
                    row["steps"],
                    row["calories"],
                    row["distance_m"],
                    row["active_minutes"],
                    _mean(heart_values),
                    min(heart_values) if heart_values else None,
                    max(heart_values) if heart_values else None,
                    _mean(row["spo2"]),
                    _mean(row["stress"]),
                    json.dumps(row["raw"], ensure_ascii=False),
                ),
            )

    return {
        "source": "mi_fitness_cloud",
        "start_date": start_text,
        "end_date": end_text,
        "body": len(body),
        "sleep": len(sleep),
        "daily_metrics": len(metrics),
        "heart_rate_samples": len(heart),
        "spo2_samples": len(spo2),
        "stress_samples": len(stress),
    }
