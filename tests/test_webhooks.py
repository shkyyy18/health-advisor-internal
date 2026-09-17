from __future__ import annotations

import asyncio
from dataclasses import replace

from fastapi.testclient import TestClient

from app import main
from app import strava


def test_webhook_verification(monkeypatch):
    monkeypatch.setattr(
        main,
        "settings",
        replace(main.settings, strava_webhook_verify_token="secret-token"),
    )
    client = TestClient(main.app)

    response = client.get(
        "/webhooks/strava",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": "secret-token",
            "hub.challenge": "challenge-value",
        },
    )

    assert response.status_code == 200
    assert response.json() == {"hub.challenge": "challenge-value"}


def test_webhook_verification_rejects_bad_token(monkeypatch):
    monkeypatch.setattr(
        main,
        "settings",
        replace(main.settings, strava_webhook_verify_token="secret-token"),
    )
    client = TestClient(main.app)
    response = client.get(
        "/webhooks/strava",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": "wrong",
            "hub.challenge": "challenge-value",
        },
    )
    assert response.status_code == 403


def test_webhook_accepts_event_and_runs_background_task(monkeypatch):
    received = []

    async def fake_process(event):
        received.append(event)
        return "synced"

    monkeypatch.setattr(main, "process_webhook_event", fake_process)
    client = TestClient(main.app)
    payload = {
        "object_type": "activity",
        "object_id": 123,
        "aspect_type": "create",
        "owner_id": 456,
        "subscription_id": 789,
        "event_time": 1_700_000_000,
        "updates": {},
    }
    response = client.post("/webhooks/strava", json=payload)

    assert response.status_code == 200
    assert response.json() == {"status": "accepted"}
    assert received == [payload]


def test_process_webhook_deletes_activity(monkeypatch):
    deleted = []
    monkeypatch.setattr(strava, "get_token", lambda: {"athlete_id": 456})
    monkeypatch.setattr(strava, "delete_activity", deleted.append)

    result = asyncio.run(
        strava.process_webhook_event(
            {
                "object_type": "activity",
                "object_id": 123,
                "aspect_type": "delete",
                "owner_id": 456,
                "updates": {},
            }
        )
    )

    assert result == "deleted"
    assert deleted == [123]


def test_process_webhook_ignores_other_athletes(monkeypatch):
    monkeypatch.setattr(strava, "get_token", lambda: {"athlete_id": 456})
    result = asyncio.run(
        strava.process_webhook_event(
            {
                "object_type": "activity",
                "object_id": 123,
                "aspect_type": "create",
                "owner_id": 999,
                "updates": {},
            }
        )
    )
    assert result == "ignored:owner-mismatch"


def test_public_tunnel_only_exposes_webhook(monkeypatch):
    monkeypatch.setattr(
        main,
        "settings",
        replace(
            main.settings,
            strava_webhook_callback_url="https://health-example.ngrok-free.app/webhooks/strava",
        ),
    )
    client = TestClient(main.app)
    response = client.get(
        "/api/activities", headers={"host": "health-example.ngrok-free.app"}
    )
    assert response.status_code == 404

    local_response = client.get("/health", headers={"host": "127.0.0.1:8000"})
    assert local_response.status_code == 200

    # 隧道判定只认 Host 与回调域名一致；x-forwarded-proto 可伪造，不再触发隧道模式
    forwarded_response = client.get(
        "/health",
        headers={"host": "localhost:8000", "x-forwarded-proto": "https"},
    )
    assert forwarded_response.status_code == 200

    tunnel_response = client.get(
        "/health",
        headers={"host": "health-example.ngrok-free.app", "x-forwarded-proto": "https"},
    )
    assert tunnel_response.status_code == 404

def test_local_strava_callback_does_not_enable_public_tunnel_mode(monkeypatch):
    monkeypatch.setattr(
        main,
        "settings",
        replace(
            main.settings,
            strava_webhook_callback_url="http://127.0.0.1:8000/webhooks/strava",
        ),
    )
    response = TestClient(main.app).get("/api/summary", headers={"host": "127.0.0.1:8000"})

    assert response.status_code == 200
