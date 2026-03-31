# -*- coding: utf-8 -*-

"""
dungeon.py  ― ダンジョン探索 Cog
main.py / config.py の実装をそのまま引き継いだ cogs 対応版
"""

import os, io, asyncio, random, datetime, json
import discord
from discord import app_commands, Interaction
from discord.ext import commands, tasks
from PIL import Image, ImageDraw

# config.py で定義されている全グローバル変数・定数をインポート

from config import (
supabase, JST,
# ダンジョン定数
D_WALL, D_FLOOR, D_START, D_STAIRS, D_CHEST, D_TRAP, D_SHOP, D_BASE, D_MINE,
I_WALL, I_FLOOR, I_EXIT, I_COUNTER, I_REST, I_STORAGE, I_BAKERY, I_DOUBLE, I_SLOT,
D_MAP_W, D_MAP_H, D_FLOORS, D_VIEW_R, TILE,
DUNGEON_IMG_CHANNEL_ID, D_ENCOUNTER_RATES, D_BIOMES, TILE_COLORS,
# ダンジョン用グローバル辞書（config.py で初期化済み）
dg_maps, dg_players, dg_starts, dg_used, dg_bases, dg_stairs,
Dg,
# ユーザーデータ
user_cache,
# 権限
moderators,
# 実績・統計
ACHIEVEMENTS, player_stats, user_achievements,
# カラー定数
COLOR_SUCCESS, COLOR_ERROR, COLOR_INFO,
# アイテム
ITEMS, UNCRAFTABLE_ITEMS,
# デイリーミッション
DAILY_MISSIONS_ALL, daily_mission_data,
# Embed用ヘルパー（main.py でグローバル定義）
)

# ================================================================

# main.py 側に定義されているヘルパー関数（Cog内から参照）

# ※ main.py から import できないため、ここで再参照するか

# Cog 外部から引数で渡す設計にする。

# ここでは bot オブジェクト経由で main.py のグローバルを使う。

# ================================================================

def embed_success(title=None, description=None):
return discord.Embed(title=title, description=description, color=COLOR_SUCCESS)

def embed_error(title=None, description=None):
return discord.Embed(title=title, description=description, color=COLOR_ERROR)

def embed_info(title=None, description=None):
return discord.Embed(title=title, description=description, color=COLOR_INFO)

# ––––––––––––––––––––––––––––––––

# アセット管理（モジュールレベルキャッシュ）

# ––––––––––––––––––––––––––––––––

_ASSET_CACHE: dict = {}   # {(biome_name, tile_id): Image}
PLAYER_IMAGE = None        # AGO.PNG

ASSET_CONFIG = {
("洞窟",     D_WALL):  "rock.PNG",
("洞窟",     D_FLOOR): "jimen.png",
("森",       D_WALL):  "mori_kabe.png",
("森",       D_FLOOR): "mori_yuka.png",
("氷雪地帯", D_WALL):  "Y_k.png",
("氷雪地帯", D_FLOOR): "Y_y.png",
("砂漠地帯", D_WALL):  "Y_k.png",
("砂漠地帯", D_FLOOR): "Y_y.png",
}

def load_all_assets():
global _ASSET_CACHE, PLAYER_IMAGE
base_dir   = os.path.dirname(os.path.abspath(__file__))
assets_dir = os.path.join(base_dir, "Assets")

```
# プレイヤー画像
p_path = os.path.join(base_dir, "AGO.PNG")
if not os.path.exists(p_path):
    p_path = os.path.join(assets_dir, "AGO.PNG")
try:
    PLAYER_IMAGE = Image.open(p_path).convert("RGBA")
    print(f"✓ プレイヤー画像読み込み完了: {p_path}")
except Exception as e:
    print(f"❌ AGO.PNG ロード失敗: {e}")
    PLAYER_IMAGE = None

# タイル画像
for (biome, tid), fname in ASSET_CONFIG.items():
    path = os.path.join(assets_dir, fname)
    if os.path.isfile(path):
        try:
            img = Image.open(path).convert("RGBA").resize(
                (TILE, TILE), Image.Resampling.NEAREST
            )
            _ASSET_CACHE[(biome, tid)] = img
            print(f"✓ {fname} 読み込み完了")
        except Exception as e:
            print(f"❌ {fname} ロード失敗: {e}")
    else:
        print(f"⚠ {fname} が見つかりません: {path}")
```

# ================================================================

# バイオームユーティリティ

# ================================================================

def d_get_biome(floor):
for f_range, name, wall_emo, floor_emo, spec_emo, color in D_BIOMES:
if floor in f_range:
return name, wall_emo, floor_emo, spec_emo, color
return "深淵", "⬛", "🔲", "💠", 0x000000

# ================================================================

# タイル描画

# ================================================================

def _draw_tile(draw, img, x, y, cell, biome, is_player=False, is_fog=False):
px, py = x * TILE, y * TILE
if is_fog:
draw.rectangle([px, py, px+TILE-1, py+TILE-1], fill=(0, 0, 0))
return

```
if is_player:
    col_src = TILE_COLORS[D_FLOOR]
    col = col_src.get(biome, (40, 30, 25)) if isinstance(col_src, dict) else col_src
    draw.rectangle([px, py, px+TILE-1, py+TILE-1], fill=col)
    col = TILE_COLORS["player"]
    margin = 6
    draw.ellipse(
        [px+margin, py+margin, px+TILE-margin-1, py+TILE-margin-1],
        fill=col
    )
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
col = col_src.get(biome, (80, 80, 80)) if isinstance(col_src, dict) else col_src
draw.rectangle([px, py, px+TILE-1, py+TILE-1], fill=col)

if cell == D_CHEST:
    m = 8
    draw.rectangle(
        [px+m, py+m, px+TILE-m-1, py+TILE-m-1],
        fill=(255, 255, 100), outline=(180, 140, 0), width=2
    )
elif cell == D_STAIRS:
    for s in range(3):
        sx = px + 6 + s*6; sy = py + TILE - 8 - s*6
        draw.rectangle([sx, sy, sx+TILE-14, sy+4], fill=(255, 255, 255))
elif cell == D_SHOP:
    draw.text((px+TILE//2, py+TILE//2), "S", fill=(255, 255, 255))
elif cell == D_MINE:
    draw.text((px+TILE//2-4, py+TILE//2-6), "⛏", fill=(200, 200, 200))
elif cell == D_BASE:
    draw.text((px+TILE//2-4, py+TILE//2-6), "🏠", fill=(255, 255, 255))
```

# ================================================================

# マップ画像生成ユーティリティ

# ================================================================

def d_build_map_image(uid, floor, px, py, radius=D_VIEW_R):
d_ensure_map(floor)
bname, *_ = d_get_biome(floor)
size = radius * 2 + 1
img  = Image.new("RGB", (size * TILE, size * TILE), (0, 0, 0))
draw = ImageDraw.Draw(img)

```
for vy_i, vy in enumerate(range(py - radius, py + radius + 1)):
    for vx_i, vx in enumerate(range(px - radius, px + radius + 1)):
        is_player = (vx == px and vy == py)
        if not (0 <= vx < D_MAP_W and 0 <= vy < D_MAP_H):
            _draw_tile(draw, img, vx_i, vy_i, D_WALL, bname, is_fog=True)
            continue
        cell = dg_maps[floor][vy][vx]
        _draw_tile(draw, img, vx_i, vy_i, cell, bname, is_player=is_player)
return img
```

def d_render_pillow(uid, floor, px, py, radius=D_VIEW_R):
img = d_build_map_image(uid, floor, px, py, radius)
buf = io.BytesIO()
img.save(buf, format="PNG")
buf.seek(0)
return discord.File(fp=buf, filename="map.png")

# ================================================================

# 施設内部レイアウト

# ================================================================

SHOP_LAYOUT = [
"#######",
"#…..#",
"#.CCC.#",
"#…..#",
"#…..#",
"#E….#",
"#######",
]
BASE_LAYOUT = [
"#########",
"#…….#",
"#.S…S.#",
"#…….#",
"#..@.R..#",
"#…….#",
"#.B…A.#",
"#E……#",
"#########",
]
LOBY_LAYOUT = [
"############",
"#……….#",
"#……….#",
"#……….#",
"#……….#",
"#……….#",
"#……….#",
"#……….#",
"############",
]

def _parse_layout(layout):
grid = {}; start = (1, 1)
for y, row in enumerate(layout):
for x, ch in enumerate(row):
if   ch == "#": grid[(x, y)] = I_WALL
elif ch == ".": grid[(x, y)] = I_FLOOR
elif ch == "E": grid[(x, y)] = I_EXIT
elif ch == "C": grid[(x, y)] = I_COUNTER
elif ch == "R": grid[(x, y)] = I_REST
elif ch == "S": grid[(x, y)] = I_STORAGE
elif ch == "@": grid[(x, y)] = I_FLOOR; start = (x, y)
elif ch == "B": grid[(x, y)] = I_BAKERY
elif ch == "L": grid[(x, y)] = I_SLOT
elif ch == "D": grid[(x, y)] = I_DOUBLE
return grid, start

