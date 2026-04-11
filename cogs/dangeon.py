# -*- coding: utf-8 -*-
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
#  定数と設定 (V2.0 統合版)
# ============================================================
JST = ZoneInfo("Asia/Tokyo")
MAP_SEED = os.environ.get("MAP_SEED", "DEFAULT_DUNGEON_SEED_2024")
D_VIEW_R = 5
TILE_SIZE = 32

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

# バイオーム定義
D_BIOMES_CONFIG = [
    (range(1,  10),  "cave",     "洞窟",     0x5C4033),
    (range(10,  20),  "forest",   "森",       0x2D5A1B),
    (range(20,  30),  "ice",      "氷雪地帯", 0x5B9BD5),
    (range(30, 41),  "desert",   "砂漠地帯", 0xC8600A),
]

# エンカウント率
D_ENCOUNTER_RATES = {
    "cave":     0.05,
    "forest":   0.20,
    "ice":      0.07,
    "desert":   0.13,
}

# 敵データベース (旧コードより継承)
D_ENEMY_NAMES = {
    "cave":     ["コウモリ","ゴブリン","岩石スライム"],
    "forest":   ["オオカミ","毒キノコ","トレント"],
    "ice":      ["雪男","アイスゴーレム","白熊"],
    "desert":   ["サソリ","砂蛇","炎トカゲ"],
}
D_SUPERENEMY_NAMES = {
    "cave":     ["セミオートキラーマシン"],
    "forest":   ["邪蛇"],
    "ice":      ["雪女"],
    "desert":   ["鬼"],
}
D_BOSS_NAMES = {
    "cave":     ["ドラゴン"],
    "forest":   ["ヌシ","ぱすた"],
    "ice":      ["凍ったコッペパン"],
    "desert":   ["炎龍"],
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
#  キャッシュ管理
# ============================================================
dg_chunks_cache = {}  # {(floor, x, y): tile_type}
dg_players_cache = {} # {user_id: stats_dict}
_ASSET_CACHE = {}

# ============================================================
#  コアロジック: マップ生成 & バイオーム
# ============================================================

def get_biome_info(floor, x, y):
    """フロアと座標からバイオームを決定"""
    # 基本バイオーム (フロア依存)
    base_id = "cave"
    base_name = "洞窟"
    base_color = 0x5C4033
    for r, b_id, b_name, b_color in D_BIOMES_CONFIG:
        if floor in r:
            base_id, base_name, base_color = b_id, b_name, b_color
            break
    
    # 座標による局所的な変化 (300x300単位)
    bx, by = x // 300, y // 300
    seed_str = f"biome_{MAP_SEED}_{bx}_{by}"
    seed_hash = int(hashlib.md5(seed_str.encode()).hexdigest(), 16)
    random.seed(seed_hash)
    
    # 20%の確率で別のバイオームが混ざるなどの拡張も可能だが、一旦シンプルに
    return base_id, base_name, base_color

def get_deterministic_tile(floor, x, y):
    """座標とシード値に基づき、決定論的にタイルを決定する。"""
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
#  データベース連携
# ============================================================

async def db_load_chunks(supabase):
    global dg_chunks_cache
    try:
        res = supabase.table("dungeon_chunks").select("*").execute()
        dg_chunks_cache = { (r["floor"], r["x"], r["y"]): r["tile_type"] for r in res.data }
    except Exception as e:
        print(f"[DungeonV2] Load chunks failed: {e}")

async def db_update_chunk(supabase, floor, x, y, tile_type):
    dg_chunks_cache[(floor, x, y)] = tile_type
    try:
        supabase.table("dungeon_chunks").upsert({"floor": floor, "x": x, "y": y, "tile_type": tile_type}).execute()
    except Exception as e:
        print(f"[DungeonV2] Update chunk failed: {e}")

async def db_load_player(supabase, user_id):
    if user_id in dg_players_cache: return dg_players_cache[user_id]
    try:
        res = supabase.table("dungeon_players").select("*").eq("user_id", user_id).execute()
        if res.data:
            dg_players_cache[user_id] = res.data[0]
            return res.data[0]
    except Exception as e:
        print(f"[DungeonV2] Load player failed: {e}")
    
    default_stats = {"user_id": user_id, "floor": 1, "x": 0, "y": 0, "hp": 100, "max_hp": 100, "atk": 10, "def_": 3, "spd": 10, "crit": 0.05, "exp": 0}
    dg_players_cache[user_id] = default_stats
    return default_stats

async def db_save_player(supabase, user_id):
    if user_id not in dg_players_cache: return
    try:
        supabase.table("dungeon_players").upsert(dg_players_cache[user_id]).execute()
    except Exception as e:
        print(f"[DungeonV2] Save player failed: {e}")

# ============================================================
#  レンダリングエンジン (Pillow)
# ============================================================

def load_asset(asset_path):
    if asset_path in _ASSET_CACHE: return _ASSET_CACHE[asset_path]
    full_path = os.path.join("Assets", asset_path)
    if os.path.exists(full_path):
        img = Image.open(full_path).convert("RGBA").resize((TILE_SIZE, TILE_SIZE))
        _ASSET_CACHE[asset_path] = img
        return img
    return None

def render_dungeon_view(floor, px, py, radius=D_VIEW_R):
    size = (radius * 2 + 1) * TILE_SIZE
    img = Image.new("RGBA", (size, size), (0, 0, 0, 255))
    draw = ImageDraw.Draw(img)
    
    for dy in range(-radius, radius + 1):
        for dx in range(-radius, radius + 1):
            tx, ty = px + dx, py + dy
            tile_type = get_deterministic_tile(floor, tx, ty)
            biome_id, _, _ = get_biome_info(floor, tx, ty)
            
            draw_x, draw_y = (dx + radius) * TILE_SIZE, (dy + radius) * TILE_SIZE
            
            asset_map = {
                D_WALL: "rock.PNG" if biome_id == "cave" else ("mori_kabe.png" if biome_id == "forest" else "Y_k.png"),
                D_FLOOR: "jimen.png" if biome_id == "cave" else ("mori_yuka.png" if biome_id == "forest" else "Y_y.png"),
                D_CHEST: "NOMAL.PNG", D_TRAP: "jimen.png", D_STAIRS: "REIBAI.PNG", D_MINE: "AGO.PNG"
            }
            
            asset_img = load_asset(asset_map.get(tile_type, "jimen.png"))
            if asset_img: img.paste(asset_img, (draw_x, draw_y), asset_img)
            
            if dx == 0 and dy == 0:
                p_img = load_asset("NOMAL.PNG")
                if p_img: img.paste(p_img, (draw_x, draw_y), p_img)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return discord.File(fp=buf, filename="map.png")

# ============================================================
#  戦闘ロジック & ヘルパー
# ============================================================

def d_hpbar(hp, max_hp, width=10):
    filled = int(width * hp / max(max_hp, 1))
    return "█" * filled + "░" * (width - filled)

def make_enemy(floor, biome_id):
    base_hp, base_atk, base_def = 15 + floor * 8, 4 + floor * 2, 1 + floor
    r = random.random()
    if r < 0.01: etype, names = "boss", D_BOSS_NAMES
    elif r < 0.11: etype, names = "elite", D_SUPERENEMY_NAMES
    else: etype, names = "normal", D_ENEMY_NAMES
    
    name = random.choice(names.get(biome_id, ["謎の敵"]))
    clean_key = name.split()[0].replace("👾", "").strip()
    m = ENEMY_STATS_MASTER.get(clean_key, ENEMY_STATS_MASTER["default"])
    
    mul_hp = 15.0 if etype=="boss" else (4.0 if etype=="elite" else 1.0)
    mul_atk = 4.0 if etype=="boss" else (2.5 if etype=="elite" else 1.0)
    
    hp = int((base_hp + random.randint(-3, 3)) * m["hp_m"] * mul_hp)
    return {
        "name": name, "type": etype, "hp": hp, "max_hp": hp,
        "atk": int((base_atk + random.randint(-1, 1)) * m["atk_m"] * mul_atk),
        "def_": int(base_def * m["def_m"]), "spd": m["spd"], "crit": m["crit"],
        "reward_coins": int(random.randint(20, 80) * floor * m["coin_m"] * mul_atk),
        "reward_xp": int(random.randint(10, 30) * floor * m["xp_m"] * mul_atk),
        "reward_box": m["boxes"] if etype=="normal" else max(1, m["boxes"])
    }

# ============================================================
#  Views
# ============================================================

class DungeonStatusView(View):
    def __init__(self, uid):
        super().__init__(timeout=60)
        self.uid = uid
    def _embed(self):
        p = dg_players_cache[self.uid]
        em = discord.Embed(title="ステータス", color=0xFFFFFF)
        em.add_field(name="HP", value=f"{d_hpbar(p['hp'], p['max_hp'])} {p['hp']}/{p['max_hp']}", inline=False)
        em.add_field(name="能力", value=f"ATK:{p['atk']} DEF:{p['def_']} SPD:{p['spd']} CRIT:{int(p['crit']*100)}%", inline=False)
        return em

class DungeonCombatView(View):
    def __init__(self, bot, uid, enemy, supabase):
        super().__init__(timeout=300)
        self.bot, self.uid, self.enemy, self.supabase = bot, uid, enemy, supabase
        self.log = []
        self.defending = False

    def _embed(self):
        p, e = dg_players_cache[self.uid], self.enemy
        em = discord.Embed(title=f"{e['name']}が現れた！", color=0xFF0000)
        em.add_field(name="あなた", value=f"HP: {p['hp']}/{p['max_hp']}\n{d_hpbar(p['hp'], p['max_hp'])}", inline=True)
        em.add_field(name=e['name'], value=f"HP: {e['hp']}/{e['max_hp']}\n{d_hpbar(e['hp'], e['max_hp'])}", inline=True)
        if self.log: em.add_field(name="ログ", value="\n".join(self.log[-5:]), inline=False)
        em.set_image(url="attachment://map.png")
        return em

    async def _finish(self, i, win=True):
        p = dg_players_cache[self.uid]
        if win:
            msg = f"勝利！ +{self.enemy['reward_coins']}G +{self.enemy['reward_xp']}XP"
            self.stop()
            await db_save_player(self.supabase, self.uid)
            mv = DungeonMainView(self.bot, self.uid, self.supabase)
            await i.edit_original_response(embed=mv._embed(msg), view=mv, attachments=[render_dungeon_view(p['floor'], p['x'], p['y'])])
        else:
            p['hp'], p['floor'], p['x'], p['y'] = p['max_hp'], 1, 0, 0
            await db_save_player(self.supabase, self.uid)
            self.stop()
            mv = DungeonMainView(self.bot, self.uid, self.supabase)
            await i.edit_original_response(embed=mv._embed("敗北した..."), view=mv, attachments=[render_dungeon_view(1, 0, 0)])

    @discord.ui.button(label="攻撃", style=discord.ButtonStyle.red)
    async def attack(self, i, b):
        p, e = dg_players_cache[self.uid], self.enemy
        # プレイヤー攻撃
        dmg = max(1, p['atk'] - e['def_'] + random.randint(-2, 2))
        e['hp'] = max(0, e['hp'] - dmg)
        self.log.append(f"あなたの攻撃！ {dmg}ダメージ")
        if e['hp'] <= 0: return await self._finish(i, True)
        # 敵攻撃
        edmg = max(1, e['atk'] - p['def_'] + random.randint(-2, 2))
        p['hp'] = max(0, p['hp'] - edmg)
        self.log.append(f"{e['name']}の攻撃！ {edmg}ダメージ")
        if p['hp'] <= 0: return await self._finish(i, False)
        await i.response.edit_message(embed=self._embed())

class DungeonMainView(View):
    def __init__(self, bot, uid, supabase):
        super().__init__(timeout=600)
        self.bot, self.uid, self.supabase = bot, uid, supabase

    def _embed(self, msg=""):
        p = dg_players_cache[self.uid]
        bid, bname, bcolor = get_biome_info(p['floor'], p['x'], p['y'])
        em = discord.Embed(title=f"Floor {p['floor']} - {bname}", color=bcolor, description=msg)
        em.add_field(name="座標", value=f"({p['x']}, {p['y']})", inline=True)
        em.add_field(name="HP", value=f"{p['hp']}/{p['max_hp']}", inline=True)
        em.set_image(url="attachment://map.png")
        return em

    async def _move(self, i, dx, dy):
        p = dg_players_cache[self.uid]
        nx, ny = p['x'] + dx, p['y'] + dy
        tile = get_deterministic_tile(p['floor'], nx, ny)
        
        if tile == D_WALL:
            return await i.response.edit_message(embed=self._embed("壁があって進めません"))
        
        p['x'], p['y'] = nx, ny
        msg = ""
        
        if tile == D_CHEST:
            g = random.randint(50, 200)
            msg = f"宝箱！ {g}G獲得"
            await db_update_chunk(self.supabase, p['floor'], nx, ny, D_FLOOR)
        elif tile == D_TRAP:
            d = random.randint(10, 20)
            p['hp'] = max(0, p['hp'] - d)
            msg = f"罠！ {d}ダメージ"
            await db_update_chunk(self.supabase, p['floor'], nx, ny, D_FLOOR)
        elif tile == D_STAIRS:
            p['floor'] += 1
            p['x'], p['y'] = 0, 0
            msg = f"階段を登って Floor {p['floor']} へ！"
        
        # エンカウント
        bid, _, _ = get_biome_info(p['floor'], p['x'], p['y'])
        if random.random() < D_ENCOUNTER_RATES.get(bid, 0.1) and tile == D_FLOOR:
            enemy = make_enemy(p['floor'], bid)
            cv = DungeonCombatView(self.bot, self.uid, enemy, self.supabase)
            return await i.response.edit_message(embed=cv._embed(), view=cv, attachments=[render_dungeon_view(p['floor'], p['x'], p['y'])])

        await db_save_player(self.supabase, self.uid)
        await i.response.edit_message(embed=self._embed(msg), attachments=[render_dungeon_view(p['floor'], p['x'], p['y'])])

    @discord.ui.button(label="⬆️", row=0)
    async def up(self, i, b): await self._move(i, 0, -1)
    @discord.ui.button(label="⬅️", row=1)
    async def left(self, i, b): await self._move(i, -1, 0)
    @discord.ui.button(label="⬇️", row=1)
    async def down(self, i, b): await self._move(i, 0, 1)
    @discord.ui.button(label="➡️", row=1)
    async def right(self, i, b): await self._move(i, 1, 0)
    @discord.ui.button(label="STATUS", style=discord.ButtonStyle.green, row=2)
    async def status(self, i, b):
        sv = DungeonStatusView(self.uid)
        await i.response.send_message(embed=sv._embed(), ephemeral=True)

# ============================================================
#  Cog クラス
# ============================================================

class DungeonCog(Cog):
    def __init__(self, bot):
        self.bot = bot
        self.supabase = getattr(bot, 'supabase', None)

    async def cog_load(self):
        if self.supabase: await db_load_chunks(self.supabase)
        self.dungeon_monthly_task.start()

    @app_commands.command(name="dungeon", description="ダンジョン探索 V2.0")
    async def dungeon(self, interaction: Interaction):
        await interaction.response.defer()
        uid = str(interaction.user.id)
        p = await db_load_player(self.supabase, uid)
        
        # BGM再生
        if interaction.user.voice:
            try:
                vc = await interaction.user.voice.channel.connect()
                vc.play(FFmpegPCMAudio("Assets/BGM.m4a"))
            except: pass

        view = DungeonMainView(self.bot, uid, self.supabase)
        await interaction.followup.send(embed=view._embed("探索開始！"), view=view, file=render_dungeon_view(p['floor'], p['x'], p['y']))

    @tasks.loop(time=datetime.time(hour=0, minute=0, tzinfo=JST))
    async def dungeon_monthly_task(self):
        if datetime.datetime.now(JST).day == 1:
            try:
                self.supabase.table("dungeon_chunks").delete().neq("floor", -1).execute()
                self.supabase.table("dungeon_players").update({"x": 0, "y": 0}).neq("floor", -1).execute()
                dg_chunks_cache.clear()
            except: pass

async def setup(bot):
    await bot.add_cog(DungeonCog(bot))
