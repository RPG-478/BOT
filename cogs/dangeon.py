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
#  定数と設定
# ============================================================
JST = ZoneInfo("Asia/Tokyo")
MAP_SEED = os.environ.get("MAP_SEED", "DEFAULT_DUNGEON_SEED_2024")
D_VIEW_R = 5
TILE_SIZE = 32

# タイルタイプ
D_WALL = "wall"
D_FLOOR = "floor"
D_CHEST = "chest"
D_TRAP = "trap"
D_STAIRS = "stairs"
D_BASE = "base"

# バイオーム設定
D_BIOMES = {
    "cave": {"name": "洞窟", "color": 0x5C4033},
    "forest": {"name": "森", "color": 0x2D5A1B},
    "ice": {"name": "氷雪", "color": 0x5B9BD5},
    "desert": {"name": "砂漠", "color": 0xC8600A},
}

# ============================================================
#  キャッシュ管理
# ============================================================
dg_chunks_cache = {}  # {(floor, x, y): tile_type}
dg_players_cache = {} # {user_id: stats_dict}
_ASSET_CACHE = {}

# ============================================================
#  コアロジック: マップ生成
# ============================================================

def get_deterministic_tile(floor, x, y):
    """
    座標とシード値に基づき、決定論的にタイルを決定する。
    """
    # 1. キャッシュ（差分データ）を優先
    if (floor, x, y) in dg_chunks_cache:
        return dg_chunks_cache[(floor, x, y)]

    # 2. シード値による計算
    seed_str = f"{MAP_SEED}_{floor}_{x}_{y}"
    seed_hash = int(hashlib.md5(seed_str.encode()).hexdigest(), 16)
    random.seed(seed_hash)
    
    roll = random.random()
    if roll < 0.001: return D_STAIRS
    if roll < 0.004: return D_CHEST
    if roll < 0.007: return D_TRAP
    if roll < 0.307: return D_WALL
    return D_FLOOR

def get_biome_at(x, y):
    """
    300x300グリッド単位でバイオームを決定する。
    """
    bx, by = x // 300, y // 300
    seed_str = f"biome_{MAP_SEED}_{bx}_{by}"
    seed_hash = int(hashlib.md5(seed_str.encode()).hexdigest(), 16)
    random.seed(seed_hash)
    
    biomes = list(D_BIOMES.keys())
    return biomes[random.randint(0, len(biomes) - 1)]

# ============================================================
#  データベース連携
# ============================================================

async def db_load_chunks(supabase):
    """dungeon_chunksテーブルから差分データをロード"""
    global dg_chunks_cache
    try:
        res = supabase.table("dungeon_chunks").select("*").execute()
        dg_chunks_cache = { (r["floor"], r["x"], r["y"]): r["tile_type"] for r in res.data }
        print(f"[DungeonV2] Loaded {len(dg_chunks_cache)} chunks from DB.")
    except Exception as e:
        print(f"[DungeonV2] Failed to load chunks: {e}")

async def db_update_chunk(supabase, floor, x, y, tile_type):
    """差分データをDBとキャッシュに保存"""
    dg_chunks_cache[(floor, x, y)] = tile_type
    try:
        supabase.table("dungeon_chunks").upsert({
            "floor": floor, "x": x, "y": y, "tile_type": tile_type
        }).execute()
    except Exception as e:
        print(f"[DungeonV2] Failed to update chunk: {e}")

async def db_load_player(supabase, user_id):
    """プレイヤーデータをDBから取得"""
    try:
        res = supabase.table("dungeon_players").select("*").eq("user_id", user_id).execute()
        if res.data:
            dg_players_cache[user_id] = res.data[0]
            return res.data[0]
    except Exception as e:
        print(f"[DungeonV2] Failed to load player {user_id}: {e}")
    
    # デフォルト値
    default_stats = {
        "user_id": user_id, "floor": 1, "x": 0, "y": 0,
        "hp": 100, "max_hp": 100, "atk": 10, "exp": 0
    }
    dg_players_cache[user_id] = default_stats
    return default_stats

async def db_save_player(supabase, user_id):
    """プレイヤーデータをDBに保存"""
    if user_id not in dg_players_cache: return
    try:
        supabase.table("dungeon_players").upsert(dg_players_cache[user_id]).execute()
    except Exception as e:
        print(f"[DungeonV2] Failed to save player {user_id}: {e}")

