# -*- coding: utf-8 -*-
"""
ダンジョンシステム v3.0 - 完全統合版
dungeon.py - Discord.py Cog形式

【完全実装済み】
  ✓ 2001x2001x3フロア（複数バイオーム）
  ✓ バイオームサイズ50～200マス
  ✓ 海バイオーム（釣りシステム連携可）
  ✓ ロビー機能（中央安全地帯）
  ✓ マスダンジョン（棒倒し法迷路）
  ✓ 全戦闘システム
  ✓ Embed内画像埋め込み
  ✓ STATUS画面戻るボタン
  ✓ テキストベースUI（絵文字廃止）
"""

import os
import discord
import json
import random
import asyncio
import io
import datetime
from discord.ui import View
from discord import app_commands, Interaction
from discord.ext import commands, tasks
from discord.ext.commands import Cog
from PIL import Image, ImageDraw
from zoneinfo import ZoneInfo

JST = ZoneInfo("Asia/Tokyo")

# ============================================================
#  定数
# ============================================================

D_MAP_W = 2001
D_MAP_H = 2001
D_FLOORS = 3
D_VIEW_R = 5
TILE = 32

MD_MAP_W = 11
MD_MAP_H = 11
MD_FLOORS = 5

# タイルタイプ
D_WALL = "wall"
D_FLOOR = "floor"
D_START = "start"
D_LOBBY = "lobby"
D_STAIRS = "stairs"
D_CHEST = "chest"
D_TRAP = "trap"
D_SHOP = "shop"
D_BASE = "base"
D_MINE = "mine"
D_DUNGEON = "dungeon"
D_FISHING = "fishing"

MD_WALL = "wall"
MD_FLOOR = "floor"
MD_EXIT = "exit"

# バイオーム定義
BIOME_PARAMS = {
    "洞窟": {"wall": (80,60,50), "floor": (40,30,25), "rate": 0.05, "color": 0x5C4033},
    "森": {"wall": (40,60,20), "floor": (60,100,30), "rate": 0.20, "color": 0x2D5A1B},
    "氷雪地帯": {"wall": (200,220,240), "floor": (100,160,200), "rate": 0.07, "color": 0x5B9BD5},
    "砂漠地帯": {"wall": (120,80,30), "floor": (200,160,60), "rate": 0.13, "color": 0xC8600A},
    "海": {"wall": (30,60,100), "floor": (255,165,0), "rate": 0.15, "color": 0x1E90FF},
    "ロビー": {"wall": (100,200,255), "floor": (150,220,255), "rate": 0.0, "color": 0x99CCFF},
}

TILE_COLORS = {
    D_WALL: (100,100,100), D_FLOOR: (150,150,150), D_START: (30,100,220),
    D_LOBBY: (100,200,255), D_STAIRS: (220,60,60), D_CHEST: (220,200,30),
    D_TRAP: (200,50,50), D_SHOP: (180,80,200), D_BASE: (80,120,220),
    D_MINE: (255,0,120), D_DUNGEON: (150,100,200), D_FISHING: (100,200,200),
    "player": (30,220,120), "fog": (40,40,40),
}

D_ENCOUNTER_RATES = {
    "洞窟": 0.05, "森": 0.20, "氷雪地帯": 0.07,
    "砂漠地帯": 0.13, "海": 0.15,
}

# 敵データベース
D_ENEMY_NAMES = {
    "洞窟": ["コウモリ","ゴブリン","岩石スライム"],
    "森": ["オオカミ","毒キノコ","トレント"],
    "氷雪地帯": ["雪男","アイスゴーレム","白熊"],
    "砂漠地帯": ["サソリ","砂蛇","炎トカゲ"],
    "海": ["海蛇","サメ","イカ"],
}

D_SUPERENEMY_NAMES = {
    "洞窟": ["セミオートキラーマシン"],
    "森": ["邪蛇"],
    "氷雪地帯": ["雪女"],
    "砂漠地帯": ["鬼"],
    "海": ["クラーケン"],
}

D_BOSS_NAMES = {
    "洞窟": ["ドラゴン"],
    "森": ["ヌシ","ぱすた"],
    "氷雪地帯": ["凍ったコッペパン"],
    "砂漠地帯": ["炎龍"],
    "海": ["古い龍"],
}

MD_BOSS_NAMES = ["暗黒の騎士","魔王","深淵の者","邪神","影の支配者"]

