# -*- coding: utf-8 -*-
"""
ダンジョンシステム Cog（スタンドアロン版）
dungeon.py - Discord.py Cog形式

【必須設定】
  .env:
    DUNGEON_IMG_CHANNEL_ID=画像投稿チャンネルID
  
  Supabase テーブル:
    - dungeon_maps (floor, grid, used_coords, start_pos)
    - dungeon_players (user_id, floor, x, y, hp, max_hp, atk, def_, spd, crit)
    - dungeon_bases (user_id, floor, x, y)
  
  main.py:
    await bot.load_extension('cogs.dungeon')
"""

import os
import discord
import json
import random
import asyncio
import io
import datetime
import logging
from discord.ui import View
from discord import app_commands, Interaction
from discord.ext import commands, tasks
from discord.ext.commands import Cog
from PIL import Image, ImageDraw
from zoneinfo import ZoneInfo

# ============================================================
#  タイムゾーン
# ============================================================
JST = ZoneInfo("Asia/Tokyo")

# ============================================================
#  定数（ダンジョンシステム用）
# ============================================================

# マップ定義
D_MAP_W = 101
D_MAP_H = 101
D_FLOORS = 40
D_VIEW_R = 5
TILE = 32

# タイルタイプ
D_WALL = "wall"
D_FLOOR = "floor"
D_START = "start"
D_STAIRS = "stairs"
D_CHEST = "chest"
D_TRAP = "trap"
D_SHOP = "shop"
D_BASE = "base"
D_MINE = "mine"
D_REST = "rest"
D_SHRINE = "shrine"
D_EVENT = "event"

I_WALL = "i_wall"
I_FLOOR = "i_floor"
I_EXIT = "i_exit"
I_COUNTER = "i_counter"
I_REST = "i_rest"
I_STORAGE = "i_storage"
I_BAKERY = "i_bakery"
I_DOUBLE = "i_double"
I_SLOT = "i_slot"

# バイオーム定義 (フロア範囲, 名前, 壁emoji, 床emoji, 霧emoji, 色)
D_BIOMES = [
    (range(1,  10),  "洞窟",     "⬜", "⬛", "🌫️", 0x5C4033),
    (range(10,  20),  "森",       "🟫", "🟩", "🌫️", 0x2D5A1B),
    (range(20,  30),  "氷雪地帯", "⬜", "🔹", "🌫️", 0x5B9BD5),
    (range(30, 41),  "砂漠地帯", "🟧", "🟨", "🌫️", 0xC8600A),
]

# エンカウント率
D_ENCOUNTER_RATES = {
    "洞窟":     0.05,
    "森":       0.20,
    "氷雪地帯": 0.07,
    "砂漠地帯": 0.13,
}

SEASON_ID = os.environ.get(
    "DUNGEON_SEASON_ID",
    f"season-{datetime.datetime.now(JST).strftime('%Y-%m')}",
)
JOB_MASTER = {
    "warrior": {"name": "戦士", "atk": 4, "def_": 4, "max_hp": 30, "spd": 0, "crit": 0.00, "skill": "power_strike"},
    "rogue": {"name": "盗賊", "atk": 2, "def_": 0, "max_hp": 0, "spd": 5, "crit": 0.08, "skill": "smoke_bomb"},
    "mage": {"name": "魔術師", "atk": 7, "def_": -1, "max_hp": -10, "spd": 1, "crit": 0.02, "skill": "fireball"},
}
EQUIPMENT_MASTER = {
    "iron_sword": {"name": "鉄の剣", "slot": "weapon", "atk": 5, "def_": 0, "hp": 0, "crit": 0},
    "leather_armor": {"name": "革鎧", "slot": "armor", "atk": 0, "def_": 3, "hp": 15, "crit": 0},
    "lucky_charm": {"name": "幸運のお守り", "slot": "accessory", "atk": 0, "def_": 0, "hp": 0, "crit": 0.10},
    "desert_ring": {"name": "砂漠の指輪", "slot": "accessory", "atk": 3, "def_": 0, "hp": 5, "crit": 0.02},
}
# 拡張コンテンツ定義。既存データに後方互換で追加できるよう、報酬はinventoryへ格納する。
ELEMENTS = {
    "none": {"name": "無", "weak": [], "resist": []},
    "fire": {"name": "火", "weak": ["ice"], "resist": ["fire"]},
    "ice": {"name": "氷", "weak": ["fire", "thunder"], "resist": ["ice"]},
    "thunder": {"name": "雷", "weak": ["water"], "resist": ["thunder"]},
    "water": {"name": "水", "weak": ["fire"], "resist": ["water"]},
    "light": {"name": "光", "weak": ["dark"], "resist": ["light"]},
    "dark": {"name": "闇", "weak": ["light"], "resist": ["dark"]},
}
STATUS_EFFECTS = {
    "poison": {"name": "毒", "turns": 3}, "burn": {"name": "火傷", "turns": 3},
    "freeze": {"name": "凍結", "turns": 1}, "paralyze": {"name": "麻痺", "turns": 1},
    "bleed": {"name": "出血", "turns": 3}, "silence": {"name": "沈黙", "turns": 2},
    "curse": {"name": "呪い", "turns": 4},
}
WEAPON_TYPES = {
    "iron_sword": {"name": "鉄の剣", "kind": "sword", "element": "none", "description": "安定した単体攻撃"},
    "moon_blade": {"name": "月影剣", "kind": "sword", "element": "light", "description": "闇属性への特効"},
    "giant_axe": {"name": "巨人斧", "kind": "axe", "element": "none", "description": "高威力・低速度"},
    "venom_dagger": {"name": "毒牙短剣", "kind": "dagger", "element": "dark", "description": "毒を付与"},
    "storm_bow": {"name": "嵐の弓", "kind": "bow", "element": "thunder", "description": "先制しやすい"},
    "frost_staff": {"name": "氷晶杖", "kind": "staff", "element": "ice", "description": "凍結を付与"},
    "sun_spear": {"name": "陽光槍", "kind": "spear", "element": "light", "description": "アンデッド特効"},
}
EQUIPMENT_MASTER.update({
    key: {"name": data["name"], "slot": "weapon", "atk": atk, "def_": 0, "hp": hp, "crit": crit,
          "element": data["element"], "kind": data["kind"], "description": data["description"]}
    for key, data, atk, hp, crit in [
        ("moon_blade", WEAPON_TYPES["moon_blade"], 9, 0, 0.04),
        ("giant_axe", WEAPON_TYPES["giant_axe"], 14, -5, -0.02),
        ("venom_dagger", WEAPON_TYPES["venom_dagger"], 6, 0, 0.12),
        ("storm_bow", WEAPON_TYPES["storm_bow"], 7, 0, 0.08),
        ("frost_staff", WEAPON_TYPES["frost_staff"], 8, 0, 0.03),
        ("sun_spear", WEAPON_TYPES["sun_spear"], 10, 5, 0.02),
    ]
})
RELIC_MASTER = {
    "lucky_coin": {"name": "幸運硬貨", "description": "宝箱報酬の抽選が少し良くなる", "effect": "treasure"},
    "phoenix_ash": {"name": "不死鳥の灰", "description": "HP0時に一度だけ30%で復活", "effect": "revive"},
    "explorer_compass": {"name": "探検家の羅針盤", "description": "隠し部屋とイベントを発見しやすい", "effect": "explore"},
    "iron_will": {"name": "鉄の意志", "description": "HP30%未満で防御力+8", "effect": "survive"},
    "d1_tactics": {"name": "作戦教本", "description": "D1の安全重視作戦を強化", "effect": "d1"},
}
QUEST_MASTER = {
    "first_10_steps": {"name": "最初の遠征", "description": "10ターン移動する", "kind": "turns", "target": 10, "reward": {"xp": 80, "season_score": 50}},
    "monster_hunter": {"name": "魔物狩り", "description": "敵を5体倒す", "kind": "kills", "target": 5, "reward": {"coins": 250, "season_score": 80}},
    "treasure_route": {"name": "宝物街道", "description": "宝箱を3個開ける", "kind": "chests", "target": 3, "reward": {"bread": 5, "season_score": 80}},
    "deep_explorer": {"name": "深層探索", "description": "10階へ到達する", "kind": "floor", "target": 10, "reward": {"relic": "explorer_compass", "season_score": 150}},
}
ROOM_MODIFIERS = {
    "fog": {"name": "濃霧", "description": "エンカウント率が上がる"},
    "blessing": {"name": "祝福の階", "description": "回復量が増える"},
    "cursed": {"name": "呪われた階", "description": "報酬は増えるが罠も増える"},
    "treasure": {"name": "宝物の階", "description": "宝箱が多い"},
}
D1_PLANS = {
    "safe": "安全探索", "speed": "最短攻略", "treasure": "財宝優先",
    "battle": "戦闘優先", "explore": "探索優先", "boss": "ボス準備優先",
}
ACHIEVEMENTS = {
    "first_step": "初めての一歩", "floor_10": "森の踏破者", "floor_20": "氷原の生存者",
    "floor_40": "深層の覇者", "first_boss": "ボスブレイカー", "treasure_hunter": "宝箱荒らし",
    "skill_user": "スキルの使い手", "camp_builder": "野営地の開拓者",
}

# タイルカラー (RGB)
TILE_COLORS = {
    D_WALL:   {"洞窟": (80,60,50),    "森": (40,60,20),   "氷雪地帯": (200,220,240), "砂漠地帯": (120,80,30)},
    D_FLOOR:  {"洞窟": (40,30,25),    "森": (60,100,30),  "氷雪地帯": (100,160,200), "砂漠地帯": (200,160,60)},
    D_START:  (30,100,220),
    D_STAIRS: (220,60,60),
    D_CHEST:  (220,200,30),
    D_TRAP:   None,
    D_SHOP:   (180,80,200),
    D_BASE:   (80,120,220),
    D_MINE:   (255,0,120),
    D_REST:   (80,180,120),
    D_SHRINE: (180,120,255),
    D_EVENT:  (255,150,60),
    "player": (30,220,120),
    "fog":    (0,0,0),
}

# アセット設定
ASSET_CONFIG = {
    ("洞窟", D_WALL): "rock.PNG",
    ("洞窟", D_FLOOR): "jimen.png",
    ("森", D_WALL): "mori_kabe.png",
    ("森", D_FLOOR): "mori_yuka.png",
    ("氷雪地帯", D_WALL): "Y_k.png",
    ("氷雪地帯", D_FLOOR): "Y_y.png",
    ("砂漠地帯", D_WALL): "Y_k.png",
    ("砂漠地帯", D_FLOOR): "Y_y.png",
}

# 敵データベース
D_ENEMY_NAMES = {
    "洞窟":     ["コウモリ","ゴブリン","岩石スライム"],
    "森":       ["オオカミ","毒キノコ","トレント"],
    "氷雪地帯": ["雪男","アイスゴーレム","白熊"],
    "砂漠地帯": ["サソリ","砂蛇","炎トカゲ"],
}

D_SUPERENEMY_NAMES = {
    "洞窟":     ["セミオートキラーマシン"],
    "森":       ["邪蛇"],
    "氷雪地帯": ["雪女"],
    "砂漠地帯": ["鬼"],
}

D_BOSS_NAMES = {
    "洞窟":     ["ドラゴン"],
    "森":       ["ヌシ","ぱすた"],
    "氷雪地帯": ["凍ったコッペパン"],
    "砂漠地帯": ["炎龍"],
}

ENEMY_STATS_MASTER = {
    "コウモリ":       {"hp_m": 0.7, "atk_m": 0.5, "def_m": 0.5, "spd": 10, "crit": 0,    "ai": ["attack","wait"], "coin_m": 0.8, "xp_m": 0.8, "boxes": 0},
    "ゴブリン":       {"hp_m": 1.0, "atk_m": 1.1, "def_m": 0.8, "spd": 15, "crit": 0.08, "ai": ["attack"], "coin_m": 1.0, "xp_m": 1.0, "boxes": 0},
    "岩石スライム":   {"hp_m": 1.5, "atk_m": 0.8, "def_m": 1.8, "spd": 5,  "crit": 0.02, "ai": ["attack"], "coin_m": 1.2, "xp_m": 1.1, "boxes": 0},
    "オオカミ":       {"hp_m": 0.9, "atk_m": 1.2, "def_m": 0.7, "spd": 20, "crit": 0.10, "ai": ["attack"], "coin_m": 1.1, "xp_m": 1.2, "boxes": 0},
    "毒キノコ":       {"hp_m": 1.2, "atk_m": 0.8, "def_m": 1.0, "spd": 5,  "crit": 0.05, "ai": ["attack"], "coin_m": 1.0, "xp_m": 1.0, "boxes": 0},
    "トレント":       {"hp_m": 2.0, "atk_m": 1.0, "def_m": 1.5, "spd": 3,  "crit": 0.03, "ai": ["attack","attack","heal"], "coin_m": 1.5, "xp_m": 1.5, "boxes": 0},
    
    "セミオートキラーマシン": {"hp_m": 4.5, "atk_m": 2.8, "def_m": 1.5, "spd": 22, "crit": 0.25, "ai": ["attack"], "coin_m": 3.0, "xp_m": 5.0, "boxes": 1},
    "邪蛇":           {"hp_m": 3.0, "atk_m": 3.4, "def_m": 1.2, "spd": 28, "crit": 0.15, "ai": ["attack"], "coin_m": 2.5, "xp_m": 4.0, "boxes": 1},
    
    "ヌシ":           {"hp_m": 20.0, "atk_m": 4.5, "def_m": 2.2, "spd": 12, "crit": 0.10, "ai": ["attack"], "coin_m": 10.0, "xp_m": 10.0, "boxes": 5},
    "ドラゴン":       {"hp_m": 18.0, "atk_m": 5.0, "def_m": 2.5, "spd": 20, "crit": 0,    "ai": ["attack"], "coin_m": 12.0, "xp_m": 12.0, "boxes": 5},
    "ぱすた":        {"hp_m": 100, "atk_m": 0, "def_m": 10, "spd": 100, "crit": 0,     "ai": ["wait"], "coin_m": 0.1, "xp_m": 0.1, "boxes": 0},

    "ミミック":       {"hp_m": 2.5, "atk_m": 2.0, "def_m": 1.2, "spd": 8,  "crit": 0.25, "ai": ["attack"], "coin_m": 5.0, "xp_m": 3.0, "boxes": 1},
    "default":        {"hp_m": 1.0, "atk_m": 1.0, "def_m": 1.0, "spd": 10, "crit": 0.05, "ai": ["attack"], "coin_m": 1.0, "xp_m": 1.0, "boxes": 0}
}
ENEMY_STATS_MASTER.update({
    "洞窟コウモリ王": {"hp_m": 2.0, "atk_m": 1.4, "def_m": 0.8, "spd": 25, "crit": 0.18, "ai": ["attack", "strong_attack"], "coin_m": 2.0, "xp_m": 2.0, "boxes": 1},
    "毒沼蛙": {"hp_m": 1.3, "atk_m": 1.0, "def_m": 1.0, "spd": 8, "crit": 0.05, "ai": ["attack", "heal"], "coin_m": 1.4, "xp_m": 1.5, "boxes": 0},
    "森の狩人": {"hp_m": 1.1, "atk_m": 1.8, "def_m": 0.8, "spd": 18, "crit": 0.2, "ai": ["attack", "wait"], "coin_m": 1.8, "xp_m": 1.6, "boxes": 0},
    "氷晶精": {"hp_m": 1.4, "atk_m": 1.5, "def_m": 1.5, "spd": 12, "crit": 0.08, "ai": ["attack", "wait"], "coin_m": 1.6, "xp_m": 1.8, "boxes": 1},
    "砂漠盗賊": {"hp_m": 1.0, "atk_m": 1.7, "def_m": 0.9, "spd": 24, "crit": 0.16, "ai": ["attack", "attack", "wait"], "coin_m": 2.2, "xp_m": 1.7, "boxes": 0},
    "雷獣": {"hp_m": 2.2, "atk_m": 2.1, "def_m": 1.2, "spd": 30, "crit": 0.22, "ai": ["strong_attack", "attack"], "coin_m": 2.8, "xp_m": 2.5, "boxes": 2},
    "深淵騎士": {"hp_m": 3.0, "atk_m": 2.4, "def_m": 2.4, "spd": 10, "crit": 0.12, "ai": ["attack", "heal"], "coin_m": 3.2, "xp_m": 3.0, "boxes": 2},
})
D_ENEMY_NAMES["洞窟"].extend(["洞窟コウモリ王", "毒沼蛙"])
D_ENEMY_NAMES["森"].extend(["森の狩人"])
D_ENEMY_NAMES["氷雪地帯"].extend(["氷晶精", "雷獣"])
D_ENEMY_NAMES["砂漠地帯"].extend(["砂漠盗賊", "深淵騎士"])