SHOP_GRID, SHOP_START = _parse_layout(SHOP_LAYOUT)
BASE_GRID,  BASE_START = _parse_layout(BASE_LAYOUT)
LOBY_GRID,  LOBY_START = _parse_layout(LOBY_LAYOUT)

T_SIZE = 32

def i_render_pillow(grid, pw, ph):
if not grid:
img = Image.new("RGBA", (T_SIZE, T_SIZE), (0, 0, 0, 255))
else:
max_x = max(x for x, y in grid) + 1
max_y = max(y for x, y in grid) + 1
img = Image.new("RGBA", (max_x * T_SIZE, max_y * T_SIZE), (0, 0, 0, 255))

```
draw = ImageDraw.Draw(img)
for (vx, vy), cell in grid.items():
    dx, dy = vx * T_SIZE, vy * T_SIZE
    if cell == I_WALL:   color = (60, 60, 60, 255)
    elif cell == I_EXIT: color = (0, 200, 100, 255)
    else:                color = (220, 220, 220, 255)
    draw.rectangle([dx, dy, dx+T_SIZE-1, dy+T_SIZE-1], fill=color)
    if vx == pw and vy == ph:
        draw.ellipse([dx+4, dy+4, dx+T_SIZE-5, dy+T_SIZE-5], fill=(255, 50, 50, 255))

buf = io.BytesIO()
img.save(buf, format="PNG")
buf.seek(0)
return discord.File(fp=buf, filename="map.png")
```

# ================================================================

# マップ生成・管理

# ================================================================

def d_gen_floor(floor):
grid = [
[D_WALL if (x == 0 or y == 0 or x == D_MAP_W-1 or y == D_MAP_H-1)
else (D_WALL if random.random() < 0.45 else D_FLOOR)
for x in range(D_MAP_W)]
for y in range(D_MAP_H)
]
for _ in range(5):
new = [[D_WALL]*D_MAP_W for _ in range(D_MAP_H)]
for y in range(D_MAP_H):
for x in range(D_MAP_W):
if x == 0 or y == 0 or x == D_MAP_W-1 or y == D_MAP_H-1:
new[y][x] = D_WALL; continue
walls = sum(
1 for dy in range(-1, 2) for dx in range(-1, 2)
if grid[y+dy][x+dx] == D_WALL
)
new[y][x] = D_WALL if walls >= 5 else D_FLOOR
grid = new

```
visited = set(); best = set()
for sy in range(1, D_MAP_H-1):
    for sx in range(1, D_MAP_W-1):
        if grid[sy][sx] == D_FLOOR and (sx, sy) not in visited:
            region = set(); queue = [(sx, sy)]
            while queue:
                cx, cy = queue.pop()
                if (cx, cy) in region: continue
                region.add((cx, cy))
                for ddx, ddy in [(0,1),(0,-1),(1,0),(-1,0)]:
                    nx, ny = cx+ddx, cy+ddy
                    if (0 < nx < D_MAP_W-1 and 0 < ny < D_MAP_H-1
                            and grid[ny][nx] == D_FLOOR
                            and (nx, ny) not in region):
                        queue.append((nx, ny))
            visited |= region
            if len(region) > len(best): best = region

for y in range(D_MAP_H):
    for x in range(D_MAP_W):
        if grid[y][x] == D_FLOOR and (x, y) not in best:
            grid[y][x] = D_WALL

candidates = list(best); random.shuffle(candidates)
sx, sy = candidates[0]
grid[sy][sx] = D_START; dg_starts[floor] = (sx, sy)

stair_x, stair_y = None, None
for ex, ey in candidates[1:]:
    if abs(ex-sx) + abs(ey-sy) > 20:
        grid[ey][ex] = D_STAIRS
        stair_x, stair_y = ex, ey
        break
else:
    if len(candidates) > 1:
        stair_x, stair_y = candidates[1][0], candidates[1][1]
        grid[stair_y][stair_x] = D_STAIRS

if stair_x is not None:
    dg_stairs[floor] = (stair_x, stair_y)
    try:
        supabase.table("dungeon_stairs").upsert(
            {"floor": floor, "x": stair_x, "y": stair_y}
        ).execute()
    except Exception as e:
        print(f"⚠️ 階段保存エラー: {e}")

floor_cells = [p for p in best if grid[p[1]][p[0]] == D_FLOOR]
random.shuffle(floor_cells)
placed_chest = placed_trap = placed_shop = placed_mine = 0
max_chest = max(3, len(floor_cells)//80)
max_trap  = max(2, len(floor_cells)//120)
max_shop  = max(1, len(floor_cells)//300)
max_mine  = max(2, len(floor_cells)//150)

for fx, fy in floor_cells:
    if all([placed_chest >= max_chest, placed_trap >= max_trap,
            placed_shop >= max_shop,   placed_mine >= max_mine]):
        break
    r = random.random()
    if placed_shop  < max_shop  and r < 0.03:
        grid[fy][fx] = D_SHOP;  placed_shop  += 1
    elif placed_mine  < max_mine  and r < 0.10:
        grid[fy][fx] = D_MINE;  placed_mine  += 1
    elif placed_chest < max_chest and r < 0.60:
        grid[fy][fx] = D_CHEST; placed_chest += 1
    elif placed_trap  < max_trap:
        grid[fy][fx] = D_TRAP;  placed_trap  += 1

return grid
```

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

# ================================================================

# HP / ステータス管理

# ================================================================

D_MAX_HP    = 150
D_BASE_ATK  = 10
D_BASE_DEF  = 5
D_BASE_SPD  = 10
D_BASE_CRIT = 0.05

def d_hpbar(hp, max_hp, n=8):
f = int((hp / max_hp) * n) if max_hp > 0 else 0
return "█"*f + "░"*(n-f)

def d_get_player(uid):
if uid not in dg_players:
dg_players[uid] = {
"floor": 1, "x": 1, "y": 1,
"hp": D_MAX_HP, "max_hp": D_MAX_HP,
"atk": D_BASE_ATK, "def_": D_BASE_DEF,
"spd": D_BASE_SPD, "crit": D_BASE_CRIT,
}
p = dg_players[uid]
lv = user_cache.get(uid, {}).get("level", 1) or 1
p["atk"]    = D_BASE_ATK + lv * 2
p["def_"]   = D_BASE_DEF + lv
p["spd"]    = D_BASE_SPD + lv * 2
p["max_hp"] = D_MAX_HP   + lv * 10
if p["hp"] > p["max_hp"]: p["hp"] = p["max_hp"]
return p

# ================================================================

# 報酬・罠・採掘

# ================================================================

def d_open_chest(uid):
u = user_cache.get(uid, {}); roll = random.random()
if roll < 0.5:
coins = random.randint(50, 300); u["coins"] = u.get("coins", 0) + coins
return f"🟨 宝箱！ コイン **+{coins}** 枚"
elif roll < 0.8:
bread = random.randint(3, 15); u["bread_count"] = u.get("bread_count", 0) + bread
return f"🟨 宝箱！ レアパン **+{bread}** 個"
elif roll < 0.95:
boxes = random.randint(1, 3); u["boxes"] = u.get("boxes", 0) + boxes
return f"🟨 宝箱！ 宝箱 **+{boxes}** 個"
else:
chips = random.randint(100, 500); u["chips"] = u.get("chips", 0) + chips
return f"🟨 宝箱！ チップ **+{chips}** 枚"

def d_trigger_trap(uid):
u = user_cache.get(uid, {}); p = d_get_player(uid); roll = random.random()
if roll < 0.4:
loss = random.randint(30, 150); u["coins"] = max(0, u.get("coins", 0) - loss)
return f"🟥 罠！ コイン **-{loss}** 枚"
elif roll < 0.7:
dmg = random.randint(10, 30); p["hp"] = max(0, p["hp"] - dmg)
return f"🟥 罠！ HP **-{dmg}**"
elif roll < 0.85:
loss = random.randint(1, 5); u["bread_count"] = max(0, u.get("bread_count", 0) - loss)
return f"🟥 罠！ レアパン **-{loss}** 個"
else:
loss = random.randint(50, 200); u["chips"] = max(0, u.get("chips", 0) - loss)
return f"🟥 罠！ チップ **-{loss}** 枚"

def d_do_mine(uid):
u = user_cache.get(uid, {})
gain = random.randint(30, 200)
u["coins"] = u.get("coins", 0) + gain
return gain

# ================================================================

# 敵データ

# ================================================================

