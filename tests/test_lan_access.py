"""LAN token guard and Xiaomi sync retry behavior (2026-07-26).

改动一：服务绑 0.0.0.0 后，非回环来源必须带令牌，回环免令牌。
改动二：xiaomi 同步网络类错误指数退避重试，鉴权类错误不重试。
"""
from __future__ import annotations

import asyncio
import json

from fastapi.testclient import TestClient

from app import config, main, xiaomi_sync
from app.xiaomi_sync import XiaomiSyncError, sync_mi_fitness
from scripts import daily_sync


# ---------- 改动一：令牌来源 ----------


def test_env_token_wins(monkeypatch, tmp_path):
    monkeypatch.setenv("HEALTH_LAN_TOKEN", "env-token")
    monkeypatch.setenv("HEALTH_LAN_TOKEN_PATH", str(tmp_path / "lan_token.txt"))
    assert config._load_lan_token() == "env-token"


def test_token_generated_and_persisted(monkeypatch, tmp_path):
    monkeypatch.delenv("HEALTH_LAN_TOKEN", raising=False)
    token_path = tmp_path / "data" / "lan_token.txt"
    monkeypatch.setenv("HEALTH_LAN_TOKEN_PATH", str(token_path))
    first = config._load_lan_token()
    assert first
    # 重启（再次加载）后令牌不变，手机书签持续有效。
    assert config._load_lan_token() == first
    assert token_path.read_text(encoding="utf-8").strip() == first


# ---------- 改动一：LAN 令牌中间件 ----------


def _as_lan_client(monkeypatch):
    # TestClient 的对端标识 "testclient" 默认视同本机；清空回环名单即模拟局域网来源。
    monkeypatch.setattr(main, "_LOOPBACK_HOSTS", set())


def test_loopback_requests_need_no_token():
    assert TestClient(main.app).get("/health").status_code == 200


def test_lan_request_without_token_is_forbidden(monkeypatch):
    _as_lan_client(monkeypatch)
    client = TestClient(main.app)
    assert client.get("/").status_code == 403
    assert client.get("/mobile").status_code == 403
    assert client.post("/api/heartbeat").status_code == 403
    assert client.get("/", params={"token": "wrong"}).status_code == 403


def test_lan_request_with_query_token_allowed(monkeypatch):
    _as_lan_client(monkeypatch)
    client = TestClient(main.app)
    token = main.settings.lan_token
    assert client.get("/", params={"token": token}).status_code == 200
    assert client.post("/api/heartbeat", params={"token": token}).status_code == 200


def test_lan_request_with_header_token_allowed(monkeypatch):
    _as_lan_client(monkeypatch)
    client = TestClient(main.app)
    response = client.get("/mobile", headers={"X-LAN-Token": main.settings.lan_token})
    assert response.status_code == 200


def test_static_assets_open_on_lan(monkeypatch):
    _as_lan_client(monkeypatch)
    assert TestClient(main.app).get("/static/js/dashboard.js").status_code == 200


# ---------- 改动二：xiaomi 采集重试分类 ----------


class FlakyCollectAdapter:
    """connect 成功，采集阶段按 failures_left 次数先失败后成功。"""

    failures_left = 0
    calls = 0
    exc_factory = staticmethod(lambda: TimeoutError("timed out"))

    def __init__(self, **kwargs):
        self.kwargs = kwargs

    async def connect(self):
        return True

    async def close(self):
        pass

    async def iter_daily_activity(self, start, end):
        type(self).calls += 1
        if type(self).failures_left:
            type(self).failures_left -= 1
            raise type(self).exc_factory()
        for item in ():
            yield item

    async def _empty(self, start, end):
        for item in ():
            yield item

    iter_sleep_sessions = _empty
    iter_body_measurements = _empty
    iter_heart_rate = _empty
    iter_spo2 = _empty
    iter_stress = _empty