# ============================================================
#  グローバルメモリキャッシュ
# ============================================================

dg_maps    = {}  # {floor: [[...], [...]]}
dg_players = {}  # {uid: {floor, x, y, hp, max_hp, atk, def_, spd, crit}}
dg_starts  = {}  # {floor: (x, y)}
dg_used    = {}  # {floor: set((x, y), ...)}
dg_bases   = {}  # {uid: (floor, x, y)}
_ASSET_CACHE = {}
_PLAYER_LOCKS = {}

# 環境変数
DUNGEON_IMG_CHANNEL_ID = int(os.environ.get("DUNGEON_IMG_CHANNEL_ID", 0))
D1_ENDPOINT = os.environ.get("D1_ENDPOINT", "http://127.0.0.1:8082/v1/systemone")
logger = logging.getLogger(__name__)

# ============================================================
#  ヘルパー関数
# ============================================================

def d_get_biome(floor):
    """フロアからバイオーム情報を取得"""
    for r, name, wall_e, floor_e, fog_e, color in D_BIOMES:
        if floor in r:
            return name, wall_e, floor_e, fog_e, color
    return "洞窟", "⬜", "⬛", "🌫️", 0x5C4033

def d_ensure_map(floor):
    """フロアのマップが存在しなければ生成"""
    if floor not in dg_maps:
        dg_maps[floor] = d_gen_floor(floor)
        dg_used[floor] = set()

def d_get_cell(floor, x, y):
    """指定座標のセルタイプを取得"""
    d_ensure_map(floor)
    if 0 <= y < D_MAP_H and 0 <= x < D_MAP_W:
        return dg_maps[floor][y][x]
    return D_WALL

def d_consume(floor, x, y):
    """座標を消費（床に変更）"""
    dg_used[floor].add((x, y))
    dg_maps[floor][y][x] = D_FLOOR

def d_get_player(uid):
    """プレイヤーのダンジョンデータを取得する。未保存の新規ユーザーも安全な初期値を持つ。"""
    uid = str(uid)
    if uid not in dg_players:
        dg_players[uid] = {
            "floor": 1, "x": 1, "y": 1,
            "hp": 100, "max_hp": 100,
            "atk": 10, "def_": 3, "spd": 10, "crit": 0.05,
            "xp": 0, "level": 1, "boxes": 0,
            "bread": 0, "chips": 0,
            "job": "warrior", "equipment": {}, "inventory": {},
            "achievements": [], "season_id": SEASON_ID, "season_score": 0,
            "turns": 0, "cooldowns": {},
            "relics": [], "active_effects": [], "materials": {},
            "quests": {key: {"progress": 0, "completed": False} for key in QUEST_MASTER},
            "run_modifiers": [], "camp_facilities": {"inn": 1, "forge": 0, "guild": 0},
            "battle_stats": {"kills": 0, "chests": 0, "escapes": 0},
        }
    else:
        p = dg_players[uid]
        p.setdefault("xp", 0); p.setdefault("level", 1)
        p.setdefault("boxes", 0); p.setdefault("bread", 0); p.setdefault("chips", 0)
        p.setdefault("job", "warrior"); p.setdefault("equipment", {})
        p.setdefault("inventory", {}); p.setdefault("achievements", [])
        p.setdefault("season_id", SEASON_ID); p.setdefault("season_score", 0)
        p.setdefault("turns", 0); p.setdefault("cooldowns", {})
        p.setdefault("relics", []); p.setdefault("active_effects", []); p.setdefault("materials", {})
        p.setdefault("quests", {key: {"progress": 0, "completed": False} for key in QUEST_MASTER})
        p.setdefault("run_modifiers", []); p.setdefault("camp_facilities", {"inn": 1, "forge": 0, "guild": 0})
        p.setdefault("battle_stats", {"kills": 0, "chests": 0, "escapes": 0})
        for key in QUEST_MASTER:
            p["quests"].setdefault(key, {"progress": 0, "completed": False})
        if p["season_id"] != SEASON_ID:
            p["season_id"] = SEASON_ID
            p["season_score"] = 0
    return dg_players[uid]


def d_effective_stats(player):
    """職業・装備込みの実効ステータスを返す。"""
    p = player
    job = JOB_MASTER.get(p.get("job", "warrior"), JOB_MASTER["warrior"])
    stats = {
        "atk": p.get("atk", 10) + job["atk"],
        "def_": p.get("def_", 3) + job["def_"],
        "max_hp": p.get("max_hp", 100) + job["max_hp"],
        "spd": p.get("spd", 10) + job["spd"],
        "crit": p.get("crit", 0.05) + job["crit"],
    }
    for key in p.get("equipment", {}).values():
        item = EQUIPMENT_MASTER.get(key, {})
        stats["atk"] += item.get("atk", 0)
        stats["def_"] += item.get("def_", 0)
        stats["max_hp"] += item.get("hp", 0)
        stats["crit"] += item.get("crit", 0)
    if "iron_will" in p.get("relics", []) and p.get("hp", 0) <= stats["max_hp"] * 0.30:
        stats["def_"] += 8
    if "storm_bow" in p.get("inventory", {}) and p.get("inventory", {}).get("storm_bow", 0) > 0:
        stats["spd"] += 2
    if "giant_axe" in p.get("equipment", {}).values():
        stats["spd"] -= 2
    stats["max_hp"] = max(1, stats["max_hp"])
    stats["def_"] = max(0, stats["def_"])
    stats["spd"] = max(0, stats["spd"])
    return stats


def d_progress_quest(uid, kind, amount=1, supabase=None):
    """既存JSON状態だけで進むクエスト。報酬は完了時に一度だけ付与する。"""
    p = d_get_player(uid)
    completed = []
    for key, quest in QUEST_MASTER.items():
        state = p["quests"].setdefault(key, {"progress": 0, "completed": False})
        if state.get("completed") or quest["kind"] != kind:
            continue
        state["progress"] = min(quest["target"], state.get("progress", 0) + int(amount))
        if state["progress"] >= quest["target"]:
            state["completed"] = True
            completed.append(key)
    return completed

def d_grant_relic(uid, relic_key):
    p = d_get_player(uid)
    if relic_key in RELIC_MASTER and relic_key not in p["relics"]:
        p["relics"].append(relic_key)
        return RELIC_MASTER[relic_key]["name"]
    return None

def d_floor_modifier(floor):
    """フロアごとの軽量な変異。固定化してD1にもログで伝えられる。"""
    key = list(ROOM_MODIFIERS)[(floor - 1) % len(ROOM_MODIFIERS)]
    return ROOM_MODIFIERS[key]["name"]

def d_content_summary(uid):
    p = d_get_player(uid)
    quests = [f"{QUEST_MASTER[k]['name']} {v.get('progress',0)}/{QUEST_MASTER[k]['target']}" for k, v in p["quests"].items() if not v.get("completed")]
    relics = [RELIC_MASTER[k]["name"] for k in p.get("relics", []) if k in RELIC_MASTER]
    return quests[:2], relics[:3]

def d_apply_status(uid, status_key, turns=None):
    p = d_get_player(uid)
    if status_key not in STATUS_EFFECTS:
        return
    turns = turns or STATUS_EFFECTS[status_key]["turns"]
    effects = p.setdefault("active_effects", [])
    for effect in effects:
        if isinstance(effect, dict) and effect.get("key") == status_key:
            effect["turns"] = max(effect.get("turns", 0), turns)
            return
    effects.append({"key": status_key, "turns": turns})

def d_tick_status(uid):
    """状態異常を1ターン進め、表示用ログとダメージを返す。"""
    p = d_get_player(uid)
    logs = []
    remaining = []
    for effect in p.setdefault("active_effects", []):
        if not isinstance(effect, dict):
            continue
        key = effect.get("key")
        turns = int(effect.get("turns", 0))
        if key in ("poison", "burn", "bleed"):
            damage = max(1, int(d_effective_stats(p)["max_hp"] * (0.03 if key == "poison" else 0.04)))
            p["hp"] = max(0, p["hp"] - damage)
            logs.append(f"{STATUS_EFFECTS.get(key, {}).get('name', key)}で{damage}ダメージ")
        turns -= 1
        if turns > 0:
            remaining.append({"key": key, "turns": turns})
    p["active_effects"] = remaining
    return logs

def d_unlock_achievement(uid, key):
    p = d_get_player(uid)
    if key in ACHIEVEMENTS and key not in p["achievements"]:
        p["achievements"].append(key)
        p["season_score"] += 100
        return ACHIEVEMENTS[key]
    return None


def d_job_name(uid):
    return JOB_MASTER.get(d_get_player(uid).get("job", "warrior"), JOB_MASTER["warrior"])["name"]


def d_get_lock(uid):
    """ユーザー単位の排他ロックを取得する。"""
    uid = str(uid)
    return _PLAYER_LOCKS.setdefault(uid, asyncio.Lock())


async def d_apply_economy(uid, supabase, coins=0):
    """ウォレットを更新する。SQL RPCがあれば原子処理を優先し、旧環境には安全なフォールバックを使う。"""
    if not supabase or not coins:
        return True

    def _apply():
        try:
            result = supabase.rpc("dungeon_apply_coins", {
                "p_user_id": str(uid), "p_delta": int(coins)
            }).execute()
            if result.data is not False:
                return True
        except Exception:
            logger.warning("dungeon_apply_coins RPC unavailable; using fallback", exc_info=True)

        row = supabase.table("users").select("balance").eq("user_id", str(uid)).execute()
        current = int(row.data[0].get("balance") or 0) if row.data else 10
        # 罠などの減算は残高0を下限とし、ゲーム操作自体は失敗させない。
        new_balance = max(0, current + int(coins))
        if row.data:
            updated = (supabase.table("users").update({"balance": new_balance})
                       .eq("user_id", str(uid)).eq("balance", current).execute())
            return bool(updated.data)
        inserted = supabase.table("users").insert({
            "user_id": str(uid), "balance": new_balance, "debt": 0
        }).execute()
        return bool(inserted.data)

    return await asyncio.to_thread(_apply)


async def d_apply_reward(uid, supabase, *, coins=0, xp=0, boxes=0, bread=0, chips=0, items=None, equipment=None, relic=None, material=None, achievement=None, season_score=0):
    """戦利品をプレイヤーとウォレットへ一度のアクションで反映する。"""
    if not await d_apply_economy(uid, supabase, coins):
        raise RuntimeError("コイン残高を更新できませんでした")
    p = d_get_player(uid)
    p["xp"] = max(0, p["xp"] + int(xp))
    p["boxes"] = max(0, p["boxes"] + int(boxes))
    p["bread"] = max(0, p["bread"] + int(bread))
    p["chips"] = max(0, p["chips"] + int(chips))
    for item_key, amount in (items or {}).items():
        p["inventory"][item_key] = max(0, p["inventory"].get(item_key, 0) + int(amount))
    if equipment:
        p["inventory"][equipment] = p["inventory"].get(equipment, 0) + 1
        slot = EQUIPMENT_MASTER.get(equipment, {}).get("slot")
        if slot and slot not in p["equipment"]:
            p["equipment"][slot] = equipment
    if relic:
        d_grant_relic(uid, relic)
    if material:
        p["materials"][material] = p["materials"].get(material, 0) + 1
    if achievement:
        d_unlock_achievement(uid, achievement)
    p["season_score"] += int(season_score)
    while p["xp"] >= p["level"] * 100:
        p["xp"] -= p["level"] * 100
        p["level"] += 1
        p["max_hp"] += 10
        p["hp"] = p["max_hp"]
        p["atk"] += 1
    return p

def d_hpbar(hp, max_hp, width=10):
    """HP バーを生成"""
    filled = int(width * hp / max(max_hp, 1))
    return "█" * filled + "░" * (width - filled)

def d_open_chest(uid, supabase):
    """宝箱の結果を決定する。反映は呼び出し側のd_apply_rewardで行う。"""
    p = d_get_player(uid)
    p.setdefault("battle_stats", {}).update({"chests": p.setdefault("battle_stats", {}).get("chests", 0) + 1})
    d_progress_quest(uid, "chests", 1)
    roll = random.random()
    if roll < 0.5:
        coins = random.randint(50, 300)
        return f"宝箱！ コイン **+{coins}** 枚", {"coins": coins}
    if roll < 0.8:
        bread = random.randint(3, 15)
        return f"宝箱！ レアパン **+{bread}** 個", {"bread": bread}
    if roll < 0.93:
        boxes = random.randint(1, 3)
        return f"宝箱！ 宝箱 **+{boxes}** 個", {"boxes": boxes}
    if roll < 0.98:
        relic = random.choice(list(RELIC_MASTER))
        return f"宝箱！ 遺物 **{RELIC_MASTER[relic]['name']}** を発見", {"relic": relic}
    equipment = random.choice(list(EQUIPMENT_MASTER))
    return f"宝箱！ 装備 **{EQUIPMENT_MASTER[equipment]['name']}** を発見", {"equipment": equipment, "achievement": "treasure_hunter"}