D_ENEMY_NAMES = {
"洞窟":     ["コウモリ", "ゴブリン", "岩石スライム"],
"森":       ["オオカミ", "毒キノコ", "トレント"],
"氷雪地帯": ["雪男", "アイスゴーレム", "白熊"],
"砂漠地帯": ["サソリ", "砂蛇", "炎トカゲ"],
}
D_SUPERENEMY_NAMES = {
"洞窟":     ["セミオートキラーマシン"],
"森":       ["邪蛇"],
"氷雪地帯": ["雪女"],
"砂漠地帯": ["鬼"],
}
D_BOSS_NAMES = {
"洞窟":     ["ドラゴン"],
"森":       ["ヌシ", "ぱすた"],
"氷雪地帯": ["凍ったコッペパン"],
"砂漠地帯": ["炎龍"],
}
ENEMY_STATS_MASTER = {
"コウモリ":           {"hp_m":0.7,  "atk_m":0.5, "def_m":0.5, "spd":10, "crit":0,    "ai":["attack","wait"], "coin_m":0.8,  "xp_m":0.8,  "boxes":0},
"ゴブリン":           {"hp_m":1.0,  "atk_m":1.1, "def_m":0.8, "spd":15, "crit":0.08, "ai":["attack"],        "coin_m":1.0,  "xp_m":1.0,  "boxes":0},
"岩石スライム":       {"hp_m":1.5,  "atk_m":0.8, "def_m":1.8, "spd":5,  "crit":0.02, "ai":["attack"],        "coin_m":1.2,  "xp_m":1.1,  "boxes":0},
"オオカミ":           {"hp_m":0.9,  "atk_m":1.2, "def_m":0.7, "spd":20, "crit":0.10, "ai":["attack"],        "coin_m":1.1,  "xp_m":1.2,  "boxes":0},
"毒キノコ":           {"hp_m":1.2,  "atk_m":0.8, "def_m":1.0, "spd":5,  "crit":0.05, "ai":["attack"],        "coin_m":1.0,  "xp_m":1.0,  "boxes":0},
"トレント":           {"hp_m":2.0,  "atk_m":1.0, "def_m":1.5, "spd":3,  "crit":0.03, "ai":["attack","attack","heal"], "coin_m":1.5,"xp_m":1.5,"boxes":0},
"セミオートキラーマシン": {"hp_m":4.5,"atk_m":2.8,"def_m":1.5,"spd":22,"crit":0.25,"ai":["attack"],          "coin_m":3.0,  "xp_m":5.0,  "boxes":1},
"邪蛇":               {"hp_m":3.0,  "atk_m":3.4, "def_m":1.2, "spd":28, "crit":0.15, "ai":["attack"],        "coin_m":2.5,  "xp_m":4.0,  "boxes":1},
"ヌシ":               {"hp_m":20.0, "atk_m":4.5, "def_m":2.2, "spd":12, "crit":0.10, "ai":["attack"],        "coin_m":10.0, "xp_m":10.0, "boxes":5},
"ドラゴン":           {"hp_m":18.0, "atk_m":5.0, "def_m":2.5, "spd":20, "crit":0,    "ai":["attack"],        "coin_m":12.0, "xp_m":12.0, "boxes":5},
"ぱすた":            {"hp_m":100,  "atk_m":0,   "def_m":10,  "spd":100,"crit":0,    "ai":["wait"],          "coin_m":0.1,  "xp_m":0.1,  "boxes":0},
"ミミック":           {"hp_m":2.5,  "atk_m":2.0, "def_m":1.2, "spd":8,  "crit":0.25, "ai":["attack"],        "coin_m":5.0,  "xp_m":3.0,  "boxes":1},
"default":            {"hp_m":1.0,  "atk_m":1.0, "def_m":1.0, "spd":10, "crit":0.05, "ai":["attack"],        "coin_m":1.0,  "xp_m":1.0,  "boxes":0},
}

def d_make_enemy(floor, forced_name=None):
base_hp  = 15 + floor * 8
base_atk = 4  + floor * 2
base_def = 1  + floor
bname, _, _, _, _ = d_get_biome(floor)

```
if forced_name:
    name  = forced_name
    etype = "normal"
else:
    r = random.random()
    if r < 0.01:
        etype = "boss"; name = random.choice(D_BOSS_NAMES.get(bname, ["ボス"]))
    elif r < 0.11:
        etype = "elite"; name = random.choice(D_SUPERENEMY_NAMES.get(bname, ["精鋭"]))
    else:
        etype = "normal"; name = random.choice(D_ENEMY_NAMES.get(bname, ["謎の敵"]))

clean_key = name.split()[0].replace("👾", "").strip()
m = ENEMY_STATS_MASTER.get(clean_key, ENEMY_STATS_MASTER["default"])

rank_hp_mul  = 4.0 if etype=="elite" else (15.0 if etype=="boss" else 1.0)
rank_atk_mul = 2.5 if etype=="elite" else (4.0  if etype=="boss" else 1.0)
rank_def_mul = 1.5 if etype=="elite" else (2.0  if etype=="boss" else 1.0)

hp   = int((base_hp  + random.randint(-3, 3)) * m["hp_m"]  * rank_hp_mul)
atk  = int((base_atk + random.randint(-1, 1)) * m["atk_m"] * rank_atk_mul)
defe = int(base_def * m["def_m"] * rank_def_mul)

if etype == "elite":
    reward_coins = int(random.randint(80,  150)  * floor * m["coin_m"])
    reward_xp    = int(random.randint(100, 800)  * floor * m["xp_m"])
    reward_box   = max(1, m["boxes"])
elif etype == "boss":
    reward_coins = int(random.randint(2000, 4000) * floor * m["coin_m"])
    reward_xp    = int(random.randint(1000, 2000) * floor * m["xp_m"])
    reward_box   = max(5, m["boxes"])
else:
    reward_coins = int(random.randint(20, 80) * floor * m["coin_m"])
    reward_xp    = int(random.randint(10, 30) * floor * m["xp_m"])
    reward_box   = m["boxes"] if m["boxes"] > 0 else (1 if random.random() < 0.05 else 0)

return {
    "name": name, "type": etype,
    "hp": hp, "max_hp": hp, "atk": atk, "def_": defe,
    "spd": m["spd"], "crit": m["crit"],
    "reward_coins": reward_coins, "reward_xp": reward_xp, "reward_box": reward_box,
}
```

# ================================================================

# Supabase 永続化ヘルパー

# ================================================================

async def dg_save_player(uid):
if uid not in dg_players: return
try:
supabase.table("dungeon_players").upsert(
{"user_id": uid, "data": dg_players[uid]}
).execute()
except Exception as e:
print(f"dg_save_player失敗 {uid}: {e}")

async def dg_save_map(floor):
if floor not in dg_maps: return
try:
supabase.table("dungeon_maps").upsert({
"floor":  floor,
"grid":   dg_maps[floor],
"starts": list(dg_starts.get(floor, (1, 1))),
"used":   [list(u) for u in dg_used.get(floor, set())],
}).execute()
except Exception as e:
print(f"dg_save_map失敗 floor={floor}: {e}")

async def dg_save_base(uid):
try:
if uid in dg_bases:
fl, x, y = dg_bases[uid]
supabase.table("dungeon_bases").upsert(
{"user_id": uid, "floor": fl, "x": x, "y": y}
).execute()
else:
supabase.table("dungeon_bases").delete().eq("user_id", uid).execute()
except Exception as e:
print(f"dg_save_base失敗 {uid}: {e}")

async def dg_load_all():
"""起動時に全データをDBからロード（on_ready から呼ぶ）"""
try:
res = supabase.table("dungeon_players").select("*").execute()
for row in res.data:
dg_players[row["user_id"]] = row["data"]
print(f"dungeon_players ロード完了: {len(dg_players)}件")
except Exception as e:
print(f"dungeon_players ロード失敗: {e}")

```
try:
    res = supabase.table("dungeon_maps").select("*").execute()
    for row in res.data:
        fl = row["floor"]
        dg_maps[fl]   = row["grid"]
        dg_starts[fl] = tuple(row["starts"]) if row["starts"] else (1, 1)
        dg_used[fl]   = set(tuple(u) for u in (row["used"] or []))
    print(f"dungeon_maps ロード完了: {len(dg_maps)}階分")
except Exception as e:
    print(f"dungeon_maps ロード失敗: {e}")

try:
    res = supabase.table("dungeon_bases").select("*").execute()
    for row in res.data:
        dg_bases[row["user_id"]] = (row["floor"], row["x"], row["y"])
    print(f"dungeon_bases ロード完了: {len(dg_bases)}件")
except Exception as e:
    print(f"dungeon_bases ロード失敗: {e}")

# ロードできなかった階はメモリ生成
for fl in range(1, D_FLOORS+1):
    d_ensure_map(fl)

# 階段座標ロード
try:
    res = supabase.table("dungeon_stairs").select("*").execute()
    for row in res.data:
        dg_stairs[int(row["floor"])] = (int(row["x"]), int(row["y"]))
    print(f"dungeon_stairs ロード完了: {len(dg_stairs)}件")
except Exception as e:
    print(f"dungeon_stairs ロード失敗: {e}")
```