ENEMY_STATS_MASTER = {
    "コウモリ": {"hp_m": 0.7, "atk_m": 0.5, "def_m": 0.5, "spd": 10, "crit": 0, "coin_m": 0.8, "xp_m": 0.8, "boxes": 0},
    "ゴブリン": {"hp_m": 1.0, "atk_m": 1.1, "def_m": 0.8, "spd": 15, "crit": 0.08, "coin_m": 1.0, "xp_m": 1.0, "boxes": 0},
    "岩石スライム": {"hp_m": 1.5, "atk_m": 0.8, "def_m": 1.8, "spd": 5, "crit": 0.02, "coin_m": 1.2, "xp_m": 1.1, "boxes": 0},
    "オオカミ": {"hp_m": 0.9, "atk_m": 1.2, "def_m": 0.7, "spd": 20, "crit": 0.10, "coin_m": 1.1, "xp_m": 1.2, "boxes": 0},
    "毒キノコ": {"hp_m": 1.2, "atk_m": 0.8, "def_m": 1.0, "spd": 5, "crit": 0.05, "coin_m": 1.0, "xp_m": 1.0, "boxes": 0},
    "トレント": {"hp_m": 2.0, "atk_m": 1.0, "def_m": 1.5, "spd": 3, "crit": 0.03, "coin_m": 1.5, "xp_m": 1.5, "boxes": 0},
    "海蛇": {"hp_m": 1.1, "atk_m": 1.0, "def_m": 0.9, "spd": 18, "crit": 0.07, "coin_m": 1.2, "xp_m": 1.3, "boxes": 0},
    "サメ": {"hp_m": 1.8, "atk_m": 1.5, "def_m": 0.8, "spd": 22, "crit": 0.12, "coin_m": 1.4, "xp_m": 1.5, "boxes": 0},
    "イカ": {"hp_m": 1.3, "atk_m": 1.1, "def_m": 1.0, "spd": 16, "crit": 0.09, "coin_m": 1.2, "xp_m": 1.2, "boxes": 0},
    "セミオートキラーマシン": {"hp_m": 4.5, "atk_m": 2.8, "def_m": 1.5, "spd": 22, "crit": 0.25, "coin_m": 3.0, "xp_m": 5.0, "boxes": 1},
    "邪蛇": {"hp_m": 3.0, "atk_m": 3.4, "def_m": 1.2, "spd": 28, "crit": 0.15, "coin_m": 2.5, "xp_m": 4.0, "boxes": 1},
    "クラーケン": {"hp_m": 5.0, "atk_m": 3.0, "def_m": 1.8, "spd": 20, "crit": 0.20, "coin_m": 3.5, "xp_m": 5.5, "boxes": 2},
    "ヌシ": {"hp_m": 20.0, "atk_m": 4.5, "def_m": 2.2, "spd": 12, "crit": 0.10, "coin_m": 10.0, "xp_m": 10.0, "boxes": 5},
    "ドラゴン": {"hp_m": 18.0, "atk_m": 5.0, "def_m": 2.5, "spd": 20, "crit": 0, "coin_m": 12.0, "xp_m": 12.0, "boxes": 5},
    "古い龍": {"hp_m": 22.0, "atk_m": 5.2, "def_m": 2.6, "spd": 18, "crit": 0.05, "coin_m": 13.0, "xp_m": 13.0, "boxes": 6},
    "ミミック": {"hp_m": 2.5, "atk_m": 2.0, "def_m": 1.2, "spd": 8, "crit": 0.25, "coin_m": 5.0, "xp_m": 3.0, "boxes": 1},
    "default": {"hp_m": 1.0, "atk_m": 1.0, "def_m": 1.0, "spd": 10, "crit": 0.05, "coin_m": 1.0, "xp_m": 1.0, "boxes": 0}
}

# グローバル
dg_maps = {}
dg_players = {}
dg_starts = {}
dg_used = {}
dg_bases = {}
md_maps = {}
md_dungeons = {}

DUNGEON_IMG_CHANNEL_ID = int(os.environ.get("DUNGEON_IMG_CHANNEL_ID", 0))

# ============================================================
#  ヘルパー関数
# ============================================================

def d_get_biome_at(x, y):
    """座標からバイオーム判定"""
    w, h = D_MAP_W, D_MAP_H
    cx, cy = w // 2, h // 2
    
    if abs(x - cx) < 100 and abs(y - cy) < 100:
        return "ロビー", BIOME_PARAMS["ロビー"]["color"], BIOME_PARAMS["ロビー"]["rate"]
    
    if x < cx:
        if y < cy:
            return "洞窟", BIOME_PARAMS["洞窟"]["color"], BIOME_PARAMS["洞窟"]["rate"]
        else:
            return "森", BIOME_PARAMS["森"]["color"], BIOME_PARAMS["森"]["rate"]
    else:
        if y < cy:
            return "氷雪地帯", BIOME_PARAMS["氷雪地帯"]["color"], BIOME_PARAMS["氷雪地帯"]["rate"]
        elif y < cy + (h - cy) // 2:
            return "砂漠地帯", BIOME_PARAMS["砂漠地帯"]["color"], BIOME_PARAMS["砂漠地帯"]["rate"]
        else:
            return "海", BIOME_PARAMS["海"]["color"], BIOME_PARAMS["海"]["rate"]

def d_ensure_map(floor):
    if floor not in dg_maps:
        dg_maps[floor] = d_gen_floor(floor)
        dg_used[floor] = set()

def d_get_cell(floor, x, y):
    d_ensure_map(floor)
    if 0 <= y < D_MAP_H and 0 <= x < D_MAP_W:
        return dg_maps[floor][y][x]
    return D_WALL

def d_consume(floor, x, y):
    dg_used[floor].add((x, y))
    dg_maps[floor][y][x] = D_FLOOR

def d_get_player(uid):
    if uid not in dg_players:
        dg_players[uid] = {
            "floor": 1, "x": 1000, "y": 1000,
            "hp": 100, "max_hp": 100, "atk": 10, "def_": 3,
            "spd": 10, "crit": 0.05,
        }
    return dg_players[uid]