# ============================================================
#  レンダリングエンジン (Pillow)
# ============================================================

def load_asset(asset_path):
    """アセットをメモリにキャッシュしてロード"""
    if asset_path in _ASSET_CACHE:
        return _ASSET_CACHE[asset_path]
    
    full_path = os.path.join("Assets", asset_path)
    if os.path.exists(full_path):
        img = Image.open(full_path).convert("RGBA").resize((TILE_SIZE, TILE_SIZE))
        _ASSET_CACHE[asset_path] = img
        return img
    return None

def render_dungeon_view(floor, px, py, radius=D_VIEW_R):
    """プレイヤー中心の5x5マップ画像を生成"""
    size = (radius * 2 + 1) * TILE_SIZE
    img = Image.new("RGBA", (size, size), (0, 0, 0, 255))
    draw = ImageDraw.Draw(img)
    
    # 描画範囲をループ
    for dy in range(-radius, radius + 1):
        for dx in range(-radius, radius + 1):
            tx, ty = px + dx, py + dy
            tile_type = get_deterministic_tile(floor, tx, ty)
            biome_id = get_biome_at(tx, ty)
            biome_info = D_BIOMES[biome_id]
            
            # 描画座標
            draw_x = (dx + radius) * TILE_SIZE
            draw_y = (dy + radius) * TILE_SIZE
            
            # アセット決定
            asset_map = {
                D_WALL: "rock.PNG" if biome_id == "cave" else ("mori_kabe.png" if biome_id == "forest" else "Y_k.png"),
                D_FLOOR: "jimen.png" if biome_id == "cave" else ("mori_yuka.png" if biome_id == "forest" else "Y_y.png"),
                D_CHEST: "NOMAL.PNG", # 暫定
                D_TRAP: "jimen.png", # 罠は床に見えるように
                D_STAIRS: "REIBAI.PNG", # 暫定
            }
            
            asset_img = load_asset(asset_map.get(tile_type, "jimen.png"))
            if asset_img:
                img.paste(asset_img, (draw_x, draw_y), asset_img)
            else:
                # アセットがない場合のフォールバック（色塗り）
                color = biome_info["color"] if tile_type == D_FLOOR else (100, 100, 100)
                draw.rectangle([draw_x, draw_y, draw_x + TILE_SIZE, draw_y + TILE_SIZE], fill=color)

            # プレイヤー（中心）
            if dx == 0 and dy == 0:
                player_asset = load_asset("NOMAL.PNG") # プレイヤー画像
                if player_asset:
                    img.paste(player_asset, (draw_x, draw_y), player_asset)
                else:
                    draw.ellipse([draw_x+4, draw_y+4, draw_x+TILE_SIZE-4, draw_y+TILE_SIZE-4], fill=(0, 255, 0))

    # バイオーム名などのオーバーレイ
    # biome_name = D_BIOMES[get_biome_at(px, py)]["name"]
    # draw.text((5, 5), f"Biome: {biome_name}", fill=(255, 255, 255))

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return discord.File(fp=buf, filename="dungeon_view.png")

# ============================================================
#  Discord UI (Views)
# ============================================================