# ================================================================

# 広域マップ（STATUS用）

# ================================================================

async def d_render_status_map(bot, uid, floor, px, py):
d_ensure_map(floor)
bname, *_ = d_get_biome(floor)
status_radius = 25
size = status_radius * 2 + 1

```
img  = Image.new("RGB", (size * TILE, size * TILE), (0, 0, 0))
draw = ImageDraw.Draw(img)
user_dg = Dg.get(uid, {}).get(floor, set())

for vy_i, vy in enumerate(range(py - status_radius, py + status_radius + 1)):
    for vx_i, vx in enumerate(range(px - status_radius, px + status_radius + 1)):
        is_player = (vx == px and vy == py)
        if not (0 <= vx < D_MAP_W and 0 <= vy < D_MAP_H): continue
        if not is_player and (vx, vy) not in user_dg: continue
        cell = dg_maps[floor][vy][vx]
        _draw_tile(draw, img, vx_i, vy_i, cell, bname, is_player=False)
        if is_player:
            dx_px, dy_px = vx_i * TILE, vy_i * TILE
            if PLAYER_IMAGE:
                img.paste(PLAYER_IMAGE, (dx_px, dy_px), PLAYER_IMAGE)
            else:
                draw.ellipse([dx_px+2, dy_px+2, dx_px+TILE-3, dy_px+TILE-3], fill=(255, 50, 50))

buf = io.BytesIO()
img.save(buf, format="PNG", optimize=True)
buf.seek(0)
try:
    target_id = int(DUNGEON_IMG_CHANNEL_ID)
    ch  = bot.get_channel(target_id) or await bot.fetch_channel(target_id)
    msg = await ch.send(file=discord.File(buf, filename="status_map.png"))
    return msg.attachments[0].url
except Exception as e:
    print(f"❌ 広域マップ生成失敗: {e}")
    return None
```

async def d_render_image(bot, uid, floor, px, py, radius=D_VIEW_R):
img = d_build_map_image(uid, floor, px, py, radius)
buf = io.BytesIO()
img.save(buf, format="PNG")
buf.seek(0)
try:
ch  = bot.get_channel(DUNGEON_IMG_CHANNEL_ID) or   
await bot.fetch_channel(DUNGEON_IMG_CHANNEL_ID)
msg = await ch.send(file=discord.File(buf, filename="map.png"))
return msg.attachments[0].url
except Exception as e:
print(f"画像アップロード失敗: {e}")
return None

# ================================================================

# 戦闘 View

# ================================================================

class DungeonCombatView(discord.ui.View):
def **init**(self, uid, floor, x, y, enemy):
super().**init**(timeout=180)
self.uid = uid; self.floor = floor; self.x = x; self.y = y
self.enemy = enemy; self.log = []; self.defending = False

```
def _embed(self):
    p = d_get_player(self.uid); e = self.enemy
    ratio  = p["hp"] / max(p["max_hp"], 1)
    color  = 0x00ff88 if ratio > 0.5 else (0xffaa00 if ratio > 0.25 else 0xff4444)
    etype  = e.get("type", "normal")
    type_text = {"normal":"通常","elite":"精鋭","boss":"ボス"}[etype]
    em = discord.Embed(title=f"⚔️ {e['name']}（{type_text}）が現れた！", color=color)
    em.set_image(url="attachment://map.png")
    em.add_field(name="あなた",
        value=f"`{d_hpbar(p['hp'],p['max_hp'])}`{p['hp']}/{p['max_hp']}\n⚔️{p['atk']} 🛡️{p['def_']}",
        inline=True)
    em.add_field(name=e["name"],
        value=f"`{d_hpbar(e['hp'],e['max_hp'])}`{e['hp']}/{e['max_hp']}",
        inline=True)
    if self.log:
        em.add_field(name="ログ", value="\n".join(self.log[-5:]), inline=False)
    return em

def _calc_dmg(self, attacker, defender, defending=False):
    is_crit = random.random() < attacker.get("crit", 0.05)
    def_val = defender.get("def_", 0) * (2 if defending else 1)
    dmg = max(1, attacker["atk"] - def_val + random.randint(-2, 3))
    return (int(dmg * 1.5), True) if is_crit else (dmg, False)

def _enemy_turn(self):
    p = d_get_player(self.uid); e = self.enemy
    raw = e["name"].split()[0].replace("👾", "").strip()
    master = ENEMY_STATS_MASTER.get(raw, ENEMY_STATS_MASTER["default"])
    action = random.choice(master.get("ai", ["attack"]))
    if action == "heal":
        amt = int(e["max_hp"] * 0.15); e["hp"] = min(e["max_hp"], e["hp"] + amt)
        msg = f"💚 {e['name']}は傷口を舐めて {amt} 回復した"
    elif action == "wait":
        msg = f"💤 {e['name']}は様子を伺っている..."
    else:
        dmg, crit = self._calc_dmg(e, p, self.defending)
        p["hp"] = max(0, p["hp"] - dmg)
        c_msg = "⚠️ **CRITICAL!!** " if crit else ""
        msg = f"{c_msg}{e['name']}の攻撃：{dmg} ダメージ"
    self.defending = False
    return msg

async def _win(self, i, cog):
    e = self.enemy
    u = user_cache.get(self.uid, {})
    u["coins"] = u.get("coins", 0) + e["reward_coins"]
    if e["reward_box"] > 0:
        u["boxes"] = u.get("boxes", 0) + e["reward_box"]
    leveled, role_grants = cog.add_xp_local(self.uid, e["reward_xp"])
    msg = f"🎉 勝利！ +{e['reward_coins']}コイン +{e['reward_xp']}XP"
    if e["reward_box"] > 0: msg += f" +宝箱{e['reward_box']}個"
    if leveled:
        lv = user_cache.get(self.uid, {}).get("level", 1)
        msg += f"\n⬆️ レベルアップ！ Lv.**{lv}**"
    self.log.append(msg)
    await cog.save_user(self.uid)
    await dg_save_player(self.uid)
    self.stop()
    mv = DungeonMainView(self.uid, self.floor, self.x, self.y)
    map_file = d_render_pillow(self.uid, self.floor, self.x, self.y)
    await i.edit_original_response(embed=mv._embed(msg), view=mv, attachments=[map_file])

async def _lose(self, i, cog):
    p = d_get_player(self.uid)
    p["hp"] = p["max_hp"]; p["floor"] = 1
    p["x"], p["y"] = dg_starts.get(1, (1, 1))
    self.log.append("敗北… スタート地点へ送還された")
    await dg_save_player(self.uid)
    self.stop()
    mv = DungeonMainView(self.uid, 1, p["x"], p["y"])
    map_file = d_render_pillow(self.uid, 1, p["x"], p["y"])
    await i.edit_original_response(embed=mv._embed("敗北して戻された…"), view=mv, attachments=[map_file])

# ボタンは cog 参照が必要なため、cog を渡す設計にする
# ※ discord.py の Button はクロージャで cog を捕捉する

@discord.ui.button(label="⚔ 攻撃", style=discord.ButtonStyle.red, row=0)
async def attack(self, i, b):
    await i.response.defer()
    cog = i.client.cogs.get("DungeonCog")
    p = d_get_player(self.uid); e = self.enemy
    p_first = p.get("spd", 10) >= e.get("spd", 10)
    if p_first:
        dmg, crit = self._calc_dmg(p, e)
        e["hp"] = max(0, e["hp"] - dmg)
        self.log.append(f"{'💥 **CRIT!!** ' if crit else ''}{dmg} ダメージ！")
        if e["hp"] <= 0: await self._win(i, cog); return
        self.log.append(self._enemy_turn())
    else:
        self.log.append(self._enemy_turn())
        if p["hp"] <= 0: await self._lose(i, cog); return
        dmg, crit = self._calc_dmg(p, e)
        e["hp"] = max(0, e["hp"] - dmg)
        self.log.append(f"{'💥 **CRIT!!** ' if crit else ''}{dmg} ダメージ！")
    if e["hp"] <= 0: await self._win(i, cog); return
    if p["hp"] <= 0: await self._lose(i, cog); return
    map_file = d_render_pillow(self.uid, self.floor, self.x, self.y)
    await i.edit_original_response(embed=self._embed(), view=self, attachments=[map_file])

@discord.ui.button(label="🛡 防御", style=discord.ButtonStyle.blurple, row=0)
async def defend(self, i, b):
    await i.response.defer()
    cog = i.client.cogs.get("DungeonCog")
    self.defending = True
    self.log.append(f"🛡 防御体制！\n{self._enemy_turn()}")
    if d_get_player(self.uid)["hp"] <= 0:
        await self._lose(i, cog); return
    map_file = d_render_pillow(self.uid, self.floor, self.x, self.y)
    await i.edit_original_response(embed=self._embed(), view=self, attachments=[map_file])

@discord.ui.button(label="逃げる", style=discord.ButtonStyle.grey, row=0)
async def run_away(self, i, b):
    await i.response.defer()
    cog = i.client.cogs.get("DungeonCog")
    if self.enemy.get("type") == "boss":
        self.log.append("ボスからは逃げられない！\n" + self._enemy_turn())
        if d_get_player(self.uid)["hp"] <= 0:
            await self._lose(i, cog); return
        await i.edit_original_response(
            embed=self._embed(), view=self,
            attachments=[d_render_pillow(self.uid, self.floor, self.x, self.y)]
        )
        return
    esc_rate = 0.2 if self.enemy.get("type") == "elite" else 0.5
    if random.random() < esc_rate:
        self.stop()
        mv = DungeonMainView(self.uid, self.floor, self.x, self.y)
        await i.edit_original_response(
            embed=mv._embed("逃走成功"), view=mv,
            attachments=[d_render_pillow(self.uid, self.floor, self.x, self.y)]
        )
    else:
        self.log.append("逃げ失敗！\n" + self._enemy_turn())
        if d_get_player(self.uid)["hp"] <= 0:
            await self._lose(i, cog); return
        await i.edit_original_response(
            embed=self._embed(), view=self,
            attachments=[d_render_pillow(self.uid, self.floor, self.x, self.y)]
        )
```