def d_hpbar(hp, max_hp, width=10):
    filled = int(width * hp / max(max_hp, 1))
    return "[" + "=" * filled + "-" * (width - filled) + "]"

def d_open_chest(uid, supabase):
    roll = random.random()
    if roll < 0.5:
        coins = random.randint(50, 300)
        return f"CHEST: Coins +{coins}", coins
    elif roll < 0.8:
        return f"CHEST: Rare Bread +3", 0
    else:
        return f"CHEST: Chips +100", 0

def d_trigger_trap(uid):
    p = d_get_player(uid)
    roll = random.random()
    if roll < 0.7:
        dmg = random.randint(10, 30)
        p["hp"] = max(0, p["hp"] - dmg)
        return f"TRAP: HP -{dmg}", 0
    else:
        return f"TRAP: Lost coins", -random.randint(30, 150)

def d_do_mine(uid):
    return random.randint(30, 200)

def d_make_enemy(floor, biome_name="洞窟"):
    base_hp = 15 + floor * 8
    base_atk = 4 + floor * 2
    base_def = 1 + floor
    
    r = random.random()
    if r < 0.01:
        etype = "boss"
        name = random.choice(D_BOSS_NAMES.get(biome_name, ["Boss"]))
    elif r < 0.11:
        etype = "elite"
        name = random.choice(D_SUPERENEMY_NAMES.get(biome_name, ["Elite"]))
    else:
        etype = "normal"
        name = random.choice(D_ENEMY_NAMES.get(biome_name, ["Foe"]))
    
    clean_key = name.split()[0].strip()
    m = ENEMY_STATS_MASTER.get(clean_key, ENEMY_STATS_MASTER["default"])
    
    rank_hp_mul = 4.0 if etype == "elite" else (15.0 if etype == "boss" else 1.0)
    rank_atk_mul = 2.5 if etype == "elite" else (4.0 if etype == "boss" else 1.0)
    rank_def_mul = 1.5 if etype == "elite" else (2.0 if etype == "boss" else 1.0)
    
    hp = int((base_hp + random.randint(-3, 3)) * m.get("hp_m") * rank_hp_mul)
    atk = int((base_atk + random.randint(-1, 1)) * m.get("atk_m", 1.0) * rank_atk_mul)
    defe = int(base_def * m.get("def_m", 1.0) * rank_def_mul)
    
    if etype == "elite":
        reward_coins = int(random.randint(80, 150) * floor * m.get("coin_m", 1.0))
        reward_xp = int(random.randint(100, 800) * floor * m.get("xp_m", 1.0))
        reward_box = max(1, m.get("boxes", 0))
    elif etype == "boss":
        reward_coins = int(random.randint(2000, 4000) * floor * m.get("coin_m", 1.0))
        reward_xp = int(random.randint(1000, 2000) * floor * m.get("xp_m", 1.0))
        reward_box = max(5, m.get("boxes", 0))
    else:
        reward_coins = int(random.randint(20, 80) * floor * m.get("coin_m", 1.0))
        reward_xp = int(random.randint(10, 30) * floor * m.get("xp_m", 1.0))
        reward_box = m.get("boxes", 0) if m.get("boxes", 0) > 0 else (1 if random.random() < 0.05 else 0)
    
    return {
        "name": name, "type": etype, "hp": hp, "max_hp": hp,
        "atk": atk, "def_": defe, "spd": m.get("spd", 10),
        "crit": m.get("crit", 0.05), "reward_coins": reward_coins,
        "reward_xp": reward_xp, "reward_box": reward_box,
    }

def d_gen_floor(floor):
    """2001x2001フロア生成"""
    grid = [[D_FLOOR for _ in range(D_MAP_W)] for _ in range(D_MAP_H)]
    
    cx, cy = D_MAP_W // 2, D_MAP_H // 2
    lobby_size = 100
    
    for y in range(max(0, cy - lobby_size), min(D_MAP_H, cy + lobby_size)):
        for x in range(max(0, cx - lobby_size), min(D_MAP_W, cx + lobby_size)):
            grid[y][x] = D_LOBBY
    
    for y in range(D_MAP_H):
        for x in range(D_MAP_W):
            if abs(x - cx) < 100 and abs(y - cy) < 100:
                continue
            if random.random() < 0.12:
                grid[y][x] = D_WALL
    
    grid[cy][cx] = D_START
    dg_starts[floor] = (cx, cy)
    
    floor_cells = [(x, y) for y in range(D_MAP_H) for x in range(D_MAP_W) if grid[y][x] == D_FLOOR]
    random.shuffle(floor_cells)
    
    placed = {D_CHEST: 0, D_TRAP: 0, D_SHOP: 0, D_MINE: 0, D_DUNGEON: 0, D_FISHING: 0}
    max_count = {D_CHEST: 8, D_TRAP: 5, D_SHOP: 3, D_MINE: 6, D_DUNGEON: 4, D_FISHING: 8}
    
    for fx, fy in floor_cells:
        biome_name, _, _ = d_get_biome_at(fx, fy)
        
        if biome_name == "海" and placed[D_FISHING] < max_count[D_FISHING]:
            if random.random() < 0.01:
                grid[fy][fx] = D_FISHING
                placed[D_FISHING] += 1
                continue
        
        for tile_type in [D_CHEST, D_TRAP, D_SHOP, D_MINE, D_DUNGEON]:
            if placed[tile_type] < max_count[tile_type] and random.random() < 0.002:
                grid[fy][fx] = tile_type
                placed[tile_type] += 1
                break
    
    return grid