class DungeonMainView(View):
    def __init__(self, bot, user_id, supabase):
        super().__init__(timeout=300)
        self.bot = bot
        self.user_id = user_id
        self.supabase = supabase

    def create_embed(self, message=""):
        player = dg_players_cache[self.user_id]
        biome_id = get_biome_at(player["x"], player["y"])
        biome_name = D_BIOMES[biome_id]["name"]
        
        embed = discord.Embed(
            title=f"ダンジョン探索 - Floor {player['floor']}",
            description=f"**バイオーム:** {biome_name}\n**座標:** ({player['x']}, {player['y']})\n**HP:** {player['hp']}/{player['max_hp']}\n\n{message}",
            color=D_BIOMES[biome_id]["color"]
        )
        embed.set_image(url="attachment://dungeon_view.png")
        return embed

    async def move(self, interaction: Interaction, dx, dy):
        player = dg_players_cache[self.user_id]
        nx, ny = player["x"] + dx, player["y"] + dy
        
        tile = get_deterministic_tile(player["floor"], nx, ny)
        
        if tile == D_WALL:
            await interaction.response.edit_message(embed=self.create_embed("壁があって進めません！"))
            return

        # 座標更新
        player["x"], player["y"] = nx, ny
        message = ""

        # 特殊タイル処理
        if tile == D_CHEST:
            gold = random.randint(10, 100)
            message = f"宝箱を見つけた！ **{gold} G** を手に入れた！"
            await db_update_chunk(self.supabase, player["floor"], nx, ny, D_FLOOR)
        elif tile == D_TRAP:
            dmg = random.randint(5, 15)
            player["hp"] = max(0, player["hp"] - dmg)
            message = f"罠を踏んだ！ **{dmg} ダメージ** を受けた！"
            await db_update_chunk(self.supabase, player["floor"], nx, ny, D_FLOOR)
        elif tile == D_STAIRS:
            message = "階段がある。上の階へ進むことができます。"

        # 戦闘判定 (20%の確率)
        if random.random() < 0.2 and tile == D_FLOOR:
            # 本来はここでDungeonCombatViewに切り替える
            message = "敵が現れた！ (戦闘システム実装中)"

        # DB保存
        await db_save_player(self.supabase, self.user_id)
        
        # 再レンダリング
        file = render_dungeon_view(player["floor"], player["x"], player["y"])
        await interaction.response.edit_message(embed=self.create_embed(message), attachments=[file], view=self)

    @discord.ui.button(label="⬆️", style=discord.ButtonStyle.gray, row=0)
    async def up(self, interaction: Interaction, button: discord.ui.Button):
        await self.move(interaction, 0, -1)

    @discord.ui.button(label="⬅️", style=discord.ButtonStyle.gray, row=1)
    async def left(self, interaction: Interaction, button: discord.ui.Button):
        await self.move(interaction, -1, 0)

    @discord.ui.button(label="⬇️", style=discord.ButtonStyle.gray, row=1)
    async def down(self, interaction: Interaction, button: discord.ui.Button):
        await self.move(interaction, 0, 1)

    @discord.ui.button(label="➡️", style=discord.ButtonStyle.gray, row=1)
    async def right(self, interaction: Interaction, button: discord.ui.Button):
        await self.move(interaction, 1, 0)

# ============================================================
#  Cog クラス
# ============================================================

class DungeonV2(Cog):
    def __init__(self, bot):
        self.bot = bot
        self.supabase = getattr(bot, "supabase", None)

    async def cog_load(self):
        if self.supabase:
            await db_load_chunks(self.supabase)
        print("[DungeonV2] Cog loaded.")

    @app_commands.command(name="dungeon", description="ダンジョン探索を開始します (V2.0)")
    async def dungeon(self, interaction: Interaction):
        await interaction.response.defer()
        user_id = str(interaction.user.id)
        player = await db_load_player(self.supabase, user_id)
        
        # BGM再生 (ボイスチャンネル接続時)
        if interaction.user.voice:
            try:
                vc = await interaction.user.voice.channel.connect()
                vc.play(FFmpegPCMAudio("Assets/BGM.m4a"), after=lambda e: print(f"BGM finished: {e}"))
            except Exception as e:
                print(f"BGM playback failed: {e}")

        file = render_dungeon_view(player["floor"], player["x"], player["y"])
        view = DungeonMainView(self.bot, user_id, self.supabase)
        await interaction.followup.send(embed=view.create_embed("探索を開始します。"), file=file, view=view)

    @tasks.loop(time=datetime.time(hour=0, minute=0, tzinfo=JST))
    async def dungeon_monthly_task(self):
        """毎月1日にデータをリセットするタスク"""
        if datetime.datetime.now(JST).day == 1:
            print("[DungeonV2] Monthly maintenance: Resetting players and chunks.")
            try:
                # 差分データ削除
                self.supabase.table("dungeon_chunks").delete().neq("floor", -1).execute()
                # プレイヤー座標リセット
                self.supabase.table("dungeon_players").update({"x": 0, "y": 0}).neq("floor", -1).execute()
                # キャッシュクリア
                dg_chunks_cache.clear()
            except Exception as e:
                print(f"[DungeonV2] Maintenance failed: {e}")

async def setup(bot):
    await bot.add_cog(DungeonV2(bot))
