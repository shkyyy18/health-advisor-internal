from __future__ import annotations

import os
import secrets
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).absolute().parents[1]


def _load_dotenv(path: Path) -> None:
    """Load a small KEY=VALUE .env file without adding another dependency."""
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


def _path_from_env(name: str, default: Path) -> Path:
    raw = os.getenv(name, "").strip()
    path = Path(raw).expanduser() if raw else default
    return path if path.is_absolute() else PROJECT_ROOT / path


def _int_from_env(name: str, default: int, minimum: int, maximum: int) -> int:
    raw = os.getenv(name, "").strip()
    try:
        value = int(raw) if raw else default
    except ValueError:
        value = default
    return max(minimum, min(maximum, value))


def _load_lan_token() -> str:
    """局域网访问令牌：HEALTH_LAN_TOKEN 优先；否则生成随机令牌并持久化到
    data/lan_token.txt（data/ 已在 .gitignore 中，令牌不进 git），保证重启后
    手机书签里的令牌仍然有效。"""
    env_token = os.getenv("HEALTH_LAN_TOKEN", "").strip()
    if env_token:
        return env_token
    token_path = _path_from_env(
        "HEALTH_LAN_TOKEN_PATH", PROJECT_ROOT / "data" / "lan_token.txt"
    )
    try:
        existing = token_path.read_text(encoding="utf-8").strip()
        if existing:
            return existing
    except OSError:
        pass
    token = secrets.token_urlsafe(24)
    try:
        token_path.parent.mkdir(parents=True, exist_ok=True)
        token_path.write_text(token + "\n", encoding="utf-8")
    except OSError:
        pass  # 写不进也能用本次生成的令牌，只是重启后会变
    return token


_load_dotenv(PROJECT_ROOT / ".env")


@dataclass(frozen=True)
class Settings:
    strava_client_id: str
    strava_client_secret: str
    strava_redirect_uri: str
    strava_webhook_callback_url: str
    strava_webhook_verify_token: str
    app_secret: str
    database_path: Path
    mi_fitness_auth_path: Path
    mi_fitness_sync_days: int
    mobile_access_password: str
    meal_llm_api_key: str
    meal_llm_base_url: str
    meal_llm_model: str
    lan_token: str

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            strava_client_id=os.getenv("STRAVA_CLIENT_ID", ""),
            strava_client_secret=os.getenv("STRAVA_CLIENT_SECRET", ""),
            strava_redirect_uri=os.getenv(
                "STRAVA_REDIRECT_URI",
                "http://127.0.0.1:8000/oauth/strava/callback",
            ),
            strava_webhook_callback_url=os.getenv(
                "STRAVA_WEBHOOK_CALLBACK_URL", ""
            ),
            strava_webhook_verify_token=os.getenv(
                "STRAVA_WEBHOOK_VERIFY_TOKEN", ""
            ),
            app_secret=os.getenv("APP_SECRET", "development-only-secret"),
            database_path=_path_from_env(
                "DATABASE_PATH", PROJECT_ROOT / "data" / "health.db"
            ),
            mi_fitness_auth_path=_path_from_env(
                "MI_FITNESS_AUTH_PATH",
                PROJECT_ROOT / "data" / ".mijia" / "auth.json",
            ),
            mi_fitness_sync_days=_int_from_env("MI_FITNESS_SYNC_DAYS", 14, 1, 90),
            mobile_access_password=os.getenv("MOBILE_ACCESS_PASSWORD", ""),
            meal_llm_api_key=os.getenv("MEAL_LLM_API_KEY", ""),
            meal_llm_base_url=os.getenv(
                "MEAL_LLM_BASE_URL", "https://cdk.goodmoonlight.com/responses"
            ),
            meal_llm_model=os.getenv("MEAL_LLM_MODEL", "gpt-5.6-sol"),
            lan_token=_load_lan_token(),
        )


settings = Settings.from_env()
