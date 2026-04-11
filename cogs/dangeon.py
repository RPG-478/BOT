# -*- coding: utf-8 -*-
"""
ダンジョンシステム Cog (V2.0 - 無限計算・低負荷・全機能統合版)
dungeon.py - Discord.py Cog形式
"""

import os
import discord
import json
import random
import asyncio
import io
import datetime
import hashlib
from discord.ui import View
from discord import app_commands, Interaction
from discord.ext import commands, tasks
from discord.ext.commands import Cog
from PIL import Image, ImageDraw
from zoneinfo import ZoneInfo
from discord import FFmpegPCMAudio

# ============================================================
#  タイムゾーンと環境設定
# ============================================================
JST = ZoneInfo("Asia/Tokyo")
MAP_SEED = os.environ.get("MAP_SEED", "DEFAULT_DUNGEON_SEED_2024")
DUNGEON_IMG_CHANNEL_ID = int(os.environ.get("DUNGEON_IMG_CHANNEL_ID", 0))

# ============================================================
#  定数定義 (旧コードより継承)
# ============================================================

# マップ設定
D_MAP_W = 2001
D_MAP_H = 2001
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

# ============================================================
#  グローバルメモリキャッシュ
# ============================================================
dg_chunks_cache = {}  # {(floor, x, y): tile_type}
dg_players_cache = {} # {uid: stats_dict}
dg_bases_cache = {}   # {uid: (floor, x, y)}
_ASSET_CACHE = {}

# ============================================================
#  コアロジック: マップ生成 & バイオーム (V2.0 決定論的)
# ============================================================

def d_get_biome(floor):
    """フロアからバイオーム情報を取得"""
    for r, name, wall_e, floor_e, fog_e, color in D_BIOMES:
        if floor in r:
            return name, wall_e, floor_e, fog_e, color
    return "洞窟", "⬜", "⬛", "🌫️", 0x5C4033

def get_deterministic_tile(floor, x, y):
    """座標とシード値に基づき、決定論的にタイルを決定する (Chunk Delta優先)"""
    if (floor, x, y) in dg_chunks_cache:
        return dg_chunks_cache[(floor, x, y)]

    seed_str = f"{MAP_SEED}_{floor}_{x}_{y}"
    seed_hash = int(hashlib.md5(seed_str.encode()).hexdigest(), 16)
    random.seed(seed_hash)
    
    roll = random.random()
    if roll < 0.001: return D_STAIRS
    if roll < 0.005: return D_CHEST
    if roll < 0.003: return D_TRAP
    if roll < 0.002: return D_MINE
    if roll < 0.30: return D_WALL
    return D_FLOOR

# ============================================================
#  ヘルパー関数 (旧コード移植)
# ============================================================

def d_hpbar(hp, max_hp, width=10):
    filled = int(width * hp / max(max_hp, 1))
    return "█" * filled + "░" * (width - filled)

def d_open_chest(uid):
    roll = random.random()
    if roll < 0.5:
        coins = random.randint(50, 300)
        return f"宝箱！ コイン **+{coins}** 枚", coins
    elif roll < 0.8:
        bread = random.randint(3, 15)
        return f"宝箱！ レアパン **+{bread}** 個", 0
    elif roll < 0.95:
        boxes = random.randint(1, 3)
        return f"宝箱！ 宝箱 **+{boxes}** 個", 0
    else:
        chips = random.randint(100, 500)
        return f"宝箱！ チップ **+{chips}** 枚", 0

def d_trigger_trap(uid):
    p = dg_players_cache[uid]
    roll = random.random()
    if roll < 0.4:
        loss = random.randint(30, 150)
        return f"罠！ コイン **-{loss}** 枚", -loss
    elif roll < 0.7:
        dmg = random.randint(10, 30)
        p["hp"] = max(0, p["hp"] - dmg)
        return f"罠！ HP **-{dmg}**", 0
    elif roll < 0.85:
        loss = random.randint(1, 5)
        return f"罠！ レアパン **-{loss}** 個", 0
    else:
        loss = random.randint(50, 200)
        return f"罠！ チップ **-{loss}** 枚", 0

