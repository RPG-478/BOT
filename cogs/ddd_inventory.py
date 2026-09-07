"""DDDの宝箱・アイテム用の共通定義とデータ操作。"""
from __future__ import annotations

import random
from typing import Any

ELEMENTS = ("虚", "実", "正", "負", "無")
STAT_KEYS = ("hp", "attack", "defense", "sp_atk", "sp_def", "speed")
STAT_LABELS = {
    "hp": "HP",
    "attack": "攻撃",
    "defense": "防御",
    "sp_atk": "特攻",
    "sp_def": "特防",
    "speed": "素早さ",
}

ORB_CODES = {element: f"orb_{element}" for element in ELEMENTS}
MOVE_RESET_TICKET = "move_reset_ticket"
TRADE_TICKET = "trade_ticket"
UPRAISE_CRYSTAL = "upraise_crystal"
HERB = "herb"

ITEM_LABELS = {
    **{code: f"{element}のオーブ" for element, code in ORB_CODES.items()},
    MOVE_RESET_TICKET: "技リセットチケット",
    TRADE_TICKET: "トレードチケット",
    UPRAISE_CRYSTAL: "アップレイズクリスタル",
    HERB: "薬草",
}


def item_label(item_code: str, metadata: dict | None = None) -> str:
    """プレイヤー向けのアイテム名を返す。"""
    label = ITEM_LABELS.get(item_code, item_code)
    if item_code == UPRAISE_CRYSTAL and metadata:
        boosts = metadata.get("boosts", [])
        parts = [f"{STAT_LABELS.get(boost.get('stat'), boost.get('stat'))} +{boost.get('amount')}"
                 for boost in boosts if boost.get("stat") in STAT_LABELS and isinstance(boost.get("amount"), int)]
        if parts:
            return f"{label}（{' / '.join(parts)}）"
    return label


def create_crystal_metadata(rng: random.Random | Any | None = None) -> dict:
    """宝箱の排出時に固定されるクリスタルの上昇内容を決める。"""
    rng = rng or random
    selected = rng.sample(list(STAT_KEYS), 2)
    return {"boosts": [{"stat": key, "amount": rng.randint(1, 10)} for key in selected]}


def chest_coin_reward(rng: random.Random | Any | None = None) -> int:
    """100を最頻値とする半正規分布型の100〜100,000コイン報酬。"""
    rng = rng or random
    amount = 100 + int(abs(rng.gauss(0, 12_500)))
    return max(100, min(100_000, amount))


def roll_item_reward(rng: random.Random | Any | None = None) -> dict:
    """宝箱に付属するアイテム1個を抽選する。"""
    rng = rng or random
    item_roll = rng.random()
    if item_roll < 0.52:
        return {"kind": "item", "item_code": rng.choice(list(ORB_CODES.values())), "metadata": {}}
    if item_roll < 0.68:
        return {"kind": "item", "item_code": HERB, "metadata": {}}
    if item_roll < 0.81:
        return {"kind": "item", "item_code": MOVE_RESET_TICKET, "metadata": {}}
    if item_roll < 0.92:
        return {"kind": "item", "item_code": TRADE_TICKET, "metadata": {}}
    return {"kind": "item", "item_code": UPRAISE_CRYSTAL, "metadata": create_crystal_metadata(rng)}


def roll_chest_reward(rng: random.Random | Any | None = None) -> dict:
    """宝箱1個のコインとアイテムの確定報酬を返す。"""
    rng = rng or random
    item = roll_item_reward(rng)
    return {**item, "kind": "bundle", "amount": chest_coin_reward(rng)}


def add_item(client, user_id: str, item_code: str, metadata: dict | None = None) -> dict:
    """アイテム1個を追加する。クリスタルの内容もこの時点で永続化する。"""
    record = {"user_id": str(user_id), "item_code": item_code, "metadata": metadata or {}}
    result = client.table("ddd_items").insert(record).execute()
    return result.data[0] if result.data else record


def consume_item(client, user_id: str, item_code: str) -> dict | None:
    """最も古い対象アイテムを1個だけ消費し、消費したレコードを返す。"""
    found = (client.table("ddd_items").select("*").eq("user_id", str(user_id))
             .eq("item_code", item_code).order("created_at").limit(1).execute())
    if not found.data:
        return None
    item = found.data[0]
    deleted = (client.table("ddd_items").delete().eq("id", item["id"])
               .eq("user_id", str(user_id)).execute())
    return item if deleted.data else None


def restore_item(client, item: dict) -> None:
    """後続処理が失敗した場合に、消費済みアイテムを同じ内容で復元する。"""
    client.table("ddd_items").insert({
        "user_id": str(item["user_id"]),
        "item_code": item["item_code"],
        "metadata": item.get("metadata") or {},
    }).execute()


def item_counts(client, user_id: str) -> dict[str, int]:
    """所持アイテム数をコード別に集計する。"""
    result = client.table("ddd_items").select("item_code").eq("user_id", str(user_id)).execute()
    counts: dict[str, int] = {}
    for item in result.data or []:
        code = item.get("item_code")
        if code:
            counts[code] = counts.get(code, 0) + 1
    return counts


async def setup(bot):
    """自動Cogローダー向けの空セットアップ。"""
