from __future__ import annotations
import datetime
import random
import uuid
import math
import io
import os
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands, tasks
from supabase import Client
from PIL import Image, ImageDraw, ImageFont

# ══════════════════════════════════════════════════════════════
# ■ 定数
# ══════════════════════════════════════════════════════════════

# --- マップ ---
MAP_SIZE_X             = 200
MAP_SIZE_Y             = 200
VIEW_RADIUS            = 5   # 描画半径（dungeon_11 流用）
TILE                   = 24  # ピクセル単位のタイルサイズ

# --- タイルHP/DEF ---
PLAIN_HP               = 100
WALL_HP                = 500
WALL_MAX_HP            = 500
CAPITAL_HP             = 300
CAPITAL_MAX_HP         = 300
DEFAULT_DEF            = 0
WALL_BASE_DEF          = 5
CAPITAL_DEF            = 3

# --- メンテナンス ---
MAINTENANCE_BASE_COST  = 20
MAINTENANCE_SCALE      = 1.05
FARM_REPAIR_HOURS      = 12

# --- プレイヤー ---
INITIAL_COINS          = 500
INITIAL_HUNGER         = 1000
HUNGER_MAX             = 1000
HUNGER_MIN             = 0
HUNGER_DECAY_PER_HOUR  = 0
HUNGER_COST_MOVE       = 0
HUNGER_COST_LABOR      = 0
HUNGER_COST_RAID       = 0
DUTY_HUNGER_MULTIPLIER = 2

# --- 経済 ---
FARM_BASE_YIELD        = 3
MINE_BASE_COIN         = 50
MINE_BASE_ORE_CHANCE   = 0.30
CHEF_LEVEL_IV_BONUS    = 5
CHEF_LEVEL_UP_COST     = 500
CASINO_MIN_BET         = 10
CASINO_MAX_BET         = 10000
CASINO_WIN_RATE        = 0.45
IV_RECOVERY_MULTIPLIER = 2.0

# --- 政治 ---
MIN_LABOR_REWARD       = 10
MAX_LABOR_REWARD       = 10000

# --- 鉄道 ---
RAILWAY_BUILD_COST     = 100

# --- レイド ---
RAID_BLOCK_DEF_BONUS   = 2
DUTY_DEF_BONUS         = 3
DEF_MAX_PERMANENT      = 10
DEF_MAX_WITH_BUFFS     = 25
DEF_UPGRADE_COST       = 200
CAPTURE_RESET_DEF      = 0
RAID_LOG_CHANNEL_NAME  = "raid-log"

# --- タイル色 (RGB) ---
TILE_COLORS = {
    "plain":      (80, 140, 60),
    "farm":       (160, 200, 80),
    "mine":       (120, 100, 70),
    "shop":       (180, 80, 200),
    "casino":     (220, 180, 30),
    "restaurant": (200, 80, 60),
    "wall":       (140, 130, 120),
    "capital":    (60, 100, 220),
    "railway":    (80, 80, 80),
    "unknown":    (40, 40, 40),   # 未開拓
    "player":     (30, 220, 120),
}

# --- タイル絵文字（テキスト描画用フォールバック） ---
TILE_LABEL = {
    "plain":      "",
    "farm":       "F",
    "mine":       "M",
    "shop":       "S",
    "casino":     "C",
    "restaurant": "R",
    "wall":       "W",
    "capital":    "K",
    "railway":    "T",
}

TILE_EMOJI = {
    "plain":      "🟩",
    "farm":       "🌾",
    "mine":       "⛏️",
    "shop":       "🏪",
    "casino":     "🎰",
    "restaurant": "🍽️",
    "wall":       "🧱",
    "capital":    "🏰",
    "railway":    "🛤️",
}

# --- 作物 ---
FARM_CROP_WEIGHTS = {
    "tomato": 40, "cabbage": 20, "potato": 20, "carrot": 15, "strawberry": 5,
}
CROP_NAMES = {
    "tomato": "トマト", "cabbage": "キャベツ", "potato": "ジャガイモ",
    "carrot": "ニンジン", "strawberry": "イチゴ",
}
CROP_TYPES = {k: "food" for k in CROP_NAMES}

# --- 高度と個体値生成用の定数（シード値やスケール） ---
NOISE_SEED_ALTITUDE  = 12345  # 高度用のノイズシード
NOISE_SEED_IV        = 67890  # 個体値(IV)用のノイズシード
MAP_SCALE_ALTITUDE   = 0.05   # 高度ノイズの滑らかさ（小さいほど広大な地形に）
MAP_SCALE_IV         = 0.1    # 個体値ノイズの滑らかさ（小さいほど大きな資源地帯に）

def get_altitude_at(x: int, y: int) -> int:
    """
    パーリンノイズから 0 ～ 100 の高度値を算出する
    """
    # get_perlin_noise は概ね -0.7 ～ 0.7 程度の値を返すため、0.0 ～ 1.0 に正規化
    noise_val = get_perlin_noise(x * MAP_SCALE_ALTITUDE, y * MAP_SCALE_ALTITUDE, NOISE_SEED_ALTITUDE)
    normalized = (noise_val + 0.7) / 1.4
    # 0 ～ 100 の範囲にクリップ
    return max(0, min(100, int(normalized * 100)))

def get_noise_iv_at(x: int, y: int) -> int:
    """
    パーリンノイズから 1 ～ 100 の個体値(IV)のベース値を算出する
    """
    noise_val = get_perlin_noise(x * MAP_SCALE_IV, y * MAP_SCALE_IV, NOISE_SEED_IV)
    normalized = (noise_val + 0.7) / 1.4
    return max(1, min(100, int(normalized * 100)))

def generate_noise_tile_data(x: int, y: int) -> dict:
    """
    座標(x, y)の高度を基に初期の地形タイプと個体値を一括生成する
    """
    altitude = get_altitude_at(x, y)
    iv_base = get_noise_iv_at(x, y)
    
    # 高度に応じたデフォルト地形タイプの決定ロジック例
    if altitude < 25:
        tile_type = "plain"  # 低地は平原
    elif altitude < 65:
        # 中高度：個体値ノイズによって農場か鉱山かが綺麗に分かれるようにする
        tile_type = "farm" if iv_base < 50 else "mine"
    else:
        tile_type = "wall"   # 高高度は進入不可の壁・山岳

    # 地形に応じた個体値(IV)の格納
    ivs = {"altitude": altitude}
    if tile_type == "farm":
        pop = list(FARM_CROP_WEIGHTS.keys())
        wts = list(FARM_CROP_WEIGHTS.values())
        ivs["fertility"] = iv_base  # ノイズ由来の肥沃度
        ivs["crop"] = random.choices(pop, weights=wts, k=1)[0]
    elif tile_type == "mine":
        ivs["purity"] = iv_base     # ノイズ由来の純度
    
    # 各地形ごとの初期HP/DEFの設定
    max_hp = PLAIN_HP
    base_def = DEFAULT_DEF
    if tile_type == "wall":
        max_hp = WALL_MAX_HP
        base_def = WALL_BASE_DEF

    return {
        "x": x,
        "y": y,
        "tile_type": tile_type,
        "hp": max_hp,
        "max_hp": max_hp,
        "def": base_def,
        "individual_values": ivs,
        "connected": False
    }

# ══════════════════════════════════════════════════════════════
# ■ Pillow マップ描画（dangeon_11.py 流用）
# ══════════════════════════════════════════════════════════════

def get_altitude_step_at(x: int, y: int) -> int:
    """
    指定された座標(x, y)の高度ノイズを計算し、1〜10の10段階のステップ値として返す。
    """
    # 【最重要】整数ではなく、0.05 などの小数を掛け算して渡すことで滑らかな波を作る
    scale = 0.08  # この数値を大きくすると起伏が激しくなり、小さくすると広大な地形になります
    
    alt_noise = get_perlin_noise(float(x) * scale, float(y) * scale, 12345)
    
    # get_perlin_noise の戻り値（だいたい -0.7 〜 0.7）を 0.0 〜 1.0 に安全に変換
    normalized = (alt_noise + 0.7) / 1.4
    normalized = max(0.0, min(1.0, normalized))
    
    # 1〜10 の10段階の整数に変換
    step = int(normalized * 9) + 1
    return step