def _run_collect(monkeypatch, tmp_path, adapter_cls):
    async def no_sleep(_seconds):
        return None

    monkeypatch.setattr(xiaomi_sync.asyncio, "sleep", no_sleep)
    adapter_cls.failures_left = 0
    adapter_cls.calls = 0
    auth = tmp_path / "auth.json"
    auth.write_text(json.dumps({"userId": "user", "passToken": "token"}), encoding="utf-8")
    return auth


def test_transient_collect_failure_retries_with_backoff(monkeypatch, tmp_path):
    auth = _run_collect(monkeypatch, tmp_path, FlakyCollectAdapter)
    FlakyCollectAdapter.failures_left = 2  # 前两次 TimeoutError，第三次成功
    result = asyncio.run(
        sync_mi_fitness(days=1, credentials_path=auth, adapter_factory=FlakyCollectAdapter)
    )
    assert result["source"] == "mi_fitness_cloud"
    assert FlakyCollectAdapter.calls == 3


def test_persistent_timeout_eventually_fails_without_blaming_pass_token(monkeypatch, tmp_path):
    auth = _run_collect(monkeypatch, tmp_path, FlakyCollectAdapter)
    FlakyCollectAdapter.failures_left = 10
    try:
        asyncio.run(
            sync_mi_fitness(days=1, credentials_path=auth, adapter_factory=FlakyCollectAdapter)
        )
    except XiaomiSyncError as exc:
        message = str(exc)
    else:
        raise AssertionError("expected XiaomiSyncError")
    assert FlakyCollectAdapter.calls == 3  # 首轮 + 2 次重试
    assert "无需重新扫码" in message
    assert "passToken 可能已过期" not in message


def test_auth_collect_failure_is_not_retried(monkeypatch, tmp_path):
    auth = _run_collect(monkeypatch, tmp_path, FlakyCollectAdapter)
    FlakyCollectAdapter.failures_left = 10
    FlakyCollectAdapter.exc_factory = staticmethod(lambda: Exception("401 Unauthorized"))
    try:
        asyncio.run(
            sync_mi_fitness(days=1, credentials_path=auth, adapter_factory=FlakyCollectAdapter)
        )
    except XiaomiSyncError as exc:
        message = str(exc)
    else:
        raise AssertionError("expected XiaomiSyncError")
    finally:
        FlakyCollectAdapter.exc_factory = staticmethod(lambda: TimeoutError("timed out"))
    assert FlakyCollectAdapter.calls == 1  # 鉴权类错误不重试
    assert "请重新扫码登录" in message


# ---------- 改动二：daily_sync 网络类失败重试 ----------


def test_daily_sync_retries_network_failures(monkeypatch):
    monkeypatch.setattr(daily_sync, "log", lambda message: None)
    monkeypatch.setattr(daily_sync.time, "sleep", lambda seconds: None)
    calls = []

    def fake_post(path):
        calls.append(path)
        if len(calls) < 3:
            return False, "TimeoutError: timed out", True
        return True, "{}", False

    monkeypatch.setattr(daily_sync, "post_sync", fake_post)
    ok, _ = daily_sync.post_sync_with_retry("xiaomi", "/api/sync/xiaomi")
    assert ok
    assert len(calls) == 3  # 首轮 + 2 次指数退避重试


def test_daily_sync_does_not_retry_http_errors(monkeypatch):
    monkeypatch.setattr(daily_sync, "log", lambda message: None)
    monkeypatch.setattr(daily_sync.time, "sleep", lambda seconds: None)
    calls = []

    def fake_post(path):
        calls.append(path)
        return False, "HTTP 400: passToken 可能已过期", False

    monkeypatch.setattr(daily_sync, "post_sync", fake_post)
    ok, detail = daily_sync.post_sync_with_retry("xiaomi", "/api/sync/xiaomi")
    assert not ok
    assert len(calls) == 1  # HTTP/鉴权类错误不重试