# ================================================================

# 鉱山 View

# ================================================================

class DungeonMineView(discord.ui.View):
def **init**(self, uid, floor, x, y, max_count=None):
super().**init**(timeout=120)
self.uid = uid; self.floor = floor; self.x = x; self.y = y
self.count = 0; self.max_count = max_count or random.randint(3, 8)
self.total = 0; self.log = []

```
def _embed(self, msg=""):
    p = d_get_player(self.uid)
    em = discord.Embed(title="⛏ 鉱山", color=0x5C4033)
    em.set_image(url="attachment://map.png")
    em.add_field(name="採掘回数", value=f"{self.count}/{self.max_count}", inline=True)
    em.add_field(name="合計",     value=f"**{self.total:,}** コイン",     inline=True)
    em.add_field(name="HP",
        value=f"`{d_hpbar(p['hp'],p['max_hp'])}` {p['hp']}/{p['max_hp']}",
        inline=True)
    if self.log: em.add_field(name="採掘履歴", value="\n".join(self.log[-4:]), inline=False)
    if msg:      em.add_field(name="お知らせ", value=msg,                      inline=False)
    return em

@discord.ui.button(label="⛏ 採掘する", style=discord.ButtonStyle.blurple, row=0)
async def mine(self, i, b):
    await i.response.defer()
    cog = i.client.cogs.get("DungeonCog")
    map_file = d_render_pillow(self.uid, self.floor, self.x, self.y)
    if self.count >= self.max_count:
        await i.edit_original_response(embed=self._embed("鉱脈が枯れた…"), attachments=[map_file], view=self)
        return
    gain = d_do_mine(self.uid); self.count += 1; self.total += gain
    self.log.append(f"⛏ {self.count}回目: **+{gain}** コイン")
    await cog.save_user(self.uid)
    if self.count >= self.max_count:
        d_consume(self.floor, self.x, self.y)
        asyncio.create_task(dg_save_map(self.floor))
        self.children[0].disabled = True
        new_map = d_render_pillow(self.uid, self.floor, self.x, self.y)
        await i.edit_original_response(embed=self._embed("💫 掘り尽くした！"), attachments=[new_map], view=self)
    else:
        await i.edit_original_response(embed=self._embed(), attachments=[map_file], view=self)

@discord.ui.button(label="立ち去る", style=discord.ButtonStyle.grey, row=0)
async def leave(self, i, b):
    await i.response.defer()
    mv = DungeonMainView(self.uid, self.floor, self.x, self.y)
    map_file = d_render_pillow(self.uid, self.floor, self.x, self.y)
    await i.edit_original_response(
        embed=mv._embed(f"採掘終了。合計 **{self.total:,}** コイン獲得"),
        attachments=[map_file], view=mv
    )
```

# ================================================================

# STATUS View

# ================================================================

class DungeonStatusView(discord.ui.View):
def **init**(self, uid, floor, x, y):
super().**init**(timeout=120)
self.uid = uid; self.floor = floor; self.x = x; self.y = y
self.children[1].disabled = (uid not in dg_bases)

```
async def _embed(self, msg=""):
    p = d_get_player(self.uid); u = user_cache.get(self.uid, {})
    bname, _, _, _, bcolor = d_get_biome(self.floor)
    own = dg_bases.get(self.uid)
    base_str = f"{own[0]}階 ({own[1]},{own[2]})" if own else "未設置"
    cog = None  # bot参照なしでURL取得は不可のため省略
    em = discord.Embed(title=f"📊 STATUS — {bname} {self.floor}階", color=bcolor)
    em.add_field(name="HP",     value=f"`{d_hpbar(p['hp'],p['max_hp'])}` {p['hp']}/{p['max_hp']}", inline=False)
    em.add_field(name="ATK",    value=str(p["atk"]),           inline=True)
    em.add_field(name="DEF",    value=str(p["def_"]),          inline=True)
    em.add_field(name="コイン", value=f"{u.get('coins',0):,}枚", inline=True)
    em.add_field(name="レアパン", value=f"{u.get('bread_count',0)}個", inline=True)
    em.add_field(name="チップ", value=f"{u.get('chips',0):,}枚",  inline=True)
    em.add_field(name="現在地", value=f"{self.floor}階 ({self.x},{self.y})", inline=True)
    em.add_field(name="拠点",   value=base_str,                inline=True)
    if msg and msg.strip(): em.add_field(name="ログ", value=msg, inline=False)
    return em

@discord.ui.button(label="🏠 拠点を設置", style=discord.ButtonStyle.blurple, row=0)
async def set_base(self, i, b):
    await i.response.defer()
    if self.uid in dg_bases:
        await i.edit_original_response(embed=await self._embed("❌ 既に拠点があります"), view=self)
        return
    dg_bases[self.uid] = (self.floor, self.x, self.y)
    dg_maps[self.floor][self.y][self.x] = D_BASE
    self.children[1].disabled = False
    asyncio.create_task(dg_save_base(self.uid))
    asyncio.create_task(dg_save_map(self.floor))
    await i.edit_original_response(embed=await self._embed("🏠 拠点を設置しました"), view=self)

@discord.ui.button(label="🌀 拠点にワープ", style=discord.ButtonStyle.green, row=0)
async def warp(self, i, b):
    await i.response.defer()
    own = dg_bases.get(self.uid)
    if not own:
        await i.edit_original_response(embed=await self._embed("❌ 拠点なし"), view=self); return
    wf, wx, wy = own; d_ensure_map(wf)
    p = d_get_player(self.uid); p["floor"] = wf; p["x"] = wx; p["y"] = wy
    asyncio.create_task(dg_save_player(self.uid))
    mv = DungeonMainView(self.uid, wf, wx, wy)
    await i.edit_original_response(
        embed=mv._embed("🌀 ワープした！"),
        attachments=[d_render_pillow(self.uid, wf, wx, wy)], view=mv
    )

@discord.ui.button(label="🍞 パンを食べて全回復", style=discord.ButtonStyle.success, row=1)
async def eat_bread(self, i, b):
    await i.response.defer()
    cog = i.client.cogs.get("DungeonCog")
    p = d_get_player(self.uid); u = user_cache.get(self.uid, {})
    if u.get("bread_count", 0) <= 0:
        await i.edit_original_response(embed=await self._embed("❌ パンがありません"), view=self); return
    u["bread_count"] -= 1; p["hp"] = p["max_hp"]
    asyncio.create_task(cog.save_user(self.uid))
    asyncio.create_task(dg_save_player(self.uid))
    await i.edit_original_response(embed=await self._embed("✨ HP全回復！"), view=self)

@discord.ui.button(label="⬅ 戻る", style=discord.ButtonStyle.grey, row=1)
async def back(self, i, b):
    await i.response.defer()
    mv = DungeonMainView(self.uid, self.floor, self.x, self.y)
    await i.edit_original_response(
        embed=mv._embed(),
        attachments=[d_render_pillow(self.uid, self.floor, self.x, self.y)], view=mv
    )
```

# ================================================================

# 施設内部 View（基底）

# ================================================================

class InteriorView(discord.ui.View):
def **init**(self, uid, grid, pw, ph, return_floor, return_x, return_y, title, color):
super().**init**(timeout=300)
self.uid = uid; self.grid = grid
self.pw = pw; self.ph = ph
self.return_floor = return_floor
self.return_x = return_x; self.return_y = return_y
self.title = title; self.color = color