def d_trigger_trap(uid):
    """罠の結果を決定し、HPだけ即時反映する。資産減少は呼び出し側で反映する。"""
    p = d_get_player(uid)
    roll = random.random()
    if roll < 0.4:
        loss = random.randint(30, 150)
        return f"罠！ コイン **-{loss}** 枚", {"coins": -loss}
    if roll < 0.7:
        dmg = random.randint(10, 30)
        p["hp"] = max(0, p["hp"] - dmg)
        return f"罠！ HP **-{dmg}**", {}
    if roll < 0.85:
        loss = random.randint(1, 5)
        return f"罠！ レアパン **-{loss}** 個", {"bread": -loss}
    loss = random.randint(50, 200)
    return f"罠！ チップ **-{loss}** 枚", {"chips": -loss}

def d_do_mine(uid):
    """採掘する"""
    gain = random.randint(30, 200)
    return gain

def d_make_enemy(floor, forced_name=None):
    """敵を生成"""
    base_hp  = 15 + floor * 8
    base_atk = 4  + floor * 2
    base_def = 1  + floor
    bname, _, _, _, _ = d_get_biome(floor)

    # ランクと名前の決定
    if forced_name:
        name = forced_name
        etype = "normal"
    else:
        r = random.random()
        if r < 0.01:
            etype = "boss"
            name = random.choice(D_BOSS_NAMES.get(bname, ["ボス"]))
        elif r < 0.11:
            etype = "elite"
            name = random.choice(D_SUPERENEMY_NAMES.get(bname, ["精鋭"]))
        else:
            etype = "normal"
            name = random.choice(D_ENEMY_NAMES.get(bname, ["謎の敵"]))

    # マスタから個別パラメータを取得
    clean_key = name.split()[0].replace("👾", "").strip()
    m = ENEMY_STATS_MASTER.get(clean_key, ENEMY_STATS_MASTER["default"])

    # ランクによる倍率補正
    rank_hp_mul  = 4.0 if etype == "elite" else (15.0 if etype == "boss" else 1.0)
    rank_atk_mul = 2.5 if etype == "elite" else (4.0 if etype == "boss" else 1.0)
    rank_def_mul = 1.5 if etype == "elite" else (2.0 if etype == "boss" else 1.0)

    # ステータス確定
    hp = int((base_hp + random.randint(-3, 3)) * m.get("hp_m") * rank_hp_mul)
    atk = int((base_atk + random.randint(-1, 1)) * m.get("atk_m", 1.0) * rank_atk_mul)
    defe = int(base_def * m.get("def_m", 1.0) * rank_def_mul)
    
    # 報酬計算
    m_coin_m = m.get("coin_m", 1.0)
    m_xp_m   = m.get("xp_m", 1.0)
    m_boxes  = m.get("boxes", 0)

    if etype == "elite":
        reward_coins = int(random.randint(80, 150) * floor * m_coin_m)
        reward_xp    = int(random.randint(100, 800) * floor * m_xp_m)
        reward_box   = max(1, m_boxes)
    elif etype == "boss":
        reward_coins = int(random.randint(2000, 4000) * floor * m_coin_m)
        reward_xp    = int(random.randint(1000, 2000) * floor * m_xp_m)
        reward_box   = max(5, m_boxes)
    else:
        reward_coins = int(random.randint(20, 80) * floor * m_coin_m)
        reward_xp    = int(random.randint(10, 30) * floor * m_xp_m)
        reward_box   = m_boxes if m_boxes > 0 else (1 if random.random() < 0.05 else 0)

    return {
        "name":         name,
        "type":         etype,
        "hp":           hp,
        "max_hp":       hp,
        "atk":          atk,
        "def_":         defe,
        "spd":          m.get("spd", 10),
        "crit":         m.get("crit", 0.05),
        "element":      random.choice(["none", "fire", "ice", "thunder"] if bname != "砂漠地帯" else ["none", "fire", "dark"]),
        "status_effect": random.choice(["poison", "burn", "freeze", "bleed"]),
        "reward_coins": reward_coins,
        "reward_xp":    reward_xp,
        "reward_box":   reward_box,
    }