def d_make_enemy(floor):
    base_hp, base_atk, base_def = 15 + floor * 8, 4 + floor * 2, 1 + floor
    bname, *_ = d_get_biome(floor)
    r = random.random()
    if r < 0.01: etype, names = "boss", D_BOSS_NAMES
    elif r < 0.11: etype, names = "elite", D_SUPERENEMY_NAMES
    else: etype, names = "normal", D_ENEMY_NAMES
    
    name = random.choice(names.get(bname, ["謎の敵"]))
    clean_key = name.split()[0].replace("👾", "").strip()
    m = ENEMY_STATS_MASTER.get(clean_key, ENEMY_STATS_MASTER["default"])
    
    rank_hp_mul = 15.0 if etype == "boss" else (4.0 if etype == "elite" else 1.0)
    rank_atk_mul = 4.0 if etype == "boss" else (2.5 if etype == "elite" else 1.0)
    rank_def_mul = 2.0 if etype == "boss" else (1.5 if etype == "elite" else 1.0)

    hp = int((base_hp + random.randint(-3, 3)) * m.get("hp_m") * rank_hp_mul)
    atk = int((base_atk + random.randint(-1, 1)) * m.get("atk_m", 1.0) * rank_atk_mul)
    defe = int(base_def * m.get("def_m", 1.0) * rank_def_mul)
    
    m_coin_m, m_xp_m, m_boxes = m.get("coin_m", 1.0), m.get("xp_m", 1.0), m.get("boxes", 0)
    if etype == "elite":
        reward_coins, reward_xp, reward_box = int(random.randint(80, 150) * floor * m_coin_m), int(random.randint(100, 800) * floor * m_xp_m), max(1, m_boxes)
    elif etype == "boss":
        reward_coins, reward_xp, reward_box = int(random.randint(2000, 4000) * floor * m_coin_m), int(random.randint(1000, 2000) * floor * m_xp_m), max(5, m_boxes)
    else:
        reward_coins, reward_xp, reward_box = int(random.randint(20, 80) * floor * m_coin_m), int(random.randint(10, 30) * floor * m_xp_m), (1 if random.random() < 0.05 else 0)

    return {"name": name, "type": etype, "hp": hp, "max_hp": hp, "atk": atk, "def_": defe, "spd": m.get("spd", 10), "crit": m.get("crit", 0.05), "reward_coins": reward_coins, "reward_xp": reward_xp, "reward_box": reward_box}

# ============================================================
#  レンダリングエンジン (Pillow)
# ============================================================

def load_all_assets():
    global _ASSET_CACHE
    assets_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "Assets")
    for (biome, tid), fname in ASSET_CONFIG.items():
        path = os.path.join(assets_dir, fname)
        if os.path.isfile(path):
            try:
                img = Image.open(path).convert("RGBA").resize((TILE, TILE), Image.Resampling.NEAREST)
                _ASSET_CACHE[(biome, tid)] = img
            except: pass