```
def _embed(self, msg=""):
    p = d_get_player(self.uid)
    em = discord.Embed(title=self.title, color=self.color)
    em.set_image(url="attachment://map.png")
    em.add_field(name="❤️ HP",
        value=f"`{d_hpbar(p['hp'],p['max_hp'])}`{p['hp']}/{p['max_hp']}", inline=True)
    if msg: em.add_field(name="ログ", value=msg, inline=False)
    return em

async def _on_step(self, cell, i=None): return ""

async def _move(self, i, dx, dy):
    await i.response.defer()
    nx, ny = self.pw + dx, self.ph + dy
    cell = self.grid.get((nx, ny), I_WALL)
    if cell == I_WALL:
        map_file = i_render_pillow(self.grid, self.pw, self.ph)
        await i.edit_original_response(embed=self._embed("🔲 壁！進めない"), attachments=[map_file])
        return
    if cell == I_EXIT:
        mv = DungeonMainView(self.uid, self.return_floor, self.return_x, self.return_y)
        map_file = d_render_pillow(self.uid, self.return_floor, self.return_x, self.return_y)
        await i.edit_original_response(embed=mv._embed("施設を出た"), view=mv, attachments=[map_file])
        return
    self.pw, self.ph = nx, ny
    msg = await self._on_step(cell, i)
    if msg is not None:
        map_file = i_render_pillow(self.grid, self.pw, self.ph)
        await i.edit_original_response(embed=self._embed(msg), view=self, attachments=[map_file])

@discord.ui.button(label="↖️", style=discord.ButtonStyle.grey, row=0, custom_id="i_lu")
async def leftup(self,   i, b): await self._move(i, -1, -1)
@discord.ui.button(label="⬆️", style=discord.ButtonStyle.grey, row=0, custom_id="i_u")
async def up(self,       i, b): await self._move(i,  0, -1)
@discord.ui.button(label="↗️", style=discord.ButtonStyle.grey, row=0, custom_id="i_ru")
async def rightup(self,  i, b): await self._move(i,  1, -1)
@discord.ui.button(label="⬅️", style=discord.ButtonStyle.grey, row=1, custom_id="i_l")
async def left(self,     i, b): await self._move(i, -1,  0)
@discord.ui.button(label="☑️", style=discord.ButtonStyle.grey, row=1, custom_id="i_c")
async def check(self,    i, b): await self._move(i,  0,  0)
@discord.ui.button(label="➡️", style=discord.ButtonStyle.grey, row=1, custom_id="i_r")
async def right(self,    i, b): await self._move(i,  1,  0)
@discord.ui.button(label="↙️", style=discord.ButtonStyle.grey, row=2, custom_id="i_ld")
async def leftdown(self, i, b): await self._move(i, -1,  1)
@discord.ui.button(label="⬇️", style=discord.ButtonStyle.grey, row=2, custom_id="i_d")
async def down(self,     i, b): await self._move(i,  0,  1)
@discord.ui.button(label="↘️", style=discord.ButtonStyle.grey, row=2, custom_id="i_rd")
async def rightdown(self,i, b): await self._move(i,  1,  1)
```

# ================================================================

# ショップ内部 View

# ================================================================

class ShopInteriorView(InteriorView):
def **init**(self, uid, return_floor, return_x, return_y):
super().**init**(uid, SHOP_GRID, SHOP_START[0], SHOP_START[1],
return_floor, return_x, return_y, "🏪 ショップ", 0x8B4513)

```
async def _on_step(self, cell, i=None):
    if cell == I_COUNTER:
        sv = ShopPurchaseView(self.uid, self)
        map_file = i_render_pillow(self.grid, self.pw, self.ph)
        await i.edit_original_response(embed=self._embed("🛒 何を買いますか？"), view=sv, attachments=[map_file])
        return None
    return ""

async def _move(self, i, dx, dy):
    await i.response.defer()
    nx, ny = self.pw + dx, self.ph + dy
    cell = self.grid.get((nx, ny), I_WALL)
    if cell == I_WALL:
        map_file = i_render_pillow(self.grid, self.pw, self.ph)
        await i.edit_original_response(embed=self._embed("🔲 壁！進めない"), view=self, attachments=[map_file])
        return
    if cell == I_EXIT:
        mv = DungeonMainView(self.uid, self.return_floor, self.return_x, self.return_y)
        map_file = d_render_pillow(self.uid, self.return_floor, self.return_x, self.return_y)
        await i.edit_original_response(embed=mv._embed("ショップを出た"), view=mv, attachments=[map_file])
        return
    self.pw, self.ph = nx, ny
    msg = await self._on_step(cell, i)
    if msg is not None:
        map_file = i_render_pillow(self.grid, self.pw, self.ph)
        await i.edit_original_response(embed=self._embed(msg), view=self, attachments=[map_file])
```

# ================================================================

# ショップ購入 View

# ================================================================

class ShopPurchaseView(discord.ui.View):
def **init**(self, uid, shop_view):
super().**init**(timeout=60)
self.uid = uid; self.shop_view = shop_view

```
def _embed(self, msg=""):
    u = user_cache.get(self.uid, {})
    em = discord.Embed(title="🛒 購入", color=0x8B4513)
    em.set_image(url="attachment://map.png")
    em.add_field(name="所持コイン", value=f"**{u.get('coins',0):,}** 枚", inline=False)
    em.add_field(name="商品一覧", value=(
        "1️⃣ HP回復薬（小） — **50コイン** HP+30\n"
        "2️⃣ HP回復薬（大） — **150コイン** HP+80\n"
        "3️⃣ レアパン — **200コイン** +1個\n"
        "4️⃣ 宝箱 — **300コイン** +1個"
    ), inline=False)
    if msg: em.add_field(name="ログ", value=msg, inline=False)
    return em

@discord.ui.button(label="HP+30 (50c)",  style=discord.ButtonStyle.green,  row=0)
async def b1(self, i, b): await self._buy(i, 50,  "hp_s")
@discord.ui.button(label="HP+80 (150c)", style=discord.ButtonStyle.green,  row=0)
async def b2(self, i, b): await self._buy(i, 150, "hp_l")
@discord.ui.button(label="パン (200c)",  style=discord.ButtonStyle.blurple, row=1)
async def b3(self, i, b): await self._buy(i, 200, "bread")
@discord.ui.button(label="宝箱+1 (300c)",style=discord.ButtonStyle.blurple, row=1)
async def b4(self, i, b): await self._buy(i, 300, "box")

@discord.ui.button(label="⬅ 戻る", style=discord.ButtonStyle.grey, row=2)
async def back(self, i, b):
    await i.response.defer()
    map_file = i_render_pillow(self.shop_view.grid, self.shop_view.pw, self.shop_view.ph)
    await i.edit_original_response(embed=self.shop_view._embed(), view=self.shop_view, attachments=[map_file])

async def _buy(self, i, price, item):
    await i.response.defer()
    cog = i.client.cogs.get("DungeonCog")
    u = user_cache.get(self.uid, {}); p = d_get_player(self.uid)
    map_file = i_render_pillow(self.shop_view.grid, self.shop_view.pw, self.shop_view.ph)
    if u.get("coins", 0) < price:
        await i.edit_original_response(embed=self._embed("❌ コインが足りません"), view=self, attachments=[map_file])
        return
    u["coins"] -= price
    if item == "hp_s":
        p["hp"] = min(p["max_hp"], p["hp"] + 30)
        msg = f"✅ HP +30（{p['hp']}/{p['max_hp']}）"
    elif item == "hp_l":
        p["hp"] = min(p["max_hp"], p["hp"] + 80)
        msg = f"✅ HP +80（{p['hp']}/{p['max_hp']}）"
    elif item == "bread":
        u["bread_count"] = u.get("bread_count", 0) + 1; msg = "✅ レアパン +1個"
    else:
        u["boxes"] = u.get("boxes", 0) + 1; msg = "✅ 宝箱 +1個"
    await cog.save_user(self.uid)
    await i.edit_original_response(embed=self._embed(msg), view=self, attachments=[map_file])
```

# ================================================================

# 拠点内部 View

# ================================================================

class BaseInteriorView(InteriorView):
def **init**(self, uid, return_floor, return_x, return_y, is_own=True):
super().**init**(uid, BASE_GRID, BASE_START[0], BASE_START[1],
return_floor, return_x, return_y, "🏠 拠点", 0x4a4a8a)
self.is_own = is_own
if self.children:
self.children[-1].disabled = not is_own

