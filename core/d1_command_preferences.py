"""ローカルD1による機能アクション代理実行のユーザー別設定。"""
from __future__ import annotations

from core.storage import KVStore

_store = KVStore("d1_command_preferences")
DEFAULT_CONFIG = {"enabled": False, "actions": [], "instruction": ""}


async def ensure_loaded() -> None:
    await _store.load_all()


def get_config(user_id: int) -> dict:
    value = _store.load_local().get(str(user_id))
    if not isinstance(value, dict):
        return dict(DEFAULT_CONFIG)
    actions = [str(item).strip().lower() for item in value.get("actions", []) if str(item).strip()]
    return {
        "enabled": bool(value.get("enabled", False)),
        "actions": list(dict.fromkeys(actions))[:50],
        "instruction": str(value.get("instruction", ""))[:1000],
    }


async def set_config(user_id: int, config: dict) -> None:
    await _store.set(str(user_id), {
        "enabled": bool(config.get("enabled", False)),
        "actions": list(dict.fromkeys(
            str(item).strip().lower() for item in config.get("actions", []) if str(item).strip()
        ))[:50],
        "instruction": str(config.get("instruction", ""))[:1000],
    })


async def update(user_id: int, **changes) -> dict:
    config = get_config(user_id)
    config.update(changes)
    await set_config(user_id, config)
    return get_config(user_id)
