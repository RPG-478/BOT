"""ユーザーごとのメッセージショートカット設定。"""
from __future__ import annotations

import copy
import re
from typing import Any

from core import guild_settings

SECTION = "message_shortcuts"
MAX_SHORTCUTS = 10
_TRIGGER_RE = re.compile(r"^\S{1,80}$")


def _all(store, guild_id: int) -> list[dict[str, Any]]:
    raw = store.get(guild_id, SECTION)
    rows = raw.get("items", []) if isinstance(raw, dict) else []
    return [copy.deepcopy(x) for x in rows if isinstance(x, dict)]


def for_user(store, guild_id: int, user_id: int) -> list[dict[str, Any]]:
    return [x for x in _all(store, guild_id) if int(x.get("user_id", 0)) == int(user_id)]


def validate_trigger(trigger: str) -> str:
    trigger = " ".join(str(trigger or "").strip().split())
    if not _TRIGGER_RE.fullmatch(trigger):
        raise ValueError("トリガーは空白を含まない1〜80文字で指定してください。")
    return trigger


async def add(store, guild_id: int, user_id: int, trigger: str, action: dict[str, Any]) -> dict[str, Any]:
    trigger = validate_trigger(trigger)
    rows = _all(store, guild_id)
    mine = [x for x in rows if int(x.get("user_id", 0)) == int(user_id)]
    if len(mine) >= MAX_SHORTCUTS:
        raise ValueError(f"ショートカットは1ユーザーにつき{MAX_SHORTCUTS}個までです。")
    if any(x.get("trigger") == trigger for x in mine):
        raise ValueError("同じトリガー名は既に登録されています。")
    item = {"id": f"{user_id}:{len(rows) + 1}", "user_id": int(user_id), "trigger": trigger,
            "action": copy.deepcopy(action)}
    rows.append(item)
    await store.update(guild_id, SECTION, items=rows)
    return item


async def update(store, guild_id: int, user_id: int, item_id: str, trigger: str | None = None,
                 action: dict[str, Any] | None = None) -> dict[str, Any]:
    rows = _all(store, guild_id)
    for item in rows:
        if item.get("id") != item_id or int(item.get("user_id", 0)) != int(user_id):
            continue
        if trigger is not None:
            trigger = validate_trigger(trigger)
            if any(x.get("trigger") == trigger and x.get("id") != item_id for x in rows
                   if int(x.get("user_id", 0)) == int(user_id)):
                raise ValueError("同じトリガー名は既に登録されています。")
            item["trigger"] = trigger
        if action is not None:
            item["action"] = copy.deepcopy(action)
        await store.update(guild_id, SECTION, items=rows)
        return item
    raise KeyError("ショートカットが見つかりません。")


async def remove(store, guild_id: int, user_id: int, item_id: str) -> bool:
    rows = _all(store, guild_id)
    kept = [x for x in rows if not (x.get("id") == item_id and int(x.get("user_id", 0)) == int(user_id))]
    if len(kept) == len(rows):
        return False
    await store.update(guild_id, SECTION, items=kept)
    return True


def matching(store, guild_id: int, trigger: str) -> list[dict[str, Any]]:
    return [x for x in _all(store, guild_id) if x.get("trigger") == trigger]
