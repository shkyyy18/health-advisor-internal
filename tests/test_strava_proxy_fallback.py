from __future__ import annotations

import asyncio

import httpx
import pytest

from app import strava


class _FakeClient:
    """首次（代理优先）请求按脚本失败/成功，记录每次构造的 kwargs。"""

    instances: list["_FakeClient"] = []
    # "connect_error"：首个 client 的 post 抛 ConnectError；"ok"：全部成功
    mode = "ok"

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        type(self).instances.append(self)

    async def __aenter__(self) -> "_FakeClient":
        return self

    async def __aexit__(self, *exc) -> bool:
        return False

    async def post(self, url, **kwargs):
        is_fallback = self.kwargs.get("trust_env") is False
        if type(self).mode == "connect_error" and not is_fallback:
            raise httpx.ConnectError("system proxy points at dead port")
        return {"url": url, "trust_env": self.kwargs.get("trust_env", "default")}


@pytest.fixture
def fake_client(monkeypatch):
    _FakeClient.instances = []
    monkeypatch.setattr(httpx, "AsyncClient", _FakeClient)
    return _FakeClient


async def _post_via_helper() -> dict:
    async def _body(client: httpx.AsyncClient) -> dict:
        return await client.post("https://www.strava.com/oauth/token")

    return await strava._run_with_client({"timeout": 5}, _body)


def test_connect_error_falls_back_to_direct_client(fake_client):
    _FakeClient.mode = "connect_error"

    result = asyncio.run(_post_via_helper())

    assert result["trust_env"] is False
    assert len(fake_client.instances) == 2
    # 首次按现状（不显式传 trust_env，跟随 httpx 默认）
    assert "trust_env" not in fake_client.instances[0].kwargs
    # 回退的第二次必须直连
    assert fake_client.instances[1].kwargs.get("trust_env") is False


def test_successful_first_attempt_does_not_fall_back(fake_client):
    _FakeClient.mode = "ok"

    result = asyncio.run(_post_via_helper())

    assert result["trust_env"] == "default"
    assert len(fake_client.instances) == 1
    assert "trust_env" not in fake_client.instances[0].kwargs


def test_fallback_failure_propagates_original_error(monkeypatch):
    class _AlwaysFailClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, url, **kwargs):
            raise httpx.ConnectError("still dead")

    monkeypatch.setattr(httpx, "AsyncClient", _AlwaysFailClient)
    with pytest.raises(httpx.ConnectError):
        asyncio.run(_post_via_helper())
