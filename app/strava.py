from __future__ import annotations

import time
from typing import Any
from urllib.parse import urlencode

import httpx

from app.config import settings
from app.db import delete_activity, delete_token, get_token, save_activity, save_token

AUTH_URL = "https://www.strava.com/oauth/authorize"
TOKEN_URL = "https://www.strava.com/oauth/token"
API_URL = "https://www.strava.com/api/v3"


class StravaConfigurationError(RuntimeError):
    pass


def ensure_configured() -> None:
    if not settings.strava_client_id or not settings.strava_client_secret:
        raise StravaConfigurationError(
            "请先设置 STRAVA_CLIENT_ID 和 STRAVA_CLIENT_SECRET。"
        )


def authorization_url(state: str) -> str:
    ensure_configured()
    query = urlencode(
        {
            "client_id": settings.strava_client_id,
            "redirect_uri": settings.strava_redirect_uri,
            "response_type": "code",
            "approval_prompt": "auto",
            "scope": "read,activity:read_all",
            "state": state,
        }
    )
    return f"{AUTH_URL}?{query}"


async def exchange_code(code: str) -> dict[str, Any]:
    ensure_configured()
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(
            TOKEN_URL,
            data={
                "client_id": settings.strava_client_id,
                "client_secret": settings.strava_client_secret,
                "code": code,
                "grant_type": "authorization_code",
            },
        )
        response.raise_for_status()
        token = response.json()
    save_token(token)
    return token


async def valid_access_token() -> str:
    ensure_configured()
    token = get_token()
    if not token:
        raise RuntimeError("尚未连接Strava。")
    if int(token["expires_at"]) > int(time.time()) + 120:
        return str(token["access_token"])

    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(
            TOKEN_URL,
            data={
                "client_id": settings.strava_client_id,
                "client_secret": settings.strava_client_secret,
                "grant_type": "refresh_token",
                "refresh_token": token["refresh_token"],
            },
        )
        response.raise_for_status()
        refreshed = response.json()
    refreshed["athlete"] = {"id": token.get("athlete_id")}
    save_token(refreshed)
    return str(refreshed["access_token"])


async def sync_activities(per_page: int = 100) -> int:
    access_token = await valid_access_token()
    count = 0
    page = 1
    headers = {"Authorization": f"Bearer {access_token}"}
    async with httpx.AsyncClient(timeout=30, headers=headers) as client:
        while page <= 5:
            response = await client.get(
                f"{API_URL}/athlete/activities",
                params={"page": page, "per_page": per_page},
            )
            response.raise_for_status()
            activities = response.json()
            if not activities:
                break
            for activity in activities:
                save_activity(activity)
                count += 1
            if len(activities) < per_page:
                break
            page += 1
    return count


async def sync_activity(activity_id: int) -> dict[str, Any] | None:
    """Fetch one activity after a webhook event and upsert it locally."""
    access_token = await valid_access_token()
    headers = {"Authorization": f"Bearer {access_token}"}
    async with httpx.AsyncClient(timeout=20, headers=headers) as client:
        response = await client.get(f"{API_URL}/activities/{activity_id}")
        if response.status_code == 404:
            delete_activity(activity_id)
            return None
        response.raise_for_status()
        activity = response.json()
    save_activity(activity)
    return activity


async def process_webhook_event(event: dict[str, Any]) -> str:
    """Apply a Strava webhook event for the currently connected athlete."""
    token = get_token()
    if not token:
        return "ignored:not-connected"
    if int(event.get("owner_id", 0)) != int(token.get("athlete_id") or 0):
        return "ignored:owner-mismatch"

    object_type = event.get("object_type")
    aspect_type = event.get("aspect_type")
    object_id = int(event.get("object_id", 0))

    if object_type == "activity":
        if aspect_type == "delete":
            delete_activity(object_id)
            return "deleted"
        if aspect_type in {"create", "update"}:
            await sync_activity(object_id)
            return "synced"

    updates = event.get("updates") or {}
    if (
        object_type == "athlete"
        and aspect_type == "update"
        and str(updates.get("authorized", "")).lower() == "false"
    ):
        delete_token()
        return "disconnected"
    return "ignored:unsupported"
