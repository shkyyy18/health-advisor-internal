from __future__ import annotations

import asyncio
from dataclasses import replace

import httpx
import pytest

from app import meal_analysis
from app.meal_analysis import MealAnalysisError, analyze_meal_photo


class _FakeResponse:
    def __init__(self, payload: dict):
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


class _FakeClient:
    """Record constructor kwargs and POST calls instead of doing real HTTP."""

    instances: list["_FakeClient"] = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.posts: list[dict] = []
        type(self).instances.append(self)

    async def __aenter__(self) -> "_FakeClient":
        return self

    async def __aexit__(self, *exc) -> bool:
        return False

    async def post(self, url, headers=None, json=None):
        self.posts.append({"url": url, "headers": headers, "json": json})
        return _FakeResponse({"output_text": '{"summary":"一餐","confidence":"中"}'})


@pytest.fixture
def fake_client(monkeypatch):
    _FakeClient.instances = []
    monkeypatch.setattr(httpx, "AsyncClient", _FakeClient)
    return _FakeClient


def _settings_with_key(monkeypatch, **overrides):
    values = {
        "meal_llm_api_key": "test-key",
        "meal_llm_base_url": "https://llm.example/responses",
        "meal_llm_model": "test-model",
    }
    values.update(overrides)
    monkeypatch.setattr(
        meal_analysis, "settings", replace(meal_analysis.settings, **values)
    )


def test_analyze_meal_photo_uses_direct_client_and_meal_llm_settings(
    monkeypatch, fake_client
):
    _settings_with_key(monkeypatch)

    result = asyncio.run(
        analyze_meal_photo(b"fake-image", "image/jpeg", "午餐", {"protein_target": "120克"})
    )

    assert result["summary"] == "一餐"
    client = fake_client.instances[0]
    # 中转站直连可达；trust_env=False 避免系统代理假死时被动跟随死代理。
    assert client.kwargs.get("trust_env") is False
    post = client.posts[0]
    assert post["url"] == "https://llm.example/responses"
    assert post["headers"]["Authorization"] == "Bearer test-key"
    assert post["json"]["model"] == "test-model"


def test_analyze_meal_photo_requires_meal_llm_key(monkeypatch, fake_client):
    _settings_with_key(monkeypatch, meal_llm_api_key="")

    with pytest.raises(MealAnalysisError, match="MEAL_LLM_API_KEY"):
        asyncio.run(analyze_meal_photo(b"fake-image", "image/jpeg", "午餐", {}))
    assert fake_client.instances == []
