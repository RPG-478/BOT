"""DSH Our Free Model の OpenAI 互換ゲートウェイを呼び出す。"""
from __future__ import annotations

import os
from typing import Any

import aiohttp

TIMEOUT = aiohttp.ClientTimeout(total=90)


def base_url() -> str:
    return os.getenv("DSH_GATEWAY_BASE_URL", "").strip().rstrip("/")


def api_key() -> str:
    return os.getenv("DSH_GATEWAY_API_KEY", "").strip()


def configured() -> bool:
    return bool(base_url() and api_key())


def default_model() -> str | None:
    model = os.getenv("DSH_GATEWAY_MODEL", "").strip()
    return model if configured() and model.startswith("combo:") else None


def is_combo(model: str) -> bool:
    return model.startswith("combo:")


def _endpoint(path: str) -> str:
    url = base_url()
    if not url:
        raise RuntimeError("DSH_GATEWAY_BASE_URL が設定されていません。")
    if url.endswith("/v1"):
        return f"{url}/{path}"
    return f"{url}/v1/{path}"


def _headers() -> dict[str, str]:
    key = api_key()
    if not key:
        raise RuntimeError("DSH_GATEWAY_API_KEY が設定されていません。")
    return {"Authorization": f"Bearer {key}"}


async def fetch_combo_models() -> list[dict[str, str]]:
    """設定済みのフォールバックチェーンのみを選択肢に出す。"""
    if not configured():
        return []
    async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
        async with session.get(_endpoint("models"), headers=_headers()) as response:
            response.raise_for_status()
            payload = await response.json()
    rows = payload.get("data", []) if isinstance(payload, dict) else []
    if not isinstance(rows, list):
        raise RuntimeError("DSH のモデル一覧の形式が不正です。")
    return sorted(
        ({"id": row["id"], "name": row.get("name") or row["id"]}
         for row in rows if isinstance(row, dict) and isinstance(row.get("id"), str)
         and is_combo(row["id"])),
        key=lambda row: row["id"],
    )


async def chat(model: str, messages: list[dict[str, str]], *, max_tokens: int = 1200) -> str:
    if not is_combo(model):
        raise ValueError("DSH には combo モデルのみ指定できます。")
    payload: dict[str, Any] = {"model": model, "messages": messages, "max_tokens": max_tokens}
    headers = {**_headers(), "Content-Type": "application/json"}
    async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
        async with session.post(_endpoint("chat/completions"), headers=headers, json=payload) as response:
            if response.status >= 400:
                # 上流のエラーボディには認証情報やプロンプトが含まれる可能性がある。
                raise RuntimeError(f"DSH gateway error {response.status}")
            data = await response.json()
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError("DSH gateway の応答に回答本文がありませんでした。") from exc
    if isinstance(content, list):
        content = "\n".join(
            part.get("text", "") for part in content
            if isinstance(part, dict) and isinstance(part.get("text"), str)
        )
    return str(content or "").strip()