```
async def _on_step(self, cell, i=None):
    if cell == I_REST:
        p = d_get_player(self.uid); old = p["hp"]; p["hp"] = p["max_hp"]
        asyncio.create_task(dg_save_player(self.uid))
        return f"休憩しました。HPが全回復しました ({old} → {p['hp']})"
    if cell == I_BAKERY:
        u = user_cache.get(self.uid, {})
        c = random.randint(10, 50); u["coins"] = u.get("coins", 0) + c
        if random.random() < 0.2:
            u["bread_count"] = u.get("bread_count", 0) + 1
            return f"パンが焼けました！ (+1個) / {c}コイン獲得"
        return f"パンをこねています... / {c}コイン獲得"
    if cell == I_STORAGE:
        u = user_cache.get(self.uid, {})
        info = f"コイン:{u.get('coins',0):,} / パン:{u.get('bread_count',0)} / チップ:{u.get('chips',0):,}"
        return f"データを確認しました。\n{info}"
    return ""

@discord.ui.button(label="拠点から出る", style=discord.ButtonStyle.grey, row=4)
async def leave(self, i, b):
    await i.response.defer()
    mv = DungeonMainView(self.uid, self.return_floor, self.return_x, self.return_y)
    map_file = d_render_pillow(self.uid, self.return_floor, self.return_x, self.return_y)
    await i.edit_original_response(embed=mv._embed("拠点を後にしました"), view=mv, attachments=[map_file])

@discord.ui.button(label="拠点を解体", style=discord.ButtonStyle.red, row=3)
async def disband(self, i, b):
    await i.response.defer()
    if not self.is_own:
        map_file = i_render_pillow(self.grid, self.pw, self.ph)
        await i.edit_original_response(embed=self._embed("権限がありません"), view=self, attachments=[map_file])
        return
    own = dg_bases.get(self.uid)
    if own:
        of, ox, oy = own
        if dg_maps.get(of) and dg_maps[of][oy][ox] == D_BASE:
            dg_maps[of][oy][ox] = D_FLOOR
        del dg_bases[self.uid]
        asyncio.create_task(dg_save_base(self.uid))
        asyncio.create_task(dg_save_map(of))
    mv = DungeonMainView(self.uid, self.return_floor, self.return_x, self.return_y)
    map_file = d_render_pillow(self.uid, self.return_floor, self.return_x, self.return_y)
    await i.edit_original_response(embed=mv._embed("拠点を解体しました"), view=mv, attachments=[map_file])
```

# ================================================================

# 階段 View

# ================================================================

class DungeonStairsView(discord.ui.View):
def **init**(self, uid, floor, x, y):
super().**init**(timeout=60)
self.uid = uid; self.floor = floor; self.x = x; self.y = y
self.children[0].disabled = (floor <= 1)
self.children[1].disabled = (floor >= D_FLOORS)

```
@discord.ui.button(label="上の階へ", style=discord.ButtonStyle.blurple, row=0)
async def go_up(self, i, b):
    await i.response.defer()
    self.floor -= 1; d_ensure_map(self.floor)
    p = d_get_player(self.uid); sx, sy = dg_starts.get(self.floor, (1, 1))
    self.x, self.y = sx, sy; p["floor"] = self.floor; p["x"], p["y"] = sx, sy
    asyncio.create_task(dg_save_player(self.uid))
    mv = DungeonMainView(self.uid, self.floor, self.x, self.y)
    await i.edit_original_response(
        embed=mv._embed(f"🔺 {self.floor}階へ戻った！"),
        view=mv, attachments=[d_render_pillow(self.uid, self.floor, self.x, self.y)]
    )

@discord.ui.button(label="下の階へ", style=discord.ButtonStyle.green, row=0)
async def go_down(self, i, b):
    await i.response.defer()
    self.floor += 1; d_ensure_map(self.floor)
    p = d_get_player(self.uid); sx, sy = dg_starts.get(self.floor, (1, 1))
    self.x, self.y = sx, sy; p["floor"] = self.floor; p["x"], p["y"] = sx, sy
    st = player_stats.get(self.uid, {})
    if self.floor > st.get("total_dungeon_floor", 0):
        st["total_dungeon_floor"] = self.floor
    asyncio.create_task(dg_save_player(self.uid))
    mv = DungeonMainView(self.uid, self.floor, self.x, self.y)
    await i.edit_original_response(
        embed=mv._embed(f"🔻 {self.floor}階へ進んだ！"),
        view=mv, attachments=[d_render_pillow(self.uid, self.floor, self.x, self.y)]
    )

@discord.ui.button(label="キャンセル", style=discord.ButtonStyle.grey, row=0)
async def cancel(self, i, b):
    await i.response.defer()
    mv = DungeonMainView(self.uid, self.floor, self.x, self.y)
    await i.edit_original_response(
        embed=mv._embed(), view=mv,
        attachments=[d_render_pillow(self.uid, self.floor, self.x, self.y)]
    )
```

# ================================================================

# メインマップ View

# ================================================================

class DungeonMainView(discord.ui.View):
def **init**(self, uid, floor, x, y):
super().**init**(timeout=600)
self.uid = uid; self.floor = floor; self.x = x; self.y = y

```
def _embed(self, msg=""):
    bname, _, _, _, bcolor = d_get_biome(self.floor)
    p = d_get_player(self.uid)
    em = discord.Embed(
        title=f"🏰 {bname} {self.floor}階 ({self.x},{self.y})",
        color=bcolor
    )
    em.set_image(url="attachment://map.png")
    em.add_field(name="HP",
        value=f"`{d_hpbar(p['hp'],p['max_hp'])}` {p['hp']}/{p['max_hp']}", inline=True)
    if msg and msg.strip():
        em.add_field(name="ログ", value=msg, inline=False)
    return em

async def _move(self, i, dx, dy):
    await i.response.defer()
    nx, ny = self.x + dx, self.y + dy
    ct = d_get_cell(self.floor, nx, ny)
    cog = i.client.cogs.get("DungeonCog")

    if ct == D_WALL:
        await i.edit_original_response(
            embed=self._embed("🔲 壁！進めない"),
            attachments=[d_render_pillow(self.uid, self.floor, self.x, self.y)],
            view=self
        )
        return

    self.x, self.y = nx, ny
    p = d_get_player(self.uid); p["floor"] = self.floor; p["x"], p["y"] = self.x, self.y

    # 探索記録
    if self.uid not in Dg: Dg[self.uid] = {}
    if self.floor not in Dg[self.uid]: Dg[self.uid][self.floor] = set()
    Dg[self.uid][self.floor].add((self.x, self.y))
    try:
        supabase.table("user_exploration").upsert({
            "uid": self.uid, "floor": self.floor,
            "explored_coords": [list(c) for c in Dg[self.uid][self.floor]]
        }).execute()
    except Exception:
        pass

    msg = ""

    if ct == D_STAIRS:
        sv = DungeonStairsView(self.uid, self.floor, self.x, self.y)
        await i.edit_original_response(
            embed=self._embed("🔺 階段がある。どうする？"),
            attachments=[d_render_pillow(self.uid, self.floor, self.x, self.y)],
            view=sv
        )
        return

    elif ct == D_CHEST:
        msg = d_open_chest(self.uid)
        d_consume(self.floor, self.x, self.y)
        asyncio.create_task(cog.save_user(self.uid))
        asyncio.create_task(dg_save_map(self.floor))

    elif ct == D_TRAP:
        msg = d_trigger_trap(self.uid)
        d_consume(self.floor, self.x, self.y)
        asyncio.create_task(cog.save_user(self.uid))
        asyncio.create_task(dg_save_map(self.floor))

    elif ct == D_SHOP:
        sv = ShopInteriorView(self.uid, self.floor, self.x, self.y)
        await i.edit_original_response(
            embed=sv._embed("🏪 ショップに入った"),
            attachments=[i_render_pillow(SHOP_GRID, SHOP_START[0], SHOP_START[1])],
            view=sv
        )
        return

    elif ct == D_BASE:
        is_own = (dg_bases.get(self.uid) == (self.floor, self.x, self.y))
        bv = BaseInteriorView(self.uid, self.floor, self.x, self.y, is_own=is_own)
        label = "🏠 自分の拠点に入った" if is_own else "🏠 他の人の拠点に入った"
        await i.edit_original_response(
            embed=bv._embed(label),
            attachments=[i_render_pillow(BASE_GRID, BASE_START[0], BASE_START[1])],
            view=bv
        )
        return

    elif ct == D_MINE:
        mv2 = DungeonMineView(self.uid, self.floor, self.x, self.y)
        await i.edit_original_response(
            embed=mv2._embed("⛏ 鉱山を発見！"),
            attachments=[d_render_pillow(self.uid, self.floor, self.x, self.y)],
            view=mv2
        )
        return

    else:
        bname, _, _, _, _ = d_get_biome(self.floor)
        rate = D_ENCOUNTER_RATES.get(bname, 0.10)
        if random.random() < rate:
            enemy = d_make_enemy(self.floor)
            cv = DungeonCombatView(self.uid, self.floor, self.x, self.y, enemy)
            await i.edit_original_response(
                embed=cv._embed(),
                attachments=[d_render_pillow(self.uid, self.floor, self.x, self.y)],
                view=cv
            )
            return

    if p["hp"] <= 0:
        p["hp"] = p["max_hp"]; p["floor"] = 1
        start_pos = dg_starts.get(1, (1, 1)); p["x"], p["y"] = start_pos
        self.floor = 1; self.x, self.y = p["x"], p["y"]
        msg += "\n力尽きた… スタート地点へ戻された"

    asyncio.create_task(dg_save_player(self.uid))
    await i.edit_original_response(
        embed=self._embed(msg),
        attachments=[d_render_pillow(self.uid, self.floor, self.x, self.y)],
        view=self
    )

@discord.ui.button(label="↖️", style=discord.ButtonStyle.grey, row=0, custom_id="dg_lu")
async def leftup(self,   i, b): await self._move(i, -1, -1)
@discord.ui.button(label="⬆️", style=discord.ButtonStyle.grey, row=0, custom_id="dg_u")
async def up(self,       i, b): await self._move(i,  0, -1)
@discord.ui.button(label="↗️", style=discord.ButtonStyle.grey, row=0, custom_id="dg_ru")
async def rightup(self,  i, b): await self._move(i,  1, -1)
@discord.ui.button(label="⬅️", style=discord.ButtonStyle.grey, row=1, custom_id="dg_l")
async def left(self,     i, b): await self._move(i, -1,  0)
@discord.ui.button(label="☑️", style=discord.ButtonStyle.grey, row=1, custom_id="dg_c")
async def check(self,    i, b): await self._move(i,  0,  0)
@discord.ui.button(label="➡️", style=discord.ButtonStyle.grey, row=1, custom_id="dg_r")
async def right(self,    i, b): await self._move(i,  1,  0)
@discord.ui.button(label="↙️", style=discord.ButtonStyle.grey, row=2, custom_id="dg_ld")
async def leftdown(self, i, b): await self._move(i, -1,  1)
@discord.ui.button(label="⬇️", style=discord.ButtonStyle.grey, row=2, custom_id="dg_d")
async def down(self,     i, b): await self._move(i,  0,  1)
@discord.ui.button(label="↘️", style=discord.ButtonStyle.grey, row=2, custom_id="dg_rd")
async def rightdown(self,i, b): await self._move(i,  1,  1)

@discord.ui.button(label="STATUS", style=discord.ButtonStyle.green, row=3, custom_id="dg_status")
async def status(self, i, b):
    await i.response.defer()
    sv = DungeonStatusView(self.uid, self.floor, self.x, self.y)
    await i.edit_original_response(embed=await sv._embed(), attachments=[], view=sv)
```