def _draw_mmo_tile(draw: ImageDraw.ImageDraw, img: Image.Image,
                   vx: int, vy: int, tile_data: Optional[dict],
                   real_x: int, real_y: int,
                   is_player: bool = False, is_capital: bool = False) -> None:
    """1タイルを描画する（未開拓・開拓済みの両方に10段階の高度明暗を適用）"""
    px, py = vx * TILE, vy * TILE

    # 10段階の高度ステップ(1〜10)を取得
    alt_step = get_altitude_step_at(real_x, real_y)
    
    # 【明暗比率の調整】
    # 最暗(ステップ1)で 0.4倍、最明(ステップ10)で 1.4倍 になるように調整
    factor = 0.3 + (alt_step / 10.0) * 1.1

    if tile_data is None:
        # 未開拓地（ベース色を少し明るめのグレー(40, 45, 60)にして陰影を見やすくします）
        base_col = (40, 42, 55)
        r = max(0, min(255, int(base_col[0] * factor)))
        g = max(0, min(255, int(base_col[1] * factor)))
        b = max(0, min(255, int(base_col[2] * factor)))
        
        draw.rectangle([px, py, px + TILE - 1, py + TILE - 1], fill=(r, g, b))
        return

    # 開拓済みタイルの処理
    tile_type = tile_data.get("tile_type", "unknown")
    col = TILE_COLORS.get(tile_type, TILE_COLORS["unknown"])
    
    r = max(0, min(255, int(col[0] * factor)))
    g = max(0, min(255, int(col[1] * factor)))
    b = max(0, min(255, int(col[2] * factor)))

    draw.rectangle([px, py, px + TILE - 1, py + TILE - 1], fill=(r, g, b))

    # ラベル文字の描画
    label = TILE_LABEL.get(tile_type, "")
    if label:
        try:
            draw.text((px + TILE // 2 - 4, py + TILE // 2 - 6), label, fill=(255, 255, 255))
        except Exception:
            pass

    # プレイヤー位置の描画
    if is_player:
        mg = 5
        draw.ellipse([px + mg, py + mg, px + TILE - mg - 1, py + TILE - mg - 1], fill=TILE_COLORS["player"])


def mmo_build_map_image(tiles_data: list[dict], cx: int, cy: int,
                        capital_pos: Optional[tuple[int, int]] = None) -> Image.Image:
    """Pillow で周辺マップ画像を生成する"""
    size = VIEW_RADIUS * 2 + 1
    img = Image.new("RGB", (size * TILE, size * TILE), (15, 15, 25))
    draw = ImageDraw.Draw(img)

    # 座標にタイルデータをマッピング
    tile_map: dict[tuple[int, int], dict] = {
        (t["x"], t["y"]): t for t in tiles_data
    }

    for vy_i, vy in enumerate(range(cy - VIEW_RADIUS, cy + VIEW_RADIUS + 1)):
        for vx_i, vx in enumerate(range(cx - VIEW_RADIUS, cx + VIEW_RADIUS + 1)):
            is_player = (vx == cx and vy == cy)
            in_bounds = (0 <= vx < MAP_SIZE_X and 0 <= vy < MAP_SIZE_Y)
            
            tile_data = tile_map.get((vx, vy)) if in_bounds else None
            is_cap = (capital_pos is not None and (vx, vy) == capital_pos)
            
            # 【変更点】引数に実際のマップ座標である vx と vy を追加で渡す
            _draw_mmo_tile(draw, img, vx_i, vy_i, tile_data,
                           real_x=vx, real_y=vy,
                           is_player=is_player, is_capital=is_cap)

    # グリッド線
    for i in range(size + 1):
        draw.line([(i * TILE, 0), (i * TILE, size * TILE - 1)], fill=(40, 40, 50), width=1)
        draw.line([(0, i * TILE), (size * TILE - 1, i * TILE)], fill=(40, 40, 50), width=1)

    return img

def mmo_render_pillow(tiles_data: list[dict], cx: int, cy: int,
                      capital_pos: Optional[tuple[int, int]] = None) -> discord.File:
    """Pillow 画像を discord.File として返す（dangeon_11.d_render_pillow 相当）"""
    img = mmo_build_map_image(tiles_data, cx, cy, capital_pos)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return discord.File(fp=buf, filename="mmo_map.png")


# ══════════════════════════════════════════════════════════════
# ■ 純粋ヘルパー関数
# ══════════════════════════════════════════════════════════════

def _fade(t: float) -> float:
    return t * t * t * (t * (t * 6.0 - 15.0) + 10.0)

def _lerp(t: float, a: float, b: float) -> float:
    return a + t * (b - a)

def _dot_grid_gradient(ix, iy, x, y, seed):
    state = (ix * 1836311903 + iy * 2971215073 + seed * 42342347) & 0xFFFFFFFF
    rg = random.Random(state)
    angle = rg.random() * 2.0 * math.pi
    dx, dy = math.cos(angle), math.sin(angle)
    return (x - float(ix)) * dx + (y - float(iy)) * dy

def get_perlin_noise(x, y, seed):
    x0, x1 = math.floor(x), math.floor(x) + 1
    y0, y1 = math.floor(y), math.floor(y) + 1
    sx, sy = _fade(x - x0), _fade(y - y0)
    return _lerp(sy, _lerp(sx, _dot_grid_gradient(x0, y0, x, y, seed),
                               _dot_grid_gradient(x1, y0, x, y, seed)),
                     _lerp(sx, _dot_grid_gradient(x0, y1, x, y, seed),
                               _dot_grid_gradient(x1, y1, x, y, seed)))

def calc_maintenance_cost(tile_count: int) -> int:
    return int(MAINTENANCE_BASE_COST * (MAINTENANCE_SCALE ** max(0, tile_count - 1)))

def generate_ivs(tile_type: str) -> dict:
    if tile_type == "farm":
        pop = list(FARM_CROP_WEIGHTS.keys())
        wts = list(FARM_CROP_WEIGHTS.values())
        return {"fertility": random.randint(1, 100),
                "crop": random.choices(pop, weights=wts, k=1)[0]}
    if tile_type == "mine":
        return {"purity": random.randint(1, 100)}
    return {"altitude": random.randint(0, 100)}

def render_map_text(tiles: list[dict], center_x: int, center_y: int) -> str:
    """テキスト版マップ（フォールバック用）"""
    grid = {(t["x"], t["y"]): TILE_EMOJI.get(t["tile_type"], "⬛") for t in tiles}
    rows = []
    for dy in range(-VIEW_RADIUS, VIEW_RADIUS + 1):
        row = []
        for dx in range(-VIEW_RADIUS, VIEW_RADIUS + 1):
            coord = (center_x + dx, center_y + dy)
            row.append("📍" if coord == (center_x, center_y) else grid.get(coord, "⬜"))
        rows.append("".join(row))
    return "\n".join(rows)

def calc_recovery(base_recovery: int, quality_iv: int) -> int:
    mult = 1.0 + (IV_RECOVERY_MULTIPLIER - 1.0) * (quality_iv / 100)
    return int(base_recovery * mult)

def calc_farm_yield(fertility: int) -> int:
    return FARM_BASE_YIELD + int(FARM_BASE_YIELD * fertility / 100)

def calc_mine_reward(purity: int) -> tuple[int, bool]:
    coins = MINE_BASE_COIN + int(MINE_BASE_COIN * purity / 100)
    ore_drop = random.random() < (MINE_BASE_ORE_CHANCE + 0.005 * purity)
    return coins, ore_drop

def roll_iv(chef_level: int) -> int:
    minimum = min(99, (chef_level - 1) * CHEF_LEVEL_IV_BONUS)
    return random.randint(minimum, 100)

def hunger_bar(hunger: int) -> str:
    filled = hunger // 100
    return "🟩" * filled + "⬜" * (10 - filled)

def hp_bar(hp: int, max_hp: int, width: int = 10) -> str:
    filled = int(width * hp / max(max_hp, 1))
    return "█" * filled + "░" * (width - filled)

# ══════════════════════════════════════════════════════════════
# ■ View クラス群
# ══════════════════════════════════════════════════════════════

# ──────────────────────────────────────────────────────────────
# 移住確認
# ──────────────────────────────────────────────────────────────
class ImmigrationConfirmView(discord.ui.View):
    def __init__(self, user, old_gid, target_guild, exit_fee, entry_fee, db):
        super().__init__(timeout=60)
        self.user = user
        self.old_gid = old_gid
        self.target_guild = target_guild
        self.exit_fee = exit_fee
        self.entry_fee = entry_fee
        self.db = db

    @discord.ui.button(label="移住する", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        uid = str(interaction.user.id)
        new_gid = self.target_guild["guild_id"]
        new_coins = self.user.get("coins", 0) - self.exit_fee - self.entry_fee
        if self.old_gid and self.exit_fee > 0:
            old_g = self.db.table("guilds").select("treasury_coins").eq(
                "guild_id", self.old_gid).maybe_single().execute().data
            if old_g:
                self.db.table("guilds").update({
                    "treasury_coins": old_g["treasury_coins"] + self.exit_fee
                }).eq("guild_id", self.old_gid).execute()
        if self.entry_fee > 0:
            new_g = self.db.table("guilds").select("treasury_coins").eq(
                "guild_id", new_gid).maybe_single().execute().data
            if new_g:
                self.db.table("guilds").update({
                    "treasury_coins": new_g["treasury_coins"] + self.entry_fee
                }).eq("guild_id", new_gid).execute()
        sx = self.target_guild.get("capital_x", 0)
        sy = self.target_guild.get("capital_y", 0)
        self.db.table("users").update({
            "guild_id": new_gid, "coins": new_coins,
            "role": "citizen", "pos_x": sx, "pos_y": sy,
        }).eq("user_id", uid).execute()
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(
            content=f"✅ `{new_gid}` へ移住しました。残コイン: {new_coins:,}",
            embed=None, view=self)

    @discord.ui.button(label="キャンセル", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(content="移住をキャンセルしました。",
                                                embed=None, view=self)


# ──────────────────────────────────────────────────────────────
# ゲームメイン View（移動パッド ＋ メニューボタン）
# ──────────────────────────────────────────────────────────────
class MMOMainView(discord.ui.View):
    """
    ゲーム画面のメインビュー。
    Row 0: ↖ ↑ ↗
    Row 1: ← ● →
    Row 2: ↙ ↓ ↘
    Row 3: [メニュー]
    """

    def __init__(self, cog: "MMOCog", uid: str):
        super().__init__(timeout=600)
        self.cog = cog
        self.uid = uid

    # ── ヘルパー ──────────────────────────────────────
    def _get_tiles(self, cx: int, cy: int) -> list[dict]:
        res = self.cog.db.table("tiles").select("x,y,tile_type,owner_guild_id") \
            .gte("x", cx - VIEW_RADIUS).lte("x", cx + VIEW_RADIUS) \
            .gte("y", cy - VIEW_RADIUS).lte("y", cy + VIEW_RADIUS).execute()
        return res.data or []

    def _capital_pos(self, gid: str) -> Optional[tuple[int, int]]:
        g = self.cog._get_guild(gid)
        if g:
            return (g.get("capital_x", 0), g.get("capital_y", 0))
        return None

    def _make_embed(self, u: dict, msg: str = "") -> discord.Embed:
        gid = u.get("guild_id") or "無所属"
        tile = self.cog._get_tile(u["pos_x"], u["pos_y"])
        ttype = TILE_EMOJI.get(tile["tile_type"], "❓") if tile else "⬜"
        em = discord.Embed(
            title=f"🗺️ MMO — ({u['pos_x']}, {u['pos_y']})",
            color=discord.Color.green()
        )
        em.add_field(name="現在地タイル", value=ttype, inline=True)
        em.add_field(name="所持金", value=f"{u['coins']:,} コイン", inline=True)
        em.add_field(name="スタミナ", value=f"{hunger_bar(u['hunger'])} {u['hunger']}/{HUNGER_MAX}", inline=False)
        em.add_field(name="所属国", value=gid, inline=True)
        em.add_field(name="役職", value=u.get("role", "citizen"), inline=True)
        if msg:
            em.add_field(name="ログ", value=msg, inline=False)
        em.set_image(url="attachment://mmo_map.png")
        return em

    async def _refresh(self, interaction: discord.Interaction, msg: str = ""):
        u = self.cog._get_user(self.uid)
        if not u:
            await interaction.edit_original_response(content="プレイヤーデータが見つかりません。", view=None)
            return
        tiles = self._get_tiles(u["pos_x"], u["pos_y"])
        cap = self._capital_pos(u.get("guild_id", ""))
        map_file = mmo_render_pillow(tiles, u["pos_x"], u["pos_y"], cap)
        await interaction.edit_original_response(
            embed=self._make_embed(u, msg),
            attachments=[map_file],
            view=self
        )

    async def _move(self, interaction: discord.Interaction, dx: int, dy: int):
        await interaction.response.defer()
        u = self.cog._get_user(self.uid)
        if not u:
            await interaction.followup.send("`/join` で参加してください。", ephemeral=True)
            return
        if u["hunger"] <= HUNGER_MIN and HUNGER_COST_MOVE > 0:
            await self._refresh(interaction, "❌ スタミナ不足！食事で回復してください。")
            return

        # ══════════════════════════════════════════════════════════════
        # ❌【修正前】 max(0, min(MAP_SIZE_X - 1, u["pos_x"] + dx)) 
        # ⭕【修正後】 下限(0)の制限を取り除き、マイナスへの進入を許可します
        # ══════════════════════════════════════════════════════════════
        nx = u["pos_x"] + dx
        ny = u["pos_y"] + dy

        # 必要に応じて最大値側の上限だけ、または十分広大な世界（例:-10000〜10000）で制限します
        # nx = max(-10000, min(10000, nx))
        # ny = max(-10000, min(10000, ny))

        new_hunger = max(HUNGER_MIN, u["hunger"] - HUNGER_COST_MOVE)
        self.cog.db.table("users").update({
            "pos_x": nx, "pos_y": ny, "hunger": new_hunger
        }).eq("user_id", self.uid).execute()
        await self._refresh(interaction, f"移動 → ({nx}, {ny})")

    # ── 移動ボタン Row 0 ──────────────────────────────
    @discord.ui.button(label="↖️", style=discord.ButtonStyle.secondary, row=0, custom_id="mmo_lu")
    async def move_lu(self, i, b): await self._move(i, -1, -1)

    @discord.ui.button(label="⬆", style=discord.ButtonStyle.secondary, row=0, custom_id="mmo_u")
    async def move_u(self, i, b): await self._move(i, 0, -1)

    @discord.ui.button(label="↗️", style=discord.ButtonStyle.secondary, row=0, custom_id="mmo_ru")
    async def move_lu(self, interaction: discord.Interaction, button: discord.ui.Button): await self._move(interaction, 1, -1)

    # ── 移動ボタン Row 1 ──────────────────────────────
    @discord.ui.button(label="⬅", style=discord.ButtonStyle.secondary, row=1, custom_id="mmo_l")
    async def move_l(self, i, b): await self._move(i, -1, 0)

    @discord.ui.button(label="🔄", style=discord.ButtonStyle.secondary, row=1, custom_id="mmo_c")
    async def move_c(self, i, b):
        await i.response.defer()
        await self._refresh(i, "現在地を確認")

    @discord.ui.button(label="➡️", style=discord.ButtonStyle.secondary, row=1, custom_id="mmo_r")
    async def move_r(self, i, b): await self._move(i, 1, 0)

    # ── 移動ボタン Row 2 ──────────────────────────────
    @discord.ui.button(label="↙️", style=discord.ButtonStyle.secondary, row=2, custom_id="mmo_ld")
    async def move_ld(self, i, b): await self._move(i, -1, 1)

    @discord.ui.button(label="⬇", style=discord.ButtonStyle.secondary, row=2, custom_id="mmo_d")
    async def move_d(self, i, b): await self._move(i, 0, 1)

    @discord.ui.button(label="↘️", style=discord.ButtonStyle.secondary, row=2, custom_id="mmo_rd")
    async def move_rd(self, i, b): await self._move(i, 1, 1)

    # ── メニューボタン Row 3 ──────────────────────────
    @discord.ui.button(label="📋 メニュー", style=discord.ButtonStyle.primary, row=3, custom_id="mmo_menu")
    async def open_menu(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        view = MMOMenuView(self.cog, self.uid)
        u = self.cog._get_user(self.uid)
        tiles = self._get_tiles(u["pos_x"], u["pos_y"]) if u else []
        cap = self._capital_pos(u.get("guild_id", "")) if u else None
        map_file = mmo_render_pillow(tiles, u["pos_x"], u["pos_y"], cap) if u else None
        em = discord.Embed(title="📋 メニュー", description="アクションまたはその他を選んでください。", color=discord.Color.blurple())
        em.set_image(url="attachment://mmo_map.png")
        kwargs = {"embed": em, "view": view}
        if map_file:
            kwargs["attachments"] = [map_file]
        await interaction.edit_original_response(**kwargs)


# ──────────────────────────────────────────────────────────────
# メニュー View（アクション / その他 / 戻る）
# ──────────────────────────────────────────────────────────────
class MMOMenuView(discord.ui.View):
    def __init__(self, cog: "MMOCog", uid: str):
        super().__init__(timeout=120)
        self.cog = cog
        self.uid = uid

    async def _back_to_main(self, interaction: discord.Interaction):
        view = MMOMainView(self.cog, self.uid)
        await view._refresh(interaction)

    @discord.ui.button(label="⚔️ アクション", style=discord.ButtonStyle.danger, row=0, custom_id="mmo_menu_action")
    async def open_action(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        view = MMOActionView(self.cog, self.uid)
        em = discord.Embed(title="⚔️ アクション", description="何をしますか？", color=discord.Color.red())
        await interaction.edit_original_response(embed=em, view=view, attachments=[])

    @discord.ui.button(label="📦 その他", style=discord.ButtonStyle.success, row=0, custom_id="mmo_menu_other")
    async def open_other(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        view = MMOOtherView(self.cog, self.uid)
        em = discord.Embed(title="📦 その他", description="情報・設定を確認できます。", color=discord.Color.green())
        await interaction.edit_original_response(embed=em, view=view, attachments=[])

    @discord.ui.button(label="⬅️ 戻る", style=discord.ButtonStyle.secondary, row=1, custom_id="mmo_menu_back")
    async def go_back(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        await self._back_to_main(interaction)


# ──────────────────────────────────────────────────────────────
# アクション View
# ──────────────────────────────────────────────────────────────
class MMOActionView(discord.ui.View):
    """
    現在地タイルに関連するアクション群。
    ・開拓
    ・農場労働 / 鉱山労働
    ・当直開始/解除
    ・レイド（座標入力Modalで）
    ・カジノ（座標確認後）
    """

    def __init__(self, cog: "MMOCog", uid: str):
        super().__init__(timeout=120)
        self.cog = cog
        self.uid = uid

    async def _back_to_menu(self, interaction: discord.Interaction):
        view = MMOMenuView(self.cog, self.uid)
        em = discord.Embed(title="📋 メニュー", description="アクションまたはその他を選んでください。", color=discord.Color.blurple())
        await interaction.edit_original_response(embed=em, view=view, attachments=[])

    async def _back_to_main(self, interaction: discord.Interaction):
        view = MMOMainView(self.cog, self.uid)
        await view._refresh(interaction)

    # ── 開拓 ──────────────────────────────────────────
    @discord.ui.button(label="🏗️ 開拓", style=discord.ButtonStyle.primary, row=0, custom_id="mmo_act_develop")
    async def act_develop(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(DevelopModal(self.cog, self.uid))

    # ── 農場労働 ──────────────────────────────────────
    @discord.ui.button(label="🌾 農場労働", style=discord.ButtonStyle.success, row=0, custom_id="mmo_act_farm")
    async def act_farm(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        uid = self.uid
        gid = str(interaction.guild_id)
        u = self.cog._get_user(uid)
        msg, color = "", discord.Color.green()
        if not u:
            msg = "❌ `/join` で参加してください。"
            color = discord.Color.red()
        elif u["hunger"] < HUNGER_COST_LABOR:
            msg = f"❌ スタミナ不足（必要: {HUNGER_COST_LABOR}）"
            color = discord.Color.red()
        else:
            tile = self.cog._get_tile(u["pos_x"], u["pos_y"])
            if not tile or tile["tile_type"] != "farm":
                msg = "❌ 現在地はファームではありません。"
                color = discord.Color.red()
            elif not tile.get("connected"):
                msg = "❌ 首都と接続されていません。"
                color = discord.Color.red()
            elif tile.get("under_maintenance"):
                msg = "❌ このファームはメンテナンス中です。"
                color = discord.Color.red()
            else:
                g = self.cog._get_guild(gid)
                if not g or g["treasury_coins"] < g["labor_reward"]:
                    msg = "❌ 国庫が不足しており給料を支払えません。"
                    color = discord.Color.red()
                else:
                    ivs = tile.get("individual_values") or {}
                    fertility = ivs.get("fertility", 50)
                    selected_crop = ivs.get("crop", "tomato")
                    yield_qty = calc_farm_yield(fertility)
                    is_foreign = u["guild_id"] != tile["owner_guild_id"]
                    reward = g["labor_reward"]
                    foreign_fee = int(reward * 0.20) if is_foreign else 0
                    reward -= foreign_fee
                    net, tax = self.cog._apply_tax(u["guild_id"], reward)
                    self.cog.db.table("guilds").update({
                        "treasury_coins": g["treasury_coins"] - g["labor_reward"] + foreign_fee
                    }).eq("guild_id", gid).execute()
                    self.cog._add_stack_item(tile["owner_guild_id"], selected_crop, yield_qty)
                    self.cog.db.table("users").update({
                        "coins": u["coins"] + net,
                        "hunger": max(0, u["hunger"] - HUNGER_COST_LABOR),
                    }).eq("user_id", uid).execute()
                    cname = CROP_NAMES.get(selected_crop, selected_crop)
                    msg = f"🌾 **農場労働完了！**\n{cname} × {yield_qty} 収穫\n給料: **{net}** コイン（税: {tax}）"
        em = discord.Embed(title="🌾 農場労働", description=msg, color=color)
        view = MMOActionView(self.cog, self.uid)
        await interaction.edit_original_response(embed=em, view=view, attachments=[])

    # ── 鉱山労働 ──────────────────────────────────────
    @discord.ui.button(label="⛏ 鉱山労働", style=discord.ButtonStyle.success, row=0, custom_id="mmo_act_mine")
    async def act_mine(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        uid = self.uid
        gid = str(interaction.guild_id)
        u = self.cog._get_user(uid)
        msg, color = "", discord.Color.orange()
        if not u:
            msg = "❌ `/join` で参加してください。"
            color = discord.Color.red()
        else:
            tile = self.cog._get_tile(u["pos_x"], u["pos_y"])
            if not tile or tile["tile_type"] != "mine":
                msg = "❌ 現在地は鉱山ではありません。"
                color = discord.Color.red()
            elif not tile.get("connected"):
                msg = "❌ 首都と接続されていません。"
                color = discord.Color.red()
            else:
                g = self.cog._get_guild(gid)
                if not g or g["treasury_coins"] < g["labor_reward"]:
                    msg = "❌ 国庫が不足しており給料を支払えません。"
                    color = discord.Color.red()
                else:
                    purity = (tile.get("individual_values") or {}).get("purity", 50)
                    coins_earned, ore = calc_mine_reward(purity)
                    is_foreign = u["guild_id"] != tile["owner_guild_id"]
                    reward = g["labor_reward"]
                    foreign_fee = int(reward * 0.20) if is_foreign else 0
                    reward -= foreign_fee
                    net, tax = self.cog._apply_tax(u["guild_id"], reward)
                    self.cog.db.table("guilds").update({
                        "treasury_coins": g["treasury_coins"] - g["labor_reward"] + coins_earned + foreign_fee
                    }).eq("guild_id", gid).execute()
                    if ore:
                        self.cog._add_stack_item(tile["owner_guild_id"], "iron_ore", 1)
                    self.cog.db.table("users").update({
                        "coins": u["coins"] + net,
                        "hunger": max(0, u["hunger"] - HUNGER_COST_LABOR),
                    }).eq("user_id", uid).execute()
                    ore_txt = "✅ 鉄鉱石ドロップ！" if ore else "鉄鉱石なし"
                    msg = f"⛏️ **鉱山労働完了！**\n採掘コイン（国庫）: {coins_earned}\n給料: **{net}** コイン（税: {tax}）\n{ore_txt}"
        em = discord.Embed(title="⛏️ 鉱山労働", description=msg, color=color)
        view = MMOActionView(self.cog, self.uid)
        await interaction.edit_original_response(embed=em, view=view, attachments=[])

    # ── 当直 ──────────────────────────────────────────
    @discord.ui.button(label="🛡 当直", style=discord.ButtonStyle.primary, row=1, custom_id="mmo_act_duty")
    async def act_duty(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        uid = self.uid
        u = self.cog._get_user(uid)
        msg, color = "", discord.Color.blurple()
        if not u:
            msg = "❌ `/join` で参加してください。"
            color = discord.Color.red()
        elif u.get("on_duty_x") is not None:
            self.cog.db.table("users").update(
                {"on_duty_x": None, "on_duty_y": None}
            ).eq("user_id", uid).execute()
            msg = "✅ 当直を解除しました。"
        else:
            tile = self.cog._get_tile(u["pos_x"], u["pos_y"])
            if not tile or tile.get("owner_guild_id") != u["guild_id"]:
                msg = "❌ 自国領土でのみ当直できます。"
                color = discord.Color.red()
            else:
                self.cog.db.table("users").update({
                    "on_duty_x": u["pos_x"], "on_duty_y": u["pos_y"]
                }).eq("user_id", uid).execute()
                self.cog.db.rpc("increment_tile_def", {
                    "p_x": u["pos_x"], "p_y": u["pos_y"], "p_amount": DUTY_DEF_BONUS
                }).execute()
                msg = f"🛡 ({u['pos_x']}, {u['pos_y']}) で当直開始。DEF +{DUTY_DEF_BONUS}"
        em = discord.Embed(title="🛡 当直", description=msg, color=color)
        view = MMOActionView(self.cog, self.uid)
        await interaction.edit_original_response(embed=em, view=view, attachments=[])

    # ── カジノ ──────────────────────────────────────
    @discord.ui.button(label="🎰 カジノ", style=discord.ButtonStyle.danger, row=1, custom_id="mmo_act_casino")
    async def act_casino(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(CasinoModal(self.cog, self.uid, str(interaction.guild_id)))

    # ── レイド ──────────────────────────────────────
    @discord.ui.button(label="⚔️ レイド", style=discord.ButtonStyle.danger, row=1, custom_id="mmo_act_raid")
    async def act_raid(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(RaidModal(self.cog, self.uid, str(interaction.guild_id)))

    # ── 戻る ──────────────────────────────────────────
    @discord.ui.button(label="⬅️ メニューへ", style=discord.ButtonStyle.secondary, row=2, custom_id="mmo_act_back")
    async def go_back(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        await self._back_to_menu(interaction)

    @discord.ui.button(label="🗺️ マップへ", style=discord.ButtonStyle.secondary, row=2, custom_id="mmo_act_map")
    async def go_map(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        await self._back_to_main(interaction)


# ──────────────────────────────────────────────────────────────
# その他 View
# ──────────────────────────────────────────────────────────────
class MMOOtherView(discord.ui.View):
    """ステータス・インベントリ・国家情報・国庫など"""

    def __init__(self, cog: "MMOCog", uid: str):
        super().__init__(timeout=120)
        self.cog = cog
        self.uid = uid

    async def _back_to_menu(self, interaction: discord.Interaction):
        view = MMOMenuView(self.cog, self.uid)
        em = discord.Embed(title="📋 メニュー", description="アクションまたはその他を選んでください。", color=discord.Color.blurple())
        await interaction.edit_original_response(embed=em, view=view, attachments=[])

    async def _back_to_main(self, interaction: discord.Interaction):
        view = MMOMainView(self.cog, self.uid)
        await view._refresh(interaction)

    # ── ステータス ────────────────────────────────────
    @discord.ui.button(label="📋 ステータス", style=discord.ButtonStyle.primary, row=0, custom_id="mmo_oth_status")
    async def oth_status(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        u = self.cog._get_user(self.uid)
        if not u:
            em = discord.Embed(description="❌ `/join` で参加してください。", color=discord.Color.red())
        else:
            on_duty = f"({u['on_duty_x']}, {u['on_duty_y']})" if u.get("on_duty_x") is not None else "なし"
            em = discord.Embed(title=f"📋 ステータス", color=discord.Color.blurple())
            em.add_field(name="所持金",     value=f"{u['coins']:,} コイン")
            em.add_field(name="スタミナ",   value=f"{hunger_bar(u['hunger'])} {u['hunger']}/{HUNGER_MAX}")
            em.add_field(name="現在地",     value=f"({u['pos_x']}, {u['pos_y']})")
            em.add_field(name="所属国",     value=u.get("guild_id") or "無所属")
            em.add_field(name="役職",       value=u.get("role", "citizen"))
            em.add_field(name="料理熟練度", value=f"Lv {u.get('chef_level', 1)}")
            em.add_field(name="当直中",     value=on_duty)
        view = MMOOtherView(self.cog, self.uid)
        await interaction.edit_original_response(embed=em, view=view, attachments=[])

    # ── インベントリ ──────────────────────────────────
    @discord.ui.button(label="🎒 インベントリ", style=discord.ButtonStyle.primary, row=0, custom_id="mmo_oth_inv")
    async def oth_inventory(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        uid = self.uid
        stacks = self.cog.db.table("item_inventories").select("item_id,quantity").eq(
            "owner_id", uid).execute().data or []
        uniques = self.cog.db.table("item_instances").select(
            "instance_id,custom_name,quality_iv").eq(
            "owner_id", uid).eq("on_sale", False).execute().data or []
        em = discord.Embed(title="🎒 インベントリ", color=discord.Color.blurple())
        if stacks:
            em.add_field(name="スタックアイテム",
                value="\n".join(f"・{s['item_id']} × {s['quantity']}" for s in stacks),
                inline=False)
        if uniques:
            em.add_field(name="ユニークアイテム",
                value="\n".join(
                    f"・[{u['instance_id'][:8]}] {u['custom_name']} (IV:{u['quality_iv']})"
                    for u in uniques),
                inline=False)
        if not stacks and not uniques:
            em.description = "（空っぽです）"
        view = MMOOtherView(self.cog, self.uid)
        await interaction.edit_original_response(embed=em, view=view, attachments=[])

    # ── 国家情報 ──────────────────────────────────────
    @discord.ui.button(label="🏛️ 国家情報", style=discord.ButtonStyle.success, row=1, custom_id="mmo_oth_nation")
    async def oth_nation(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        gid = str(interaction.guild_id)
        g = self.cog._get_guild(gid)
        if not g:
            em = discord.Embed(description="❌ 国家データが存在しません。", color=discord.Color.red())
        else:
            cnt = len(self.cog.db.table("tiles").select("x").eq("owner_guild_id", gid).execute().data or [])
            em = discord.Embed(title=f"🏛️ 国家情報: {interaction.guild.name}", color=discord.Color.blurple())
            em.add_field(name="国庫",         value=f"{g['treasury_coins']:,} コイン")
            em.add_field(name="所有マス数",   value=f"{cnt} マス")
            em.add_field(name="税率",         value=f"{int(g['tax_rate']*100)} %")
            em.add_field(name="国策労働給料", value=f"{g['labor_reward']} コイン")
            em.add_field(name="入国料",       value=f"{g['entry_fee']} コイン")
            em.add_field(name="出国税",       value=f"{int(g['exit_fee_rate']*100)} %")
            em.add_field(name="首都",         value=f"({g['capital_x']}, {g['capital_y']})")
            alliances = g.get("alliances") or []
            em.add_field(name="同盟国", value=", ".join(alliances) if alliances else "なし")
        view = MMOOtherView(self.cog, self.uid)
        await interaction.edit_original_response(embed=em, view=view, attachments=[])

    # ── 国庫 ──────────────────────────────────────────
    @discord.ui.button(label="🏦 国庫", style=discord.ButtonStyle.success, row=1, custom_id="mmo_oth_treasury")
    async def oth_treasury(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        gid = str(interaction.guild_id)
        g = self.cog._get_guild(gid)
        if not g:
            em = discord.Embed(description="❌ 国家データが見つかりません。", color=discord.Color.red())
        else:
            inv = self.cog.db.table("item_inventories").select("item_id,quantity").eq(
                "owner_id", gid).execute().data or []
            em = discord.Embed(title=f"🏦 国庫: {interaction.guild.name}", color=discord.Color.gold())
            em.add_field(name="残高", value=f"{g['treasury_coins']:,} コイン", inline=False)
            em.add_field(name="倉庫",
                value="\n".join(f"・{i['item_id']} × {i['quantity']}" for i in inv) or "（空っぽ）",
                inline=False)
        view = MMOOtherView(self.cog, self.uid)
        await interaction.edit_original_response(embed=em, view=view, attachments=[])

    # ── タイル情報 ────────────────────────────────────
    @discord.ui.button(label="🔍 タイル情報", style=discord.ButtonStyle.secondary, row=2, custom_id="mmo_oth_tile")
    async def oth_tileinfo(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        u = self.cog._get_user(self.uid)
        if not u:
            em = discord.Embed(description="❌ プレイヤーデータなし", color=discord.Color.red())
        else:
            x, y = u["pos_x"], u["pos_y"]
            tile = self.cog._get_tile(x, y)
            if not tile:
                em = discord.Embed(description=f"({x}, {y}) は未開拓地です。", color=discord.Color.greyple())
            else:
                em = discord.Embed(
                    title=f"{TILE_EMOJI.get(tile['tile_type'], '❓')} タイル情報 ({x}, {y})",
                    color=discord.Color.blurple())
                em.add_field(name="種別",     value=tile["tile_type"])
                em.add_field(name="HP",       value=f"{tile['hp']} / {tile['max_hp']}")
                em.add_field(name="DEF",      value=str(tile["def"]))
                em.add_field(name="接続状態", value="✅" if tile["connected"] else "❌")
                em.add_field(name="個体値",   value=str(tile.get("individual_values") or {}))
                em.add_field(name="所有国",   value=tile.get("owner_guild_id") or "（未所有）")
        view = MMOOtherView(self.cog, self.uid)
        await interaction.edit_original_response(embed=em, view=view, attachments=[])

    # ── 戻る ──────────────────────────────────────────
    @discord.ui.button(label="⬅️ メニューへ", style=discord.ButtonStyle.secondary, row=3, custom_id="mmo_oth_back")
    async def go_back(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        await self._back_to_menu(interaction)

    @discord.ui.button(label="🗺️ マップへ", style=discord.ButtonStyle.secondary, row=3, custom_id="mmo_oth_map")
    async def go_map(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        await self._back_to_main(interaction)


# ──────────────────────────────────────────────────────────────
# Modal 群
# ──────────────────────────────────────────────────────────────
class DevelopModal(discord.ui.Modal, title="🏗️ 開拓"):
    tile_type = discord.ui.TextInput(
        label="施設種別 (farm/mine/shop/casino/restaurant/wall)",
        placeholder="farm",
        max_length=20
    )

    def __init__(self, cog: "MMOCog", uid: str):
        super().__init__()
        self.cog = cog
        self.uid = uid

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer()
        VALID = {"farm", "mine", "shop", "casino", "restaurant", "wall"}
        ttype = self.tile_type.value.strip().lower()
        uid = self.uid
        gid = str(interaction.guild_id)
        color = discord.Color.gold()
        if ttype not in VALID:
            msg = f"❌ 無効な種別です。選択肢: {', '.join(VALID)}"
            color = discord.Color.red()
        else:
            u = self.cog.db.table("users").select("pos_x,pos_y,hunger,guild_id").eq(
                "user_id", uid).maybe_single().execute().data
            if not u:
                msg = "❌ `/join` で参加してください。"
                color = discord.Color.red()
            elif u["guild_id"] != gid:
                msg = "❌ このサーバーの国民ではありません。"
                color = discord.Color.red()
            elif u["hunger"] < 20:
                msg = "❌ スタミナが不足しています（20必要）。"
                color = discord.Color.red()
            else:
                existing = self.cog._get_tile(u["pos_x"], u["pos_y"])
                if existing and existing.get("owner_guild_id"):
                    msg = "❌ そのマスはすでに占有されています。"
                    color = discord.Color.red()
                else:
                    x, y = u["pos_x"], u["pos_y"]

                    # ══════════════════════════════════════════════════════════════
                    # 【追加】パーリンノイズによる高度値と個体値ベースの算出
                    # ══════════════════════════════════════════════════════════════
                    # 高度用ノイズ（シード: 12345, スケール: 0.05 で緩やかな起伏）
                    alt_noise = get_perlin_noise(x * 0.05, y * 0.05, 12345)
                    altitude = max(0, min(100, int(((alt_noise + 0.7) / 1.4) * 100)))

                    # 資源・個体値用ノイズ（シード: 67890, スケール: 0.1 で資源の脈を形成）
                    iv_noise = get_perlin_noise(x * 0.1, y * 0.1, 67890)
                    iv_base = max(1, min(100, int(((iv_noise + 0.7) / 1.4) * 100)))

                    # 既存のランダムIV生成を取得し、ノイズベースの値で上書き・追加する
                    ivs = generate_ivs(ttype)
                    ivs["altitude"] = altitude  # 高度値を個体値に記録

                    # タイルタイプに応じた個別ノイズ特性の適用
                    if ttype == "farm":
                        ivs["fertility"] = iv_base  # 肥沃度をノイズ由来（土地の脈）にする
                    elif ttype == "mine":
                        ivs["purity"] = iv_base     # 純度をノイズ由来にする
                    # ══════════════════════════════════════════════════════════════

                    if ttype == "farm":
                        selected_crop = ivs.get("crop", "tomato")
                        try:
                            ex_item = self.cog.db.table("items").select("item_id").eq(
                                "item_id", selected_crop).maybe_single().execute()
                            if not ex_item or not getattr(ex_item, "data", None):
                                self.cog.db.table("items").insert({
                                    "item_id": selected_crop,
                                    "name": CROP_NAMES.get(selected_crop, selected_crop),
                                    "type": CROP_TYPES.get(selected_crop, "material")
                                }).execute()
                        except Exception:
                            pass
                    hp = WALL_HP if ttype == "wall" else PLAIN_HP
                    max_hp = WALL_MAX_HP if ttype == "wall" else PLAIN_HP
                    base_def = WALL_BASE_DEF if ttype == "wall" else DEFAULT_DEF
                    self.cog.db.table("tiles").upsert({
                        "x": x, "y": y,
                        "owner_guild_id": gid,
                        "owner_user_id": uid if ttype not in {"farm", "mine"} else None,
                        "tile_type": ttype, "individual_values": ivs,
                        "hp": hp, "max_hp": max_hp, "def": base_def, "connected": False,
                    }).execute()
                    self.cog.db.table("users").update({"hunger": u["hunger"] - 20}).eq(
                        "user_id", uid).execute()
                    self.cog._update_connections(gid)
                    crop_disp = ""
                    if ttype == "farm" and "crop" in ivs:
                        cname = CROP_NAMES.get(ivs["crop"], ivs["crop"])
                        crop_disp = f"\n🌾 決定した栽培作物: **{cname}**"
                    
                    msg = (
                        f"✅ ({x}, {y}) を **{ttype}** に開拓！\n"
                        f"⛰️ 土地の高度: `{altitude}`\n"
                        f"📊 個体値データ: {ivs}{crop_disp}"
                    )

        em = discord.Embed(title="🏗️ 開拓", description=msg, color=color)
        view = MMOActionView(self.cog, self.uid)
        await interaction.edit_original_response(embed=em, view=view, attachments=[])

class CasinoModal(discord.ui.Modal, title="🎰 カジノ"):
    bet_input = discord.ui.TextInput(
        label=f"ベット額 ({CASINO_MIN_BET}〜{CASINO_MAX_BET} コイン)",
        placeholder="100",
        max_length=6
    )

    def __init__(self, cog: "MMOCog", uid: str, gid: str):
        super().__init__()
        self.cog = cog
        self.uid = uid
        self.gid = gid

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer()
        try:
            bet = int(self.bet_input.value.strip())
        except ValueError:
            em = discord.Embed(description="❌ 数値を入力してください。", color=discord.Color.red())
            await interaction.edit_original_response(embed=em, view=MMOActionView(self.cog, self.uid), attachments=[])
            return

        uid = self.uid
        gid = self.gid
        u = self.cog._get_user(uid)
        color = discord.Color.gold()
        if not u:
            msg = "❌ `/join` で参加してください。"
            color = discord.Color.red()
        else:
            tile = self.cog._get_tile(u["pos_x"], u["pos_y"])
            if not tile or tile["tile_type"] != "casino":
                msg = "❌ カジノマスにいる必要があります。"
                color = discord.Color.red()
            elif not (CASINO_MIN_BET <= bet <= CASINO_MAX_BET):
                msg = f"❌ ベット額は {CASINO_MIN_BET}〜{CASINO_MAX_BET} で指定してください。"
                color = discord.Color.red()
            elif u["coins"] < bet:
                msg = "❌ コインが不足しています。"
                color = discord.Color.red()
            else:
                won = random.random() < CASINO_WIN_RATE
                if won:
                    net, _ = self.cog._apply_tax(gid, bet)
                    delta = net
                else:
                    delta = -bet
                    g = self.cog._get_guild(gid)
                    if g:
                        self.cog.db.table("guilds").update({
                            "treasury_coins": g["treasury_coins"] + bet
                        }).eq("guild_id", gid).execute()
                self.cog.db.table("users").update({
                    "coins": u["coins"] + delta
                }).eq("user_id", uid).execute()
                result = "🎉 勝利！" if won else "💸 敗北…"
                msg = f"{result}\nベット額: {bet} コイン\n収支: {'+' if delta >= 0 else ''}{delta} コイン\n所持金: {u['coins'] + delta:,} コイン"
                color = discord.Color.gold() if won else discord.Color.red()

        em = discord.Embed(title="🎰 カジノ", description=msg, color=color)
        view = MMOActionView(self.cog, self.uid)
        await interaction.edit_original_response(embed=em, view=view, attachments=[])


class RaidModal(discord.ui.Modal, title="⚔️ レイド"):
    x_input = discord.ui.TextInput(label="攻撃対象 X 座標", placeholder="0", max_length=4)
    y_input = discord.ui.TextInput(label="攻撃対象 Y 座標", placeholder="0", max_length=4)
    weapon_id = discord.ui.TextInput(
        label="武器インスタンスID（省略可）", placeholder="なし", required=False, max_length=40)

    def __init__(self, cog: "MMOCog", uid: str, gid: str):
        super().__init__()
        self.cog = cog
        self.uid = uid
        self.gid = gid

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer()
        try:
            tx = int(self.x_input.value.strip())
            ty = int(self.y_input.value.strip())
        except ValueError:
            em = discord.Embed(description="❌ 座標は数値で入力してください。", color=discord.Color.red())
            await interaction.edit_original_response(embed=em, view=MMOActionView(self.cog, self.uid), attachments=[])
            return

        weapon_instance_id = self.weapon_id.value.strip() if self.weapon_id.value else ""
        uid = self.uid
        gid = self.gid
        u = self.cog._get_user(uid)
        color = discord.Color.red()
        msg = ""

        if not u:
            msg = "❌ `/join` で参加してください。"
        elif u.get("guild_id") != gid:
            msg = "❌ このサーバーの国民ではありません。"
        elif u["hunger"] < HUNGER_COST_RAID:
            msg = f"❌ スタミナ不足（必要: {HUNGER_COST_RAID}）。"
        else:
            tile = self.cog._get_tile(tx, ty)
            if not tile:
                msg = "❌ 攻撃対象のマスが存在しません。"
            elif tile.get("owner_guild_id") == gid:
                msg = "❌ 自国のマスは攻撃できません。"
            elif not tile.get("owner_guild_id"):
                msg = "❌ 未所有マスは攻撃できません。"
            elif not self.cog._is_adjacent_to_guild(gid, tx, ty):
                msg = "❌ 攻撃対象に隣接する自国領土がありません。"
            else:
                atk = 0
                weapon_name = "素手"
                if weapon_instance_id:
                    w = self.cog.db.table("item_instances").select("*").eq(
                        "instance_id", weapon_instance_id).eq(
                        "owner_id", uid).maybe_single().execute().data
                    if not w:
                        msg = "❌ その武器を所持していません。"
                    else:
                        wm = self.cog.db.table("items").select("base_atk,type,name").eq(
                            "item_id", w["item_id"]).maybe_single().execute().data
                        if not wm or wm.get("type") != "weapon":
                            msg = "❌ 武器ではありません。"
                        else:
                            atk = wm.get("base_atk", 0)
                            weapon_name = w.get("custom_name") or wm["name"]
                            self.cog.db.table("item_instances").delete().eq(
                                "instance_id", weapon_instance_id).execute()

                if not msg:
                    eff_def = self.cog._get_effective_def(tile)
                    self.cog.db.table("users").update({
                        "hunger": max(0, u["hunger"] - HUNGER_COST_RAID)
                    }).eq("user_id", uid).execute()
                    if atk <= eff_def:
                        self.cog.db.table("raid_logs").insert({
                            "attacker_uid": uid, "attacker_gid": gid,
                            "target_x": tx, "target_y": ty, "damage_dealt": 0, "captured": False,
                        }).execute()
                        msg = f"🛡️ **ダメージなし！** ATK({atk}) ≤ DEF({eff_def})"
                    else:
                        damage = atk - eff_def
                        new_hp = max(0, tile["hp"] - damage)
                        self.cog.db.table("tiles").update({"hp": new_hp}).eq("x", tx).eq("y", ty).execute()
                        self.cog.db.table("raid_logs").insert({
                            "attacker_uid": uid, "attacker_gid": gid,
                            "target_x": tx, "target_y": ty,
                            "damage_dealt": damage, "captured": new_hp == 0,
                        }).execute()
                        if new_hp == 0:
                            await self.cog._capture_tile(tx, ty, gid, uid)
                            result = "🚩 **占領成功！**"
                            color = discord.Color.gold()
                        else:
                            result = f"残HP: {new_hp} / {tile['max_hp']}"
                        msg = (f"⚔️ **レイド: ({tx}, {ty})**\n"
                               f"武器: {weapon_name} | ATK: {atk} | DEF: {eff_def}\n"
                               f"ダメージ: **{damage}**\n{result}")

        em = discord.Embed(title="⚔️ レイド", description=msg, color=color)
        view = MMOActionView(self.cog, self.uid)
        await interaction.edit_original_response(embed=em, view=view, attachments=[])


# ══════════════════════════════════════════════════════════════
# ■ MMO 統合 Cog
# ══════════════════════════════════════════════════════════════

class MMOCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db: Client = None  # type: ignore

    async def cog_load(self) -> None:
        class SafePostgrestBuilder:
            def __init__(self, builder):
                self._builder = builder
            def __getattr__(self, name):
                attr = getattr(self._builder, name)
                if callable(attr):
                    def wrapper(*args, **kwargs):
                        res = attr(*args, **kwargs)
                        if name == "execute":
                            if res is None:
                                class FakeResponse:
                                    data = None
                                return FakeResponse()
                            return res
                        if res and res.__class__.__module__.startswith("postgrest"):
                            return SafePostgrestBuilder(res)
                        return res
                    return wrapper
                return attr

        class SafeDB:
            def __init__(self, db):
                self._db = db
            def table(self, *args, **kwargs):
                return SafePostgrestBuilder(self._db.table(*args, **kwargs))
            def rpc(self, *args, **kwargs):
                return self._db.rpc(*args, **kwargs)
            def __getattr__(self, name):
                return getattr(self._db, name)

        self.db = SafeDB(self.bot.supabase)  # type: ignore

        # 作物マスタデータ自動同期
        try:
            new_crops = [
                {"item_id": "cabbage",    "name": "キャベツ",   "item_type": "food"},
                {"item_id": "potato",     "name": "ジャガイモ", "item_type": "food"},
                {"item_id": "carrot",     "name": "ニンジン",   "item_type": "food"},
                {"item_id": "strawberry", "name": "イチゴ",     "item_type": "food"},
            ]
            for crop in new_crops:
                existing = self.db.table("items").select("item_id").eq(
                    "item_id", crop["item_id"]).maybe_single().execute()
                if not existing or not getattr(existing, "data", None):
                    self.db.table("items").insert(crop).execute()
        except Exception as e:
            print(f"[Warning] 作物マスタ自動追加失敗: {e}")

        self.hunger_decay_task.start()
        self.farm_maintenance_task.start()
        self.capture_check_task.start()

    async def cog_unload(self) -> None:
        self.hunger_decay_task.cancel()
        self.farm_maintenance_task.cancel()
        self.capture_check_task.cancel()

    # ──────────────────────────────────────────
    # 共通 DB ヘルパー
    # ──────────────────────────────────────────

    def _get_user(self, uid: str) -> Optional[dict]:
        res = self.db.table("users").select("*").eq("user_id", uid).maybe_single().execute()
        return res.data if res else None

    def _get_guild(self, gid: str) -> Optional[dict]:
        res = self.db.table("guilds").select("*").eq("guild_id", gid).maybe_single().execute()
        return res.data if res else None

    def _get_tile(self, x: int, y: int) -> Optional[dict]:
        res = self.db.table("tiles").select("*").eq("x", x).eq("y", y).maybe_single().execute()
        return res.data if res else None

    def _get_railway(self, x: int, y: int) -> Optional[dict]:
        res = self.db.table("railways").select("*").eq("x", x).eq("y", y).maybe_single().execute()
        return res.data if res else None

    def _ensure_guild(self, guild_id: str) -> dict:
        res = self.db.table("guilds").select("*").eq("guild_id", guild_id).maybe_single().execute()
        if res and res.data:
            return res.data
        new_guild = {"guild_id": guild_id, "treasury_coins": 1000}
        self.db.table("guilds").insert(new_guild).execute()
        return new_guild

    def _add_stack_item(self, owner_id: str, item_id: str, qty: int) -> None:
        ex = self.db.table("item_inventories").select("quantity").eq(
            "owner_id", owner_id).eq("item_id", item_id).maybe_single().execute().data
        if ex:
            self.db.table("item_inventories").update({
                "quantity": ex["quantity"] + qty
            }).eq("owner_id", owner_id).eq("item_id", item_id).execute()
        else:
            self.db.table("item_inventories").insert({
                "owner_id": owner_id, "item_id": item_id, "quantity": qty
            }).execute()

    def _consume_stack_item(self, owner_id: str, item_id: str, qty: int) -> bool:
        ex = self.db.table("item_inventories").select("quantity").eq(
            "owner_id", owner_id).eq("item_id", item_id).maybe_single().execute().data
        if not ex or ex["quantity"] < qty:
            return False
        new_qty = ex["quantity"] - qty
        if new_qty == 0:
            self.db.table("item_inventories").delete().eq(
                "owner_id", owner_id).eq("item_id", item_id).execute()
        else:
            self.db.table("item_inventories").update({"quantity": new_qty}).eq(
                "owner_id", owner_id).eq("item_id", item_id).execute()
        return True

    def _apply_tax(self, gid: str, gross: int) -> tuple[int, int]:
        g = self.db.table("guilds").select("tax_rate,treasury_coins").eq(
            "guild_id", gid).maybe_single().execute().data
        if not g:
            return gross, 0
        tax = int(gross * g["tax_rate"])
        net = gross - tax
        self.db.table("guilds").update({
            "treasury_coins": g["treasury_coins"] + tax
        }).eq("guild_id", gid).execute()
        return net, tax

    def _require_role(self, uid: str, gid: str, roles: set[str]) -> Optional[str]:
        u = self._get_user(uid)
        if not u or u.get("guild_id") != gid or u.get("role") not in roles:
            return "国王または大臣のみ実行できます。"
        return None

    def _update_connections(self, guild_id: str) -> None:
        g = self.db.table("guilds").select("capital_x,capital_y").eq(
            "guild_id", guild_id).maybe_single().execute().data
        if not g:
            return
        owned = self.db.table("tiles").select("x,y,connected").eq(
            "owner_guild_id", guild_id).execute().data or []
        rails = self.db.table("railways").select("x,y").eq(
            "owner_guild_id", guild_id).execute().data or []
        passable = {(t["x"], t["y"]) for t in owned} | {(r["x"], r["y"]) for r in rails}
        visited: set[tuple] = set()
        queue = [(g["capital_x"], g["capital_y"])]
        while queue:
            cx, cy = queue.pop(0)
            if (cx, cy) in visited:
                continue
            visited.add((cx, cy))
            for dx, dy in [(1, 0), (-1, 0), (0, 1), (0, -1)]:
                nb = (cx + dx, cy + dy)
                if nb in passable and nb not in visited:
                    queue.append(nb)
        for t in owned:
            connected = (t["x"], t["y"]) in visited
            if t["connected"] != connected:
                self.db.table("tiles").update({"connected": connected}).eq(
                    "x", t["x"]).eq("y", t["y"]).execute()

    def _get_effective_def(self, tile: dict) -> int:
        base = tile.get("def", 0)
        on_duty = self.db.table("users").select("user_id").eq(
            "on_duty_x", tile["x"]).eq("on_duty_y", tile["y"]).execute().data or []
        duty_b = DUTY_DEF_BONUS if on_duty else 0
        block_b = (tile.get("individual_values") or {}).get("raid_block_def", 0)
        return min(DEF_MAX_WITH_BUFFS, base + duty_b + block_b)

    def _is_adjacent_to_guild(self, attacker_gid: str, tx: int, ty: int) -> bool:
        for dx, dy in [(1, 0), (-1, 0), (0, 1), (0, -1)]:
            adj = self.db.table("tiles").select("owner_guild_id").eq(
                "x", tx + dx).eq("y", ty + dy).maybe_single().execute().data
            if adj and adj.get("owner_guild_id") == attacker_gid:
                return True
        return False

    def _rail_reachable(self, start_gid: str, tx: int, ty: int,
                        alliances: list[str]) -> tuple[bool, list[dict]]:
        g = self.db.table("guilds").select("capital_x,capital_y").eq(
            "guild_id", start_gid).maybe_single().execute().data
        if not g:
            return False, []
        all_rail = self.db.table("railways").select("*").execute().data or []
        rail_map = {(r["x"], r["y"]): r for r in all_rail}
        visited: set[tuple] = set()
        queue = [(g["capital_x"], g["capital_y"])]
        path: list[dict] = []
        while queue:
            cx, cy = queue.pop(0)
            if (cx, cy) in visited:
                continue
            visited.add((cx, cy))
            if r := rail_map.get((cx, cy)):
                path.append(r)
            if (cx, cy) == (tx, ty):
                return True, path
            for dx, dy in [(1, 0), (-1, 0), (0, 1), (0, -1)]:
                nb = (cx + dx, cy + dy)
                if nb in visited:
                    continue
                nb_rail = rail_map.get(nb)
                if nb_rail is None:
                    continue
                perm = nb_rail.get("permissions", "all")
                bl = nb_rail.get("blacklist_guilds") or []
                owner = nb_rail.get("owner_guild_id")
                if start_gid in bl:
                    continue
                if perm == "citizens_only" and owner != start_gid:
                    continue
                if perm == "allies_only" and owner != start_gid and owner not in alliances:
                    continue
                queue.append(nb)
        return False, []

    async def _post_raid_log(self, guild: Optional[discord.Guild], msg: str) -> None:
        if not guild:
            return
        ch = discord.utils.get(guild.text_channels, name=RAID_LOG_CHANNEL_NAME)
        if ch:
            await ch.send(msg)

    async def _capture_tile(self, x: int, y: int, gid: str, uid: str) -> None:
        self.db.table("tiles").update({
            "owner_guild_id": gid, "owner_user_id": uid,
            "def": CAPTURE_RESET_DEF, "hp": 50, "connected": False,
        }).eq("x", x).eq("y", y).execute()
        tile = self._get_tile(x, y)
        if tile:
            ivs = dict(tile.get("individual_values") or {})
            ivs.pop("raid_block_def", None)
            self.db.table("tiles").update({"individual_values": ivs}).eq(
                "x", x).eq("y", y).execute()

    # ══════════════════════════════════════════
    # ■ メインコマンド（ゲーム画面）
    # ══════════════════════════════════════════

    @app_commands.command(name="playmmo", description="MMOゲーム画面を開きます")
    async def cmd_play(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        uid = str(interaction.user.id)
        u = self._get_user(uid)
        if not u:
            await interaction.followup.send(
                "❌ まだ参加していません。`/join` で国家に参加してください。", ephemeral=True)
            return

        view = MMOMainView(self, uid)
        tiles = view._get_tiles(u["pos_x"], u["pos_y"])
        gid = u.get("guild_id", "")
        cap = view._capital_pos(gid) if gid else None
        map_file = mmo_render_pillow(tiles, u["pos_x"], u["pos_y"], cap)
        em = view._make_embed(u, "ゲームへようこそ！移動ボタンで探索しましょう。")
        await interaction.followup.send(embed=em, file=map_file, view=view)

    # ══════════════════════════════════════════
    # ■ プレイヤー系コマンド（スラッシュ）
    # ══════════════════════════════════════════

    @app_commands.command(name="join", description="このサーバーの国家に参加します")
    async def cmd_join(self, interaction: discord.Interaction) -> None:
        uid = str(interaction.user.id)
        gid = str(interaction.guild_id)
        if self._get_user(uid):
            await interaction.response.send_message(
                "すでに国家に所属しています。移住は `/immigrate` を使用してください。", ephemeral=True)
            return
        g = self._ensure_guild(gid)
        sx, sy = g.get("capital_x", 0), g.get("capital_y", 0)
        existing_citizens = self.db.table("users").select("user_id").eq("guild_id", gid).execute().data or []
        assigned_role = "king" if len(existing_citizens) == 0 else "citizen"
        self.db.table("users").insert({
            "user_id": uid, "guild_id": gid,
            "coins": INITIAL_COINS, "hunger": INITIAL_HUNGER,
            "pos_x": sx, "pos_y": sy, "role": assigned_role,
        }).execute()
        role_text = "👑 国王" if assigned_role == "king" else "国民"
        embed = discord.Embed(
            title="🎉 参加完了",
            color=discord.Color.green(),
            description=f"国家 `{gid}` に参加！\n役職: **{role_text}**\n初期所持金: **{INITIAL_COINS}コイン**\n出現地: ({sx}, {sy})\n\n`/playmmo` でゲーム画面を開けます！"
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="transfer_king", description="【国王専用】国王の座を他の国民に譲渡します")
    @app_commands.describe(target="譲渡対象の国民")
    async def cmd_transfer_king(self, interaction: discord.Interaction, target: discord.Member) -> None:
        uid = str(interaction.user.id)
        gid = str(interaction.guild_id)
        target_uid = str(target.id)
        current_user = self._get_user(uid)
        if not current_user or current_user.get("guild_id") != gid or current_user.get("role") != "king":
            await interaction.response.send_message("❌ このコマンドは国王のみが実行できます。", ephemeral=True)
            return
        if uid == target_uid:
            await interaction.response.send_message("❌ 自分自身に国王を譲渡することはできません。", ephemeral=True)
            return
        target_user = self._get_user(target_uid)
        if not target_user or target_user.get("guild_id") != gid:
            await interaction.response.send_message("❌ 対象のユーザーはこの国家の国民ではありません。", ephemeral=True)
            return
        self.db.table("users").update({"role": "king"}).eq("user_id", target_uid).execute()
        self.db.table("users").update({"role": "citizen"}).eq("user_id", uid).execute()
        embed = discord.Embed(
            title="👑 国王位譲渡", color=discord.Color.gold(),
            description=f"{interaction.user.mention} 様から {target.mention} へ国王の座が譲渡されました！"
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="transfer_item", description="手持ちのアイテムを他のプレイヤーに譲渡します")
    @app_commands.describe(target="譲渡先のプレイヤー", item_id="アイテムID", quantity="数量")
    async def cmd_transfer_item(self, interaction: discord.Interaction,
                                target: discord.Member, item_id: str, quantity: int) -> None:
        uid = str(interaction.user.id)
        target_uid = str(target.id)
        u = self._get_user(uid)
        if not u:
            await interaction.response.send_message("❌ `/join` で参加してください。", ephemeral=True)
            return
        if not self._get_user(target_uid):
            await interaction.response.send_message("❌ 譲渡対象はゲームに参加していません。", ephemeral=True)
            return
        if uid == target_uid:
            await interaction.response.send_message("❌ 自分自身には譲渡できません。", ephemeral=True)
            return
        if quantity <= 0:
            await interaction.response.send_message("❌ 数量は1以上を指定してください。", ephemeral=True)
            return
        if not self._consume_stack_item(uid, item_id, quantity):
            await interaction.response.send_message(f"❌ `{item_id}` が不足しています。", ephemeral=True)
            return
        self._add_stack_item(target_uid, item_id, quantity)
        embed = discord.Embed(title="🎁 アイテム譲渡完了", color=discord.Color.green(),
            description=f"{interaction.user.mention} から {target.mention} へ `{item_id}` × {quantity} を譲渡しました。")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="maintain", description="マスのHPを国庫から回復します（大臣以上）")
    @app_commands.describe(x="X座標", y="Y座標")
    async def cmd_maintain(self, interaction: discord.Interaction, x: int, y: int) -> None:
        gid = str(interaction.guild_id)
        uid = str(interaction.user.id)
        err = self._require_role(uid, gid, {"king", "minister"})
        if err:
            await interaction.response.send_message(err)
            return
        tile = self._get_tile(x, y)
        if not tile or tile.get("owner_guild_id") != gid:
            await interaction.response.send_message("自国領土ではありません。")
            return
        g = self._ensure_guild(gid)
        count = len(self.db.table("tiles").select("x").eq("owner_guild_id", gid).execute().data or [])
        cost = calc_maintenance_cost(count)
        if g["treasury_coins"] < cost:
            await interaction.response.send_message(
                f"国庫不足（必要: {cost}コイン, 残高: {g['treasury_coins']}コイン）。")
            return
        if tile["tile_type"] == "farm":
            end = (discord.utils.utcnow() + datetime.timedelta(hours=FARM_REPAIR_HOURS)).isoformat()
            self.db.table("tiles").update({
                "under_maintenance": True, "maintenance_end_time": end
            }).eq("x", x).eq("y", y).execute()
            self.db.table("guilds").update({
                "treasury_coins": g["treasury_coins"] - cost
            }).eq("guild_id", gid).execute()
            await interaction.response.send_message(
                f"ファーム修復開始（{FARM_REPAIR_HOURS}時間後完了）。費用: {cost}コイン")
        else:
            self.db.table("tiles").update({"hp": tile["max_hp"]}).eq("x", x).eq("y", y).execute()
            self.db.table("guilds").update({
                "treasury_coins": g["treasury_coins"] - cost
            }).eq("guild_id", gid).execute()
            await interaction.response.send_message(f"({x}, {y}) HP全回復。費用: {cost}コイン")

    @app_commands.command(name="distribute", description="国庫倉庫から食材を国民に配布します（大臣以上）")
    @app_commands.describe(target="配布先ユーザー", item_id="食材ID", quantity="数量")
    async def cmd_distribute(self, interaction: discord.Interaction,
                             target: discord.Member, item_id: str, quantity: int) -> None:
        gid = str(interaction.guild_id)
        err = self._require_role(str(interaction.user.id), gid, {"king", "minister"})
        if err:
            await interaction.response.send_message(err)
            return
        if quantity <= 0:
            await interaction.response.send_message("数量は1以上を指定してください。")
            return
        if not self._consume_stack_item(gid, item_id, quantity):
            await interaction.response.send_message(f"国庫倉庫に {item_id} × {quantity} がありません。")
            return
        self._add_stack_item(str(target.id), item_id, quantity)
        await interaction.response.send_message(
            f"✅ {target.mention} に **{item_id} × {quantity}** を配布しました。")

    @app_commands.command(name="craft", description="料理・武器をクラフトします")
    @app_commands.describe(item_id="クラフトするアイテムID", custom_name="料理名（任意）")
    async def cmd_craft(self, interaction: discord.Interaction,
                        item_id: str, custom_name: str = "") -> None:
        uid = str(interaction.user.id)
        u = self._get_user(uid)
        if not u:
            await interaction.response.send_message("`/join` で参加してください。")
            return
        item = self.db.table("items").select("*").eq(
            "item_id", item_id).maybe_single().execute().data
        if not item or item["type"] not in {"food", "weapon", "block"}:
            await interaction.response.send_message("クラフト可能なアイテムIDではありません。")
            return
        recipe: dict = item.get("recipe") or {}
        if not recipe:
            await interaction.response.send_message("このアイテムはレシピがありません。")
            return
        missing = [f"{k} × {v}" for k, v in recipe.items()
                   if not (self.db.table("item_inventories").select("quantity").eq(
                       "owner_id", uid).eq("item_id", k).maybe_single().execute().data or {}).get("quantity", 0) >= v]
        if missing:
            await interaction.response.send_message(f"素材不足: {', '.join(missing)}")
            return
        for k, v in recipe.items():
            self._consume_stack_item(uid, k, v)
        iv = roll_iv(u.get("chef_level", 1))
        name = custom_name.strip() or item["name"]
        self.db.table("item_instances").insert({
            "instance_id": str(uuid.uuid4()), "item_id": item_id,
            "owner_id": uid, "custom_name": name,
            "quality_iv": iv, "price": 0, "crafted_by": uid, "on_sale": False,
        }).execute()
        embed = discord.Embed(title="🍳 クラフト成功", color=discord.Color.gold())
        embed.add_field(name="作成品",    value=name)
        embed.add_field(name="個体値 IV", value=f"**{iv}** / 100")
        if item.get("base_recovery", 0) > 0:
            embed.add_field(name="回復量", value=f"{calc_recovery(item['base_recovery'], iv)} スタミナ")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="list_food", description="料理を飯屋に陳列します")
    @app_commands.describe(instance_id="料理インスタンスID", price="販売価格（コイン）")
    async def cmd_list_food(self, interaction: discord.Interaction,
                            instance_id: str, price: int) -> None:
        uid = str(interaction.user.id)
        if price <= 0:
            await interaction.response.send_message("価格は1以上を指定してください。")
            return
        inst = self.db.table("item_instances").select("*").eq(
            "instance_id", instance_id).eq("owner_id", uid).maybe_single().execute().data
        if not inst:
            await interaction.response.send_message("所持していないアイテムです。")
            return
        u = self._get_user(uid)
        tile = self._get_tile(u["pos_x"], u["pos_y"])
        if not tile or tile["tile_type"] != "restaurant" or tile.get("owner_user_id") != uid:
            await interaction.response.send_message("自分が経営する飯屋マスにいる必要があります。")
            return
        self.db.table("item_instances").update({
            "price": price, "on_sale": True,
            "owner_id": f"{u['pos_x']}_{u['pos_y']}",
        }).eq("instance_id", instance_id).execute()
        await interaction.response.send_message(
            f"✅ **{inst['custom_name']}** を {price} コインで陳列しました。")

    @app_commands.command(name="buy_food", description="飯屋の料理を購入します")
    @app_commands.describe(instance_id="購入する料理のインスタンスID")
    async def cmd_buy_food(self, interaction: discord.Interaction, instance_id: str) -> None:
        uid = str(interaction.user.id)
        gid = str(interaction.guild_id)
        u = self._get_user(uid)
        if not u:
            await interaction.response.send_message("`/join` で参加してください。")
            return
        inst = self.db.table("item_instances").select("*").eq(
            "instance_id", instance_id).eq("on_sale", True).maybe_single().execute().data
        if not inst:
            await interaction.response.send_message("その料理は販売されていません。")
            return
        if u["coins"] < inst["price"]:
            await interaction.response.send_message(
                f"コイン不足（必要: {inst['price']}, 所持: {u['coins']}）。")
            return
        seller_pos = inst["owner_id"]
        sx, sy = map(int, seller_pos.split("_"))
        seller_tile = self._get_tile(sx, sy)
        seller_uid = seller_tile.get("owner_user_id") if seller_tile else None
        self.db.table("users").update({"coins": u["coins"] - inst["price"]}).eq("user_id", uid).execute()
        if seller_uid:
            net, _ = self._apply_tax(gid, inst["price"])
            su = self._get_user(seller_uid)
            if su:
                self.db.table("users").update({"coins": su["coins"] + net}).eq("user_id", seller_uid).execute()
        self.db.table("item_instances").update({
            "owner_id": uid, "on_sale": False, "price": 0
        }).eq("instance_id", instance_id).execute()
        im = self.db.table("items").select("base_recovery").eq(
            "item_id", inst["item_id"]).maybe_single().execute().data
        rec = calc_recovery(im["base_recovery"] if im else 0, inst["quality_iv"])
        await interaction.response.send_message(
            f"🍽️ **{inst['custom_name']}** を購入（{inst['price']}コイン）。\nIV: {inst['quality_iv']} / 回復量: {rec}")

    @app_commands.command(name="eat", description="料理を食べてスタミナを回復します")
    @app_commands.describe(instance_id="食べる料理のインスタンスID")
    async def cmd_eat(self, interaction: discord.Interaction, instance_id: str) -> None:
        uid = str(interaction.user.id)
        u = self._get_user(uid)
        if not u:
            await interaction.response.send_message("`/join` で参加してください。")
            return
        inst = self.db.table("item_instances").select("*").eq(
            "instance_id", instance_id).eq("owner_id", uid).maybe_single().execute().data
        if not inst:
            await interaction.response.send_message("所持していない料理です。")
            return
        im = self.db.table("items").select("base_recovery,type").eq(
            "item_id", inst["item_id"]).maybe_single().execute().data
        if not im or im["type"] != "food":
            await interaction.response.send_message("食べ物ではありません。")
            return
        rec = calc_recovery(im["base_recovery"], inst["quality_iv"])
        new_hunger = min(HUNGER_MAX, u["hunger"] + rec)
        self.db.table("users").update({"hunger": new_hunger}).eq("user_id", uid).execute()
        self.db.table("item_instances").delete().eq("instance_id", instance_id).execute()
        await interaction.response.send_message(
            f"🍴 **{inst['custom_name']}** を食べました！\nスタミナ: {u['hunger']} → **{new_hunger}** (+{rec})")

    @app_commands.command(name="chef_levelup", description="料理熟練度をレベルアップします")
    async def cmd_chef_levelup(self, interaction: discord.Interaction) -> None:
        uid = str(interaction.user.id)
        u = self._get_user(uid)
        if not u:
            await interaction.response.send_message("`/join` で参加してください。")
            return
        lv = u.get("chef_level", 1)
        cost = CHEF_LEVEL_UP_COST * lv
        if u["coins"] < cost:
            await interaction.response.send_message(f"コイン不足（必要: {cost}, 所持: {u['coins']}）。")
            return
        new_lv = lv + 1
        min_iv = min(99, (new_lv - 1) * CHEF_LEVEL_IV_BONUS)
        self.db.table("users").update({
            "coins": u["coins"] - cost, "chef_level": new_lv
        }).eq("user_id", uid).execute()
        await interaction.response.send_message(
            f"👨‍🍳 料理熟練度 **Lv {new_lv}**！IV下限 **{min_iv}** 以上が保証されます。")

    @app_commands.command(name="set_tax", description="所得税率を設定します（0〜50%）")
    @app_commands.describe(rate="税率（整数パーセント）")
    async def cmd_set_tax(self, interaction: discord.Interaction, rate: int) -> None:
        gid = str(interaction.guild_id)
        err = self._require_role(str(interaction.user.id), gid, {"king", "minister"})
        if err:
            await interaction.response.send_message(err)
            return
        if not (0 <= rate <= 50):
            await interaction.response.send_message("税率は 0〜50 で指定してください。")
            return
        self.db.table("guilds").update({"tax_rate": rate / 100}).eq("guild_id", gid).execute()
        await interaction.response.send_message(f"✅ 所得税率を **{rate}%** に設定しました。")

    @app_commands.command(name="set_labor_reward", description="国策労働給料を設定します")
    @app_commands.describe(amount="給料（コイン）")
    async def cmd_set_labor_reward(self, interaction: discord.Interaction, amount: int) -> None:
        gid = str(interaction.guild_id)
        err = self._require_role(str(interaction.user.id), gid, {"king", "minister"})
        if err:
            await interaction.response.send_message(err)
            return
        if not (MIN_LABOR_REWARD <= amount <= MAX_LABOR_REWARD):
            await interaction.response.send_message(
                f"給料は {MIN_LABOR_REWARD}〜{MAX_LABOR_REWARD} の範囲で指定してください。")
            return
        self.db.table("guilds").update({"labor_reward": amount}).eq("guild_id", gid).execute()
        await interaction.response.send_message(f"✅ 国策労働給料を **{amount} コイン** に設定しました。")

    @app_commands.command(name="set_entry_fee", description="入国料を設定します")
    @app_commands.describe(amount="入国料（コイン）")
    async def cmd_set_entry_fee(self, interaction: discord.Interaction, amount: int) -> None:
        gid = str(interaction.guild_id)
        err = self._require_role(str(interaction.user.id), gid, {"king", "minister"})
        if err:
            await interaction.response.send_message(err)
            return
        if amount < 0:
            await interaction.response.send_message("入国料は0以上を指定してください。")
            return
        self.db.table("guilds").update({"entry_fee": amount}).eq("guild_id", gid).execute()
        await interaction.response.send_message(f"✅ 入国料を **{amount} コイン** に設定しました。")

    @app_commands.command(name="set_exit_fee", description="出国税率を設定します（0〜80%）")
    @app_commands.describe(rate="出国税率（整数パーセント）")
    async def cmd_set_exit_fee(self, interaction: discord.Interaction, rate: int) -> None:
        gid = str(interaction.guild_id)
        err = self._require_role(str(interaction.user.id), gid, {"king", "minister"})
        if err:
            await interaction.response.send_message(err)
            return
        if not (0 <= rate <= 80):
            await interaction.response.send_message("出国税率は 0〜80 で指定してください。")
            return
        self.db.table("guilds").update({"exit_fee_rate": rate / 100}).eq("guild_id", gid).execute()
        await interaction.response.send_message(f"✅ 出国税率を **{rate}%** に設定しました。")

    @app_commands.command(name="appoint", description="国民を大臣に任命します（国王専用）")
    @app_commands.describe(target="任命するメンバー")
    async def cmd_appoint(self, interaction: discord.Interaction, target: discord.Member) -> None:
        gid = str(interaction.guild_id)
        err = self._require_role(str(interaction.user.id), gid, {"king"})
        if err:
            await interaction.response.send_message(err)
            return
        tu = self._get_user(str(target.id))
        if not tu or tu.get("guild_id") != gid:
            await interaction.response.send_message("対象者はこの国の国民ではありません。")
            return
        self.db.table("users").update({"role": "minister"}).eq("user_id", str(target.id)).execute()
        await interaction.response.send_message(f"✅ {target.mention} を **大臣** に任命しました。")

    @app_commands.command(name="dismiss", description="大臣を一般市民に戻します（国王専用）")
    @app_commands.describe(target="解任するメンバー")
    async def cmd_dismiss(self, interaction: discord.Interaction, target: discord.Member) -> None:
        gid = str(interaction.guild_id)
        err = self._require_role(str(interaction.user.id), gid, {"king"})
        if err:
            await interaction.response.send_message(err)
            return
        self.db.table("users").update({"role": "citizen"}).eq("user_id", str(target.id)).execute()
        await interaction.response.send_message(f"✅ {target.mention} を一般市民に戻しました。")

    @app_commands.command(name="immigrate", description="別のサーバー（国家）に移住します")
    @app_commands.describe(target_guild_id="移住先のサーバーID")
    async def cmd_immigrate(self, interaction: discord.Interaction, target_guild_id: str) -> None:
        uid = str(interaction.user.id)
        u = self._get_user(uid)
        if not u:
            await interaction.response.send_message("`/join` で参加してください。")
            return
        old_gid = u.get("guild_id")
        if old_gid == target_guild_id:
            await interaction.response.send_message("すでにその国家に所属しています。")
            return
        tg = self._get_guild(target_guild_id)
        if not tg:
            await interaction.response.send_message("移住先の国家が見つかりません。")
            return
        exit_rate = (self._get_guild(old_gid) or {}).get("exit_fee_rate", 0.0) if old_gid else 0.0
        exit_fee = int(u["coins"] * exit_rate)
        entry_fee = tg.get("entry_fee", 0)
        total_cost = exit_fee + entry_fee
        if u["coins"] < total_cost:
            await interaction.response.send_message(
                f"コイン不足。出国税: {exit_fee} / 入国料: {entry_fee} / 合計: {total_cost}\n所持: {u['coins']} コイン")
            return
        view = ImmigrationConfirmView(u, old_gid, tg, exit_fee, entry_fee, self.db)
        embed = discord.Embed(title="🛂 移住確認", color=discord.Color.orange(),
            description=(
                f"移住先: `{target_guild_id}`\n"
                f"出国税 ({int(exit_rate*100)}%): **{exit_fee} コイン**\n"
                f"入国料: **{entry_fee} コイン** / 合計: **{total_cost} コイン**\n\n実行しますか？"))
        await interaction.response.send_message(embed=embed, view=view)

    @app_commands.command(name="alliance_request", description="他国と同盟を締結します（国王専用）")
    @app_commands.describe(target_guild_id="同盟先のサーバーID")
    async def cmd_alliance_request(self, interaction: discord.Interaction, target_guild_id: str) -> None:
        gid = str(interaction.guild_id)
        err = self._require_role(str(interaction.user.id), gid, {"king"})
        if err:
            await interaction.response.send_message(err)
            return
        tg = self._get_guild(target_guild_id)
        if not tg:
            await interaction.response.send_message("対象の国家が見つかりません。")
            return
        mg = self._get_guild(gid)
        al = list(mg.get("alliances") or [])
        if target_guild_id in al:
            await interaction.response.send_message("すでに同盟を結んでいます。")
            return
        al.append(target_guild_id)
        self.db.table("guilds").update({"alliances": al}).eq("guild_id", gid).execute()
        tal = list(tg.get("alliances") or [])
        tal.append(gid)
        self.db.table("guilds").update({"alliances": tal}).eq("guild_id", target_guild_id).execute()
        await interaction.response.send_message(f"✅ `{target_guild_id}` と同盟を締結しました。")

    @app_commands.command(name="build_railway", description="現在地に線路を敷設します（大臣以上）")
    async def cmd_build_railway(self, interaction: discord.Interaction) -> None:
        uid = str(interaction.user.id)
        gid = str(interaction.guild_id)
        err = self._require_role(uid, gid, {"king", "minister"})
        if err:
            await interaction.response.send_message(err)
            return
        g = self._get_guild(gid)
        if not g or g["treasury_coins"] < RAILWAY_BUILD_COST:
            await interaction.response.send_message(
                f"国庫不足（必要: {RAILWAY_BUILD_COST} コイン）。")
            return
        u = self._get_user(uid)
        cx, cy = u["pos_x"], u["pos_y"]
        if self._get_railway(cx, cy):
            await interaction.response.send_message(f"({cx}, {cy}) にはすでに線路があります。")
            return
        self.db.table("railways").insert({
            "x": cx, "y": cy, "owner_guild_id": gid,
            "permissions": "all", "blacklist_guilds": [], "fare": 0,
        }).execute()
        self.db.table("tiles").upsert({
            "x": cx, "y": cy, "owner_guild_id": gid,
            "tile_type": "railway", "hp": 100, "max_hp": 100, "def": 0, "connected": True,
        }).execute()
        self.db.table("guilds").update({
            "treasury_coins": g["treasury_coins"] - RAILWAY_BUILD_COST
        }).eq("guild_id", gid).execute()
        await interaction.response.send_message(
            f"🛤️ ({cx}, {cy}) に線路を敷設しました（費用: {RAILWAY_BUILD_COST} コイン）。")

    @app_commands.command(name="warp", description="線路を使って指定座標にワープします")
    @app_commands.describe(x="移動先X座標", y="移動先Y座標")
    async def cmd_warp(self, interaction: discord.Interaction, x: int, y: int) -> None:
        await interaction.response.defer()
        uid = str(interaction.user.id)
        u = self._get_user(uid)
        if not u:
            await interaction.followup.send("`/join` で参加してください。")
            return
        if u["hunger"] <= 0:
            await interaction.followup.send("スタミナ 0 です。食事で回復してください。")
            return
        gid = u.get("guild_id", "")
        g = self._get_guild(gid) if gid else None
        alliances = list(g.get("alliances") or []) if g else []
        reachable, _ = self._rail_reachable(gid, x, y, alliances)
        if not reachable:
            await interaction.followup.send(f"({x}, {y}) へは線路で到達できません。")
            return
        total_fare = 0
        dest_rail = self._get_railway(x, y)
        if dest_rail:
            owner = dest_rail.get("owner_guild_id")
            if owner and owner != gid:
                fare = dest_rail.get("fare", 0)
                if fare > 0 and u["coins"] >= fare:
                    self.db.table("users").update({
                        "coins": u["coins"] - fare
                    }).eq("user_id", uid).execute()
                    og = self._get_guild(owner)
                    if og:
                        self.db.table("guilds").update({
                            "treasury_coins": og["treasury_coins"] + fare
                        }).eq("guild_id", owner).execute()
                    total_fare = fare
        self.db.table("users").update({"pos_x": x, "pos_y": y}).eq("user_id", uid).execute()
        msg = f"🚄 ({x}, {y}) にワープしました！"
        if total_fare > 0:
            msg += f"\n通行料: {total_fare} コイン 徴収されました。"
        await interaction.followup.send(msg)

    @app_commands.command(name="upgrade_def", description="マスのDEFを永続強化します（大臣以上）")
    @app_commands.describe(x="X座標", y="Y座標")
    async def cmd_upgrade_def(self, interaction: discord.Interaction, x: int, y: int) -> None:
        gid = str(interaction.guild_id)
        err = self._require_role(str(interaction.user.id), gid, {"king", "minister"})
        if err:
            await interaction.response.send_message(err)
            return
        tile = self._get_tile(x, y)
        if not tile or tile.get("owner_guild_id") != gid:
            await interaction.response.send_message("自国領土ではありません。")
            return
        if tile["def"] >= DEF_MAX_PERMANENT:
            await interaction.response.send_message(
                f"DEFはすでに最大値（{DEF_MAX_PERMANENT}）です。")
            return
        g = self._get_guild(gid)
        if not g or g["treasury_coins"] < DEF_UPGRADE_COST:
            await interaction.response.send_message(
                f"国庫不足（必要: {DEF_UPGRADE_COST} コイン）。")
            return
        self.db.table("tiles").update({"def": tile["def"] + 1}).eq("x", x).eq("y", y).execute()
        self.db.table("guilds").update({
            "treasury_coins": g["treasury_coins"] - DEF_UPGRADE_COST
        }).eq("guild_id", gid).execute()
        await interaction.response.send_message(
            f"🛡️ ({x}, {y}) DEF → **{tile['def']+1}**（費用: {DEF_UPGRADE_COST} コイン）")

    @app_commands.command(name="place_block", description="レイドブロックを設置してDEFを一時強化します")
    @app_commands.describe(x="X座標", y="Y座標")
    async def cmd_place_block(self, interaction: discord.Interaction, x: int, y: int) -> None:
        uid = str(interaction.user.id)
        gid = str(interaction.guild_id)
        if self._get_user(uid).get("guild_id") != gid:
            await interaction.response.send_message("このサーバーの国民ではありません。")
            return
        tile = self._get_tile(x, y)
        if not tile or tile.get("owner_guild_id") != gid:
            await interaction.response.send_message("自国領土にのみ設置できます。")
            return
        if not self._consume_stack_item(uid, "raid_block", 1):
            await interaction.response.send_message(
                "レイドブロックを所持していません。`/craft` でクラフトしてください。")
            return
        ivs = dict(tile.get("individual_values") or {})
        ivs["raid_block_def"] = ivs.get("raid_block_def", 0) + RAID_BLOCK_DEF_BONUS
        self.db.table("tiles").update({"individual_values": ivs}).eq("x", x).eq("y", y).execute()
        await interaction.response.send_message(
            f"🧱 ({x}, {y}) にレイドブロック設置。DEF +{RAID_BLOCK_DEF_BONUS}")

    @app_commands.command(name="build_wall", description="平地を城壁マスにアップグレードします（大臣以上）")
    @app_commands.describe(x="X座標", y="Y座標")
    async def cmd_build_wall(self, interaction: discord.Interaction, x: int, y: int) -> None:
        gid = str(interaction.guild_id)
        err = self._require_role(str(interaction.user.id), gid, {"king", "minister"})
        if err:
            await interaction.response.send_message(err)
            return
        tile = self._get_tile(x, y)
        if not tile or tile.get("owner_guild_id") != gid:
            await interaction.response.send_message("自国領土ではありません。")
            return
        if tile["tile_type"] != "plain":
            await interaction.response.send_message("プレーン（平地）マスのみ城壁にできます。")
            return
        for mat, qty in [("iron_ore", 5), ("wood", 5)]:
            inv = self.db.table("item_inventories").select("quantity").eq(
                "owner_id", gid).eq("item_id", mat).maybe_single().execute().data
            if not inv or inv["quantity"] < qty:
                await interaction.response.send_message(
                    f"国庫倉庫の資材不足（{mat} × {qty} 必要）。")
                return
        for mat, qty in [("iron_ore", 5), ("wood", 5)]:
            self._consume_stack_item(gid, mat, qty)
        self.db.table("tiles").update({
            "tile_type": "wall", "hp": 500, "max_hp": 500, "def": 5,
        }).eq("x", x).eq("y", y).execute()
        await interaction.response.send_message(
            f"🧱 ({x}, {y}) を **城壁** に強化しました！HP: 500 / DEF: 5")

    @app_commands.command(name="set_railway_perm", description="線路の通行権限・通行料を設定します")
    @app_commands.describe(x="X座標", y="Y座標",
                           permissions="通行権限 (all/allies_only/citizens_only)",
                           fare="通行料（コイン）")
    async def cmd_set_railway_perm(self, interaction: discord.Interaction,
                                   x: int, y: int, permissions: str, fare: int = 0) -> None:
        gid = str(interaction.guild_id)
        err = self._require_role(str(interaction.user.id), gid, {"king", "minister"})
        if err:
            await interaction.response.send_message(err)
            return
        if permissions not in {"all", "allies_only", "citizens_only"}:
            await interaction.response.send_message(
                "権限は all / allies_only / citizens_only のいずれかを指定してください。")
            return
        rail = self._get_railway(x, y)
        if not rail or rail.get("owner_guild_id") != gid:
            await interaction.response.send_message("自国の線路ではありません。")
            return
        self.db.table("railways").update({
            "permissions": permissions, "fare": max(0, fare)
        }).eq("x", x).eq("y", y).execute()
        await interaction.response.send_message(
            f"✅ ({x}, {y}) 線路更新。権限: {permissions} / 通行料: {fare} コイン")

    @app_commands.command(name="railway_blacklist", description="線路通行ブラックリストを管理します")
    @app_commands.describe(x="X座標", y="Y座標",
                           target_guild_id="対象サーバーID", action="add または remove")
    async def cmd_railway_blacklist(self, interaction: discord.Interaction,
                                    x: int, y: int, target_guild_id: str, action: str) -> None:
        gid = str(interaction.guild_id)
        err = self._require_role(str(interaction.user.id), gid, {"king", "minister"})
        if err:
            await interaction.response.send_message(err)
            return
        if action not in {"add", "remove"}:
            await interaction.response.send_message("action は add または remove を指定してください。")
            return
        rail = self._get_railway(x, y)
        if not rail or rail.get("owner_guild_id") != gid:
            await interaction.response.send_message("自国の線路ではありません。")
            return
        bl = list(rail.get("blacklist_guilds") or [])
        if action == "add" and target_guild_id not in bl:
            bl.append(target_guild_id)
        elif action == "remove" and target_guild_id in bl:
            bl.remove(target_guild_id)
        self.db.table("railways").update({"blacklist_guilds": bl}).eq("x", x).eq("y", y).execute()
        await interaction.response.send_message(f"✅ ({x}, {y}) ブラックリスト更新: {bl}")

    @app_commands.command(name="railway_info", description="指定座標の線路情報を表示します")
    @app_commands.describe(x="X座標", y="Y座標")
    async def cmd_railway_info(self, interaction: discord.Interaction, x: int, y: int) -> None:
        rail = self._get_railway(x, y)
        if not rail:
            await interaction.response.send_message(f"({x}, {y}) に線路はありません。")
            return
        bl = rail.get("blacklist_guilds") or []
        embed = discord.Embed(title=f"🛤️ 線路情報 ({x}, {y})", color=discord.Color.blue())
        embed.add_field(name="所有国",       value=rail.get("owner_guild_id") or "不明")
        embed.add_field(name="通行権限",     value=rail.get("permissions", "all"))
        embed.add_field(name="通行料",       value=f"{rail.get('fare', 0)} コイン")
        embed.add_field(name="ブラックリスト", value=", ".join(bl) if bl else "なし")
        await interaction.response.send_message(embed=embed)

    # ══════════════════════════════════════════
    # ■ 定期タスク
    # ══════════════════════════════════════════

    @tasks.loop(hours=1)
    async def hunger_decay_task(self) -> None:
        res = self.db.table("users").select("user_id,hunger,on_duty_x").execute()
        for u in (res.data or []):
            mult = DUTY_HUNGER_MULTIPLIER if u.get("on_duty_x") is not None else 1
            new_hunger = max(HUNGER_MIN, u["hunger"] - HUNGER_DECAY_PER_HOUR * mult)
            self.db.table("users").update({"hunger": new_hunger}).eq("user_id", u["user_id"]).execute()

    @tasks.loop(minutes=10)
    async def farm_maintenance_task(self) -> None:
        now = discord.utils.utcnow().isoformat()
        res = self.db.table("tiles").select("x,y,max_hp").eq(
            "under_maintenance", True).lte("maintenance_end_time", now).execute()
        for tile in (res.data or []):
            self.db.table("tiles").update({
                "hp": tile["max_hp"],
                "under_maintenance": False,
                "maintenance_end_time": None,
            }).eq("x", tile["x"]).eq("y", tile["y"]).execute()

    @tasks.loop(minutes=5)
    async def capture_check_task(self) -> None:
        res = self.db.table("tiles").select("x,y").eq("hp", 0).neq("owner_guild_id", None).execute()
        for tile in (res.data or []):
            self.db.table("tiles").update({"def": CAPTURE_RESET_DEF}).eq(
                "x", tile["x"]).eq("y", tile["y"]).execute()


# ══════════════════════════════════════════════════════════════
# ■ セットアップ
# ══════════════════════════════════════════════════════════════

async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(MMOCog(bot))
