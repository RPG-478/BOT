"""BlockRunメンションエージェントのユーザー別設定。"""
from __future__ import annotations

from core.storage import KVStore

_store = KVStore("blockrun_preferences")
ALLOWED_TOOLS = {"web_search"}
DEFAULT_CONFIG = {"enabled": False, "tools": ["web_search"], "instruction": ""}


async def ensure_loaded() -> None:
    await _store.load_all()


def get_config(user_id: int) -> dict:
    value = _store.load_local().get(str(user_id))
    if not isinstance(value, dict):
        return dict(DEFAULT_CONFIG)
    tools = [tool for tool in value.get("tools", []) if tool in ALLOWED_TOOLS]
    return {
        "enabled": bool(value.get("enabled", False)),
        "tools": tools,
        "instruction": str(value.get("instruction", ""))[:1000],
    }


async def set_config(user_id: int, config: dict) -> None:
    tools = [tool for tool in config.get("tools", []) if tool in ALLOWED_TOOLS]
    await _store.set(str(user_id), {
        "enabled": bool(config.get("enabled", False)),
        "tools": tools,
        "instruction": str(config.get("instruction", ""))[:1000],
    })


async def update(user_id: int, **changes) -> dict:
    config = get_config(user_id)
    config.update(changes)
    await set_config(user_id, config)
    return get_config(user_id)
