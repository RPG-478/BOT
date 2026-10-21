"""Logfare の OpenAI 互換 API クライアント。"""
from __future__ import annotations

import asyncio
import os
from typing import Any

import aiohttp

BASE_URL = os.getenv("LOGFARE_BASE_URL", "https://logfare.ai/v1").rstrip("/")
AUTO_MODEL = "logfare/auto"
DEFAULT_TIMEOUT = aiohttp.ClientTimeout(total=45)


def api_key() -> str | None:
    return os.getenv("LOGFARE_API_KEY")


def configured_default_model() -> str:
    return os.getenv("LOGFARE_DEFAULT_MODEL", AUTO_MODEL).strip() or AUTO_MODEL


def _is_free_chat_model(model: dict[str, Any]) -> bool:
    endpoints = model.get("endpoints") or []
    return (
        "chat/completions" in endpoints
        and model.get("requires_training_optin") is not True
        and isinstance(model.get("id"), str)
        and bool(model["id"].strip())
    )


async def fetch_free_chat_models() -> list[dict[str, Any]]:
    """Logfare の公開カタログから、free のチャットモデルだけを返す。"""
    async with aiohttp.ClientSession(timeout=DEFAULT_TIMEOUT) as session:
        async with session.get(f"{BASE_URL}/models") as response:
            response.raise_for_status()
            payload = await response.json()
    models = [model for model in payload.get("data", []) if _is_free_chat_model(model)]
    return sorted(models, key=lambda model: (model["id"] != AUTO_MODEL, model["id"]))


async def resolve_model(preferred: str | None = None) -> tuple[str, bool]:
    """指定モデルを使えるか確認し、使えなければ auto にフォールバックする。"""
    requested = (preferred or configured_default_model()).strip() or AUTO_MODEL
    try:
        model_ids = {item["id"] for item in await fetch_free_chat_models()}
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, KeyError):
        # カタログが一時的に取得できなくても、auto は Logfare 側で解決できる。
        return requested, False
    if requested in model_ids:
        return requested, True
    return AUTO_MODEL, False


async def chat(model: str, messages: list[dict[str, str]], *, max_tokens: int = 1200) -> str:
    """Chat Completions を実行し、回答本文だけを返す。"""
    key = api_key()
    if not key:
        raise RuntimeError("LOGFARE_API_KEY が設定されていません。")
    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
    }
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    async with aiohttp.ClientSession(timeout=DEFAULT_TIMEOUT) as session:
        async with session.post(f"{BASE_URL}/chat/completions", headers=headers, json=payload) as response:
            body = await response.text()
            if response.status >= 400:
                raise RuntimeError(f"Logfare API error {response.status}: {body[:300]}")
            try:
                data = await response.json()
            except ValueError as exc:
                raise RuntimeError("Logfare API の応答をJSONとして解釈できませんでした。") from exc
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError("Logfare API の応答に回答本文がありませんでした。") from exc
    return str(content or "").strip()
