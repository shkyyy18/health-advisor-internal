from __future__ import annotations

import base64
import json
from typing import Any

import httpx

from app.config import settings

ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}
MAX_IMAGE_BYTES = 8 * 1024 * 1024


class MealAnalysisError(RuntimeError):
    pass


def validate_meal_image(image: bytes, content_type: str) -> None:
    if content_type not in ALLOWED_IMAGE_TYPES:
        raise MealAnalysisError(
            "仅支持JPEG（常见照片格式）、PNG（无损图片格式）或WebP（网页图片格式）图片。"
        )
    if not image:
        raise MealAnalysisError("没有读取到图片内容。")
    if len(image) > MAX_IMAGE_BYTES:
        raise MealAnalysisError("图片不能超过8MB（兆字节），请在手机相册中压缩后再上传。")


def _extract_output_text(payload: dict[str, Any]) -> str:
    if isinstance(payload.get("output_text"), str):
        return payload["output_text"]
    chunks: list[str] = []
    for item in payload.get("output", []):
        if not isinstance(item, dict):
            continue
        for content in item.get("content", []):
            if (
                isinstance(content, dict)
                and content.get("type") == "output_text"
                and isinstance(content.get("text"), str)
            ):
                chunks.append(content["text"])
    return "\n".join(chunks)


def _json_from_text(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = (
            cleaned.removeprefix("```json")
            .removeprefix("```")
            .rsplit("```", 1)[0]
            .strip()
        )
    try:
        result = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise MealAnalysisError("图片分析结果格式异常，请重新拍摄后再试。") from exc
    if not isinstance(result, dict):
        raise MealAnalysisError("图片分析结果不是有效对象，请重新尝试。")
    return result


def _normalize_analysis(result: dict[str, Any]) -> dict[str, Any]:
    """Keep model output shape predictable for storage and the mobile UI."""
    normalized = dict(result)
    normalized["summary"] = str(result.get("summary") or "餐食分析")
    normalized["meal_total"] = (
        result["meal_total"] if isinstance(result.get("meal_total"), dict) else {}
    )
    normalized["foods"] = (
        [item for item in result.get("foods", []) if isinstance(item, dict)]
        if isinstance(result.get("foods"), list)
        else []
    )
    for key in ("good_points", "improvements", "science_reason", "uncertainty"):
        value = result.get(key)
        normalized[key] = [str(item) for item in value] if isinstance(value, list) else []
    normalized["next_meal"] = str(result.get("next_meal") or "暂无建议")
    confidence = str(result.get("confidence") or "低")
    normalized["confidence"] = confidence if confidence in {"低", "中", "高"} else "低"
    return normalized


async def analyze_meal_photo(
    image: bytes,
    content_type: str,
    meal_type: str,
    nutrition_context: dict[str, Any],
) -> dict[str, Any]:
    validate_meal_image(image, content_type)
    if not settings.meal_llm_api_key:
        raise MealAnalysisError(
            "尚未配置MEAL_LLM_API_KEY（图片分析接口密钥），图片分析暂不可用。"
        )

    encoded = base64.b64encode(image).decode("ascii")
    prompt = f"""你是个人运动营养记录助手。分析这张{meal_type or "餐食"}照片，并结合用户目标给出可执行建议。
用户蛋白质目标：{nutrition_context.get("protein_target", "未知")}。今日训练饮食安排：{nutrition_context.get("today", "未知")}
只能根据可见食物估算；无法判断的油和调料写入uncertainty（不确定因素）。所有专业词或英文缩写首次出现时紧跟中文括号解释。份量使用个、碗、手掌、克、毫升。解释为什么改，关联热量缺口、蛋白质、训练恢复或饱腹感。热量和营养素给区间。只输出JSON（结构化文本），不要Markdown（排版标记）。
JSON结构：{{"summary":"一句话说明构成","foods":[{{"name":"食物","portion":"估计份量","kcal_range":"200–260千卡","protein_g_range":"20–26克","carb_g_range":"10–20克","fat_g_range":"5–10克"}}],"meal_total":{{"kcal_range":"","protein_g_range":"","carb_g_range":"","fat_g_range":""}},"good_points":["具体优点"],"improvements":["明确到食物和份量的调整"],"science_reason":["调整及科学原因"],"next_meal":"下一餐具体吃什么及份量","uncertainty":["照片无法确认的内容"],"confidence":"低/中/高"}}"""
    payload = {
        "model": settings.meal_llm_model,
        "input": [
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": prompt},
                    {
                        "type": "input_image",
                        "image_url": f"data:{content_type};base64,{encoded}",
                    },
                ],
            }
        ],
    }
    try:
        timeout = httpx.Timeout(90, connect=15)
        # 图片分析中转站直连可达；trust_env=False 避免 Windows 系统代理假死时
        # httpx 被动跟随死代理导致请求被拒（2026-08-13 同步失败同一根因）。
        async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
            response = await client.post(
                settings.meal_llm_base_url,
                headers={
                    "Authorization": f"Bearer {settings.meal_llm_api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise MealAnalysisError(
            f"图片分析接口返回错误：{exc.response.text[:300]}"
        ) from exc
    except httpx.HTTPError as exc:
        raise MealAnalysisError("连接图片分析服务失败，请检查网络后重试。") from exc

    return _normalize_analysis(_json_from_text(_extract_output_text(response.json())))