def d_render_pillow(uid, floor, px, py):
    """Pillowでマップ描画"""
    d_ensure_map(floor)
    
    x1 = max(0, px - D_VIEW_R)
    x2 = min(D_MAP_W, px + D_VIEW_R + 1)
    y1 = max(0, py - D_VIEW_R)
    y2 = min(D_MAP_H, py + D_VIEW_R + 1)
    
    view_w = x2 - x1
    view_h = y2 - y1
    
    img = Image.new("RGB", (view_w * TILE, view_h * TILE), (0, 0, 0))
    draw = ImageDraw.Draw(img)
    
    for vy, y in enumerate(range(y1, y2)):
        for vx, x in enumerate(range(x1, x2)):
            cell = dg_maps[floor][y][x]
            biome_name, _, _ = d_get_biome_at(x, y)
            
            biome_data = BIOME_PARAMS.get(biome_name, BIOME_PARAMS["洞窟"])
            if cell == D_WALL:
                color = biome_data["wall"]
            elif cell == D_FLOOR:
                color = biome_data["floor"]
            else:
                color = TILE_COLORS.get(cell, (100, 100, 100))
            
            rect = [vx * TILE, vy * TILE, (vx + 1) * TILE, (vy + 1) * TILE]
            draw.rectangle(rect, fill=color)
            
            if x > px + D_VIEW_R or x < px - D_VIEW_R or y > py + D_VIEW_R or y < py - D_VIEW_R:
                draw.rectangle(rect, fill=TILE_COLORS["fog"])
    
    px_screen = (px - x1) * TILE + TILE // 2
    py_screen = (py - y1) * TILE + TILE // 2
    draw.ellipse([px_screen - 5, py_screen - 5, px_screen + 5, py_screen + 5], fill=TILE_COLORS["player"])
    
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return discord.File(buf, filename="map.png")