def _draw_tile(draw, img, x, y, cell, biome, is_player=False, is_fog=False):
    px, py = x * TILE, y * TILE
    if is_fog:
        draw.rectangle([px, py, px+TILE-1, py+TILE-1], fill=(0, 0, 0))
        return
    if is_player:
        floor_col = TILE_COLORS[D_FLOOR].get(biome, (40, 30, 25))
        draw.rectangle([px, py, px+TILE-1, py+TILE-1], fill=floor_col)
        draw.ellipse([px+6, py+6, px+TILE-7, py+TILE-7], fill=TILE_COLORS["player"])
        return
    tile_img = _ASSET_CACHE.get((biome, cell))
    if tile_img:
        img.paste(tile_img, (px, py), tile_img)
        return
    if cell == D_TRAP:
        draw.rectangle([px, py, px+TILE-1, py+TILE-1], fill=TILE_COLORS[D_FLOOR].get(biome, (40, 30, 25)))
        return
    col = TILE_COLORS.get(cell, (80, 80, 80))
    if isinstance(col, dict): col = col.get(biome, (80, 80, 80))
    draw.rectangle([px, py, px+TILE-1, py+TILE-1], fill=col)
    if cell == D_CHEST:
        draw.rectangle([px+8, py+8, px+TILE-9, py+TILE-9], fill=(255, 255, 100), outline=(180, 140, 0), width=2)
    elif cell == D_STAIRS:
        for s in range(3): draw.rectangle([px+6+s*6, py+TILE-8-s*6, px+TILE-8, py+TILE-4-s*6], fill=(255, 255, 255))
    elif cell == D_MINE:
        draw.text((px+TILE//2-4, py+TILE//2-6), "⛏", fill=(200, 200, 200))

def d_render_pillow(uid, floor, px, py, radius=D_VIEW_R):
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
            cell = get_deterministic_tile(floor, vx, vy)
            _draw_tile(draw, img, vx_i, vy_i, cell, bname, is_player=is_player)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return discord.File(fp=buf, filename="map.png")

# ============================================================
#  データベース連携
# ============================================================

async def dg_load_all(supabase):
    global dg_players_cache, dg_chunks_cache, dg_bases_cache
    try:
        res = supabase.table("dungeon_chunks").select("*").execute()
        for r in res.data: dg_chunks_cache[(r["floor"], r["x"], r["y"])] = r["tile_type"]
        res = supabase.table("dungeon_players").select("*").execute()
        for r in res.data: dg_players_cache[r["user_id"]] = r
        res = supabase.table("dungeon_bases").select("*").execute()
        for r in res.data: dg_bases_cache[r["user_id"]] = (r["floor"], r["x"], r["y"])
    except Exception as e: print(f"DB Load Error: {e}")

async def dg_save_player(uid, supabase):
    if uid not in dg_players_cache: return
    try: supabase.table("dungeon_players").upsert(dg_players_cache[uid]).execute()
    except Exception as e: print(f"Save Player Error: {e}")

async def dg_save_chunk(floor, x, y, tile_type, supabase):
    dg_chunks_cache[(floor, x, y)] = tile_type
    try: supabase.table("dungeon_chunks").upsert({"floor": floor, "x": x, "y": y, "tile_type": tile_type}).execute()
    except Exception as e: print(f"Save Chunk Error: {e}")

# ============================================================
#  Views (旧コード完全移植)
# ============================================================

class DungeonStatusView(View):
    def __init__(self, uid, floor, x, y):
        super().__init__(timeout=60)
        self.uid, self.floor, self.x, self.y = uid, floor, x, y
    def _embed(self):
        p = dg_players_cache[self.uid]
        em = discord.Embed(title="ダンジョン ステータス", color=0xFFFFFF)
        em.add_field(name="現在位置", value=f"フロア **{self.floor}** ({self.x}, {self.y})", inline=False)
        em.add_field(name="HP", value=f"{d_hpbar(p['hp'], p['max_hp'])} {p['hp']}/{p['max_hp']}", inline=False)
        em.add_field(name="ステータス", value=f"ATK:{p['atk']} DEF:{p['def_']} SPD:{p['spd']} CRIT:{int(p['crit']*100)}%", inline=False)
        return em

class DungeonStairsView(View):
    def __init__(self, uid, floor, x, y, supabase):
        super().__init__(timeout=180)
        self.uid, self.floor, self.x, self.y, self.supabase = uid, floor, x, y, supabase
    def _embed(self, msg=""):
        em = discord.Embed(title="階段がある", color=0xFFFFFF, description=msg)
        em.set_image(url="attachment://map.png")
        return em
    @discord.ui.button(label="⬆️ 上へ進む", style=discord.ButtonStyle.green)
    async def up(self, i, b):
        await i.response.defer()
        if self.floor < D_FLOORS:
            p = dg_players_cache[self.uid]
            p["floor"] += 1
            p["hp"] = p["max_hp"]
            p["x"], p["y"] = 0, 0
            await dg_save_player(self.uid, self.supabase)
            mv = DungeonMainView(self.uid, p["floor"], p["x"], p["y"], self.supabase)
            await i.edit_original_response(embed=mv._embed(f"フロア {p['floor']}へ到達！"), view=mv, attachments=[d_render_pillow(self.uid, p["floor"], p["x"], p["y"])])
        else:
            await i.edit_original_response(embed=discord.Embed(title="ゴール！", description="ダンジョンをクリアしました！", color=0xFFFFFF))
    @discord.ui.button(label="⬅️ 戻る", style=discord.ButtonStyle.grey)
    async def back(self, i, b):
        await i.response.defer()
        mv = DungeonMainView(self.uid, self.floor, self.x, self.y, self.supabase)
        await i.edit_original_response(embed=mv._embed(""), view=mv, attachments=[d_render_pillow(self.uid, self.floor, self.x, self.y)])

class DungeonMineView(View):
    def __init__(self, uid, floor, x, y, supabase):
        super().__init__(timeout=60)
        self.uid, self.floor, self.x, self.y, self.supabase = uid, floor, x, y, supabase
    def _embed(self, msg=""):
        em = discord.Embed(title="鉱山", color=0xFFFFFF, description=msg)
        em.set_image(url="attachment://map.png")
        return em
    @discord.ui.button(label="⛏ 採掘する", style=discord.ButtonStyle.green)
    async def mine(self, i, b):
        await i.response.defer()
        gain = random.randint(30, 200)
        await dg_save_chunk(self.floor, self.x, self.y, D_FLOOR, self.supabase)
        mv = DungeonMainView(self.uid, self.floor, self.x, self.y, self.supabase)
        await i.edit_original_response(embed=mv._embed(f"採掘！ **+{gain}** コイン"), view=mv, attachments=[d_render_pillow(self.uid, self.floor, self.x, self.y)])
    @discord.ui.button(label="⬅️ 戻る", style=discord.ButtonStyle.grey)
    async def back(self, i, b):
        await i.response.defer()
        mv = DungeonMainView(self.uid, self.floor, self.x, self.y, self.supabase)
        await i.edit_original_response(embed=mv._embed(""), view=mv, attachments=[d_render_pillow(self.uid, self.floor, self.x, self.y)])

class DungeonCombatView(View):
    def __init__(self, uid, floor, x, y, enemy, supabase):
        super().__init__(timeout=180)
        self.uid, self.floor, self.x, self.y, self.enemy, self.supabase = uid, floor, x, y, enemy, supabase
        self.log, self.defending = [], False
    def _embed(self):
        p, e = dg_players_cache[self.uid], self.enemy
        etype = e.get("type", "normal")
        type_text = {"normal": "通常", "elite": "精鋭", "boss": "ボス"}[etype]
        em = discord.Embed(title=f"{e['name']}（{type_text}）が現れた！", color=0xFFFFFF)
        em.set_image(url="attachment://map.png")
        em.add_field(name="あなた", value=f"`{d_hpbar(p['hp'],p['max_hp'])}`{p['hp']}/{p['max_hp']}\nATK:{p['atk']} DEF:{p['def_']}", inline=True)
        em.add_field(name=e["name"], value=f"`{d_hpbar(e['hp'],e['max_hp'])}`{e['hp']}/{e['max_hp']}\nATK:{e['atk']} DEF:{e['def_']}", inline=True)
        if self.log: em.add_field(name="ログ", value="\n".join(self.log[-5:]), inline=False)
        return em
    def _calculate_damage(self, attacker, defender, is_defending=False):
        is_crit = random.random() < attacker.get("crit", 0.05)
        target_def = defender.get("def_", 0) * (2 if is_defending else 1)
        dmg = max(1, attacker["atk"] - target_def + random.randint(-2, 3))
        return (int(dmg * 1.5), True) if is_crit else (dmg, False)
    def _enemy_turn(self):
        p, e = dg_players_cache[self.uid], self.enemy
        master = ENEMY_STATS_MASTER.get(e["name"].split()[0].replace("👾", "").strip(), ENEMY_STATS_MASTER["default"])
        action = random.choice(master.get("ai", ["attack"]))
        if action == "strong_attack":
            dmg, _ = self._calculate_damage(e, p, self.defending)
            dmg = int(dmg * 1.4)
            p["hp"] = max(0, p["hp"] - dmg)
            log_msg = f"**{e['name']}の強攻撃！！** {dmg} ダメージ"
        elif action == "heal":
            heal_amt = int(e["max_hp"] * 0.15)
            e["hp"] = min(e["max_hp"], e["hp"] + heal_amt)
            log_msg = f"{e['name']}は傷口を舐めて {heal_amt} 回復した"
        elif action == "wait": log_msg = f"{e['name']}は様子を伺っている..."
        else:
            dmg, crit = self._calculate_damage(e, p, self.defending)
            p["hp"] = max(0, p["hp"] - dmg)
            log_msg = f"{'**CRITICAL!!** ' if crit else ''}{e['name']}の攻撃：{dmg} ダメージ"
        self.defending = False
        return log_msg
    async def _win(self, i):
        e = self.enemy
        msg = f"勝利！ +{e['reward_coins']}コイン +{e['reward_xp']}XP"
        if e["reward_box"] > 0: msg += f" +宝箱{e['reward_box']}個"
        self.log.append(msg)
        await dg_save_player(self.uid, self.supabase)
        self.stop()
        mv = DungeonMainView(self.uid, self.floor, self.x, self.y, self.supabase)
        await i.edit_original_response(embed=mv._embed(msg), view=mv, attachments=[d_render_pillow(self.uid, self.floor, self.x, self.y)])
    async def _lose(self, i):
        p = dg_players_cache[self.uid]
        p["hp"], p["floor"], p["x"], p["y"] = p["max_hp"], 1, 0, 0
        self.log.append("敗北… スタート地点へ送還された")
        await dg_save_player(self.uid, self.supabase)
        self.stop()
        mv = DungeonMainView(self.uid, 1, 0, 0, self.supabase)
        await i.edit_original_response(embed=mv._embed("敗北して戻された…"), view=mv, attachments=[d_render_pillow(self.uid, 1, 0, 0)])
    @discord.ui.button(label="⚔ 攻撃", style=discord.ButtonStyle.red)
    async def attack(self, i, b):
        await i.response.defer()
        p, e = dg_players_cache[self.uid], self.enemy
        if p.get("spd", 10) >= e.get("spd", 10):
            dmg, crit = self._calculate_damage(p, e)
            e["hp"] = max(0, e["hp"] - dmg)
            self.log.append(f"{'**CRIT!!** ' if crit else ''}{dmg} ダメージ！")
            if e["hp"] <= 0: return await self._win(i)
            self.log.append(self._enemy_turn())
        else:
            self.log.append(self._enemy_turn())
            if p["hp"] <= 0: return await self._lose(i)
            dmg, crit = self._calculate_damage(p, e)
            e["hp"] = max(0, e["hp"] - dmg)
            self.log.append(f"{'**CRIT!!** ' if crit else ''}{dmg} ダメージ！")
        if e["hp"] <= 0: await self._win(i)
        elif p["hp"] <= 0: await self._lose(i)
        else: await i.edit_original_response(embed=self._embed(), attachments=[d_render_pillow(self.uid, self.floor, self.x, self.y)])
    @discord.ui.button(label="🛡 防御", style=discord.ButtonStyle.blurple)
    async def defend(self, i, b):
        await i.response.defer()
        self.defending = True
        self.log.append(f"防御体制！\n{self._enemy_turn()}")
        if dg_players_cache[self.uid]["hp"] <= 0: await self._lose(i)
        else: await i.edit_original_response(embed=self._embed(), attachments=[d_render_pillow(self.uid, self.floor, self.x, self.y)])
    @discord.ui.button(label="逃げる", style=discord.ButtonStyle.grey)
    async def run_away(self, i, b):
        await i.response.defer()
        if self.enemy.get("type") == "boss":
            self.log.append("ボスからは逃げられない！\n" + self._enemy_turn())
            if dg_players_cache[self.uid]["hp"] <= 0: await self._lose(i)
            else: await i.edit_original_response(embed=self._embed(), attachments=[d_render_pillow(self.uid, self.floor, self.x, self.y)])
            return
        if random.random() < (0.2 if self.enemy.get("type") == "elite" else 0.5):
            self.stop()
            mv = DungeonMainView(self.uid, self.floor, self.x, self.y, self.supabase)
            await i.edit_original_response(embed=mv._embed("逃走成功"), view=mv, attachments=[d_render_pillow(self.uid, self.floor, self.x, self.y)])
        else:
            self.log.append("逃げ失敗！\n" + self._enemy_turn())
            if dg_players_cache[self.uid]["hp"] <= 0: await self._lose(i)
            else: await i.edit_original_response(embed=self._embed(), attachments=[d_render_pillow(self.uid, self.floor, self.x, self.y)])

class DungeonMainView(View):
    def __init__(self, uid, floor, x, y, supabase):
        super().__init__(timeout=600)
        self.uid, self.floor, self.x, self.y, self.supabase = uid, floor, x, y, supabase
    def _embed(self, msg=""):
        p = dg_players_cache[self.uid]
        bname, *_ = d_get_biome(self.floor)
        em = discord.Embed(title=f"フロア {self.floor} ({bname})", color=0xFFFFFF)
        em.set_image(url="attachment://map.png")
        em.add_field(name="位置", value=f"({p['x']}, {p['y']})", inline=True)
        em.add_field(name="HP", value=f"{d_hpbar(p['hp'], p['max_hp'])} {p['hp']}/{p['max_hp']}", inline=True)
        if msg: em.add_field(name="ログ", value=msg, inline=False)
        return em
    async def _move(self, i, dx, dy):
        await i.response.defer()
        p = dg_players_cache[self.uid]
        nx, ny = p["x"] + dx, p["y"] + dy
        if not (0 <= nx < D_MAP_W and 0 <= ny < D_MAP_H):
            return await i.edit_original_response(embed=self._embed("境界！進めない"), attachments=[d_render_pillow(self.uid, self.floor, p["x"], p["y"])])
        ct = get_deterministic_tile(self.floor, nx, ny)
        if ct == D_WALL:
            return await i.edit_original_response(embed=self._embed("壁！進めない"), attachments=[d_render_pillow(self.uid, self.floor, p["x"], p["y"])])
        p["x"], p["y"], msg = nx, ny, ""
        if ct == D_STAIRS:
            sv = DungeonStairsView(self.uid, self.floor, p["x"], p["y"], self.supabase)
            return await i.edit_original_response(embed=sv._embed("階段がある。どうする？"), attachments=[d_render_pillow(self.uid, self.floor, p["x"], p["y"])], view=sv)
        elif ct == D_CHEST:
            msg, _ = d_open_chest(self.uid)
            await dg_save_chunk(self.floor, nx, ny, D_FLOOR, self.supabase)
        elif ct == D_TRAP:
            msg, _ = d_trigger_trap(self.uid)
            await dg_save_chunk(self.floor, nx, ny, D_FLOOR, self.supabase)
        elif ct == D_MINE:
            v = DungeonMineView(self.uid, self.floor, p["x"], p["y"], self.supabase)
            return await i.edit_original_response(embed=v._embed("鉱山を発見！"), attachments=[d_render_pillow(self.uid, self.floor, p["x"], p["y"])], view=v)
        else:
            bname, *_ = d_get_biome(self.floor)
            if random.random() < D_ENCOUNTER_RATES.get(bname, 0.10):
                enemy = d_make_enemy(self.floor)
                cv = DungeonCombatView(self.uid, self.floor, p["x"], p["y"], enemy, self.supabase)
                return await i.edit_original_response(embed=cv._embed(), attachments=[d_render_pillow(self.uid, self.floor, p["x"], p["y"])], view=cv)
        if p["hp"] <= 0:
            p["hp"], p["floor"], p["x"], p["y"] = p["max_hp"], 1, 0, 0
            msg += "\n力尽きた… スタート地点へ戻された"
        await dg_save_player(self.uid, self.supabase)
        await i.edit_original_response(embed=self._embed(msg), attachments=[d_render_pillow(self.uid, p["floor"], p["x"], p["y"])], view=self)

    @discord.ui.button(label="↖️", row=0)
    async def lu(self, i, b): await self._move(i, -1, -1)
    @discord.ui.button(label="⬆️", row=0)
    async def u(self, i, b): await self._move(i, 0, -1)
    @discord.ui.button(label="↗️", row=0)
    async def ru(self, i, b): await self._move(i, 1, -1)
    @discord.ui.button(label="⬅️", row=1)
    async def l(self, i, b): await self._move(i, -1, 0)
    @discord.ui.button(label="☑️", row=1)
    async def c(self, i, b): await self._move(i, 0, 0)
    @discord.ui.button(label="➡️", row=1)
    async def r(self, i, b): await self._move(i, 1, 0)
    @discord.ui.button(label="↙️", row=2)
    async def ld(self, i, b): await self._move(i, -1, 1)
    @discord.ui.button(label="⬇️", row=2)
    async def d(self, i, b): await self._move(i, 0, 1)
    @discord.ui.button(label="↘️", row=2)
    async def rd(self, i, b): await self._move(i, 1, 1)
    @discord.ui.button(label="STATUS", style=discord.ButtonStyle.green, row=3)
    async def status(self, i, b):
        await i.response.defer()
        sv = DungeonStatusView(self.uid, self.floor, self.x, self.y)
        await i.edit_original_response(embed=sv._embed(), attachments=[], view=sv)

# ============================================================
#  Cog クラス
# ============================================================

class DungeonCog(Cog):
    def __init__(self, bot):
        self.bot = bot
        self.supabase = getattr(bot, 'supabase', None)
    async def cog_load(self):
        if self.supabase: await dg_load_all(self.supabase)
        load_all_assets()
        if not self.dungeon_monthly_task.is_running(): self.dungeon_monthly_task.start()
    @app_commands.command(name="dungeon", description="ダンジョン探索 V2.0")
    async def dungeon(self, interaction: Interaction):
        await interaction.response.defer()
        uid = str(interaction.user.id)
        p = dg_players_cache.get(uid)
        if not p:
            p = {"user_id": uid, "floor": 1, "x": 0, "y": 0, "hp": 100, "max_hp": 100, "atk": 10, "def_": 3, "spd": 10, "crit": 0.05, "exp": 0}
            dg_players_cache[uid] = p
            if self.supabase: await dg_save_player(uid, self.supabase)
        if interaction.user.voice:
            try:
                vc = await interaction.user.voice.channel.connect()
                vc.play(FFmpegPCMAudio("Assets/BGM.m4a"))
            except: pass
        mv = DungeonMainView(uid, p["floor"], p["x"], p["y"], self.supabase)
        await interaction.followup.send(embed=mv._embed("ダンジョンへようこそ！"), view=mv, file=d_render_pillow(uid, p["floor"], p["x"], p["y"]))

    @tasks.loop(hours=1)
    async def dungeon_monthly_task(self):
        now = datetime.datetime.now(JST)
        if now.day == 1 and now.hour == 0:
            dg_chunks_cache.clear()
            if self.supabase:
                try:
                    self.supabase.table("dungeon_chunks").delete().neq("floor", 0).execute()
                    self.supabase.table("dungeon_players").update({"x": 0, "y": 0}).neq("floor", -1).execute()
                except: pass

async def setup(bot):
    await bot.add_cog(DungeonCog(bot))
