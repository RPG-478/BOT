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
from discord.ui import View
from discord import app_commands, Interaction
from discord.ext import commands, tasks
from discord.ext.commands import Cog
from PIL import Image, ImageDraw
from zoneinfo import ZoneInfo
from discord import FFmpegPCMAudio # 追加

# ============================================================
#  タイムゾーン
# ============================================================
JST = ZoneInfo("Asia/Tokyo")

# ============================================================
#  定数（ダンジョンシステム用）
# ============================================================

# マップ定義
D_MAP_W = 2001
D_MAP_H = 2001
D_FLOORS = 1
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
# (フロア範囲, 名前, 色) に簡略化
D_BIOMES = [
    (range(1,  10),  "洞窟",     0x5C4033),
    (range(10,  20),  "森",       0x2D5A1B),
    (range(20,  30),  "氷雪地帯", 0x5B9BD5),
    (range(30, 40),  "砂漠地帯", 0xC8600A),
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

dg_players = {}  # {uid: {floor, x, y, hp, max_hp, atk, def_, spd, crit}}
dg_bases   = {}  # {uid: (floor, x, y)}
_ASSET_CACHE = {}
dg_chunks = {}

# 環境変数
DUNGEON_IMG_CHANNEL_ID = int(os.environ.get("DUNGEON_IMG_CHANNEL_ID", 0))

# ============================================================
#  ヘルパー関数
# ============================================================

def d_get_biome(x, y):
    """
    30〜150マスの範囲でランダムに変化するバイオームを座標から特定する
    """
    # 簡易的なグリッド分割によるバイオーム決定
    # 本格的にはノイズ関数(Perlin等)が望ましいですが、hashでも代用可能
    grid_x = x // 100 
    grid_y = y // 100
    
    random.seed(hash(f"biome_{grid_x}_{grid_y}_{MAP_SEED}"))
    biome_id = random.randint(0, len(D_BIOMES) - 1)
    
    return D_BIOMES[biome_id] # (名前, 色) を返す

def d_get_cell(floor, x, y):
    """
    シード値と座標からその場所のタイルを計算で導き出す。
    """
    # 1. 差分（破壊された壁など）をチェック
    # (DBやdg_chunksキャッシュを確認するロジックをここに挿入)
    
    # 2. 計算による生成
    random.seed(hash(f"{MAP_SEED}_{floor}_{x}_{y}"))
    
    # 30%の確率で壁、それ以外は床
    if random.random() < 0.3:
        return D_WALL
    return D_FLOOR

def d_consume(floor, x, y):
    """座標を消費（床に変更）"""
    dg_used[floor].add((x, y))
    dg_maps[floor][y][x] = D_FLOOR

def d_get_player(uid):
    """プレイヤーのダンジョンデータを取得"""
    if uid not in dg_players:
        dg_players[uid] = {
            "floor": 1,
            "x": 1,
            "y": 1,
            "hp": 100,
            "max_hp": 100,
            "atk": 10,
            "def_": 3,
            "spd": 10,
            "crit": 0.05,
        }
    return dg_players[uid]

def d_hpbar(hp, max_hp, width=10):
    """HP バーを生成"""
    filled = int(width * hp / max(max_hp, 1))
    return "█" * filled + "░" * (width - filled)

def d_open_chest(uid, supabase):
    """宝箱を開く"""
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
    """罠を発動"""
    p = d_get_player(uid)
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
    max_chest = max(3, len(floor_cells)//80)
    max_trap  = max(2, len(floor_cells)//120)
    max_shop  = max(1, len(floor_cells)//300)
    max_mine  = max(2, len(floor_cells)//150)
    
    for fx, fy in floor_cells:
        if all([placed_chest >= max_chest, placed_trap >= max_trap,
                placed_shop >= max_shop,   placed_mine >= max_mine]):
            break
        r = random.random()
        if placed_shop < max_shop and r < 0.03:
            grid[fy][fx] = D_SHOP
            placed_shop += 1
        elif placed_mine < max_mine and r < 0.10:
            grid[fy][fx] = D_MINE
            placed_mine += 1
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

class DungeonStatusView(View):
    """ステータス表示"""
    def __init__(self, uid, floor, x, y):
        super().__init__(timeout=60)
        self.uid = uid
        self.floor = floor
        self.x = x
        self.y = y
    
    def _embed(self):
        p = d_get_player(self.uid)
        em = discord.Embed(title="ダンジョン ステータス", color=0xFFFFFF)
        em.add_field(name="現在位置", value=f"フロア **{self.floor}** ({self.x}, {self.y})", inline=False)
        em.add_field(name="HP", value=f"{d_hpbar(p['hp'], p['max_hp'])} {p['hp']}/{p['max_hp']}", inline=False)
        em.add_field(name="ステータス", value=f"ATK:{p['atk']} DEF:{p['def_']} SPD:{p['spd']} CRIT:{int(p['crit']*100)}%", inline=False)
        return em

class DungeonStairsView(View):
    """階段View"""
    def __init__(self, uid, floor, x, y, supabase):
        super().__init__(timeout=180)
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
    async def up(self, i, b):
        await i.response.defer()
        if self.floor < D_FLOORS:
            p = d_get_player(self.uid)
            p["floor"] = self.floor + 1
            p["hp"] = p["max_hp"]
            start_pos = dg_starts.get(self.floor + 1, (1, 1))
            p["x"], p["y"] = start_pos
            await dg_save_player(self.uid, self.supabase)
            mv = DungeonMainView(self.uid, p["floor"], p["x"], p["y"], self.supabase)
            map_file = d_render_pillow(self.uid, p["floor"], p["x"], p["y"])
            await i.edit_original_response(embed=mv._embed(f"フロア {self.floor + 1}へ到達！"), view=mv, attachments=[map_file])
        else:
            await i.edit_original_response(embed=discord.Embed(title="ゴール！", description="ダンジョンをクリアしました！", color=0xFFFFFF))
    
    @discord.ui.button(label="⬅️ 戻る", style=discord.ButtonStyle.grey)
    async def back(self, i, b):
        await i.response.defer()
        mv = DungeonMainView(self.uid, self.floor, self.x, self.y, self.supabase)
        map_file = d_render_pillow(self.uid, self.floor, self.x, self.y)
        await i.edit_original_response(embed=mv._embed(""), view=mv, attachments=[map_file])

class DungeonMineView(View):
    """採掘View"""
    def __init__(self, uid, floor, x, y, supabase):
        super().__init__(timeout=60)
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
    async def mine(self, i, b):
        await i.response.defer()
        gain = d_do_mine(self.uid)
        d_consume(self.floor, self.x, self.y)
        await dg_save_map(self.floor, self.supabase)
        mv = DungeonMainView(self.uid, self.floor, self.x, self.y, self.supabase)
        map_file = d_render_pillow(self.uid, self.floor, self.x, self.y)
        await i.edit_original_response(embed=mv._embed(f"採掘！ **+{gain}** コイン"), view=mv, attachments=[map_file])
    
    @discord.ui.button(label="⬅️ 戻る", style=discord.ButtonStyle.grey)
    async def back(self, i, b):
        await i.response.defer()
        mv = DungeonMainView(self.uid, self.floor, self.x, self.y, self.supabase)
        map_file = d_render_pillow(self.uid, self.floor, self.x, self.y)
        await i.edit_original_response(embed=mv._embed(""), view=mv, attachments=[map_file])

class DungeonCombatView(View):
    """戦闘View"""
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
        type_text = {"normal": "通常", "elite": "精鋭", "boss": "ボス"}[etype]

        em = discord.Embed(title=f"{e['name']}（{type_text}）が現れた！", color=0xFFFFFF)
        em.set_image(url="attachment://map.png")

        em.add_field(name="あなた",
            value=f"`{d_hpbar(p['hp'],p['max_hp'])}`{p['hp']}/{p['max_hp']}\nATK:{p['atk']} DEF:{p['def_']}",
            inline=True)

        em.add_field(name=e["name"],
            value=f"`{d_hpbar(e['hp'],e['max_hp'])}`{e['hp']}/{e['max_hp']}\nATK:{e['atk']} DEF:{e['def_']}",
            inline=True)

        if self.log:
            em.add_field(name="ログ", value="\n".join(self.log[-5:]), inline=False)
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

        self.defending = False
        return log_msg
    async def on_timeout(self):
        if self.supabase:
            await dg_save_player(self.uid, self.supabase)
    async def _win(self, i):
        e = self.enemy
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
    async def attack(self, i, b):
        await i.response.defer()
        p = d_get_player(self.uid)
        e = self.enemy
        p_first = p.get("spd", 10) >= e.get("spd", 10)
        
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
    async def run_away(self, i, b):
        await i.response.defer()
        if self.enemy.get("type") == "boss":
            self.log.append("ボスからは逃げられない！\n" + self._enemy_turn())
            if d_get_player(self.uid)["hp"] <= 0:
                await self._lose(i)
                return
            await i.edit_original_response(embed=self._embed(), view=self, attachments=[d_render_pillow(self.uid, self.floor, self.x, self.y)])
            return
        
        escape_rate = 0.2 if self.enemy.get("type") == "elite" else 0.5
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

class DungeonMainView(View):
    """ダンジョンメインView"""
    def __init__(self, uid, floor, x, y, supabase):
        super().__init__(timeout=600)
        self.uid = uid
        self.floor = floor
        self.x = x
        self.y = y
        self.supabase = supabase
    
    def _embed(self, msg="", has_image=True, image_url=None):
        p = d_get_player(self.uid)
        bname, _, _, _, _ = d_get_biome(self.floor)
        em = discord.Embed(title=f"フロア {self.floor} ({bname})", color=0xFFFFFF)
        if has_image and image_url:
            em.set_image(url=image_url)
        em.add_field(name="位置", value=f"({p['x']}, {p['y']})", inline=True)
        em.add_field(name="HP", value=f"{d_hpbar(p['hp'], p['max_hp'])} {p['hp']}/{p['max_hp']}", inline=True)
        if msg:
            em.add_field(name="ログ", value=msg, inline=False)
        return em
    async def on_timeout(self):
        if self.supabase:
            await dg_save_player(self.uid, self.supabase)

    async def _move(self, i, dx, dy):
        await i.response.defer()
        
        p = d_get_player(self.uid)
        nx, ny = p["x"] + dx, p["y"] + dy
        
        # 境界チェック
        if not (0 <= nx < D_MAP_W and 0 <= ny < D_MAP_H):
            map_file = d_render_pillow(self.uid, self.floor, p["x"], p["y"])
            await i.edit_original_response(embed=self._embed("壁！進めない"), attachments=[map_file], view=self)
            return
        
        ct = d_get_cell(self.floor, nx, ny)
        if ct == D_WALL:
            map_file = d_render_pillow(self.uid, self.floor, p["x"], p["y"])
            await i.edit_original_response(embed=self._embed("壁！進めない"), attachments=[map_file], view=self)
            return
        
        # 座標更新
        p["x"], p["y"] = nx, ny
        
        msg = ""

        # 特殊タイル判定
        if ct == D_STAIRS:
            sv = DungeonStairsView(self.uid, self.floor, p["x"], p["y"], self.supabase)
            map_file = d_render_pillow(self.uid, self.floor, p["x"], p["y"])
            await i.edit_original_response(embed=self._embed("階段がある。どうする？"), attachments=[map_file], view=sv)
            return

        elif ct == D_CHEST:
            msg, coins_gain = d_open_chest(self.uid, self.supabase)
            d_consume(self.floor, p["x"], p["y"])
            await dg_save_map(self.floor, self.supabase)

        elif ct == D_TRAP:
            msg, coins_loss = d_trigger_trap(self.uid)
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
                await i.edit_original_response(embed=cv._embed(), attachments=[map_file], view=cv)
                return

        # 死亡判定
        if p["hp"] <= 0:
            p["hp"] = p["max_hp"]
            p["floor"] = 1
            start_pos = dg_starts.get(1, (1, 1))
            p["x"], p["y"] = start_pos
            msg += "\n力尽きた… スタート地点へ戻された"

        # 最終的な画面更新
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
        sv = DungeonStatusView(self.uid, self.floor, self.x, self.y)
        status_embed = sv._embed()
        await i.edit_original_response(embed=status_embed, attachments=[], view=sv)


# ============================================================
#  Cog クラス
# ============================================================

class DungeonCog(Cog):
    """ダンジョンシステムCog"""
    def __init__(self, bot):
        self.bot = bot
        self.supabase = None
    # --- BGM関連のメソッド ---
    async def play_dungeon_bgm(self, interaction: Interaction):
        """ユーザーがVCにいる場合、ボットを接続してBGMをループ再生する"""
        if not interaction.user.voice:
            return # VCにいない場合は何もしない

        voice_channel = interaction.user.voice.channel
        
        # すでに他のVCに接続しているか確認、なければ接続
        vc = interaction.guild.voice_client
        if vc:
            if vc.channel != voice_channel:
                await vc.move_to(voice_channel)
        else:
            vc = await voice_channel.connect()

        # BGM再生 (ループ再生用の関数)
        def repeat_bgm(error):
            if error:
                print(f"BGM再生エラー: {error}")
            if vc.is_connected():
                # 再帰的に自分を呼び出してループさせる
                vc.play(FFmpegPCMAudio("Assets/a.minister.m4a"), after=repeat_bgm)

        if not vc.is_playing():
            vc.play(FFmpegPCMAudio("Assets/a.minister.m4a"), after=repeat_bgm)
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
        
        # --- BGM再生処理を追加 ---
        try:
            await self.play_dungeon_bgm(interaction)
        except Exception as e:
            print(f"BGM開始失敗: {e}")
        # ----------------------

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

        # Viewの作成
        mv = DungeonMainView(uid, floor, x, y, self.supabase)
        
        # 初期表示用のマップ画像を生成
        map_url = await d_render_image(uid, floor, x, y, self.bot)

        # Embedの生成
        em = mv._embed("ダンジョンへようこそ！", has_image=True, image_url=map_url)

        # 送信
        await interaction.followup.send(embed=em, view=mv)

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
        """月次リセットタスク（1日0時）"""
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