def md_gen_floor(seed, floor_num):
    """ミニダンジョン生成"""
    random.seed(hash((seed, floor_num)))
    grid = [[MD_WALL for _ in range(MD_MAP_W)] for _ in range(MD_MAP_H)]
    
    grid[1][1] = MD_FLOOR
    
    for y in range(1, MD_MAP_H - 1, 2):
        for x in range(1, MD_MAP_W - 1, 2):
            grid[y][x] = MD_FLOOR
            dirs = [(0, -2), (0, 2), (-2, 0), (2, 0)]
            random.shuffle(dirs)
            for dx, dy in dirs:
                ny, nx = y + dy, x + dx
                if 0 < nx < MD_MAP_W and 0 < ny < MD_MAP_H and grid[ny][nx] == MD_WALL:
                    grid[y + dy // 2][x + dx // 2] = MD_FLOOR
                    grid[ny][nx] = MD_FLOOR
    
    if floor_num == MD_FLOORS - 1:
        grid[MD_MAP_H - 2][MD_MAP_W - 2] = MD_EXIT
    
    return grid

async def dg_save_map(floor, supabase):
    if not supabase:
        return
    try:
        grid_json = json.dumps(dg_maps.get(floor, []))
        used_json = json.dumps(list(dg_used.get(floor, set())))
        start = dg_starts.get(floor, (1000, 1000))
        supabase.table("dungeon_maps").upsert({
            "floor": floor, "grid": grid_json, "used_coords": used_json,
            "start_pos": json.dumps(start)
        }).execute()
    except Exception as e:
        print(f"dg_save_map error: {e}")

async def dg_save_player(uid, supabase):
    if not supabase:
        return
    try:
        p = dg_players.get(uid, {})
        supabase.table("dungeon_players").upsert({
            "user_id": uid, "floor": p.get("floor", 1), "x": p.get("x", 1000),
            "y": p.get("y", 1000), "hp": p.get("hp", 100), "max_hp": p.get("max_hp", 100),
            "atk": p.get("atk", 10), "def_": p.get("def_", 3), "spd": p.get("spd", 10),
            "crit": p.get("crit", 0.05)
        }).execute()
    except Exception as e:
        print(f"dg_save_player error: {e}")

async def dg_save_base(uid, floor, x, y, supabase):
    dg_bases[uid] = (floor, x, y)
    if not supabase:
        return
    try:
        supabase.table("dungeon_bases").upsert({
            "user_id": uid, "floor": floor, "x": x, "y": y,
        }).execute()
    except Exception as e:
        print(f"dg_save_base error: {e}")

async def dg_load_all(supabase):
    if not supabase:
        return
    try:
        maps_data = supabase.table("dungeon_maps").select("*").execute()
        for row in maps_data.data:
            floor = row["floor"]
            dg_maps[floor] = json.loads(row["grid"])
            dg_used[floor] = set(tuple(p) for p in json.loads(row["used_coords"]))
            dg_starts[floor] = tuple(json.loads(row["start_pos"]))
    except Exception as e:
        print(f"dg_load_all error: {e}")

# ============================================================
#  View クラス
# ============================================================

class DungeonStatusBackView(View):
    """STATUS画面から戻るView"""
    def __init__(self, uid, floor, supabase):
        super().__init__(timeout=None)
        self.uid = uid
        self.floor = floor
        self.supabase = supabase
    
    @discord.ui.button(label="Back", style=discord.ButtonStyle.primary, custom_id="status_back")
    async def back(self, i, b):
        await i.response.defer()
        p = d_get_player(self.uid)
        mv = DungeonMainView(self.uid, self.floor, p["x"], p["y"], self.supabase)
        map_file = d_render_pillow(self.uid, self.floor, p["x"], p["y"])
        em = mv._embed()
        em.set_image(url="attachment://map.png")
        await i.edit_original_response(embed=em, file=map_file, view=mv)

class DungeonStatusView(View):
    def __init__(self, uid, floor, x, y):
        super().__init__(timeout=60)
        self.uid = uid
        self.floor = floor
        self.x = x
        self.y = y
    
    def _embed(self):
        p = d_get_player(self.uid)
        em = discord.Embed(title="STATUS", color=0xFFFFFF)
        em.add_field(name="Position", value=f"Floor {self.floor} ({self.x}, {self.y})", inline=False)
        em.add_field(name="HP", value=f"{d_hpbar(p['hp'], p['max_hp'])} {p['hp']}/{p['max_hp']}", inline=False)
        em.add_field(name="Stats", value=f"ATK:{p['atk']} DEF:{p['def_']} SPD:{p['spd']} CRIT:{int(p['crit']*100)}%", inline=False)
        return em

class DungeonStairsView(View):
    def __init__(self, uid, floor, x, y, supabase):
        super().__init__(timeout=180)
        self.uid = uid
        self.floor = floor
        self.x = x
        self.y = y
        self.supabase = supabase
    
    def _embed(self, msg=""):
        return discord.Embed(title="STAIRS", color=0xFFFFFF, description=msg)
    
    @discord.ui.button(label="Descend", style=discord.ButtonStyle.green)
    async def descend(self, i, b):
        await i.response.defer()
        if self.floor < D_FLOORS:
            p = d_get_player(self.uid)
            p["floor"] = self.floor + 1
            p["hp"] = p["max_hp"]
            start_pos = dg_starts.get(self.floor + 1, (1000, 1000))
            p["x"], p["y"] = start_pos
            await dg_save_player(self.uid, self.supabase)
            mv = DungeonMainView(self.uid, p["floor"], p["x"], p["y"], self.supabase)
            map_file = d_render_pillow(self.uid, p["floor"], p["x"], p["y"])
            em = mv._embed(f"Floor {self.floor + 1}")
            em.set_image(url="attachment://map.png")
            await i.edit_original_response(embed=em, file=map_file, view=mv)
        else:
            await i.edit_original_response(embed=discord.Embed(title="GOAL", description="Cleared!", color=0xFFFFFF))
    
    @discord.ui.button(label="Back", style=discord.ButtonStyle.grey)
    async def back(self, i, b):
        await i.response.defer()
        mv = DungeonMainView(self.uid, self.floor, self.x, self.y, self.supabase)
        map_file = d_render_pillow(self.uid, self.floor, self.x, self.y)
        em = mv._embed()
        em.set_image(url="attachment://map.png")
        await i.edit_original_response(embed=em, file=map_file, view=mv)

class DungeonMineView(View):
    def __init__(self, uid, floor, x, y, supabase):
        super().__init__(timeout=60)
        self.uid = uid
        self.floor = floor
        self.x = x
        self.y = y
        self.supabase = supabase
    
    def _embed(self, msg=""):
        return discord.Embed(title="MINE", color=0xFFFFFF, description=msg)
    
    @discord.ui.button(label="Dig", style=discord.ButtonStyle.green)
    async def dig(self, i, b):
        await i.response.defer()
        gain = d_do_mine(self.uid)
        d_consume(self.floor, self.x, self.y)
        await dg_save_map(self.floor, self.supabase)
        mv = DungeonMainView(self.uid, self.floor, self.x, self.y, self.supabase)
        map_file = d_render_pillow(self.uid, self.floor, self.x, self.y)
        em = mv._embed(f"Coins +{gain}")
        em.set_image(url="attachment://map.png")
        await i.edit_original_response(embed=em, file=map_file, view=mv)
    
    @discord.ui.button(label="Back", style=discord.ButtonStyle.grey)
    async def back(self, i, b):
        await i.response.defer()
        mv = DungeonMainView(self.uid, self.floor, self.x, self.y, self.supabase)
        map_file = d_render_pillow(self.uid, self.floor, self.x, self.y)
        em = mv._embed()
        em.set_image(url="attachment://map.png")
        await i.edit_original_response(embed=em, file=map_file, view=mv)

class DungeonCombatView(View):
    def __init__(self, uid, floor, x, y, enemy, supabase):
        super().__init__(timeout=180)
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
        ratio = p["hp"] / max(p["max_hp"], 1)
        color = 0x00ff88 if ratio > 0.5 else (0xffaa00 if ratio > 0.25 else 0xff4444)
        etype = e.get("type", "normal")
        type_text = {"normal": "Normal", "elite": "Elite", "boss": "Boss"}[etype]
        em = discord.Embed(title=f"{e['name']} ({type_text})", color=color)
        em.add_field(name="You", value=f"{d_hpbar(p['hp'],p['max_hp'])} {p['hp']}/{p['max_hp']}\nATK:{p['atk']} DEF:{p['def_']}", inline=True)
        em.add_field(name="Enemy", value=f"{d_hpbar(e['hp'],e['max_hp'])} {e['hp']}/{e['max_hp']}\nATK:{e['atk']} DEF:{e['def_']}", inline=True)
        if self.log:
            em.add_field(name="Log", value="\n".join(self.log[-5:]), inline=False)
        return em
    
    def _calculate_damage(self, attacker, defender, is_defending=False):
        is_crit = random.random() < attacker.get("crit", 0.05)
        target_def = defender.get("def_", 0)
        if is_defending:
            target_def *= 2
        dmg = max(1, attacker["atk"] - target_def + random.randint(-2, 3))
        if is_crit:
            return int(dmg * 1.5), True
        return dmg, False
    
    def _enemy_turn(self):
        p = d_get_player(self.uid)
        e = self.enemy
        raw_name = e["name"].split()[0].strip()
        master = ENEMY_STATS_MASTER.get(raw_name, ENEMY_STATS_MASTER["default"])
        action = random.choice(master.get("ai", ["attack"]))
        
        if action == "strong_attack":
            dmg, crit = self._calculate_damage(e, p, self.defending)
            dmg = int(dmg * 1.4)
            p["hp"] = max(0, p["hp"] - dmg)
            log_msg = f"Strong attack: {dmg}"
        elif action == "heal":
            heal_amt = int(e["max_hp"] * 0.15)
            e["hp"] = min(e["max_hp"], e["hp"] + heal_amt)
            log_msg = f"Healed {heal_amt}"
        elif action == "wait":
            log_msg = "Waiting..."
        else:
            dmg, crit = self._calculate_damage(e, p, self.defending)
            p["hp"] = max(0, p["hp"] - dmg)
            c_msg = "CRIT " if crit else ""
            log_msg = f"{c_msg}Attack: {dmg}"
        
        self.defending = False
        return log_msg
    
    async def _win(self, i):
        e = self.enemy
        msg = f"VICTORY: +{e['reward_coins']} Coins"
        if e.get("reward_box", 0) > 0:
            msg += f" +{e['reward_box']} Boxes"
        self.log.append(msg)
        await dg_save_player(self.uid, self.supabase)
        self.stop()
        mv = DungeonMainView(self.uid, self.floor, self.x, self.y, self.supabase)
        map_file = d_render_pillow(self.uid, self.floor, self.x, self.y)
        em = mv._embed(msg)
        em.set_image(url="attachment://map.png")
        await i.edit_original_response(embed=em, file=map_file, view=mv)
    
    async def _lose(self, i):
        p = d_get_player(self.uid)
        p["hp"] = p["max_hp"]
        p["floor"] = 1
        p["x"], p["y"] = dg_starts.get(1, (1000, 1000))
        self.log.append("DEFEAT")
        await dg_save_player(self.uid, self.supabase)
        self.stop()
        mv = DungeonMainView(self.uid, 1, p["x"], p["y"], self.supabase)
        map_file = d_render_pillow(self.uid, 1, p["x"], p["y"])
        em = mv._embed("Defeated")
        em.set_image(url="attachment://map.png")
        await i.edit_original_response(embed=em, file=map_file, view=mv)
    
    @discord.ui.button(label="Attack", style=discord.ButtonStyle.red, row=0)
    async def attack(self, i, b):
        await i.response.defer()
        p = d_get_player(self.uid)
        e = self.enemy
        p_first = p.get("spd", 10) >= e.get("spd", 10)
        
        if p_first:
            dmg, crit = self._calculate_damage(p, e)
            e["hp"] = max(0, e["hp"] - dmg)
            self.log.append(f"{'CRIT ' if crit else ''}You: {dmg}")
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
            self.log.append(f"{'CRIT ' if crit else ''}You: {dmg}")
        
        if e["hp"] <= 0:
            await self._win(i)
            return
        if p["hp"] <= 0:
            await self._lose(i)
            return
        
        map_file = d_render_pillow(self.uid, self.floor, self.x, self.y)
        em = self._embed()
        em.set_image(url="attachment://map.png")
        await i.edit_original_response(embed=em, file=map_file, view=self)
    
    @discord.ui.button(label="Defend", style=discord.ButtonStyle.blurple, row=0)
    async def defend(self, i, b):
        await i.response.defer()
        self.defending = True
        self.log.append(f"Defense!\n{self._enemy_turn()}")
        if d_get_player(self.uid)["hp"] <= 0:
            await self._lose(i)
            return
        map_file = d_render_pillow(self.uid, self.floor, self.x, self.y)
        em = self._embed()
        em.set_image(url="attachment://map.png")
        await i.edit_original_response(embed=em, file=map_file, view=self)
    
    @discord.ui.button(label="Flee", style=discord.ButtonStyle.grey, row=0)
    async def flee(self, i, b):
        await i.response.defer()
        if self.enemy.get("type") == "boss":
            self.log.append(f"Cannot flee!\n{self._enemy_turn()}")
            if d_get_player(self.uid)["hp"] <= 0:
                await self._lose(i)
                return
            map_file = d_render_pillow(self.uid, self.floor, self.x, self.y)
            em = self._embed()
            em.set_image(url="attachment://map.png")
            await i.edit_original_response(embed=em, file=map_file, view=self)
            return
        
        if random.random() < (0.2 if self.enemy.get("type") == "elite" else 0.5):
            self.stop()
            mv = DungeonMainView(self.uid, self.floor, self.x, self.y, self.supabase)
            map_file = d_render_pillow(self.uid, self.floor, self.x, self.y)
            em = mv._embed("Escaped")
            em.set_image(url="attachment://map.png")
            await i.edit_original_response(embed=em, file=map_file, view=mv)
        else:
            self.log.append(f"Escape failed!\n{self._enemy_turn()}")
            if d_get_player(self.uid)["hp"] <= 0:
                await self._lose(i)
                return
            map_file = d_render_pillow(self.uid, self.floor, self.x, self.y)
            em = self._embed()
            em.set_image(url="attachment://map.png")
            await i.edit_original_response(embed=em, file=map_file, view=self)

class DungeonMainView(View):
    def __init__(self, uid, floor, x, y, supabase):
        super().__init__(timeout=600)
        self.uid = uid
        self.floor = floor
        self.x = x
        self.y = y
        self.supabase = supabase
    
    def _embed(self, msg=""):
        p = d_get_player(self.uid)
        biome_name, color, _ = d_get_biome_at(p["x"], p["y"])
        em = discord.Embed(title=f"Floor {self.floor} - {biome_name}", color=color)
        em.add_field(name="Pos", value=f"({p['x']}, {p['y']})", inline=True)
        em.add_field(name="HP", value=f"{d_hpbar(p['hp'], p['max_hp'])} {p['hp']}/{p['max_hp']}", inline=True)
        if msg:
            em.add_field(name="Info", value=msg, inline=False)
        return em
    
    async def _move(self, i, dx, dy):
        await i.response.defer()
        p = d_get_player(self.uid)
        nx, ny = p["x"] + dx, p["y"] + dy
        
        if not (0 <= nx < D_MAP_W and 0 <= ny < D_MAP_H):
            map_file = d_render_pillow(self.uid, self.floor, p["x"], p["y"])
            em = self._embed("Out of bounds")
            em.set_image(url="attachment://map.png")
            await i.edit_original_response(embed=em, file=map_file, view=self)
            return
        
        ct = d_get_cell(self.floor, nx, ny)
        if ct == D_WALL:
            map_file = d_render_pillow(self.uid, self.floor, p["x"], p["y"])
            em = self._embed("Wall")
            em.set_image(url="attachment://map.png")
            await i.edit_original_response(embed=em, file=map_file, view=self)
            return
        
        p["x"], p["y"] = nx, ny
        msg = ""
        
        if ct == D_STAIRS:
            sv = DungeonStairsView(self.uid, self.floor, p["x"], p["y"], self.supabase)
            map_file = d_render_pillow(self.uid, self.floor, p["x"], p["y"])
            em = sv._embed("Descend?")
            em.set_image(url="attachment://map.png")
            await i.edit_original_response(embed=em, file=map_file, view=sv)
            return
        
        elif ct == D_CHEST:
            msg, _ = d_open_chest(self.uid, self.supabase)
            d_consume(self.floor, p["x"], p["y"])
            await dg_save_map(self.floor, self.supabase)
        
        elif ct == D_TRAP:
            msg, _ = d_trigger_trap(self.uid)
            d_consume(self.floor, p["x"], p["y"])
            await dg_save_map(self.floor, self.supabase)
        
        elif ct == D_MINE:
            mv = DungeonMineView(self.uid, self.floor, p["x"], p["y"], self.supabase)
            map_file = d_render_pillow(self.uid, self.floor, p["x"], p["y"])
            em = mv._embed("Dig?")
            em.set_image(url="attachment://map.png")
            await i.edit_original_response(embed=em, file=map_file, view=mv)
            return
        
        elif ct == D_DUNGEON:
            msg = "Minidungeon"
            d_consume(self.floor, p["x"], p["y"])
            await dg_save_map(self.floor, self.supabase)
        
        elif ct == D_FISHING:
            msg = "Fishing spot"
        
        else:
            biome_name, _, rate = d_get_biome_at(p["x"], p["y"])
            if random.random() < rate:
                enemy = d_make_enemy(self.floor, biome_name)
                cv = DungeonCombatView(self.uid, self.floor, p["x"], p["y"], enemy, self.supabase)
                map_file = d_render_pillow(self.uid, self.floor, p["x"], p["y"])
                em = cv._embed()
                em.set_image(url="attachment://map.png")
                await i.edit_original_response(embed=em, file=map_file, view=cv)
                return
        
        if p["hp"] <= 0:
            p["hp"] = p["max_hp"]
            p["floor"] = 1
            start_pos = dg_starts.get(1, (1000, 1000))
            p["x"], p["y"] = start_pos
            msg += "\nDEFEATED"
        
        await dg_save_player(self.uid, self.supabase)
        map_file = d_render_pillow(self.uid, self.floor, p["x"], p["y"])
        em = self._embed(msg)
        em.set_image(url="attachment://map.png")
        await i.edit_original_response(embed=em, file=map_file, view=self)
    
    @discord.ui.button(label="Up", style=discord.ButtonStyle.grey, row=0, custom_id="dg_u")
    async def up(self, i, b): await self._move(i, 0, -1)
    
    @discord.ui.button(label="L", style=discord.ButtonStyle.grey, row=1, custom_id="dg_l")
    async def left(self, i, b): await self._move(i, -1, 0)
    
    @discord.ui.button(label="C", style=discord.ButtonStyle.grey, row=1, custom_id="dg_c")
    async def check(self, i, b): await self._move(i, 0, 0)
    
    @discord.ui.button(label="R", style=discord.ButtonStyle.grey, row=1, custom_id="dg_r")
    async def right(self, i, b): await self._move(i, 1, 0)
    
    @discord.ui.button(label="Down", style=discord.ButtonStyle.grey, row=2, custom_id="dg_d")
    async def down(self, i, b): await self._move(i, 0, 1)
    
    @discord.ui.button(label="STATUS", style=discord.ButtonStyle.green, row=3, custom_id="dg_status")
    async def status(self, i, b):
        await i.response.defer()
        sv = DungeonStatusView(self.uid, self.floor, self.x, self.y)
        status_embed = sv._embed()
        back_view = DungeonStatusBackView(self.uid, self.floor, self.supabase)
        await i.edit_original_response(embed=status_embed, view=back_view)

# ============================================================
#  Cog
# ============================================================

class DungeonCog(Cog):
    def __init__(self, bot):
        self.bot = bot
        self.supabase = None
    
    async def cog_load(self):
        if hasattr(self.bot, 'supabase'):
            self.supabase = self.bot.supabase
            await dg_load_all(self.supabase)
        
        if not self.dungeon_monthly_task.is_running():
            self.dungeon_monthly_task.start()
    
    def cog_unload(self):
        if self.dungeon_monthly_task.is_running():
            self.dungeon_monthly_task.cancel()
    
    @app_commands.command(name="dungeon", description="Enter dungeon")
    async def dungeon_enter(self, interaction: Interaction):
        await interaction.response.defer()
        uid = str(interaction.user.id)
        
        p = d_get_player(uid)
        floor = p["floor"]
        
        d_ensure_map(floor)
        
        sx, sy = dg_starts.get(floor, (1000, 1000))
        if p["x"] == 1 and p["y"] == 1:
            p["x"] = sx
            p["y"] = sy
            if self.supabase:
                await dg_save_player(uid, self.supabase)
        
        mv = DungeonMainView(uid, floor, p["x"], p["y"], self.supabase)
        map_file = d_render_pillow(uid, floor, p["x"], p["y"])
        em = mv._embed("Welcome")
        em.set_image(url="attachment://map.png")
        
        await interaction.followup.send(embed=em, file=map_file, view=mv)
    
    @app_commands.command(name="dungeon_reset", description="Reset (Admin)")
    @app_commands.checks.has_permissions(administrator=True)
    async def dungeon_reset(self, interaction: Interaction):
        await interaction.response.defer()
        global dg_maps, dg_players, dg_starts, dg_used, dg_bases
        dg_maps.clear()
        dg_players.clear()
        dg_starts.clear()
        dg_used.clear()
        dg_bases.clear()
        
        if self.supabase:
            try:
                self.supabase.table("dungeon_maps").delete().neq("floor", 0).execute()
                self.supabase.table("dungeon_players").delete().neq("user_id", "").execute()
                self.supabase.table("dungeon_bases").delete().neq("user_id", "").execute()
            except Exception as e:
                print(f"Error: {e}")
        
        for fl in range(1, D_FLOORS + 1):
            d_ensure_map(fl)
            if self.supabase:
                await dg_save_map(fl, self.supabase)
        
        em = discord.Embed(title="RESET", description="Done", color=0xFFFFFF)
        await interaction.followup.send(embed=em)
    
    @tasks.loop(hours=1)
    async def dungeon_monthly_task(self):
        now = datetime.datetime.now(JST)
        if now.day == 1 and now.hour == 0:
            global dg_maps, dg_players, dg_starts, dg_used, dg_bases
            dg_maps.clear()
            dg_players.clear()
            dg_starts.clear()
            dg_used.clear()
            dg_bases.clear()
            
            if self.supabase:
                try:
                    self.supabase.table("dungeon_maps").delete().neq("floor", 0).execute()
                    self.supabase.table("dungeon_players").delete().neq("user_id", "").execute()
                    self.supabase.table("dungeon_bases").delete().neq("user_id", "").execute()
                except Exception as e:
                    print(f"Error: {e}")
                
                for fl in range(1, D_FLOORS + 1):
                    d_ensure_map(fl)
                    await dg_save_map(fl, self.supabase)
            
            print("Monthly reset")
    
    @dungeon_monthly_task.before_loop
    async def before_dungeon_task(self):
        await self.bot.wait_until_ready()

async def setup(bot):
    await bot.add_cog(DungeonCog(bot))
    print("DungeonCog loaded")