def d_gen_floor(floor):
    """セルオートマトン法でフロアを生成"""
    grid = [[D_WALL if (x == 0 or y == 0 or x == D_MAP_W-1 or y == D_MAP_H-1)
             else (D_WALL if random.random() < 0.45 else D_FLOOR)
             for x in range(D_MAP_W)] for y in range(D_MAP_H)]
    
    for _ in range(5):
        new = [[D_WALL]*D_MAP_W for _ in range(D_MAP_H)]
        for y in range(D_MAP_H):
            for x in range(D_MAP_W):
                if x == 0 or y == 0 or x == D_MAP_W-1 or y == D_MAP_H-1:
                    new[y][x] = D_WALL
                    continue
                walls = sum(1 for dy in range(-1, 2) for dx in range(-1, 2)
                          if grid[y+dy][x+dx] == D_WALL)
                new[y][x] = D_WALL if walls >= 5 else D_FLOOR
        grid = new
    
    visited = set()
    best = set()
    for sy in range(1, D_MAP_H-1):
        for sx in range(1, D_MAP_W-1):
            if grid[sy][sx] == D_FLOOR and (sx, sy) not in visited:
                region = set()
                queue = [(sx, sy)]
                while queue:
                    cx, cy = queue.pop()
                    if (cx, cy) in region:
                        continue
                    region.add((cx, cy))
                    for dx, dy in [(0, 1), (0, -1), (1, 0), (-1, 0)]:
                        nx, ny = cx + dx, cy + dy
                        if (0 < nx < D_MAP_W-1 and 0 < ny < D_MAP_H-1
                                and grid[ny][nx] == D_FLOOR
                                and (nx, ny) not in region):
                            queue.append((nx, ny))
                visited |= region
                if len(region) > len(best):
                    best = region
    
    for y in range(D_MAP_H):
        for x in range(D_MAP_W):
            if grid[y][x] == D_FLOOR and (x, y) not in best:
                grid[y][x] = D_WALL
    
    candidates = list(best)
    random.shuffle(candidates)
    sx, sy = candidates[0]
    grid[sy][sx] = D_START
    dg_starts[floor] = (sx, sy)
    
    for ex, ey in candidates[1:]:
        if abs(ex-sx) + abs(ey-sy) > 20:
            grid[ey][ex] = D_STAIRS
            break
    else:
        if len(candidates) > 1:
            grid[candidates[1][1]][candidates[1][0]] = D_STAIRS
    
    floor_cells = [p for p in best if grid[p[1]][p[0]] == D_FLOOR]
    random.shuffle(floor_cells)
    
    placed_chest = 0
    placed_trap = 0
    placed_shop = 0
    placed_mine = 0
    placed_rest = 0
    placed_shrine = 0
    placed_event = 0
    max_chest = max(3, len(floor_cells)//80)
    max_trap  = max(2, len(floor_cells)//120)
    max_shop  = max(1, len(floor_cells)//300)
    max_mine  = max(2, len(floor_cells)//150)
    max_rest = max(1, len(floor_cells)//500)
    max_shrine = max(1, len(floor_cells)//450)
    max_event = max(1, len(floor_cells)//400)
    
    for fx, fy in floor_cells:
        if all([placed_chest >= max_chest, placed_trap >= max_trap,
                placed_shop >= max_shop, placed_mine >= max_mine,
                placed_rest >= max_rest, placed_shrine >= max_shrine,
                placed_event >= max_event]):
            break
        r = random.random()
        if placed_shop < max_shop and r < 0.03:
            grid[fy][fx] = D_SHOP
            placed_shop += 1
        elif placed_mine < max_mine and r < 0.10:
            grid[fy][fx] = D_MINE
            placed_mine += 1
        elif placed_rest < max_rest and r < 0.13:
            grid[fy][fx] = D_REST
            placed_rest += 1
        elif placed_shrine < max_shrine and r < 0.18:
            grid[fy][fx] = D_SHRINE
            placed_shrine += 1
        elif placed_event < max_event and r < 0.23:
            grid[fy][fx] = D_EVENT
            placed_event += 1
        elif placed_chest < max_chest and r < 0.60:
            grid[fy][fx] = D_CHEST
            placed_chest += 1
        elif placed_trap < max_trap:
            grid[fy][fx] = D_TRAP
            placed_trap += 1
    
    return grid

def load_all_assets():
    """Assetsフォルダから画像を読み込みキャッシュする"""
    global _ASSET_CACHE
    base_dir = os.path.dirname(os.path.abspath(__file__))
    assets_dir = os.path.join(base_dir, "..", "Assets")
    
    _ASSET_CACHE = {}
    for (biome, tid), fname in ASSET_CONFIG.items():
        path = os.path.join(assets_dir, fname)
        if os.path.isfile(path):
            try:
                img = Image.open(path).convert("RGBA").resize((TILE, TILE), Image.Resampling.NEAREST)
                _ASSET_CACHE[(biome, tid)] = img
                print(f"✓ {fname} を読み込みました")
            except Exception as e:
                print(f"❌ {fname} ロード失敗: {e}")

def _draw_tile(draw, img, x, y, cell, biome, is_player=False, is_fog=False):
    """タイルを描画"""
    px, py = x * TILE, y * TILE
    if is_fog:
        draw.rectangle([px, py, px+TILE-1, py+TILE-1], fill=(0, 0, 0))
        return
    
    if is_player:
        floor_col = TILE_COLORS[D_FLOOR].get(biome, (40, 30, 25)) if isinstance(TILE_COLORS[D_FLOOR], dict) else TILE_COLORS[D_FLOOR]
        draw.rectangle([px, py, px+TILE-1, py+TILE-1], fill=floor_col)
        col = TILE_COLORS["player"]
        margin = 6
        draw.ellipse([px+margin, py+margin, px+TILE-margin-1, py+TILE-margin-1], fill=col)
        return

    tile_img = _ASSET_CACHE.get((biome, cell))
    if tile_img is not None:
        img.paste(tile_img, (px, py), tile_img)
        return

    if cell == D_TRAP:
        col_src = TILE_COLORS[D_FLOOR]
        col = col_src.get(biome, (40, 30, 25)) if isinstance(col_src, dict) else col_src
        draw.rectangle([px, py, px+TILE-1, py+TILE-1], fill=col)
        return
    
    col_src = TILE_COLORS.get(cell, (80, 80, 80))
    if isinstance(col_src, dict):
        col = col_src.get(biome, (80, 80, 80))
    else:
        col = col_src
    draw.rectangle([px, py, px+TILE-1, py+TILE-1], fill=col)
    
    if cell == D_CHEST:
        margin = 8
        draw.rectangle([px+margin, py+margin, px+TILE-margin-1, py+TILE-margin-1],
                       fill=(255, 255, 100), outline=(180, 140, 0), width=2)
    elif cell == D_STAIRS:
        for s in range(3):
            sx = px + 6 + s*6
            sy = py + TILE - 8 - s*6
            draw.rectangle([sx, sy, sx+TILE-14, sy+4], fill=(255, 255, 255))
    elif cell == D_SHOP:
        draw.text((px+TILE//2, py+TILE//2), "S", fill=(255, 255, 255))
    elif cell == D_MINE:
        draw.text((px+TILE//2-4, py+TILE//2-6), "⛏", fill=(200, 200, 200))
    elif cell == D_REST:
        draw.text((px+TILE//2-5, py+TILE//2-7), "R", fill=(255, 255, 255))
    elif cell == D_SHRINE:
        draw.text((px+TILE//2-5, py+TILE//2-7), "✦", fill=(255, 255, 255))
    elif cell == D_EVENT:
        draw.text((px+TILE//2-5, py+TILE//2-7), "?", fill=(255, 255, 255))
    elif cell == D_BASE:
        draw.text((px+TILE//2-4, py+TILE//2-6), "🏠", fill=(255, 255, 255))

def d_build_map_image(uid, floor, px, py, radius=D_VIEW_R):
    """マップをPillow Imageとして生成"""
    d_ensure_map(floor)
    bname, *_ = d_get_biome(floor)
    size = radius * 2 + 1
    img = Image.new("RGB", (size * TILE, size * TILE), (0, 0, 0))
    draw = ImageDraw.Draw(img)

    for vy_i, vy in enumerate(range(py - radius, py + radius + 1)):
        for vx_i, vx in enumerate(range(px - radius, px + radius + 1)):
            is_player = (vx == px and vy == py)
            if not (0 <= vx < D_MAP_W and 0 <= vy < D_MAP_H):
                _draw_tile(draw, img, vx_i, vy_i, D_WALL, bname, is_fog=True)
                continue
            cell = dg_maps[floor][vy][vx]
            _draw_tile(draw, img, vx_i, vy_i, cell, bname, is_player=is_player)

    return img

def d_render_pillow(uid, floor, px, py, radius=D_VIEW_R):
    """マップをPillow画像として生成しdiscord.Fileを返す"""
    img = d_build_map_image(uid, floor, px, py, radius)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return discord.File(fp=buf, filename="map.png")

async def d_render_image(uid, floor, px, py, bot, radius=D_VIEW_R):
    """マップを画像として生成しDiscordにアップロード、URLを返す"""
    img = d_build_map_image(uid, floor, px, py, radius)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    try:
        ch = bot.get_channel(DUNGEON_IMG_CHANNEL_ID) or \
             await bot.fetch_channel(DUNGEON_IMG_CHANNEL_ID)
        msg = await ch.send(file=discord.File(buf, filename="map.png"))
        return msg.attachments[0].url
    except Exception as e:
        print(f"画像アップロード失敗: {e}")
        return None

# ============================================================
#  DB 操作
# ============================================================

async def dg_load_all(supabase):
    """Supabaseから全ダンジョンデータを読み込む"""
    global dg_maps, dg_players, dg_starts, dg_used, dg_bases
    
    try:
        res = supabase.table("dungeon_maps").select("*").execute()
        for row in res.data:
            floor = row["floor"]
            dg_maps[floor] = json.loads(row["grid"])
            dg_used[floor] = set(tuple(p) for p in json.loads(row.get("used_coords", "[]")))
            if "start_pos" in row and row["start_pos"]:
                dg_starts[floor] = tuple(row["start_pos"])
        print(f"✓ ダンジョンマップ読み込み完了: {len(dg_maps)}フロア")
    except Exception as e:
        print(f"❌ ダンジョンマップ読み込み失敗: {e}")
    
    try:
        res = supabase.table("dungeon_players").select("*").execute()
        for row in res.data:
            inventory = row.get("inventory", {}) or {}
            meta = inventory.pop("_dungeon_meta", {}) if isinstance(inventory, dict) else {}
            dg_players[row["user_id"]] = {
                "floor": row.get("floor", 1),
                "x": row.get("x", 1),
                "y": row.get("y", 1),
                "hp": row.get("hp", 100),
                "max_hp": row.get("max_hp", 100),
                "atk": row.get("atk", 10),
                "def_": row.get("def_", 3),
                "spd": row.get("spd", 10),
                "crit": row.get("crit", 0.05),
                "xp": row.get("xp", 0), "level": row.get("level", 1),
                "boxes": row.get("boxes", 0), "bread": row.get("bread", 0),
                "chips": row.get("chips", 0),
                "job": row.get("job", "warrior"),
                "equipment": row.get("equipment", {}) or {},
                "inventory": inventory,
                "achievements": row.get("achievements", []) or [],
                "season_id": row.get("season_id", SEASON_ID),
                "season_score": row.get("season_score", 0),
                "turns": row.get("turns", 0), "cooldowns": row.get("cooldowns", {}) or {},
                "relics": meta.get("relics", []) or [],
                "active_effects": meta.get("active_effects", []) or [],
                "materials": meta.get("materials", {}) or {},
                "quests": meta.get("quests", {}) or {},
                "run_modifiers": meta.get("run_modifiers", []) or [],
                "camp_facilities": meta.get("camp_facilities", {"inn": 1, "forge": 0, "guild": 0}),
                "battle_stats": meta.get("battle_stats", {"kills": 0, "chests": 0, "escapes": 0}),
                "skill_points": meta.get("skill_points", 0), "skills": meta.get("skills", []) or [],
                "npc_flags": meta.get("npc_flags", {}) or {}, "story_flags": meta.get("story_flags", {}) or {},
                "run_id": meta.get("run_id"), "run_summary": meta.get("run_summary", {}) or {},
                "pending_rewards": meta.get("pending_rewards", []) or [], "reward_ledger": meta.get("reward_ledger", []) or [],
                "action_log": meta.get("action_log", []) or [], "state_version": meta.get("state_version", 0),
                "front_back": meta.get("front_back", "front"), "battle_resource": meta.get("battle_resource", {"mp": 20, "max_mp": 20, "rage": 0, "combo": 0, "guard": 0}),
                "floor_goals": meta.get("floor_goals", {}) or {},
            }
        print(f"✓ ダンジョンプレイヤー読み込み完了: {len(dg_players)}人")
    except Exception as e:
        print(f"❌ ダンジョンプレイヤー読み込み失敗: {e}")
    
    try:
        res = supabase.table("dungeon_bases").select("*").execute()
        for row in res.data:
            dg_bases[row["user_id"]] = (row["floor"], row["x"], row["y"])
        print(f"✓ ダンジョン拠点読み込み完了: {len(dg_bases)}個")
    except Exception as e:
        print(f"❌ ダンジョン拠点読み込み失敗: {e}")

async def dg_save_map(floor, supabase):
    """フロアマップをSupabaseに保存"""
    if floor not in dg_maps:
        return
    try:
        grid_json = json.dumps(dg_maps[floor], ensure_ascii=False)
        used_coords = list(dg_used.get(floor, set()))
        start_pos = dg_starts.get(floor, (1, 1))
        supabase.table("dungeon_maps").upsert({
            "floor": floor,
            "grid": grid_json,
            "used_coords": json.dumps(used_coords),
            "start_pos": list(start_pos),
        }).execute()
    except Exception as e:
        print(f"dg_save_map失敗 floor={floor}: {e}")

async def dg_save_player(uid, supabase):
    """プレイヤーのダンジョンデータをSupabaseに保存"""
    if uid not in dg_players:
        return
    try:
        p = dg_players[uid]
        inventory = dict(p.get("inventory", {}))
        inventory["_dungeon_meta"] = {
            "relics": p.get("relics", []),
            "active_effects": p.get("active_effects", []),
            "materials": p.get("materials", {}),
            "quests": p.get("quests", {}),
            "run_modifiers": p.get("run_modifiers", []),
            "camp_facilities": p.get("camp_facilities", {"inn": 1, "forge": 0, "guild": 0}),
            "battle_stats": p.get("battle_stats", {"kills": 0, "chests": 0, "escapes": 0}),
        }
        supabase.table("dungeon_players").upsert({
            "user_id": uid,
            "floor": p["floor"],
            "x": p["x"],
            "y": p["y"],
            "hp": p["hp"],
            "max_hp": p["max_hp"],
            "atk": p["atk"],
            "def_": p["def_"],
            "spd": p["spd"],
            "crit": p["crit"],
            "xp": p.get("xp", 0), "level": p.get("level", 1),
            "boxes": p.get("boxes", 0), "bread": p.get("bread", 0),
            "chips": p.get("chips", 0),
            "job": p.get("job", "warrior"),
            "equipment": p.get("equipment", {}), "inventory": inventory,
            "achievements": p.get("achievements", []),
            "season_id": p.get("season_id", SEASON_ID),
            "season_score": p.get("season_score", 0), "turns": p.get("turns", 0),
            "cooldowns": p.get("cooldowns", {}),
        }).execute()
    except Exception as e:
        print(f"dg_save_player失敗 uid={uid}: {e}")

async def dg_save_base(uid, floor, x, y, supabase):
    """プレイヤーの拠点をSupabaseに保存"""
    dg_bases[uid] = (floor, x, y)
    try:
        supabase.table("dungeon_bases").upsert({
            "user_id": uid,
            "floor": floor,
            "x": x,
            "y": y,
        }).execute()
    except Exception as e:
        print(f"dg_save_base失敗 uid={uid}: {e}")

# ============================================================
#  Views
# ============================================================

def d_lock_callback(func):
    async def wrapped(self, interaction, button):
        lock = d_get_lock(self.uid)
        if lock.locked():
            await interaction.response.send_message("前の操作を処理中です。少し待ってください。", ephemeral=True)
            return
        async with lock:
            return await func(self, interaction, button)
    wrapped.__name__ = func.__name__
    wrapped.__doc__ = func.__doc__
    return wrapped


class DungeonViewBase(View):
    """全ダンジョンUIの共通基底。所有者以外の操作を拒否する。"""
    def __init__(self, uid, *, timeout):
        super().__init__(timeout=timeout)
        self.uid = str(uid)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if str(interaction.user.id) != self.uid:
            await interaction.response.send_message(
                "このダンジョン画面は開始者本人のみ操作できます。", ephemeral=True
            )
            return False
        return True

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


class DungeonStatusView(DungeonViewBase):
    """ステータス表示"""
    def __init__(self, uid, floor, x, y, supabase):
        super().__init__(uid, timeout=60)
        self.uid = uid
        self.floor = floor
        self.x = x
        self.y = y
        self.supabase = supabase
    
    def _embed(self):
        p = d_get_player(self.uid)
        stats = d_effective_stats(p)
        em = discord.Embed(title="ダンジョン ステータス", color=0xFFFFFF)
        em.add_field(name="現在位置", value=f"フロア **{self.floor}** ({self.x}, {self.y})", inline=False)
        em.add_field(name="HP", value=f"{d_hpbar(p['hp'], stats['max_hp'])} {p['hp']}/{stats['max_hp']}", inline=False)
        em.add_field(name="職業", value=d_job_name(self.uid), inline=True)
        em.add_field(name="ステータス", value=f"ATK:{stats['atk']} DEF:{stats['def_']} SPD:{stats['spd']} CRIT:{int(stats['crit']*100)}%", inline=False)
        effects = [STATUS_EFFECTS.get(e.get('key'), {}).get('name', e.get('key')) for e in p.get('active_effects', []) if isinstance(e, dict)]
        em.add_field(name="成長", value=f"Lv.{p['level']} XP:{p['xp']} / 次:{p['level']*100}\n実績:{len(p['achievements'])}/{len(ACHIEVEMENTS)} スコア:{p['season_score']}", inline=False)
        em.add_field(name="状態異常", value="、".join(effects) if effects else "なし", inline=True)
        em.add_field(name="遺物・属性", value=f"遺物: {', '.join(RELIC_MASTER.get(k, {}).get('name', k) for k in p.get('relics', [])) or 'なし'}\n装備属性: {', '.join(EQUIPMENT_MASTER.get(k, {}).get('element', 'none') for k in p.get('equipment', {}).values()) or 'none'}", inline=False)
        quests, _ = d_content_summary(self.uid)
        em.add_field(name="クエスト", value="\n".join(quests) if quests else "全クエスト達成", inline=False)
        return em

    @discord.ui.button(label="⬅️ ダンジョンへ戻る", style=discord.ButtonStyle.grey)
    async def back(self, i, b):
        await i.response.defer()
        p = d_get_player(self.uid)
        mv = DungeonMainView(self.uid, p["floor"], p["x"], p["y"], self.supabase)
        await i.edit_original_response(
            embed=mv._embed(""), view=mv,
            attachments=[d_render_pillow(self.uid, p["floor"], p["x"], p["y"])]
        )

class DungeonStairsView(DungeonViewBase):
    """階段View"""
    def __init__(self, uid, floor, x, y, supabase):
        super().__init__(uid, timeout=180)
        self.uid = uid
        self.floor = floor
        self.x = x
        self.y = y
        self.supabase = supabase
    
    def _embed(self, msg=""):
        em = discord.Embed(title="階段がある", color=0xFFFFFF, description=msg)
        em.set_image(url="attachment://map.png")
        return em
    
    @discord.ui.button(label="⬆️ 上へ進む", style=discord.ButtonStyle.green)
    @d_lock_callback
    async def up(self, i, b):
        await i.response.defer()
        if self.floor < D_FLOORS:
            p = d_get_player(self.uid)
            p["floor"] = self.floor + 1
            p["hp"] = p["max_hp"]
            next_floor = self.floor + 1
            d_ensure_map(next_floor)
            p["x"], p["y"] = dg_starts[next_floor]
            d_progress_quest(self.uid, "floor", max(1, next_floor - self.floor))
            await dg_save_player(self.uid, self.supabase)
            mv = DungeonMainView(self.uid, p["floor"], p["x"], p["y"], self.supabase)
            map_file = d_render_pillow(self.uid, p["floor"], p["x"], p["y"])
            await i.edit_original_response(embed=mv._embed(f"フロア {self.floor + 1}へ到達！"), view=mv, attachments=[map_file])
        else:
            await i.edit_original_response(embed=discord.Embed(title="ゴール！", description="ダンジョンをクリアしました！", color=0xFFFFFF))
    
    @discord.ui.button(label="⬅️ 戻る", style=discord.ButtonStyle.grey)
    @d_lock_callback
    async def back(self, i, b):
        await i.response.defer()
        mv = DungeonMainView(self.uid, self.floor, self.x, self.y, self.supabase)
        map_file = d_render_pillow(self.uid, self.floor, self.x, self.y)
        await i.edit_original_response(embed=mv._embed(""), view=mv, attachments=[map_file])

class DungeonMineView(DungeonViewBase):
    """採掘View"""
    def __init__(self, uid, floor, x, y, supabase):
        super().__init__(uid, timeout=60)
        self.uid = uid
        self.floor = floor
        self.x = x
        self.y = y
        self.supabase = supabase
    
    def _embed(self, msg=""):
        em = discord.Embed(title="鉱山", color=0xFFFFFF, description=msg)
        em.set_image(url="attachment://map.png")
        return em
    
    @discord.ui.button(label="⛏ 採掘する", style=discord.ButtonStyle.green)
    @d_lock_callback
    async def mine(self, i, b):
        await i.response.defer()
        gain = d_do_mine(self.uid)
        await d_apply_reward(self.uid, self.supabase, coins=gain)
        d_consume(self.floor, self.x, self.y)
        await dg_save_map(self.floor, self.supabase)
        await dg_save_player(self.uid, self.supabase)
        mv = DungeonMainView(self.uid, self.floor, self.x, self.y, self.supabase)
        map_file = d_render_pillow(self.uid, self.floor, self.x, self.y)
        await i.edit_original_response(embed=mv._embed(f"採掘！ **+{gain}** コイン"), view=mv, attachments=[map_file])
    
    @discord.ui.button(label="⬅️ 戻る", style=discord.ButtonStyle.grey)
    @d_lock_callback
    async def back(self, i, b):
        await i.response.defer()
        mv = DungeonMainView(self.uid, self.floor, self.x, self.y, self.supabase)
        map_file = d_render_pillow(self.uid, self.floor, self.x, self.y)
        await i.edit_original_response(embed=mv._embed(""), view=mv, attachments=[map_file])

def d_use_job_skill(uid, enemy):
    """職業スキルを1回実行し、表示用ログとダメージを返す。"""
    p = d_get_player(uid)
    job = p.get("job", "warrior")
    skill = JOB_MASTER.get(job, JOB_MASTER["warrior"])["skill"]
    cooldowns = p.setdefault("cooldowns", {})
    if cooldowns.get(skill, 0) > 0:
        return f"{skill}はあと{cooldowns[skill]}ターン使用できません。", 0
    stats = d_effective_stats(p)
    if skill == "power_strike":
        damage = max(1, stats["atk"] * 2 - enemy.get("def_", 0))
        cooldowns[skill] = 2
        return f"戦士の強撃！ {damage}ダメージ", damage
    if skill == "smoke_bomb":
        cooldowns[skill] = 3
        cooldowns["smoke_buff"] = 2
        return "盗賊の煙幕！ 次の逃走成功率が上がった。", 0
    damage = max(1, int(stats["atk"] * 2.2) - enemy.get("def_", 0))
    cooldowns[skill] = 3
    return f"魔術師の火球！ {damage}ダメージ", damage


class DungeonShopView(DungeonViewBase):
    """軽量な商店View。購入はサーバー側で価格を検証する。"""
    def __init__(self, uid, floor, x, y, supabase):
        super().__init__(uid, timeout=120)
        self.floor, self.x, self.y, self.supabase = floor, x, y, supabase

    def _embed(self, msg=""):
        p = d_get_player(self.uid)
        em = discord.Embed(title="旅の商店", description=msg, color=0xB450C8)
        em.set_image(url="attachment://map.png")
        em.add_field(name="レアパン 30 AGO", value="HPを回復するアイテム", inline=True)
        em.add_field(name="革鎧 250 AGO", value="DEF+3 / HP+15", inline=True)
        em.add_field(name="所持", value=f"レアパン:{p['bread']} / 宝箱:{p['boxes']}", inline=False)
        return em

    async def _buy(self, i, price, reward, label):
        await i.response.defer()
        try:
            await d_apply_reward(self.uid, self.supabase, coins=-price, **reward)
            msg = f"{label}を購入しました。"
        except Exception:
            msg = "コインが足りないか、購入に失敗しました。"
        await dg_save_player(self.uid, self.supabase)
        await i.edit_original_response(embed=self._embed(msg), view=self, attachments=[d_render_pillow(self.uid, self.floor, self.x, self.y)])

    @discord.ui.button(label="パンを買う", style=discord.ButtonStyle.green)
    @d_lock_callback
    async def buy_bread(self, i, b):
        await self._buy(i, 30, {"bread": 1}, "レアパン")

    @discord.ui.button(label="革鎧を買う", style=discord.ButtonStyle.blurple)
    @d_lock_callback
    async def buy_armor(self, i, b):
        await self._buy(i, 250, {"equipment": "leather_armor"}, "革鎧")

    @discord.ui.button(label="⬅️ 戻る", style=discord.ButtonStyle.grey, row=1)
    @d_lock_callback
    async def back(self, i, b):
        await i.response.defer()
        mv = DungeonMainView(self.uid, self.floor, self.x, self.y, self.supabase)
        await i.edit_original_response(embed=mv._embed(""), view=mv, attachments=[d_render_pillow(self.uid, self.floor, self.x, self.y)])


class DungeonCombatView(DungeonViewBase):
    """戦闘View"""
    def __init__(self, uid, floor, x, y, enemy, supabase):
        super().__init__(uid, timeout=180)
        self.uid = uid
        self.floor = floor
        self.x = x
        self.y = y
        self.enemy = enemy
        self.log = []
        self.defending = False
        self.supabase = supabase
    
    def _embed(self):
        p = d_get_player(self.uid)
        e = self.enemy
        p_stats = d_effective_stats(p)
        ratio = p["hp"] / max(p_stats["max_hp"], 1)
        color = 0x00ff88 if ratio > 0.5 else (0xffaa00 if ratio > 0.25 else 0xff4444)

        etype = e.get("type", "normal")
        type_text = {"normal": "通常", "elite": "精鋭", "boss": "ボス"}.get(etype, "通常")

        em = discord.Embed(title=f"{e['name']}（{type_text}）が現れた！", color=0xFFFFFF)
        em.set_image(url="attachment://map.png")

        em.add_field(name="あなた",
            value=f"`{d_hpbar(p['hp'],p_stats['max_hp'])}`{p['hp']}/{p_stats['max_hp']}\nATK:{p_stats['atk']} DEF:{p_stats['def_']}",
            inline=True)

        em.add_field(name=e["name"],
            value=f"`{d_hpbar(e['hp'],e['max_hp'])}`{e['hp']}/{e['max_hp']}\nATK:{e['atk']} DEF:{e['def_']}",
            inline=True)

        player_first = p_stats.get("spd", 10) >= e.get("spd", 10)
        raw_name = e["name"].split()[0].replace("👾", "").strip()
        enemy_ai = ENEMY_STATS_MASTER.get(raw_name, ENEMY_STATS_MASTER["default"]).get("ai", ["attack"])
        preview = {"attack": "通常攻撃", "strong_attack": "強攻撃", "heal": "回復", "wait": "様子見"}
        next_action = preview.get(enemy_ai[0], "通常攻撃")
        em.add_field(
            name="行動順 / 敵の予告",
            value=f"{'あなた → ' + e['name'] if player_first else e['name'] + ' → あなた'}\n次: **{next_action}**",
            inline=False,
        )

        if self.log:
            em.add_field(name="ログ", value="\n".join(self.log[-5:]), inline=False)
        return em

    def _calculate_damage(self, attacker, defender, is_defending=False):
        attacker_stats = d_effective_stats(attacker) if "job" in attacker else attacker
        defender_stats = d_effective_stats(defender) if "job" in defender else defender
        is_crit = random.random() < attacker_stats.get("crit", 0.05)
        target_def = defender_stats.get("def_", 0)
        if is_defending:
            target_def *= 2
        dmg = max(1, attacker_stats["atk"] - target_def + random.randint(-2, 3))
        # プレイヤーの属性は装備中の武器から解決する。従来はEmbedに属性を
        # 表示するだけで、実際のダメージ計算へ接続されていなかった。
        attacker_element = attacker.get("element", "none") if isinstance(attacker, dict) else "none"
        if "job" in attacker:
            weapon_key = attacker.get("equipment", {}).get("weapon")
            attacker_element = EQUIPMENT_MASTER.get(weapon_key, {}).get("element", "none")
        defender_element = defender.get("element", "none") if isinstance(defender, dict) else "none"
        if attacker_element in ELEMENTS and defender_element in ELEMENTS:
            if defender_element in ELEMENTS[attacker_element].get("weak", []):
                dmg = int(dmg * 1.35)
            elif defender_element in ELEMENTS[attacker_element].get("resist", []):
                dmg = max(1, int(dmg * 0.75))
        if is_crit:
            return int(dmg * 1.5), True
        return dmg, False

    def _enemy_turn(self):
        p = d_get_player(self.uid)
        e = self.enemy
        effect_logs = d_tick_status(self.uid)
        raw_name = e["name"].split()[0].replace("👾", "").strip()
        master = ENEMY_STATS_MASTER.get(raw_name, ENEMY_STATS_MASTER["default"])
        action = random.choice(master.get("ai", ["attack"]))
        
        log_msg = ""
        if action == "strong_attack":
            dmg, crit = self._calculate_damage(e, p, self.defending)
            dmg = int(dmg * 1.4)
            p["hp"] = max(0, p["hp"] - dmg)
            log_msg = f"**{e['name']}の強攻撃！！** {dmg} ダメージ"
        elif action == "heal":
            heal_amt = int(e["max_hp"] * 0.15)
            e["hp"] = min(e["max_hp"], e["hp"] + heal_amt)
            log_msg = f"{e['name']}は傷口を舐めて {heal_amt} 回復した"
        elif action == "wait":
            log_msg = f"{e['name']}は様子を伺っている..."
        else:
            dmg, crit = self._calculate_damage(e, p, self.defending)
            p["hp"] = max(0, p["hp"] - dmg)
            c_msg = "**CRITICAL!!** " if crit else ""
            log_msg = f"{c_msg}{e['name']}の攻撃：{dmg} ダメージ"

        if p["hp"] > 0 and random.random() < 0.25 and e.get("status_effect"):
            d_apply_special_status(self.uid, e["status_effect"])
            log_msg += f" / {STATUS_EFFECTS[e['status_effect']]['name']}を受けた"

        self.defending = False
        p_cooldowns = d_get_player(self.uid).setdefault("cooldowns", {})
        for key in list(p_cooldowns):
            if p_cooldowns[key] > 0:
                p_cooldowns[key] -= 1
        return " / ".join(effect_logs + [log_msg])

    async def _win(self, i):
        e = self.enemy
        await d_apply_reward(
            self.uid, self.supabase,
            coins=e["reward_coins"], xp=e["reward_xp"], boxes=e["reward_box"],
            achievement="first_boss" if e.get("type") == "boss" else None,
            season_score=500 if e.get("type") == "boss" else 25
        )
        p = d_get_player(self.uid)
        p.setdefault("battle_stats", {})["kills"] = p.setdefault("battle_stats", {}).get("kills", 0) + 1
        completed_quests = d_progress_quest(self.uid, "kills", 1)
        for quest_key in completed_quests:
            await d_apply_reward(self.uid, self.supabase, **QUEST_MASTER[quest_key]["reward"])
        msg = f"勝利！ +{e['reward_coins']}コイン +{e['reward_xp']}XP"
        if e["reward_box"] > 0:
            msg += f" +宝箱{e['reward_box']}個"
        self.log.append(msg)
        await dg_save_player(self.uid, self.supabase)
        self.stop()
        mv = DungeonMainView(self.uid, self.floor, self.x, self.y, self.supabase)
        map_file = d_render_pillow(self.uid, self.floor, self.x, self.y)
        await i.edit_original_response(embed=mv._embed(msg), view=mv, attachments=[map_file])

    async def _lose(self, i):
        p = d_get_player(self.uid)
        p["hp"] = p["max_hp"]
        p["floor"] = 1
        p["x"], p["y"] = dg_starts.get(1, (1, 1))
        self.log.append("敗北… スタート地点へ送還された")
        await dg_save_player(self.uid, self.supabase)
        self.stop()
        mv = DungeonMainView(self.uid, 1, p["x"], p["y"], self.supabase)
        map_file = d_render_pillow(self.uid, 1, p["x"], p["y"])
        await i.edit_original_response(embed=mv._embed("敗北して戻された…"), view=mv, attachments=[map_file])

    @discord.ui.button(label="⚔ 攻撃", style=discord.ButtonStyle.red, row=0)
    @d_lock_callback
    async def attack(self, i, b):
        await i.response.defer()
        p = d_get_player(self.uid)
        e = self.enemy
        p_first = d_effective_stats(p).get("spd", 10) >= e.get("spd", 10)
        
        if p_first:
            dmg, crit = self._calculate_damage(p, e)
            e["hp"] = max(0, e["hp"] - dmg)
            self.log.append(f"{'**CRIT!!** ' if crit else ''}{dmg} ダメージ！")
            if e["hp"] <= 0:
                await self._win(i)
                return
            self.log.append(self._enemy_turn())
        else:
            self.log.append(self._enemy_turn())
            if p["hp"] <= 0:
                await self._lose(i)
                return
            dmg, crit = self._calculate_damage(p, e)
            e["hp"] = max(0, e["hp"] - dmg)
            self.log.append(f"{'**CRIT!!** ' if crit else ''}{dmg} ダメージ！")

        if e["hp"] <= 0:
            await self._win(i)
            return
        if p["hp"] <= 0:
            await self._lose(i)
            return
        
        map_file = d_render_pillow(self.uid, self.floor, self.x, self.y)
        await i.edit_original_response(embed=self._embed(), view=self, attachments=[map_file])

    @discord.ui.button(label="🛡 防御", style=discord.ButtonStyle.blurple, row=0)
    @d_lock_callback
    async def defend(self, i, b):
        await i.response.defer()
        self.defending = True
        self.log.append(f"防御体制！\n{self._enemy_turn()}")
        if d_get_player(self.uid)["hp"] <= 0:
            await self._lose(i)
            return
        map_file = d_render_pillow(self.uid, self.floor, self.x, self.y)
        await i.edit_original_response(embed=self._embed(), view=self, attachments=[map_file])

    @discord.ui.button(label="逃げる", style=discord.ButtonStyle.grey, row=0)
    @d_lock_callback
    async def run_away(self, i, b):
        await i.response.defer()
        if self.enemy.get("type") == "boss":
            self.log.append("ボスからは逃げられない！\n" + self._enemy_turn())
            if d_get_player(self.uid)["hp"] <= 0:
                await self._lose(i)
                return
            await i.edit_original_response(embed=self._embed(), view=self, attachments=[d_render_pillow(self.uid, self.floor, self.x, self.y)])
            return
        
        p = d_get_player(self.uid)
        escape_rate = 0.2 if self.enemy.get("type") == "elite" else 0.5
        if p.get("cooldowns", {}).get("smoke_buff", 0) > 0:
            escape_rate = min(0.95, escape_rate + 0.30)
        if random.random() < escape_rate:
            self.stop()
            mv = DungeonMainView(self.uid, self.floor, self.x, self.y, self.supabase)
            await i.edit_original_response(embed=mv._embed("逃走成功"), view=mv, attachments=[d_render_pillow(self.uid, self.floor, self.x, self.y)])
        else:
            self.log.append("逃げ失敗！\n" + self._enemy_turn())
            if d_get_player(self.uid)["hp"] <= 0:
                await self._lose(i)
                return
            await i.edit_original_response(embed=self._embed(), view=self, attachments=[d_render_pillow(self.uid, self.floor, self.x, self.y)])

    @discord.ui.button(label="✨ スキル", style=discord.ButtonStyle.blurple, row=1)
    @d_lock_callback
    async def skill(self, i, b):
        await i.response.defer()
        p = d_get_player(self.uid)
        log, damage = d_use_job_skill(self.uid, self.enemy)
        self.enemy["hp"] = max(0, self.enemy["hp"] - damage)
        self.log.append(log)
        d_unlock_achievement(self.uid, "skill_user")
        if self.enemy["hp"] <= 0:
            await self._win(i)
            return
        self.log.append(self._enemy_turn())
        if p["hp"] <= 0:
            await self._lose(i)
            return
        await dg_save_player(self.uid, self.supabase)
        await i.edit_original_response(embed=self._embed(), view=self, attachments=[d_render_pillow(self.uid, self.floor, self.x, self.y)])


class DungeonMainView(DungeonViewBase):
    """ダンジョンメインView"""
    def __init__(self, uid, floor, x, y, supabase):
        super().__init__(uid, timeout=600)
        self.uid = uid
        self.floor = floor
        self.x = x
        self.y = y
        self.supabase = supabase
    
    def _embed(self, msg="", has_image=True, image_url=None):
        p = d_get_player(self.uid)
        stats = d_effective_stats(p)
        bname, _, _, _, _ = d_get_biome(self.floor)
        em = discord.Embed(title=f"フロア {self.floor} ({bname})", color=0xFFFFFF)
        if has_image and image_url:
            em.set_image(url=image_url)
        em.add_field(name="位置", value=f"{p['floor']}F / ({p['x']}, {p['y']}) / {d_floor_modifier(self.floor)}", inline=True)
        em.add_field(name="HP", value=f"{d_hpbar(p['hp'], stats['max_hp'])} {p['hp']}/{stats['max_hp']}", inline=True)
        quests, relics = d_content_summary(self.uid)
        em.add_field(name="冒険パネル", value=f"職業: {d_job_name(self.uid)}\nターン: {p['turns']} / スコア: {p['season_score']}\n遺物: {', '.join(relics) if relics else 'なし'}", inline=False)
        em.add_field(name="進行中の目的", value="\n".join(quests) if quests else "全クエスト達成", inline=False)
        if msg:
            em.add_field(name="ログ", value=msg, inline=False)
        return em

    async def _move(self, i, dx, dy):
        lock = d_get_lock(self.uid)
        if lock.locked():
            await i.response.send_message("前の操作を処理中です。少し待ってください。", ephemeral=True)
            return
        await lock.acquire()
        try:
            await self._move_locked(i, dx, dy)
        finally:
            lock.release()

    async def _move_locked(self, i, dx, dy):
        await i.response.defer()
        
        p = d_get_player(self.uid)
        nx, ny = p["x"] + dx, p["y"] + dy
        
        # 境界チェック
        if not (0 <= nx < D_MAP_W and 0 <= ny < D_MAP_H):
            map_file = d_render_pillow(self.uid, self.floor, p["x"], p["y"])
            await i.edit_original_response(embed=self._embed("壁！進めない"), attachments=[map_file], view=self)
            return
        
        ct = d_get_cell(self.floor, nx, ny)
        if dx != 0 and dy != 0 and (
            d_get_cell(self.floor, p["x"] + dx, p["y"]) == D_WALL
            or d_get_cell(self.floor, p["x"], p["y"] + dy) == D_WALL
        ):
            ct = D_WALL
        if ct == D_WALL:
            map_file = d_render_pillow(self.uid, self.floor, p["x"], p["y"])
            await i.edit_original_response(embed=self._embed("壁！進めない"), attachments=[map_file], view=self)
            return
        
        # 座標更新
        p["x"], p["y"] = nx, ny
        
        msg = ""

        p["turns"] += 1
        p["season_score"] += 1
        completed_quests = d_progress_quest(self.uid, "turns", 1)
        for quest_key in completed_quests:
            quest_reward = QUEST_MASTER[quest_key]["reward"]
            await d_apply_reward(self.uid, self.supabase, **quest_reward)
        d_unlock_achievement(self.uid, "first_step")
        if self.floor >= 10: d_unlock_achievement(self.uid, "floor_10")
        if self.floor >= 20: d_unlock_achievement(self.uid, "floor_20")
        if self.floor >= 40: d_unlock_achievement(self.uid, "floor_40")

        # 特殊タイル判定
        if ct == D_STAIRS:
            sv = DungeonStairsView(self.uid, self.floor, p["x"], p["y"], self.supabase)
            map_file = d_render_pillow(self.uid, self.floor, p["x"], p["y"])
            await dg_save_player(self.uid, self.supabase)
            await i.edit_original_response(embed=self._embed("階段がある。どうする？"), attachments=[map_file], view=sv)
            return

        elif ct == D_CHEST:
            msg, reward = d_open_chest(self.uid, self.supabase)
            await d_apply_reward(self.uid, self.supabase, **reward)
            d_consume(self.floor, p["x"], p["y"])
            await dg_save_map(self.floor, self.supabase)

        elif ct == D_TRAP:
            msg, penalty = d_trigger_trap(self.uid)
            await d_apply_reward(self.uid, self.supabase, **penalty)
            d_consume(self.floor, p["x"], p["y"])
            await dg_save_map(self.floor, self.supabase)

        elif ct == D_SHOP:
            shop = DungeonShopView(self.uid, self.floor, p["x"], p["y"], self.supabase)
            map_file = d_render_pillow(self.uid, self.floor, p["x"], p["y"])
            await dg_save_player(self.uid, self.supabase)
            await i.edit_original_response(embed=shop._embed("商店を発見！"), attachments=[map_file], view=shop)
            return

        elif ct == D_REST:
            before = p["hp"]
            p["hp"] = min(d_effective_stats(p)["max_hp"], p["hp"] + max(20, d_effective_stats(p)["max_hp"] // 3))
            msg = f"休憩した。HPが {p['hp'] - before} 回復した。"
            d_consume(self.floor, p["x"], p["y"])
            await dg_save_map(self.floor, self.supabase)

        elif ct == D_SHRINE:
            p["atk"] += 2
            msg = "祭壇の祝福！ 基礎ATKが2上昇した。"
            d_consume(self.floor, p["x"], p["y"])
            await dg_save_map(self.floor, self.supabase)

        elif ct == D_EVENT:
            gain = random.randint(20, 80)
            await d_apply_reward(self.uid, self.supabase, coins=gain, xp=gain, season_score=25)
            msg = f"旅人の依頼を達成した。コイン+{gain}、XP+{gain}"
            d_consume(self.floor, p["x"], p["y"])
            await dg_save_map(self.floor, self.supabase)

        elif ct == D_MINE:
            mv = DungeonMineView(self.uid, self.floor, p["x"], p["y"], self.supabase)
            map_file = d_render_pillow(self.uid, self.floor, p["x"], p["y"])
            await i.edit_original_response(embed=mv._embed("鉱山を発見！"), attachments=[map_file], view=mv)
            return

        else:
            bname, _, _, _, _ = d_get_biome(self.floor)
            rate = D_ENCOUNTER_RATES.get(bname, 0.10)
            if random.random() < rate:
                enemy = d_make_enemy(self.floor)
                cv = DungeonCombatView(self.uid, self.floor, p["x"], p["y"], enemy, self.supabase)
                map_file = d_render_pillow(self.uid, self.floor, p["x"], p["y"])
                await dg_save_player(self.uid, self.supabase)
                await i.edit_original_response(embed=cv._embed(), attachments=[map_file], view=cv)
                return

        # 死亡判定
        if p["hp"] <= 0:
            p["hp"] = p["max_hp"]
            p["floor"] = 1
            start_pos = dg_starts.get(1, (1, 1))
            p["x"], p["y"] = start_pos
            self.floor = 1
            msg += "\n力尽きた… スタート地点へ戻された"

        # 最終的な画面更新
        await dg_save_player(self.uid, self.supabase)
        map_file = d_render_pillow(self.uid, self.floor, p["x"], p["y"])
        await i.edit_original_response(embed=self._embed(msg), attachments=[map_file], view=self)

    @discord.ui.button(label="↖️", style=discord.ButtonStyle.grey, row=0, custom_id="dg_lu")
    async def leftup(self, i, b): await self._move(i, -1, -1)
    
    @discord.ui.button(label="⬆️", style=discord.ButtonStyle.grey, row=0, custom_id="dg_u")
    async def up(self, i, b): await self._move(i, 0, -1)
    
    @discord.ui.button(label="↗️", style=discord.ButtonStyle.grey, row=0, custom_id="dg_ru")
    async def rightup(self, i, b): await self._move(i, 1, -1)
    
    @discord.ui.button(label="⬅️", style=discord.ButtonStyle.grey, row=1, custom_id="dg_l")
    async def left(self, i, b): await self._move(i, -1, 0)
    
    @discord.ui.button(label="☑️", style=discord.ButtonStyle.grey, row=1, custom_id="dg_c")
    async def check(self, i, b): await self._move(i, 0, 0)
    
    @discord.ui.button(label="➡️", style=discord.ButtonStyle.grey, row=1, custom_id="dg_r")
    async def right(self, i, b): await self._move(i, 1, 0)
    
    @discord.ui.button(label="↙️", style=discord.ButtonStyle.grey, row=2, custom_id="dg_ld")
    async def leftdown(self, i, b): await self._move(i, -1, 1)
    
    @discord.ui.button(label="⬇️", style=discord.ButtonStyle.grey, row=2, custom_id="dg_d")
    async def down(self, i, b): await self._move(i, 0, 1)
    
    @discord.ui.button(label="↘️", style=discord.ButtonStyle.grey, row=2, custom_id="dg_rd")
    async def rightdown(self, i, b): await self._move(i, 1, 1)

    @discord.ui.button(label="STATUS", style=discord.ButtonStyle.green, row=3, custom_id="dg_status")
    async def status(self, i, b):
        await i.response.defer()
        sv = DungeonStatusView(self.uid, self.floor, self.x, self.y, self.supabase)
        status_embed = sv._embed()
        await i.edit_original_response(embed=status_embed, attachments=[], view=sv)



class DungeonUnifiedView(DungeonMainView):
    """/dungeon一つで操作を完結させる圧縮UI。"""
    def __init__(self, uid, floor, x, y, supabase):
        super().__init__(uid, floor, x, y, supabase)
        self.d1_plan = "安全探索"
        self.clear_items()
        directions = [
            ("↖️", -1, -1, 0), ("⬆️", 0, -1, 0), ("↗️", 1, -1, 0),
            ("⬅️", -1, 0, 1), ("ENTER", 0, 0, 1), ("➡️", 1, 0, 1),
            ("↙️", -1, 1, 2), ("⬇️", 0, 1, 2), ("↘️", 1, 1, 2),
        ]
        for label, dx, dy, row in directions:
            button = discord.ui.Button(label=label, style=discord.ButtonStyle.green if label == "ENTER" else discord.ButtonStyle.grey, row=row)
            async def move_callback(interaction, dx=dx, dy=dy):
                await self._move(interaction, dx, dy)
            button.callback = move_callback
            self.add_item(button)

        operation = discord.ui.Button(label="操作 / STATUS", style=discord.ButtonStyle.green, row=3)
        operation.callback = self.open_operations
        self.add_item(operation)
        d1 = discord.ui.Button(label="🤖 D1開始", style=discord.ButtonStyle.blurple, row=3)
        d1.callback = self.start_d1
        self.add_item(d1)
        stop = discord.ui.Button(label="■ 終了", style=discord.ButtonStyle.red, row=3)
        stop.callback = self.end_session
        self.add_item(stop)
        plan_select = discord.ui.Select(
            placeholder="D1作戦を選択",
            options=[discord.SelectOption(label=name, value=key) for key, name in D1_PLANS.items()],
            row=4,
        )
        plan_select.callback = self.select_plan
        self.add_item(plan_select)

    async def select_plan(self, interaction):
        await interaction.response.defer()
        key = interaction.data.get("values", ["safe"])[0]
        self.d1_plan = D1_PLANS.get(key, D1_PLANS["safe"])
        p = d_get_player(self.uid)
        await interaction.edit_original_response(
            embed=self._embed(f"D1作戦を **{self.d1_plan}** に設定しました。", has_image=True, image_url="attachment://map.png"),
            view=self, attachments=[d_render_pillow(self.uid, p["floor"], p["x"], p["y"])]
        )

    async def open_operations(self, interaction):
        await interaction.response.defer()
        op = DungeonOperationView(self.uid, self.floor, self.x, self.y, self.supabase)
        p = d_get_player(self.uid)
        await interaction.edit_original_response(
            embed=op._embed("操作メニュー"), view=op,
            attachments=[d_render_pillow(self.uid, p["floor"], p["x"], p["y"])]
        )

    async def start_d1(self, interaction):
        cog = interaction.client.get_cog("D1DungeonPlayerCog")
        if cog is None:
            await interaction.response.send_message("D1機能が読み込まれていません。", ephemeral=True)
            return
        await cog.start_loop(interaction, self)

    async def end_session(self, interaction):
        cog = interaction.client.get_cog("D1DungeonPlayerCog")
        if cog:
            await cog.stop_loop(self.uid)
        self.stop()
        await interaction.response.defer()
        p = d_get_player(self.uid)
        embed = self._embed("ダンジョンを終了しました。再開する場合は `/dungeon` を実行してください。")
        await interaction.edit_original_response(
            embed=embed, view=None,
            attachments=[d_render_pillow(self.uid, p["floor"], p["x"], p["y"])]
        )


class DungeonOperationView(DungeonViewBase):
    """ステータス・アイテム・拠点・現在地操作を1画面に集約する。"""
    def __init__(self, uid, floor, x, y, supabase):
        super().__init__(uid, timeout=600)
        self.floor, self.x, self.y, self.supabase = floor, x, y, supabase

    def _embed(self, msg=""):
        p = d_get_player(self.uid)
        stats = d_effective_stats(p)
        em = discord.Embed(title="ダンジョン操作メニュー", description=msg, color=0x4EA1FF)
        em.add_field(name="位置", value=f"{p['floor']}F ({p['x']},{p['y']}) / {d_floor_modifier(p['floor'])}", inline=True)
        em.add_field(name="HP", value=f"{p['hp']}/{stats['max_hp']}", inline=True)
        em.add_field(name="所持資源", value=f"パン:{p['bread']} / 宝箱:{p['boxes']} / チップ:{p['chips']}", inline=False)
        em.add_field(name="装備", value="、".join(EQUIPMENT_MASTER.get(k, {}).get('name', k) for k in p.get('equipment', {}).values()) or "なし", inline=True)
        em.add_field(name="遺物", value="、".join(RELIC_MASTER.get(k, {}).get('name', k) for k in p.get('relics', [])) or "なし", inline=True)
        facilities = p.get('camp_facilities', {})
        em.add_field(name="拠点施設", value=f"宿屋Lv.{facilities.get('inn', 0)} / 鍛冶Lv.{facilities.get('forge', 0)} / ギルドLv.{facilities.get('guild', 0)}", inline=False)
        return em

    async def _back(self, interaction, msg=""):
        p = d_get_player(self.uid)
        view = DungeonUnifiedView(self.uid, p["floor"], p["x"], p["y"], self.supabase)
        await interaction.edit_original_response(
            embed=view._embed(msg, has_image=True, image_url="attachment://map.png"),
            view=view, attachments=[d_render_pillow(self.uid, p["floor"], p["x"], p["y"])]
        )

    async def status(self, interaction):
        await interaction.response.defer()
        p = d_get_player(self.uid)
        status = DungeonStatusView(self.uid, p["floor"], p["x"], p["y"], self.supabase)
        em = status._embed()
        em.set_image(url="attachment://map.png")
        await interaction.edit_original_response(
            embed=em, view=self,
            attachments=[d_render_pillow(self.uid, p["floor"], p["x"], p["y"])]
        )

    async def use_bread(self, interaction):
        await interaction.response.defer()
        p = d_get_player(self.uid)
        if p.get("bread", 0) <= 0:
            await self._back(interaction, "レアパンを持っていません。")
            return
        stats = d_effective_stats(p)
        before = p["hp"]
        p["bread"] -= 1
        p["hp"] = min(stats["max_hp"], p["hp"] + max(25, stats["max_hp"] // 4))
        await dg_save_player(self.uid, self.supabase)
        await self._back(interaction, f"レアパンを使用し、HPが {p['hp'] - before} 回復しました。")

    async def camp(self, interaction):
        await interaction.response.defer()
        p = d_get_player(self.uid)
        if p["floor"] != 1 and p["floor"] % 5 != 0:
            await self._back(interaction, "拠点は1階または5階ごとのフロアで設置できます。")
            return
        d_ensure_map(p["floor"])
        dg_maps[p["floor"]][p["y"]][p["x"]] = D_BASE
        await dg_save_base(self.uid, p["floor"], p["x"], p["y"], self.supabase)
        await dg_save_map(p["floor"], self.supabase)
        d_unlock_achievement(self.uid, "camp_builder")
        await dg_save_player(self.uid, self.supabase)
        await self._back(interaction, "現在地に拠点を設置しました。")

    async def achievements(self, interaction):
        await interaction.response.defer()
        p = d_get_player(self.uid)
        unlocked = [f"✅ {ACHIEVEMENTS[k]}" for k in p["achievements"] if k in ACHIEVEMENTS]
        locked = [f"🔒 {name}" for k, name in ACHIEVEMENTS.items() if k not in p["achievements"]]
        await self._back(interaction, "\n".join(unlocked + locked))

    async def select_job(self, interaction):
        await interaction.response.defer()
        p = d_get_player(self.uid)
        if p.get("turns", 0) > 0:
            await self._back(interaction, "冒険開始後は職業を変更できません。")
            return
        selected = interaction.data.get("values", [""])[0]
        if selected not in JOB_MASTER:
            await self._back(interaction, "無効な職業です。")
            return
        p["job"] = selected
        await dg_save_player(self.uid, self.supabase)
        await self._back(interaction, f"職業を **{JOB_MASTER[selected]['name']}** に設定しました。")

    async def current_action(self, interaction):
        await interaction.response.defer()
        p = d_get_player(self.uid)
        cell = d_get_cell(p["floor"], p["x"], p["y"])
        msg = "この場所では操作できません。"
        if cell == D_STAIRS and p["floor"] < D_FLOORS:
            p["floor"] += 1
            p["hp"] = d_effective_stats(p)["max_hp"]
            d_ensure_map(p["floor"])
            p["x"], p["y"] = dg_starts[p["floor"]]
            msg = f"階段を上り、{p['floor']}Fへ進みました。"
        elif cell == D_MINE:
            gain = d_do_mine(self.uid)
            await d_apply_reward(self.uid, self.supabase, coins=gain)
            d_consume(p["floor"], p["x"], p["y"])
            await dg_save_map(p["floor"], self.supabase)
            msg = f"採掘してコインを{gain}枚獲得しました。"
        elif cell == D_REST:
            stats = d_effective_stats(p)
            before = p["hp"]
            p["hp"] = min(stats["max_hp"], p["hp"] + max(20, stats["max_hp"] // 3))
            d_consume(p["floor"], p["x"], p["y"])
            await dg_save_map(p["floor"], self.supabase)
            msg = f"休憩してHPが {p['hp'] - before} 回復しました。"
        elif cell == D_SHOP:
            try:
                await d_apply_reward(self.uid, self.supabase, coins=-30, bread=1)
                msg = "商店でレアパンを購入しました。"
            except Exception:
                msg = "コイン不足で購入できません。"
        await dg_save_player(self.uid, self.supabase)
        await self._back(interaction, msg)

    async def back(self, interaction):
        await interaction.response.defer()
        await self._back(interaction)

    def _add(self, label, callback, row=0, style=discord.ButtonStyle.grey):
        button = discord.ui.Button(label=label, style=style, row=row)
        button.callback = callback
        self.add_item(button)

    def __init_subclass__(cls, **kwargs):
        return super().__init_subclass__(**kwargs)

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True


# Operation buttons are attached after class creation to keep the screen compact.
def _operation_buttons_init(self, uid, floor, x, y, supabase):
    DungeonViewBase.__init__(self, uid, timeout=600)
    self.floor, self.x, self.y, self.supabase = floor, x, y, supabase
    self._add("STATUS", self.status, 0, discord.ButtonStyle.green)
    self._add("🍞 パン", self.use_bread, 0, discord.ButtonStyle.blurple)
    self._add("現在地を操作", self.current_action, 1, discord.ButtonStyle.primary)
    self._add("🏕 拠点", self.camp, 1, discord.ButtonStyle.grey)
    self._add("実績", self.achievements, 2, discord.ButtonStyle.grey)
    self._add("⬅️ 戻る", self.back, 2, discord.ButtonStyle.grey)
    job_select = discord.ui.Select(
        placeholder="職業を選択（冒険開始前のみ）",
        options=[discord.SelectOption(label=data["name"], value=key) for key, data in JOB_MASTER.items()],
        row=3,
    )
    job_select.callback = self.select_job
    self.add_item(job_select)

DungeonOperationView.__init__ = _operation_buttons_init

# ============================================================
#  Cog クラス
# ============================================================

class DungeonCog(Cog):
    """ダンジョンシステムCog"""
    def __init__(self, bot):
        self.bot = bot
        self.supabase = None
    
    async def cog_load(self):
        """Cog読み込み時"""
        # 親botのsupabaseを取得
        if hasattr(self.bot, 'supabase'):
            self.supabase = self.bot.supabase
            await dg_load_all(self.supabase)
        
        # アセットを読み込み
        load_all_assets()
        
        # タスク開始
        if not self.dungeon_monthly_task.is_running():
            self.dungeon_monthly_task.start()

    def cog_unload(self):
        """Cog アンロード時"""
        if self.dungeon_monthly_task.is_running():
            self.dungeon_monthly_task.cancel()

    @app_commands.command(name="dungeon", description="ダンジョンに入ります")
    async def dungeon_enter(self, interaction: Interaction):
        """ダンジョンコマンド"""
        await interaction.response.defer()
        uid = str(interaction.user.id)
        
        # プレイヤーデータ取得
        p = d_get_player(uid)
        floor, x, y = p["floor"], p["x"], p["y"]
        
        # マップ確認
        d_ensure_map(floor)
        
        # 初期位置設定
        sx, sy = dg_starts.get(floor, (1, 1))
        if x == 1 and y == 1:
            x, y = sx, sy
            p["x"] = x
            p["y"] = y
            if self.supabase:
                await dg_save_player(uid, self.supabase)

        # すべての通常操作・ステータス・D1開始/停止を1つの画面へ集約する。
        mv = DungeonUnifiedView(uid, floor, x, y, self.supabase)
        
        # 初期画像は専用チャンネルへ投げず、コマンド応答へ直接添付する。
        map_file = d_render_pillow(uid, floor, x, y)
        em = mv._embed("ダンジョンへようこそ！ 操作/STATUSから詳細操作を開けます。", has_image=True, image_url="attachment://map.png")
        await interaction.followup.send(embed=em, view=mv, file=map_file)

    @app_commands.command(name="dungeon_reset", description="ダンジョンマップをリセット（管理者のみ）")
    @app_commands.checks.has_permissions(administrator=True)
    async def dungeon_reset(self, interaction: Interaction):
        """ダンジョンリセットコマンド"""
        await interaction.response.defer()
        global dg_maps, dg_players, dg_starts, dg_used, dg_bases
        dg_maps.clear()
        dg_players.clear()
        dg_starts.clear()
        dg_used.clear()
        dg_bases.clear()
        
        # DBも全消去
        if self.supabase:
            try:
                self.supabase.table("dungeon_maps").delete().neq("floor", 0).execute()
                self.supabase.table("dungeon_players").delete().neq("user_id", "").execute()
                self.supabase.table("dungeon_bases").delete().neq("user_id", "").execute()
            except Exception as e:
                print(f"dungeon_reset DB削除失敗: {e}")
        
        for fl in range(1, D_FLOORS+1):
            d_ensure_map(fl)
            if self.supabase:
                await dg_save_map(fl, self.supabase)
        
        em = discord.Embed(title="リセット完了", description="マップを再生成しました！", color=0xFFFFFF)
        await interaction.followup.send(embed=em)

    @tasks.loop(hours=1)
    async def dungeon_monthly_task(self):
        """月初にマップとラン中状態だけを更新し、永続進行は保持する。"""
        now = datetime.datetime.now(JST)
        if now.day == 1 and now.hour == 0:
            global dg_maps, dg_players, dg_starts, dg_used, dg_bases
            dg_maps.clear()
            dg_starts.clear()
            dg_used.clear()
            dg_bases.clear()

            for player in dg_players.values():
                player["season_id"] = SEASON_ID
                player["season_score"] = 0
                player["floor"] = 1
                player["x"] = 1
                player["y"] = 1
                player["hp"] = d_effective_stats(player)["max_hp"]
                player["turns"] = 0
                player["cooldowns"] = {}
            
            if self.supabase:
                try:
                    self.supabase.table("dungeon_maps").delete().neq("floor", 0).execute()
                    self.supabase.table("dungeon_bases").delete().neq("user_id", "").execute()
                    self.supabase.table("dungeon_players").update({
                        "season_id": SEASON_ID,
                        "season_score": 0,
                        "floor": 1,
                        "x": 1,
                        "y": 1,
                        "turns": 0,
                        "cooldowns": {},
                    }).neq("user_id", "").execute()
                except Exception as e:
                    print(f"dungeon月次リセットDB削除失敗: {e}")
                
                for fl in range(1, D_FLOORS+1):
                    d_ensure_map(fl)
                    await dg_save_map(fl, self.supabase)
            
            print("✓ ダンジョン月次リセット完了")

    @dungeon_monthly_task.before_loop
    async def before_dungeon_task(self):
        await self.bot.wait_until_ready()


# セットアップ関数
async def setup(bot):
    """Cogをロード"""
    await bot.add_cog(DungeonCog(bot))
    print("✓ DungeonCog loaded")
# -*- coding: utf-8 -*-
"""MD差分を既存のダンジョン状態へ接続する拡張ブロック。"""

# 追加職業とスキル選択
JOB_MASTER.update({
    "priest": {"name": "僧侶", "atk": 0, "def_": 5, "max_hp": 15, "spd": 0, "crit": 0.0, "skill": "heal", "skills": ["heal", "blessing", "cleanse"]},
    "hunter": {"name": "狩人", "atk": 5, "def_": 1, "max_hp": 0, "spd": 4, "crit": 0.10, "skill": "mark", "skills": ["mark", "first_shot", "track"]},
    "alchemist": {"name": "錬金術師", "atk": 3, "def_": 1, "max_hp": 5, "spd": 2, "crit": 0.03, "skill": "acid", "skills": ["acid", "tonic", "smoke"]},
    "knight": {"name": "騎士", "atk": 2, "def_": 8, "max_hp": 25, "spd": -2, "crit": 0.0, "skill": "taunt", "skills": ["taunt", "iron_wall", "counter"]},
    "warlock": {"name": "呪術師", "atk": 6, "def_": -1, "max_hp": -5, "spd": 1, "crit": 0.04, "skill": "curse", "skills": ["curse", "silence", "drain"]},
    "adventurer": {"name": "冒険家", "atk": 2, "def_": 2, "max_hp": 8, "spd": 3, "crit": 0.05, "skill": "scout", "skills": ["scout", "lucky_find", "escape"]},
    "chef": {"name": "料理人", "atk": 1, "def_": 3, "max_hp": 20, "spd": 0, "crit": 0.0, "skill": "cook", "skills": ["cook", "season", "feast"]},
})
D1_PLANS.update({"xp": "経験値優先"})

# 装備の固定効果スキーマを全装備へ付与し、追加装備を登録する。
for _item in EQUIPMENT_MASTER.values():
    _item.setdefault("attack_count", 1); _item.setdefault("range", 1); _item.setdefault("penetration", 0)
    _item.setdefault("status_effect", None); _item.setdefault("passive_effects", []); _item.setdefault("set_id", None); _item.setdefault("upgrade_level", 0)
EQUIPMENT_MASTER.update({
    "hunter_bow": {"name": "狩人の長弓", "slot": "weapon", "atk": 8, "def_": 0, "hp": 0, "crit": .12, "element": "none", "kind": "bow", "description": "射程3・先制", "attack_count": 1, "range": 3, "passive_effects": ["first_strike"]},
    "knight_lance": {"name": "騎士槍", "slot": "weapon", "atk": 9, "def_": 3, "hp": 0, "crit": .02, "element": "light", "kind": "spear", "description": "防御貫通", "penetration": 5},
    "venom_cloak": {"name": "毒蛇外套", "slot": "armor", "atk": 0, "def_": 4, "hp": 10, "crit": 0, "element": "dark", "status_effect": "poison", "passive_effects": ["poison_resist"]},
    "scholar_ring": {"name": "賢者の指輪", "slot": "accessory", "atk": 4, "def_": 1, "hp": 5, "crit": .04, "element": "fire", "passive_effects": ["skill_cooldown"]},
})

NPC_MASTER = {
    "traveler": {"name": "旅人レオン", "steps": [{"text": "安全な道を教える", "flag": "traveler_help", "reward": {"bread": 2}}, {"text": "地図を交換する", "flag": "traveler_map", "reward": {"material": "map_fragment"}}]},
    "blacksmith": {"name": "鍛冶師ミナ", "steps": [{"text": "素材を渡す", "flag": "forge_help", "reward": {"material": "iron_ore"}}, {"text": "武器を強化する", "flag": "forge_upgrade", "reward": {"season_score": 30}}]},
    "scholar": {"name": "学者ユイ", "steps": [{"text": "図鑑を読む", "flag": "library_seen", "reward": {"xp": 50}}, {"text": "古代文字を解読する", "flag": "library_decode", "reward": {"relic": "explorer_compass"}}]},
    "prisoner": {"name": "囚人カイ", "steps": [{"text": "救出する", "flag": "prisoner_saved", "reward": {"coins": 100}}, {"text": "秘密を聞く", "flag": "prisoner_secret", "reward": {"season_score": 50}}]},
    "guildmaster": {"name": "ギルド長", "steps": [{"text": "依頼を受ける", "flag": "guild_quest", "reward": {"xp": 100}}, {"text": "深層の報告をする", "flag": "guild_report", "reward": {"relic": "d1_tactics"}}]},
}
FLOOR_GOALS = {
    "open_chests": {"name": "宝箱を開ける", "kind": "chests", "target": 3, "reward": {"relic": "lucky_coin"}},
    "defeat_enemies": {"name": "敵を倒す", "kind": "kills", "target": 3, "reward": {"season_score": 100}},
    "reach_floor": {"name": "深層へ進む", "kind": "floor", "target": 5, "reward": {"material": "ancient_shard"}},
}

_LEGACY_GET_PLAYER = d_get_player
_LEGACY_EFFECTIVE_STATS = d_effective_stats
_LEGACY_OPEN_CHEST = d_open_chest
_LEGACY_TRIGGER_TRAP = d_trigger_trap

def d_get_player(uid):
    p = _LEGACY_GET_PLAYER(uid)
    p.setdefault("skill_points", 0); p.setdefault("skills", []); p.setdefault("npc_flags", {})
    p.setdefault("story_flags", {}); p.setdefault("run_id", None); p.setdefault("run_started_at", None)
    p.setdefault("floor_goals", {}); p.setdefault("pending_rewards", []); p.setdefault("run_summary", {})
    p.setdefault("reward_ledger", []); p.setdefault("action_log", []); p.setdefault("state_version", 0)
    p.setdefault("front_back", "front"); p.setdefault("battle_resource", {"mp": 20, "max_mp": 20, "rage": 0, "combo": 0, "guard": 0})
    return p

def d_effective_stats(player):
    stats = _LEGACY_EFFECTIVE_STATS(player)
    p = player
    # upgrade level and set/passive effects are deterministic and persist in the JSON state.
    equipped = list(p.get("equipment", {}).values())
    for key in equipped:
        item = EQUIPMENT_MASTER.get(key, {})
        level = int(item.get("upgrade_level", 0))
        stats["atk"] += level; stats["def_"] += level
        if "speed_up" in item.get("passive_effects", []): stats["spd"] += 2
    if "set_steel" in [EQUIPMENT_MASTER.get(k, {}).get("set_id") for k in equipped]:
        stats["def_"] += 3
    if p.get("battle_resource", {}).get("guard", 0) > 0: stats["def_"] += p["battle_resource"]["guard"]
    return stats

def d_equipment_profile(uid):
    p = d_get_player(uid)
    return [dict(EQUIPMENT_MASTER.get(k, {}), key=k) for k in p.get("inventory", {}) if k in EQUIPMENT_MASTER]

def d_upgrade_equipment(uid, key, material="iron_ore"):
    p = d_get_player(uid)
    if key not in EQUIPMENT_MASTER or p.get("materials", {}).get(material, 0) <= 0: return False
    p["materials"][material] -= 1; EQUIPMENT_MASTER[key]["upgrade_level"] = int(EQUIPMENT_MASTER[key].get("upgrade_level", 0)) + 1
    return True

def d_open_chest(uid, supabase=None):
    text, reward = _LEGACY_OPEN_CHEST(uid, supabase)
    d_apply_floor_goal(uid, "chests", 1)
    p = d_get_player(uid)
    if "lucky_coin" in p.get("relics", []) and random.random() < .25:
        reward = {"coins": random.randint(100, 350)}; text = "幸運硬貨が輝いた！ " + text
    return text, reward

def d_trigger_trap(uid):
    p = d_get_player(uid)
    if "explorer_compass" in p.get("relics", []) and random.random() < .25:
        return "羅針盤が罠を発見し、回避しました。", {}
    return _LEGACY_TRIGGER_TRAP(uid)

def d_apply_special_status(uid, key, turns=None):
    d_apply_status(uid, key, turns)
    p = d_get_player(uid)
    if key == "freeze": p.setdefault("battle_flags", {})["skip_next"] = True
    elif key == "paralyze": p.setdefault("battle_flags", {})["paralyzed"] = True
    elif key == "silence": p.setdefault("battle_flags", {})["silenced"] = True
    elif key == "curse": p.setdefault("battle_flags", {})["cursed"] = True

def d_apply_floor_goal(uid, kind, amount=1):
    p = d_get_player(uid); goal = p.setdefault("floor_goals", {}).setdefault(str(p["floor"]), {"kind": "chests", "progress": 0, "target": 3, "completed": False})
    if goal.get("completed") or goal.get("kind") != kind: return None
    goal["progress"] = min(goal.get("target", 1), goal.get("progress", 0) + int(amount))
    if goal["progress"] >= goal["target"]: goal["completed"] = True; return goal
    return None

def d_floor_routes(uid):
    p = d_get_player(uid); floor = p.get("floor", 1)
    return [{"id": "safe", "label": "安全", "risk": 1, "reward": 1, "score": 4}, {"id": "treasure", "label": "財宝", "risk": 3, "reward": 4, "score": 3}, {"id": "battle", "label": "戦闘", "risk": 4, "reward": 5, "score": 2}]

def d1_action_candidates(uid, plan="安全探索"):
    p = d_get_player(uid); routes = d_floor_routes(uid); names = {v: k for k, v in D1_PLANS.items()}; key = names.get(plan, "safe")
    weights = {"safe": (3, -2), "speed": (1, 5), "treasure": (4, 0), "battle": (-1, 2), "explore": (2, 1), "boss": (1, 3), "xp": (0, 4)}
    risk_w, reward_w = weights.get(key, weights["safe"])
    for route in routes: route["plan_score"] = route["reward"] * reward_w - route["risk"] * risk_w
    return routes

def d1_candidate_log(uid, plan):
    candidates = d1_action_candidates(uid, plan)
    return "候補評価: " + " / ".join(f"{c['id']}:{c['label']} 危険度{c['risk']} 報酬{c['reward']} 作戦点{c['plan_score']}" for c in candidates)

def d_normalize_choice(value, legal, fallback=None):
    value = str(value or "").strip().lower().replace(" ", "")
    aliases = {"enter": "enter", "check": "enter", "upward": "up", "downward": "down"}
    value = aliases.get(value, value)
    return value if value in legal else (fallback if fallback in legal else None)

def d_make_reward_choices(uid, enemy):
    p = d_get_player(uid); base = [{"label": "コイン", "reward": {"coins": enemy.get("reward_coins", 0)}}, {"label": "経験値", "reward": {"xp": enemy.get("reward_xp", 0)}}, {"label": "宝箱", "reward": {"boxes": max(1, enemy.get("reward_box", 0))}}]
    if "d1_tactics" in p.get("relics", []): base[0]["reward"]["season_score"] = 10
    return base

def d_choose_reward(uid, choice):
    p = d_get_player(uid); pending = p.setdefault("pending_rewards", [])
    if not pending or choice not in range(len(pending)): return None
    reward = pending.pop(choice); return reward

def d_begin_run(uid, mode="manual"):
    p = d_get_player(uid); p["run_id"] = f"run-{uid}-{int(datetime.datetime.now().timestamp())}"; p["run_started_at"] = datetime.datetime.now(JST).isoformat(); p["run_summary"] = {"mode": mode, "turns": 0, "kills": 0, "floor": p["floor"]}; return p["run_id"]

def d_end_run(uid, reason="ended"):
    p = d_get_player(uid); p.setdefault("run_summary", {})["end_reason"] = reason; p["run_id"] = None; p["active_effects"] = []; p["cooldowns"] = {}; return p["run_summary"]

def d_record_action(uid, action, source="manual", result=None, reward=None, hp_before=None):
    p = d_get_player(uid); p["state_version"] += 1; entry = {"id": p["state_version"], "run_id": p.get("run_id"), "turn": p.get("turns", 0), "floor": p["floor"], "x": p["x"], "y": p["y"], "action": action, "source": source, "result": result, "reward": reward, "hp_before": hp_before, "hp_after": p["hp"], "created_at": datetime.datetime.now(JST).isoformat()}; p["action_log"] = (p.get("action_log", []) + [entry])[-100:]; return entry

def d_record_reward(uid, action_id, reward):
    p = d_get_player(uid); keys = [x.get("action_id") for x in p.get("reward_ledger", [])]
    if action_id in keys: return False
    p["reward_ledger"].append({"action_id": action_id, "reward": reward, "created_at": datetime.datetime.now(JST).isoformat()}); return True

# Existing code resolves these globals at call time, so wrappers become active immediately.

# 追加職業のスキル効果と拡張状態の接続
_LEGACY_USE_JOB_SKILL = d_use_job_skill
def d_use_job_skill(uid, enemy):
    p = d_get_player(uid); job = JOB_MASTER.get(p.get("job", "warrior"), JOB_MASTER["warrior"])
    skill = job.get("skill", "power_strike"); cooldowns = p.setdefault("cooldowns", {})
    if cooldowns.get(skill, 0) > 0:
        return f"{skill}はあと{cooldowns[skill]}ターン使用できません。", 0
    stats = d_effective_stats(p); cooldowns[skill] = 3
    if skill == "heal":
        before = p["hp"]; p["hp"] = min(stats["max_hp"], p["hp"] + max(20, stats["max_hp"] // 3)); return f"僧侶の回復！ HPが{p['hp'] - before}回復", 0
    if skill == "blessing":
        cooldowns["blessing_buff"] = 3; return "僧侶の祝福！ 次の防御力が上昇", 0
    if skill in ("cleanse", "tonic"):
        p["active_effects"] = []; p.setdefault("battle_flags", {}).clear(); return "状態異常を解除しました", 0
    if skill in ("mark", "curse", "acid"):
        d_apply_special_status(uid, "curse" if skill == "curse" else "bleed", 3)
        damage = max(1, int(stats["atk"] * 1.4) - enemy.get("def_", 0)); return f"{job['name']}の{skill}！ {damage}ダメージ", damage
    if skill in ("first_shot", "scout", "lucky_find"):
        damage = max(1, int(stats["atk"] * 1.8) - enemy.get("def_", 0)); return f"{job['name']}の先制攻撃！ {damage}ダメージ", damage
    if skill in ("taunt", "iron_wall"):
        p.setdefault("battle_resource", {})["guard"] = 8; return f"{job['name']}の鉄壁！ 防御力が上昇", 0
    if skill in ("counter", "drain"):
        damage = max(1, int(stats["atk"] * 1.6) - enemy.get("def_", 0)); return f"{job['name']}の反撃！ {damage}ダメージ", damage
    if skill in ("cook", "feast"):
        p["battle_resource"]["rage"] = min(100, p["battle_resource"].get("rage", 0) + 30); return "料理人の料理！ 怒気が上昇", 0
    return _LEGACY_USE_JOB_SKILL(uid, enemy)

# 既存の敵ターンへ凍結・麻痺・沈黙・呪いを接続する。
_LEGACY_ENEMY_TURN = DungeonCombatView._enemy_turn
def _enemy_turn_with_status(self):
    p = d_get_player(self.uid); flags = p.setdefault("battle_flags", {})
    if flags.pop("skip_next", False):
        self.defending = False; return "凍結で行動できませんでした"
    if flags.pop("paralyzed", False) and random.random() < .5:
        self.defending = False; return "麻痺で行動に失敗しました"
    result = _LEGACY_ENEMY_TURN(self)
    if flags.get("cursed"):
        p["hp"] = max(0, p["hp"] - 2); result += " / 呪いで2ダメージ"
    return result
DungeonCombatView._enemy_turn = _enemy_turn_with_status

# 報酬・状態ログを既存保存へ追加する。
_LEGACY_SAVE_PLAYER = dg_save_player
async def dg_save_player(uid, supabase):
    await _LEGACY_SAVE_PLAYER(uid, supabase)
    if not supabase or str(uid) not in dg_players:
        return
    p = d_get_player(uid); inventory = dict(p.get("inventory", {})); inventory["_dungeon_meta"] = {
        "relics": p.get("relics", []), "active_effects": p.get("active_effects", []), "materials": p.get("materials", {}),
        "quests": p.get("quests", {}), "run_modifiers": p.get("run_modifiers", []), "camp_facilities": p.get("camp_facilities", {}),
        "battle_stats": p.get("battle_stats", {}), "skill_points": p.get("skill_points", 0), "skills": p.get("skills", []),
        "npc_flags": p.get("npc_flags", {}), "story_flags": p.get("story_flags", {}), "run_id": p.get("run_id"),
        "run_summary": p.get("run_summary", {}), "pending_rewards": p.get("pending_rewards", []), "reward_ledger": p.get("reward_ledger", []),
        "action_log": p.get("action_log", [])[-100:], "state_version": p.get("state_version", 0), "front_back": p.get("front_back", "front"),
        "battle_resource": p.get("battle_resource", {}), "floor_goals": p.get("floor_goals", {}),
    }
    try:
        supabase.table("dungeon_players").update({"inventory": inventory}).eq("user_id", str(uid)).execute()
    except Exception:
        logger.warning("extended dungeon state save failed", exc_info=True)

class DungeonRewardChoiceView(DungeonViewBase):
    """戦闘勝利時に3候補から1つだけ受け取るView。"""
    def __init__(self, uid, floor, x, y, supabase, choices):
        super().__init__(uid, timeout=120); self.floor, self.x, self.y, self.supabase, self.choices = floor, x, y, supabase, choices
        for index, item in enumerate(choices):
            button = discord.ui.Button(label=item["label"], style=discord.ButtonStyle.green, row=0)
            async def choose(interaction, index=index):
                await interaction.response.defer(); p = d_get_player(self.uid)
                if not p.get("pending_rewards"):
                    await interaction.edit_original_response(embed=discord.Embed(title="報酬は受取済みです"), view=None, attachments=[]); return
                reward = d_choose_reward(self.uid, index)
                if reward is None:
                    await interaction.edit_original_response(embed=discord.Embed(title="報酬の選択に失敗しました"), view=self); return
                await d_apply_reward(self.uid, self.supabase, **reward); await dg_save_player(self.uid, self.supabase); self.stop()
                mv = DungeonMainView(self.uid, p["floor"], p["x"], p["y"], self.supabase)
                await interaction.edit_original_response(embed=mv._embed(f"報酬を選択: {item['label']}"), view=mv, attachments=[d_render_pillow(self.uid, p["floor"], p["x"], p["y"])])
            button.callback = choose; self.add_item(button)

_LEGACY_COMBAT_WIN = DungeonCombatView._win
async def _combat_win_with_choices(self, interaction):
    if interaction.__class__.__name__ == "_NoopInteraction":
        return await _LEGACY_COMBAT_WIN(self, interaction)
    choices = d_make_reward_choices(self.uid, self.enemy); p = d_get_player(self.uid); p["pending_rewards"] = [x["reward"] for x in choices]
    self.log.append("勝利！報酬を3候補から1つ選択してください")
    await dg_save_player(self.uid, self.supabase); self.stop()
    view = DungeonRewardChoiceView(self.uid, self.floor, self.x, self.y, self.supabase, choices)
    await interaction.edit_original_response(embed=self._embed(), view=view, attachments=[d_render_pillow(self.uid, self.floor, self.x, self.y)])
DungeonCombatView._win = _combat_win_with_choices

async def _show_inventory(self, interaction):
    await interaction.response.defer(); p = d_get_player(self.uid)
    lines = [f"{EQUIPMENT_MASTER[k]['name']} ×{v}" for k, v in p.get("inventory", {}).items() if k in EQUIPMENT_MASTER]
    lines += [f"素材: {k} ×{v}" for k, v in p.get("materials", {}).items()]
    await self._back(interaction, "所持品\n" + ("\n".join(lines) or "なし"))

async def _show_npcs(self, interaction):
    await interaction.response.defer(); p = d_get_player(self.uid)
    lines = [f"{v['name']}: {'進行済み' if any(x.get('flag') in p.get('npc_flags', {}) for x in v['steps']) else '未訪問'}" for v in NPC_MASTER.values()]
    await self._back(interaction, "NPC・依頼\n" + "\n".join(lines))

async def _show_goals(self, interaction):
    await interaction.response.defer(); p = d_get_player(self.uid)
    goal = p.setdefault("floor_goals", {}).get(str(p["floor"]), {"kind": "chests", "progress": 0, "target": 3, "completed": False})
    name = next((v["name"] for v in FLOOR_GOALS.values() if v["kind"] == goal.get("kind")), "宝箱を開ける")
    await self._back(interaction, f"フロア目標: {name} {goal.get('progress', 0)}/{goal.get('target', 3)}")

async def _upgrade_forge(self, interaction):
    await interaction.response.defer(); p = d_get_player(self.uid)
    weapon = p.get("equipment", {}).get("weapon")
    msg = "鍛冶対象の武器がありません。"
    if weapon and d_upgrade_equipment(self.uid, weapon): msg = f"{EQUIPMENT_MASTER[weapon]['name']}を強化しました。"
    await dg_save_player(self.uid, self.supabase); await self._back(interaction, msg)

DungeonOperationView.show_inventory = _show_inventory
DungeonOperationView.show_npcs = _show_npcs
DungeonOperationView.show_goals = _show_goals
DungeonOperationView.upgrade_forge = _upgrade_forge
_OLD_OPERATION_INIT = DungeonOperationView.__init__
def _extended_operation_init(self, uid, floor, x, y, supabase):
    _OLD_OPERATION_INIT(self, uid, floor, x, y, supabase)
    self._add("所持品", self.show_inventory, 2, discord.ButtonStyle.grey)
    self._add("NPC/依頼", self.show_npcs, 2, discord.ButtonStyle.grey)
    self._add("フロア目標", self.show_goals, 3, discord.ButtonStyle.primary)
    self._add("鍛冶強化", self.upgrade_forge, 3, discord.ButtonStyle.grey)
DungeonOperationView.__init__ = _extended_operation_init