# ================================================================

# Cog 本体

# ================================================================

class DungeonCog(commands.Cog, name="DungeonCog"):
def **init**(self, bot):
self.bot = bot

```
async def cog_load(self):
    load_all_assets()
    print("✅ DungeonCog: アセット読み込み完了")

# ----------------------------------------------------------
#  main.py の save_user / add_xp を Cog 内で呼べるラッパー
# ----------------------------------------------------------
async def save_user(self, uid: str):
    """main.py の save_user 相当（Cog 内部用）"""
    if uid not in user_cache: return
    try:
        data = dict(user_cache[uid]); data["user_id"] = uid
        data.pop("rare_bread", None); data.pop("rare_avg", None)
        import json as _json
        data["items"] = _json.dumps(data.get("items", {}), ensure_ascii=False)
        supabase.table("user_data").upsert(data).execute()
    except Exception as e:
        print(f"save_user失敗 {uid}: {e}")

def add_xp_local(self, uid: str, xp: int):
    """XP加算・レベルアップ判定（main.py の add_xp 相当）"""
    u = user_cache.get(uid, {}); u["xp"] = u.get("xp", 0) + xp
    leveled = False; levels_gained = []
    def xp_needed(lv): return lv * 100
    while u["xp"] >= xp_needed(u.get("level", 0) + 1):
        u["xp"] -= xp_needed(u.get("level", 0) + 1)
        u["level"] = u.get("level", 0) + 1
        leveled = True; levels_gained.append(u["level"])
    return leveled, []

# ----------------------------------------------------------
#  スラッシュコマンド
# ----------------------------------------------------------
@app_commands.command(name="dungeon", description="ダンジョンに入ります")
async def dungeon_enter(self, interaction: Interaction):
    await interaction.response.defer()
    uid = str(interaction.user.id)

    # ユーザーデータ読み込み（main.py の load_user 相当）
    if uid not in user_cache:
        try:
            res = supabase.table("user_data").select("*").eq("user_id", uid).execute()
            if res.data:
                row = res.data[0]
                row.setdefault("rare_bread", 0); row.setdefault("rare_avg", 0)
                if not isinstance(row.get("items"), dict):
                    try: row["items"] = json.loads(row["items"] or "{}")
                    except: row["items"] = {}
                user_cache[uid] = row
            else:
                user_cache[uid] = {
                    "user_id": uid, "bread_count": 0, "bread_prob": 0.1,
                    "login_available": 1, "coins": 0, "chips": 0,
                    "xp": 0, "level": 0, "boxes": 0, "sake": 0,
                    "hesokuri": 0, "rare_bread": 0, "rare_avg": 0, "items": {}
                }
        except Exception as e:
            print(f"load_user失敗: {e}")
            user_cache[uid] = {
                "user_id": uid, "bread_count": 0, "bread_prob": 0.1,
                "login_available": 1, "coins": 0, "chips": 0,
                "xp": 0, "level": 0, "boxes": 0, "sake": 0,
                "hesokuri": 0, "rare_bread": 0, "rare_avg": 0, "items": {}
            }

    p = d_get_player(uid)
    floor, x, y = p["floor"], p["x"], p["y"]
    d_ensure_map(floor)

    sx, sy = dg_starts.get(floor, (1, 1))
    if x == 1 and y == 1:
        x, y = sx, sy; p["x"] = x; p["y"] = y
        asyncio.create_task(dg_save_player(uid))

    mv = DungeonMainView(uid, floor, x, y)
    map_url = await d_render_image(self.bot, uid, floor, x, y)
    em = discord.Embed(
        title=f"🏰 ダンジョンへようこそ！ {floor}階",
        color=d_get_biome(floor)[4]
    )
    if map_url:
        em.set_image(url=map_url)
    em.add_field(name="HP",
        value=f"`{d_hpbar(p['hp'],p['max_hp'])}` {p['hp']}/{p['max_hp']}", inline=True)
    await interaction.followup.send(embed=em, view=mv)

@app_commands.command(name="dungeon_reset", description="ダンジョンマップをリセットします（モデレーターのみ）")
async def dungeon_reset(self, interaction: Interaction):
    if str(interaction.user.id) not in moderators:
        await interaction.response.send_message(
            embed=embed_error("権限エラー", "権限がありません"), ephemeral=True
        )
        return
    await interaction.response.defer()
    dg_maps.clear(); dg_players.clear(); dg_starts.clear()
    dg_used.clear(); dg_bases.clear()
    try:
        supabase.table("dungeon_maps").delete().neq("floor", 0).execute()
        supabase.table("dungeon_players").delete().neq("user_id", "").execute()
        supabase.table("dungeon_bases").delete().neq("user_id", "").execute()
    except Exception as e:
        print(f"dungeon_reset DB削除失敗: {e}")
    for fl in range(1, D_FLOORS+1):
        d_ensure_map(fl)
        asyncio.create_task(dg_save_map(fl))
    await interaction.followup.send(
        embed=embed_success("リセット完了", "マップを再生成しました！")
    )

# ----------------------------------------------------------
#  月次リセットタスク
# ----------------------------------------------------------
@tasks.loop(hours=1)
async def dungeon_task(self):
    now = datetime.datetime.now(JST)
    if now.day == 1 and now.hour == 0:
        dg_maps.clear(); dg_players.clear(); dg_starts.clear()
        dg_used.clear(); dg_bases.clear()
        try:
            supabase.table("dungeon_maps").delete().neq("floor", 0).execute()
            supabase.table("dungeon_players").delete().neq("user_id", "").execute()
            supabase.table("dungeon_bases").delete().neq("user_id", "").execute()
        except Exception as e:
            print(f"dungeon月次リセットDB削除失敗: {e}")
        for fl in range(1, D_FLOORS+1):
            d_ensure_map(fl)
            asyncio.create_task(dg_save_map(fl))
        print("ダンジョン月次リセット完了")

@dungeon_task.before_loop
async def before_dungeon_task(self):
    await self.bot.wait_until_ready()

async def cog_unload(self):
    self.dungeon_task.cancel()
```

# ================================================================

# setup 関数（cogs ローダーが呼ぶ）

# ================================================================

async def setup(bot: commands.Bot):
cog = DungeonCog(bot)
await bot.add_cog(cog)
# タスク開始
if not cog.dungeon_task.is_running():
cog.dungeon_task.start()
print("✅ DungeonCog をロードしました")