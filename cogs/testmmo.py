
from __future__ import annotations
import datetime
import random
import uuid
import math
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands, tasks
from supabase import Client

# ══════════════════════════════════════════════════════════════
# ■ 定数
# ══════════════════════════════════════════════════════════════

# --- マップ ---
MAP_SIZE_X             = 200
MAP_SIZE_Y             = 200
VIEW_RADIUS            = 3

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
INITIAL_HUNGER         = 100
HUNGER_MAX             = 100
HUNGER_MIN             = 0
HUNGER_DECAY_PER_HOUR  = 5
HUNGER_COST_MOVE       = 10
HUNGER_COST_LABOR      = 20
HUNGER_COST_RAID       = 20
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

# --- タイル絵文字 ---
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

# ══════════════════════════════════════════════════════════════
# ■ 純粋ヘルパー関数
# ══════════════════════════════════════════════════════════════

def _fade(t: float) -> float:
    """Perlinノイズ用の5次エルミート補間（なめらかにする計算）"""
    return t * t * t * (t * (t * 6.0 - 15.0) + 10.0)

def _lerp(t: float, a: float, b: float) -> float:
    """線形補間"""
    return a + t * (b - a)

def _dot_grid_gradient(ix: int, iy: int, x: float, y: float, seed: int) -> float:
    """格子点(ix, iy)のランダムな勾配ベクトルと、点(x, y)へのベクトルとの内積を計算"""
    state = (ix * 1836311903 + iy * 2971215073 + seed * 42342347) & 0xFFFFFFFF
    rg = random.Random(state)
    angle = rg.random() * 2.0 * math.pi
    dx = math.cos(angle)
    dy = math.sin(angle)
    xf = x - float(ix)
    yf = y - float(iy)
    return (xf * dx + yf * dy)

def get_perlin_noise(x: float, y: float, seed: int) -> float:
    """指定した座標(x, y)におけるPerlinノイズの値を返します"""
    x0 = math.floor(x)
    x1 = x0 + 1
    y0 = math.floor(y)
    y1 = y0 + 1
    sx = _fade(x - float(x0))
    sy = _fade(y - float(y0))
    n00 = _dot_grid_gradient(x0, y0, x, y, seed)
    n10 = _dot_grid_gradient(x1, y0, x, y, seed)
    n01 = _dot_grid_gradient(x0, y1, x, y, seed)
    n11 = _dot_grid_gradient(x1, y1, x, y, seed)
    ix0 = _lerp(sx, n00, n10)
    ix1 = _lerp(sx, n01, n11)
    return _lerp(sy, ix0, ix1)

def get_individual_value_perlin(x: int, y: int, seed: int = 0, max_iv: int = 31) -> int:
    """メイン関数：Perlinノイズを用いて座標(x, y)の個体値を 0 〜 max_iv の間で返します"""
    frequency = 15.0
    nx = x / frequency
    ny = y / frequency
    noise_val = get_perlin_noise(nx, ny, seed)
    normalized = (noise_val / 1.414) + 0.5
    normalized = max(0.0, min(1.0, normalized))
    return round(normalized * max_iv)
    
def calc_maintenance_cost(tile_count: int) -> int:
    return int(MAINTENANCE_BASE_COST * (MAINTENANCE_SCALE ** max(0, tile_count - 1)))

def generate_ivs(tile_type: str) -> dict:
    if tile_type == "farm":
        return {"fertility": random.randint(1, 100)}
    if tile_type == "mine":
        return {"purity": random.randint(1, 100)}
    return {"altitude": random.randint(0, 100)}

def render_map(tiles: list[dict], center_x: int, center_y: int) -> str:
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
    coins    = MINE_BASE_COIN + int(MINE_BASE_COIN * purity / 100)
    ore_drop = random.random() < (MINE_BASE_ORE_CHANCE + 0.005 * purity)
    return coins, ore_drop

def roll_iv(chef_level: int) -> int:
    minimum = min(99, (chef_level - 1) * CHEF_LEVEL_IV_BONUS)
    return random.randint(minimum, 100)

def hunger_bar(hunger: int) -> str:
    filled = hunger // 10
    return "🟩" * filled + "⬜" * (10 - filled)

# ══════════════════════════════════════════════════════════════
# ■ View クラス
# ══════════════════════════════════════════════════════════════

class ImmigrationConfirmView(discord.ui.View):
    def __init__(self, user: dict, old_gid: str, target_guild: dict,
                 exit_fee: int, entry_fee: int, db: Client):
        super().__init__(timeout=60)
        self.user         = user
        self.old_gid      = old_gid
        self.target_guild = target_guild
        self.exit_fee     = exit_fee
        self.entry_fee    = entry_fee
        self.db           = db

    @discord.ui.button(label="移住する", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        uid       = str(interaction.user.id)
        new_gid   = self.target_guild["guild_id"]
        new_coins = self.user["coins"] - self.exit_fee - self.entry_fee
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
        spawn_x = self.target_guild.get("capital_x", 0)
        spawn_y = self.target_guild.get("capital_y", 0)
        self.db.table("users").update({
            "guild_id": new_gid, "coins": new_coins,
            "role": "citizen", "pos_x": spawn_x, "pos_y": spawn_y,
        }).eq("user_id", uid).execute()
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(
            content=f"✅ `{new_gid}` へ移住しました。残コイン: {new_coins:,}",
            embed=None, view=self)

    @discord.ui.button(label="キャンセル", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(content="移住をキャンセルしました。",
                                                embed=None, view=self)

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
            def __getattr__(self, name):
                return getattr(self._db, name)

        self.db = SafeDB(self.bot.supabase)  # type: ignore
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
        res = self.db.table("guilds").select("*").eq(
            "guild_id", guild_id).maybe_single().execute()
        if res and res.data:  # ← res が None でないことも確認する
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
        """国庫に納税し (net, tax) を返す"""
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
        """首都からBFSで接続フラグを更新"""
        g = self.db.table("guilds").select("capital_x,capital_y").eq(
            "guild_id", guild_id).maybe_single().execute().data
        if not g:
            return
        owned = self.db.table("tiles").select("x,y,connected").eq(
            "owner_guild_id", guild_id).execute().data or []
        rails  = self.db.table("railways").select("x,y").eq(
            "owner_guild_id", guild_id).execute().data or []
        passable = {(t["x"], t["y"]) for t in owned} | {(r["x"], r["y"]) for r in rails}
        visited: set[tuple] = set()
        queue = [(g["capital_x"], g["capital_y"])]
        while queue:
            cx, cy = queue.pop(0)
            if (cx, cy) in visited:
                continue
            visited.add((cx, cy))
            for dx, dy in [(1,0),(-1,0),(0,1),(0,-1)]:
                nb = (cx+dx, cy+dy)
                if nb in passable and nb not in visited:
                    queue.append(nb)
        for t in owned:
            connected = (t["x"], t["y"]) in visited
            if t["connected"] != connected:
                self.db.table("tiles").update({"connected": connected}).eq(
                    "x", t["x"]).eq("y", t["y"]).execute()

    def _get_effective_def(self, tile: dict) -> int:
        base      = tile.get("def", 0)
        on_duty   = self.db.table("users").select("user_id").eq(
            "on_duty_x", tile["x"]).eq("on_duty_y", tile["y"]).execute().data or []
        duty_b    = DUTY_DEF_BONUS if on_duty else 0
        block_b   = (tile.get("individual_values") or {}).get("raid_block_def", 0)
        return min(DEF_MAX_WITH_BUFFS, base + duty_b + block_b)

    def _is_adjacent_to_guild(self, attacker_gid: str, tx: int, ty: int) -> bool:
        for dx, dy in [(1,0),(-1,0),(0,1),(0,-1)]:
            adj = self.db.table("tiles").select("owner_guild_id").eq(
                "x", tx+dx).eq("y", ty+dy).maybe_single().execute().data
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
        queue   = [(g["capital_x"], g["capital_y"])]
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
            for dx, dy in [(1,0),(-1,0),(0,1),(0,-1)]:
                nb = (cx+dx, cy+dy)
                if nb in visited:
                    continue
                nb_rail = rail_map.get(nb)
                if nb_rail is None:
                    continue
                perm  = nb_rail.get("permissions", "all")
                bl    = nb_rail.get("blacklist_guilds") or []
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
    # ■ プレイヤー系コマンド
    # ══════════════════════════════════════════

    @app_commands.command(name="join", description="このサーバーの国家に参加します")
    async def cmd_join(self, interaction: discord.Interaction) -> None:
        uid = str(interaction.user.id)
        gid = str(interaction.guild_id)
        if self._get_user(uid):
            await interaction.response.send_message(
                "すでに国家に所属しています。移住は `/immigrate` を使用してください。",
                ephemeral=True)
            return
        g = self._ensure_guild(gid)
        sx, sy = g.get("capital_x", 0), g.get("capital_y", 0)

        # サーバー（国家）に既に他のユーザーが所属しているかチェック
        existing_citizens = self.db.table("users").select("user_id").eq("guild_id", gid).execute().data or []
        
        # 最初の参加者なら国王(king)、それ以外は一般国民(citizen)にする
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
            description=f"国家 `{gid}` に参加！\n役職: **{role_text}**\n初期所持金: **{INITIAL_COINS}コイン** / 出現地: ({sx}, {sy})"
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="transfer_king", description="【国王専用】国王の座を他の国民に譲渡します")
    @app_commands.describe(target="譲渡対象の国民")
    async def cmd_transfer_king(self, interaction: discord.Interaction, target: discord.Member) -> None:
        uid = str(interaction.user.id)
        gid = str(interaction.guild_id)
        target_uid = str(target.id)

        # 1. 自分が国王であるかチェック
        current_user = self._get_user(uid)
        if not current_user or current_user.get("guild_id") != gid or current_user.get("role") != "king":
            await interaction.response.send_message("❌ このコマンドは国王のみが実行できます。", ephemeral=True)
            return

        # 2. 自分自身に譲渡しようとしていないかチェック
        if uid == target_uid:
            await interaction.response.send_message("❌ 自分自身に国王を譲渡することはできません。", ephemeral=True)
            return

        # 3. 譲渡対象が同じ国の国民かチェック
        target_user = self._get_user(target_uid)
        if not target_user or target_user.get("guild_id") != gid:
            await interaction.response.send_message("❌ 対象のユーザーはこの国家の国民ではありません。", ephemeral=True)
            return

        # 4. 役職の更新処理 (トランザクション的に2件とも確実にアップデート)
        # 対象者を国王に昇格
        self.db.table("users").update({"role": "king"}).eq("user_id", target_uid).execute()
        # 元の国王(自分)を一般国民に降格
        self.db.table("users").update({"role": "citizen"}).eq("user_id", uid).execute()

        embed = discord.Embed(
            title="👑 国王位譲渡",
            color=discord.Color.gold(),
            description=f"{interaction.user.mention} 様から {target.mention} へ国王の座が譲渡されました！\n"
                        f"新たな国王の誕生を称えましょう！"
        )
        await interaction.response.send_message(embed=embed)
    
    @app_commands.command(name="status", description="自分のステータスを確認します")
    async def cmd_status(self, interaction: discord.Interaction) -> None:
        u = self._get_user(str(interaction.user.id))
        if not u:
            await interaction.response.send_message("`/join` で参加してください。")
            return
        on_duty = f"({u['on_duty_x']}, {u['on_duty_y']})" if u.get("on_duty_x") is not None else "なし"
        embed = discord.Embed(title=f"📋 {interaction.user.display_name} のステータス",
                              color=discord.Color.blurple())
        embed.add_field(name="所持金",     value=f"{u['coins']:,} コイン")
        embed.add_field(name="スタミナ",   value=f"{hunger_bar(u['hunger'])}  {u['hunger']}/{HUNGER_MAX}")
        embed.add_field(name="現在地",     value=f"({u['pos_x']}, {u['pos_y']})")
        embed.add_field(name="所属国",     value=u.get("guild_id") or "無所属")
        embed.add_field(name="役職",       value=u.get("role", "citizen"))
        embed.add_field(name="料理熟練度", value=f"Lv {u.get('chef_level', 1)}")
        embed.add_field(name="当直中",     value=on_duty)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="move", description="隣接マスへ手動移動します（スタミナ-10）")
    @app_commands.describe(direction="移動方向 (north/south/east/west)")
    async def cmd_move(self, interaction: discord.Interaction, direction: str) -> None:
        DIRS = {"north": (0,-1), "south": (0,1), "east": (1,0), "west": (-1,0)}
        if direction not in DIRS:
            await interaction.response.send_message(
                "方向は north / south / east / west で指定してください。", ephemeral=True)
            return
        u = self._get_user(str(interaction.user.id))
        if not u:
            await interaction.response.send_message("`/join` で参加してください。")
            return
        if u["hunger"] <= HUNGER_MIN:
            await interaction.response.send_message("スタミナ 0 です。食事で回復してください。")
            return
        dx, dy = DIRS[direction]
        nx = max(0, min(MAP_SIZE_X - 1, u["pos_x"] + dx))
        ny = max(0, min(MAP_SIZE_Y - 1, u["pos_y"] + dy))
        new_hunger = max(HUNGER_MIN, u["hunger"] - HUNGER_COST_MOVE)
        self.db.table("users").update({
            "pos_x": nx, "pos_y": ny, "hunger": new_hunger
        }).eq("user_id", str(interaction.user.id)).execute()
        await interaction.response.send_message(
            f"**{direction}** へ移動 → ({nx}, {ny}) / スタミナ: {new_hunger}/{HUNGER_MAX}")

    @app_commands.command(name="duty", description="現在地で当直（警備）を開始/解除します")
    async def cmd_duty(self, interaction: discord.Interaction) -> None:
        uid = str(interaction.user.id)
        u   = self._get_user(uid)
        if not u:
            await interaction.response.send_message("`/join` で参加してください。")
            return
        if u.get("on_duty_x") is not None:
            self.db.table("users").update(
                {"on_duty_x": None, "on_duty_y": None}
            ).eq("user_id", uid).execute()
            await interaction.response.send_message("当直を解除しました。")
        else:
            tile = self._get_tile(u["pos_x"], u["pos_y"])
            if not tile or tile.get("owner_guild_id") != u["guild_id"]:
                await interaction.response.send_message("自国領土でのみ当直できます。")
                return
            self.db.table("users").update({
                "on_duty_x": u["pos_x"], "on_duty_y": u["pos_y"]
            }).eq("user_id", uid).execute()
            self.db.rpc("increment_tile_def", {
                "p_x": u["pos_x"], "p_y": u["pos_y"], "p_amount": DUTY_DEF_BONUS
            }).execute()
            await interaction.response.send_message(
                f"({u['pos_x']}, {u['pos_y']}) で当直開始。DEF +{DUTY_DEF_BONUS}\n"
                "⚠️ 当直中はスタミナ減少が2倍になります。")

    # ══════════════════════════════════════════
    # ■ マップ・タイル系コマンド
    # ══════════════════════════════════════════

    @app_commands.command(name="map", description="現在地周辺のマップを表示します")
    async def cmd_map(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        u = self._get_user(str(interaction.user.id))
        if not u:
            await interaction.followup.send("`/join` で参加してください。")
            return
        cx, cy = u["pos_x"], u["pos_y"]
        tiles  = self.db.table("tiles").select("x,y,tile_type,owner_guild_id") \
            .gte("x", cx - VIEW_RADIUS).lte("x", cx + VIEW_RADIUS) \
            .gte("y", cy - VIEW_RADIUS).lte("y", cy + VIEW_RADIUS).execute()
        embed  = discord.Embed(
            title=f"🗺️ マップ（中心: {cx}, {cy}）",
            description=f"```\n{render_map(tiles.data or [], cx, cy)}\n```",
            color=discord.Color.green())
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="tileinfo", description="指定座標のマス情報を表示します")
    @app_commands.describe(x="X座標", y="Y座標")
    async def cmd_tileinfo(self, interaction: discord.Interaction, x: int, y: int) -> None:
        tile = self._get_tile(x, y)
        if not tile:
            await interaction.response.send_message(f"({x}, {y}) は未開拓地です。")
            return
        embed = discord.Embed(
            title=f"{TILE_EMOJI.get(tile['tile_type'], '❓')} タイル情報 ({x}, {y})",
            color=discord.Color.blurple())
        embed.add_field(name="種別",     value=tile["tile_type"])
        embed.add_field(name="HP",       value=f"{tile['hp']} / {tile['max_hp']}")
        embed.add_field(name="DEF",      value=str(tile["def"]))
        embed.add_field(name="接続状態", value="✅" if tile["connected"] else "❌")
        embed.add_field(name="個体値",   value=str(tile.get("individual_values") or {}))
        embed.add_field(name="所有国",   value=tile.get("owner_guild_id") or "（未所有）")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="develop", description="現在地のマスを開拓します（スタミナ-20）")
    @app_commands.describe(tile_type="施設種別 (farm/mine/shop/casino/restaurant/wall)")
    async def cmd_develop(self, interaction: discord.Interaction, tile_type: str) -> None:
        VALID = {"farm", "mine", "shop", "casino", "restaurant", "wall"}
        if tile_type not in VALID:
            await interaction.response.send_message(
                f"無効な種別です。選択肢: {', '.join(VALID)}", ephemeral=True)
            return
        uid = str(interaction.user.id)
        gid = str(interaction.guild_id)
        u   = self.db.table("users").select("pos_x,pos_y,hunger,guild_id").eq(
            "user_id", uid).maybe_single().execute().data
        if not u:
            await interaction.response.send_message("`/join` で参加してください。")
            return
        if u["guild_id"] != gid:
            await interaction.response.send_message("このサーバーの国民ではありません。")
            return
        if u["hunger"] < 20:
            await interaction.response.send_message("スタミナが不足しています（20必要）。")
            return
        existing = self._get_tile(u["pos_x"], u["pos_y"])
        if existing and existing.get("owner_guild_id"):
            await interaction.response.send_message("そのマスはすでに占有されています。")
            return
        ivs     = generate_ivs(tile_type)
        hp      = WALL_HP    if tile_type == "wall" else PLAIN_HP
        max_hp  = WALL_MAX_HP if tile_type == "wall" else PLAIN_HP
        base_def = WALL_BASE_DEF if tile_type == "wall" else DEFAULT_DEF
        self.db.table("tiles").upsert({
            "x": u["pos_x"], "y": u["pos_y"],
            "owner_guild_id": gid,
            "owner_user_id":  uid if tile_type not in {"farm", "mine"} else None,
            "tile_type": tile_type, "individual_values": ivs,
            "hp": hp, "max_hp": max_hp, "def": base_def, "connected": False,
        }).execute()
        self.db.table("users").update({"hunger": u["hunger"] - 20}).eq("user_id", uid).execute()
        self._update_connections(gid)
        embed = discord.Embed(title="🏗️ 開拓完了", color=discord.Color.gold(),
            description=f"({u['pos_x']}, {u['pos_y']}) を **{tile_type}** に開拓！\n個体値: {ivs}")
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
        g     = self._ensure_guild(gid)
        count = len(self.db.table("tiles").select("x").eq("owner_guild_id", gid).execute().data or [])
        cost  = calc_maintenance_cost(count)
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
            await interaction.response.send_message(
                f"({x}, {y}) HP全回復。費用: {cost}コイン")

    # ══════════════════════════════════════════
    # ■ 経済系コマンド
    # ══════════════════════════════════════════

    @app_commands.command(name="farm_work", description="現在地のファームで国策労働します")
    async def cmd_farm_work(self, interaction: discord.Interaction) -> None:
        uid = str(interaction.user.id)
        gid = str(interaction.guild_id)
        u   = self._get_user(uid)
        if not u:
            await interaction.response.send_message("`/join` で参加してください。")
            return
        if u["hunger"] < HUNGER_COST_LABOR:
            await interaction.response.send_message(f"スタミナ不足（必要: {HUNGER_COST_LABOR}）。")
            return
        tile = self._get_tile(u["pos_x"], u["pos_y"])
        if not tile or tile["tile_type"] != "farm":
            await interaction.response.send_message("現在地はファームではありません。")
            return
        if not tile["connected"]:
            await interaction.response.send_message("首都と接続されていません（サプライライン未整備）。")
            return
        if tile.get("under_maintenance"):
            await interaction.response.send_message("このファームはメンテナンス中です。")
            return
        g = self._get_guild(gid)
        if not g or g["treasury_coins"] < g["labor_reward"]:
            await interaction.response.send_message("国庫が不足しており給料を支払えません。")
            return
        fertility = (tile.get("individual_values") or {}).get("fertility", 50)
        yield_qty = calc_farm_yield(fertility)
        is_foreign  = u["guild_id"] != tile["owner_guild_id"]
        reward      = g["labor_reward"]
        foreign_fee = int(reward * 0.20) if is_foreign else 0
        reward     -= foreign_fee
        net, tax    = self._apply_tax(u["guild_id"], reward)
        self.db.table("guilds").update({
            "treasury_coins": g["treasury_coins"] - g["labor_reward"] + foreign_fee
        }).eq("guild_id", gid).execute()
        self._add_stack_item(tile["owner_guild_id"], "tomato", yield_qty)
        self.db.table("users").update({
            "coins":  u["coins"] + net,
            "hunger": max(0, u["hunger"] - HUNGER_COST_LABOR),
        }).eq("user_id", uid).execute()
        embed = discord.Embed(title="🌾 ファーム労働完了", color=discord.Color.green())
        embed.add_field(name="収穫量（国庫倉庫へ）", value=f"トマト × {yield_qty}")
        embed.add_field(name="給料（税引後）",       value=f"{net} コイン（税: {tax}）")
        if is_foreign:
            embed.add_field(name="外国人手数料", value=f"{foreign_fee} コイン")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="mine_work", description="現在地の鉱山で国策労働します")
    async def cmd_mine_work(self, interaction: discord.Interaction) -> None:
        uid = str(interaction.user.id)
        gid = str(interaction.guild_id)
        u   = self._get_user(uid)
        if not u:
            await interaction.response.send_message("`/join` で参加してください。")
            return
        if u["hunger"] < HUNGER_COST_LABOR:
            await interaction.response.send_message(f"スタミナ不足（必要: {HUNGER_COST_LABOR}）。")
            return
        tile = self._get_tile(u["pos_x"], u["pos_y"])
        if not tile or tile["tile_type"] != "mine":
            await interaction.response.send_message("現在地は鉱山ではありません。")
            return
        if not tile["connected"]:
            await interaction.response.send_message("首都と接続されていません。")
            return
        g = self._get_guild(gid)
        if not g or g["treasury_coins"] < g["labor_reward"]:
            await interaction.response.send_message("国庫が不足しており給料を支払えません。")
            return
        purity              = (tile.get("individual_values") or {}).get("purity", 50)
        coins_earned, ore   = calc_mine_reward(purity)
        is_foreign          = u["guild_id"] != tile["owner_guild_id"]
        reward              = g["labor_reward"]
        foreign_fee         = int(reward * 0.20) if is_foreign else 0
        reward             -= foreign_fee
        net, tax            = self._apply_tax(u["guild_id"], reward)
        self.db.table("guilds").update({
            "treasury_coins": g["treasury_coins"] - g["labor_reward"] + coins_earned + foreign_fee
        }).eq("guild_id", gid).execute()
        if ore:
            self._add_stack_item(tile["owner_guild_id"], "iron_ore", 1)
        self.db.table("users").update({
            "coins":  u["coins"] + net,
            "hunger": max(0, u["hunger"] - HUNGER_COST_LABOR),
        }).eq("user_id", uid).execute()
        embed = discord.Embed(title="⛏️ 鉱山労働完了", color=discord.Color.orange())
        embed.add_field(name="採掘コイン（国庫）", value=f"{coins_earned} コイン")
        embed.add_field(name="給料（税引後）",     value=f"{net} コイン（税: {tax}）")
        embed.add_field(name="鉄鉱石ドロップ",     value="✅ あり" if ore else "❌ なし")
        await interaction.response.send_message(embed=embed)

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
        uid  = str(interaction.user.id)
        u    = self._get_user(uid)
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
        iv   = roll_iv(u.get("chef_level", 1))
        name = custom_name.strip() or item["name"]
        self.db.table("item_instances").insert({
            "instance_id": str(uuid.uuid4()), "item_id": item_id,
            "owner_id": uid, "custom_name": name,
            "quality_iv": iv, "price": 0, "crafted_by": uid, "on_sale": False,
        }).execute()
        embed = discord.Embed(title="🍳 クラフト成功", color=discord.Color.gold())
        embed.add_field(name="作成品",    value=name)
        embed.add_field(name="個体値 IV", value=f"**{iv}** / 100")
        if item["base_recovery"] > 0:
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
        u    = self._get_user(uid)
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
        u   = self._get_user(uid)
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
        seller_pos   = inst["owner_id"]  # "x_y"
        sx, sy       = map(int, seller_pos.split("_"))
        seller_tile  = self._get_tile(sx, sy)
        seller_uid   = seller_tile.get("owner_user_id") if seller_tile else None
        self.db.table("users").update({
            "coins": u["coins"] - inst["price"]
        }).eq("user_id", uid).execute()
        if seller_uid:
            net, _ = self._apply_tax(gid, inst["price"])
            su = self._get_user(seller_uid)
            if su:
                self.db.table("users").update({
                    "coins": su["coins"] + net
                }).eq("user_id", seller_uid).execute()
        self.db.table("item_instances").update({
            "owner_id": uid, "on_sale": False, "price": 0
        }).eq("instance_id", instance_id).execute()
        im  = self.db.table("items").select("base_recovery").eq(
            "item_id", inst["item_id"]).maybe_single().execute().data
        rec = calc_recovery(im["base_recovery"] if im else 0, inst["quality_iv"])
        await interaction.response.send_message(
            f"🍽️ **{inst['custom_name']}** を購入（{inst['price']}コイン）。\n"
            f"IV: {inst['quality_iv']} / 回復量: {rec}")

    @app_commands.command(name="eat", description="料理を食べてスタミナを回復します")
    @app_commands.describe(instance_id="食べる料理のインスタンスID")
    async def cmd_eat(self, interaction: discord.Interaction, instance_id: str) -> None:
        uid  = str(interaction.user.id)
        u    = self._get_user(uid)
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
        rec       = calc_recovery(im["base_recovery"], inst["quality_iv"])
        new_hunger = min(HUNGER_MAX, u["hunger"] + rec)
        self.db.table("users").update({"hunger": new_hunger}).eq("user_id", uid).execute()
        self.db.table("item_instances").delete().eq("instance_id", instance_id).execute()
        await interaction.response.send_message(
            f"🍴 **{inst['custom_name']}** を食べました！\n"
            f"スタミナ: {u['hunger']} → **{new_hunger}** (+{rec})")

    @app_commands.command(name="casino", description="カジノでギャンブルします")
    @app_commands.describe(bet="ベット額（コイン）")
    async def cmd_casino(self, interaction: discord.Interaction, bet: int) -> None:
        uid  = str(interaction.user.id)
        gid  = str(interaction.guild_id)
        u    = self._get_user(uid)
        if not u:
            await interaction.response.send_message("`/join` で参加してください。")
            return
        tile = self._get_tile(u["pos_x"], u["pos_y"])
        if not tile or tile["tile_type"] != "casino":
            await interaction.response.send_message("カジノマスにいる必要があります。")
            return
        if not (CASINO_MIN_BET <= bet <= CASINO_MAX_BET):
            await interaction.response.send_message(
                f"ベット額は {CASINO_MIN_BET}〜{CASINO_MAX_BET} で指定してください。")
            return
        if u["coins"] < bet:
            await interaction.response.send_message("コインが不足しています。")
            return
        won = random.random() < CASINO_WIN_RATE
        if won:
            net, _ = self._apply_tax(gid, bet)
            delta  = net
        else:
            delta = -bet
            g = self._get_guild(gid)
            if g:
                self.db.table("guilds").update({
                    "treasury_coins": g["treasury_coins"] + bet
                }).eq("guild_id", gid).execute()
        self.db.table("users").update({
            "coins": u["coins"] + delta
        }).eq("user_id", uid).execute()
        embed = discord.Embed(
            title=f"🎰 {'🎉 勝利！' if won else '💸 敗北…'}",
            color=discord.Color.gold() if won else discord.Color.red())
        embed.add_field(name="ベット額", value=f"{bet} コイン")
        embed.add_field(name="収支",     value=f"{'+' if won else ''}{delta} コイン")
        embed.add_field(name="所持金",   value=f"{u['coins'] + delta:,} コイン")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="chef_levelup", description="料理熟練度をレベルアップします")
    async def cmd_chef_levelup(self, interaction: discord.Interaction) -> None:
        uid = str(interaction.user.id)
        u   = self._get_user(uid)
        if not u:
            await interaction.response.send_message("`/join` で参加してください。")
            return
        lv   = u.get("chef_level", 1)
        cost = CHEF_LEVEL_UP_COST * lv
        if u["coins"] < cost:
            await interaction.response.send_message(f"コイン不足（必要: {cost}, 所持: {u['coins']}）。")
            return
        new_lv  = lv + 1
        min_iv  = min(99, (new_lv - 1) * CHEF_LEVEL_IV_BONUS)
        self.db.table("users").update({
            "coins": u["coins"] - cost, "chef_level": new_lv
        }).eq("user_id", uid).execute()
        await interaction.response.send_message(
            f"👨‍🍳 料理熟練度 **Lv {new_lv}**！IV下限 **{min_iv}** 以上が保証されます。")

    @app_commands.command(name="inventory", description="所持アイテムを確認します")
    async def cmd_inventory(self, interaction: discord.Interaction) -> None:
        uid     = str(interaction.user.id)
        stacks  = self.db.table("item_inventories").select("item_id,quantity").eq(
            "owner_id", uid).execute().data or []
        uniques = self.db.table("item_instances").select(
            "instance_id,custom_name,quality_iv").eq(
            "owner_id", uid).eq("on_sale", False).execute().data or []
        embed = discord.Embed(title=f"🎒 {interaction.user.display_name} のインベントリ",
                              color=discord.Color.blurple())
        if stacks:
            embed.add_field(name="スタックアイテム",
                value="\n".join(f"・{s['item_id']} × {s['quantity']}" for s in stacks),
                inline=False)
        if uniques:
            embed.add_field(name="ユニークアイテム",
                value="\n".join(
                    f"・[{u['instance_id'][:8]}] {u['custom_name']} (IV:{u['quality_iv']})"
                    for u in uniques),
                inline=False)
        if not stacks and not uniques:
            embed.description = "（空っぽです）"
        await interaction.response.send_message(embed=embed)

    # ══════════════════════════════════════════
    # ■ 政治系コマンド
    # ══════════════════════════════════════════

    @app_commands.command(name="nation_info", description="自国の国家情報を表示します")
    async def cmd_nation_info(self, interaction: discord.Interaction) -> None:
        gid = str(interaction.guild_id)
        g   = self._get_guild(gid)
        if not g:
            await interaction.response.send_message("国家データが存在しません。")
            return
        cnt = len(self.db.table("tiles").select("x").eq("owner_guild_id", gid).execute().data or [])
        embed = discord.Embed(title=f"🏛️ 国家情報: {interaction.guild.name}",
                              color=discord.Color.blurple())
        embed.add_field(name="国庫",         value=f"{g['treasury_coins']:,} コイン")
        embed.add_field(name="所有マス数",   value=f"{cnt} マス")
        embed.add_field(name="税率",         value=f"{int(g['tax_rate']*100)} %")
        embed.add_field(name="国策労働給料", value=f"{g['labor_reward']} コイン")
        embed.add_field(name="入国料",       value=f"{g['entry_fee']} コイン")
        embed.add_field(name="出国税",       value=f"{int(g['exit_fee_rate']*100)} %")
        embed.add_field(name="首都",         value=f"({g['capital_x']}, {g['capital_y']})")
        alliances = g.get("alliances") or []
        embed.add_field(name="同盟国",       value=", ".join(alliances) if alliances else "なし")
        await interaction.response.send_message(embed=embed)

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
        self.db.table("users").update({"role": "minister"}).eq(
            "user_id", str(target.id)).execute()
        await interaction.response.send_message(f"✅ {target.mention} を **大臣** に任命しました。")

    @app_commands.command(name="dismiss", description="大臣を一般市民に戻します（国王専用）")
    @app_commands.describe(target="解任するメンバー")
    async def cmd_dismiss(self, interaction: discord.Interaction, target: discord.Member) -> None:
        gid = str(interaction.guild_id)
        err = self._require_role(str(interaction.user.id), gid, {"king"})
        if err:
            await interaction.response.send_message(err)
            return
        self.db.table("users").update({"role": "citizen"}).eq(
            "user_id", str(target.id)).execute()
        await interaction.response.send_message(f"✅ {target.mention} を一般市民に戻しました。")

    @app_commands.command(name="immigrate", description="別のサーバー（国家）に移住します")
    @app_commands.describe(target_guild_id="移住先のサーバーID")
    async def cmd_immigrate(self, interaction: discord.Interaction,
                            target_guild_id: str) -> None:
        uid = str(interaction.user.id)
        u   = self._get_user(uid)
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
        exit_rate  = (self._get_guild(old_gid) or {}).get("exit_fee_rate", 0.0) if old_gid else 0.0
        exit_fee   = int(u["coins"] * exit_rate)
        entry_fee  = tg.get("entry_fee", 0)
        total_cost = exit_fee + entry_fee
        if u["coins"] < total_cost:
            await interaction.response.send_message(
                f"コイン不足。出国税: {exit_fee} / 入国料: {entry_fee} / 合計: {total_cost}\n"
                f"所持: {u['coins']} コイン")
            return
        view  = ImmigrationConfirmView(u, old_gid, tg, exit_fee, entry_fee, self.db)
        embed = discord.Embed(title="🛂 移住確認", color=discord.Color.orange(),
            description=(
                f"移住先: `{target_guild_id}`\n"
                f"出国税 ({int(exit_rate*100)}%): **{exit_fee} コイン**\n"
                f"入国料: **{entry_fee} コイン** / 合計: **{total_cost} コイン**\n\n"
                "実行しますか？"))
        await interaction.response.send_message(embed=embed, view=view)

    @app_commands.command(name="alliance_request", description="他国と同盟を締結します（国王専用）")
    @app_commands.describe(target_guild_id="同盟先のサーバーID")
    async def cmd_alliance_request(self, interaction: discord.Interaction,
                                   target_guild_id: str) -> None:
        gid = str(interaction.guild_id)
        err = self._require_role(str(interaction.user.id), gid, {"king"})
        if err:
            await interaction.response.send_message(err)
            return
        tg = self._get_guild(target_guild_id)
        if not tg:
            await interaction.response.send_message("対象の国家が見つかりません。")
            return
        mg  = self._get_guild(gid)
        al  = list(mg.get("alliances") or [])
        if target_guild_id in al:
            await interaction.response.send_message("すでに同盟を結んでいます。")
            return
        al.append(target_guild_id)
        self.db.table("guilds").update({"alliances": al}).eq("guild_id", gid).execute()
        tal = list(tg.get("alliances") or [])
        tal.append(gid)
        self.db.table("guilds").update({"alliances": tal}).eq("guild_id", target_guild_id).execute()
        await interaction.response.send_message(f"✅ `{target_guild_id}` と同盟を締結しました。")

    @app_commands.command(name="treasury", description="国庫の残高と倉庫を確認します")
    async def cmd_treasury(self, interaction: discord.Interaction) -> None:
        gid = str(interaction.guild_id)
        g   = self._get_guild(gid)
        if not g:
            await interaction.response.send_message("国家データが見つかりません。")
            return
        inv   = self.db.table("item_inventories").select("item_id,quantity").eq(
            "owner_id", gid).execute().data or []
        embed = discord.Embed(title=f"🏦 国庫: {interaction.guild.name}", color=discord.Color.gold())
        embed.add_field(name="残高", value=f"{g['treasury_coins']:,} コイン", inline=False)
        embed.add_field(name="倉庫",
            value="\n".join(f"・{i['item_id']} × {i['quantity']}" for i in inv) or "（空っぽ）",
            inline=False)
        await interaction.response.send_message(embed=embed)

    # ══════════════════════════════════════════
    # ■ 鉄道系コマンド
    # ══════════════════════════════════════════

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
        u  = self._get_user(uid)
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

    @app_commands.command(name="railway_blacklist",
                          description="線路通行ブラックリストを管理します")
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
        self.db.table("railways").update({"blacklist_guilds": bl}).eq(
            "x", x).eq("y", y).execute()
        await interaction.response.send_message(f"✅ ({x}, {y}) ブラックリスト更新: {bl}")

    @app_commands.command(name="warp", description="線路を使って指定座標にワープします（スタミナ消費なし）")
    @app_commands.describe(x="移動先X座標", y="移動先Y座標")
    async def cmd_warp(self, interaction: discord.Interaction, x: int, y: int) -> None:
        await interaction.response.defer()
        uid = str(interaction.user.id)
        u   = self._get_user(uid)
        if not u:
            await interaction.followup.send("`/join` で参加してください。")
            return
        if u["hunger"] <= 0:
            await interaction.followup.send("スタミナ 0 です。食事で回復してください。")
            return
        gid       = u.get("guild_id", "")
        g         = self._get_guild(gid) if gid else None
        alliances = list(g.get("alliances") or []) if g else []
        reachable, _ = self._rail_reachable(gid, x, y, alliances)
        if not reachable:
            await interaction.followup.send(
                f"({x}, {y}) へは線路で到達できません（権限・接続を確認）。")
            return
        total_fare = 0
        dest_rail  = self._get_railway(x, y)
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
        msg = f"🚄 ({x}, {y}) にワープしました！（スタミナ消費: 0）"
        if total_fare > 0:
            msg += f"\n通行料: {total_fare} コイン 徴収されました。"
        await interaction.followup.send(msg)

    @app_commands.command(name="railway_info", description="指定座標の線路情報を表示します")
    @app_commands.describe(x="X座標", y="Y座標")
    async def cmd_railway_info(self, interaction: discord.Interaction, x: int, y: int) -> None:
        rail = self._get_railway(x, y)
        if not rail:
            await interaction.response.send_message(f"({x}, {y}) に線路はありません。")
            return
        bl    = rail.get("blacklist_guilds") or []
        embed = discord.Embed(title=f"🛤️ 線路情報 ({x}, {y})", color=discord.Color.blue())
        embed.add_field(name="所有国",       value=rail.get("owner_guild_id") or "不明")
        embed.add_field(name="通行権限",     value=rail.get("permissions", "all"))
        embed.add_field(name="通行料",       value=f"{rail.get('fare', 0)} コイン")
        embed.add_field(name="ブラックリスト", value=", ".join(bl) if bl else "なし")
        await interaction.response.send_message(embed=embed)

    # ══════════════════════════════════════════
    # ■ レイド系コマンド
    # ══════════════════════════════════════════

    @app_commands.command(name="raid", description="隣接する敵領土を攻撃します")
    @app_commands.describe(x="攻撃対象X座標", y="攻撃対象Y座標",
                           weapon_instance_id="使用する武器のインスタンスID（省略可）")
    async def cmd_raid(self, interaction: discord.Interaction,
                       x: int, y: int, weapon_instance_id: str = "") -> None:
        await interaction.response.defer()
        uid = str(interaction.user.id)
        gid = str(interaction.guild_id)
        u   = self._get_user(uid)
        if not u:
            await interaction.followup.send("`/join` で参加してください。")
            return
        if u.get("guild_id") != gid:
            await interaction.followup.send("このサーバーの国民ではありません。")
            return
        if u["hunger"] < HUNGER_COST_RAID:
            await interaction.followup.send(f"スタミナ不足（必要: {HUNGER_COST_RAID}）。")
            return
        tile = self._get_tile(x, y)
        if not tile:
            await interaction.followup.send("攻撃対象のマスが存在しません。")
            return
        if tile.get("owner_guild_id") == gid:
            await interaction.followup.send("自国のマスは攻撃できません。")
            return
        if not tile.get("owner_guild_id"):
            await interaction.followup.send("未所有マスは攻撃できません。")
            return
        if not self._is_adjacent_to_guild(gid, x, y):
            await interaction.followup.send("攻撃対象に隣接する自国領土がありません。")
            return
        atk         = 0
        weapon_name = "素手"
        if weapon_instance_id:
            w = self.db.table("item_instances").select("*").eq(
                "instance_id", weapon_instance_id).eq(
                "owner_id", uid).maybe_single().execute().data
            if not w:
                await interaction.followup.send("その武器を所持していません。")
                return
            wm = self.db.table("items").select("base_atk,type,name").eq(
                "item_id", w["item_id"]).maybe_single().execute().data
            if not wm or wm.get("type") != "weapon":
                await interaction.followup.send("武器ではありません。")
                return
            atk         = wm.get("base_atk", 0)
            weapon_name = w.get("custom_name") or wm["name"]
            self.db.table("item_instances").delete().eq(
                "instance_id", weapon_instance_id).execute()
        eff_def = self._get_effective_def(tile)
        self.db.table("users").update({
            "hunger": max(0, u["hunger"] - HUNGER_COST_RAID)
        }).eq("user_id", uid).execute()
        if atk <= eff_def:
            self.db.table("raid_logs").insert({
                "attacker_uid": uid, "attacker_gid": gid,
                "target_x": x, "target_y": y, "damage_dealt": 0, "captured": False,
            }).execute()
            await interaction.followup.send(
                f"🛡️ **ダメージなし！** ATK({atk}) ≤ DEF({eff_def})\nスタミナ -{HUNGER_COST_RAID}")
            return
        damage = atk - eff_def
        new_hp = max(0, tile["hp"] - damage)
        self.db.table("tiles").update({"hp": new_hp}).eq("x", x).eq("y", y).execute()
        self.db.table("raid_logs").insert({
            "attacker_uid": uid, "attacker_gid": gid,
            "target_x": x, "target_y": y, "damage_dealt": damage, "captured": new_hp == 0,
        }).execute()
        embed = discord.Embed(title=f"⚔️ レイド: ({x}, {y})", color=discord.Color.red())
        embed.add_field(name="武器",     value=weapon_name)
        embed.add_field(name="ATK",      value=str(atk))
        embed.add_field(name="実効DEF",  value=str(eff_def))
        embed.add_field(name="ダメージ", value=str(damage))
        embed.add_field(name="残HP",     value=f"{new_hp} / {tile['max_hp']}")
        if new_hp == 0:
            await self._capture_tile(x, y, gid, uid)
            embed.add_field(name="結果", value="🚩 **占領成功！**", inline=False)
            embed.color = discord.Color.gold()
        await interaction.followup.send(embed=embed)
        await self._post_raid_log(interaction.guild,
            f"⚔️ `{uid}` ({gid}) が ({x},{y}) を攻撃。ダメージ: {damage} / 残HP: {new_hp}")

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
        self.db.table("tiles").update({"individual_values": ivs}).eq(
            "x", x).eq("y", y).execute()
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

    # ══════════════════════════════════════════
    # ■ 定期タスク
    # ══════════════════════════════════════════

    @tasks.loop(hours=1)
    async def hunger_decay_task(self) -> None:
        """全プレイヤーのスタミナを毎時間減少（当直中は2倍）"""
        res = self.db.table("users").select("user_id,hunger,on_duty_x").execute()
        for u in (res.data or []):
            mult      = DUTY_HUNGER_MULTIPLIER if u.get("on_duty_x") is not None else 1
            new_hunger = max(HUNGER_MIN, u["hunger"] - HUNGER_DECAY_PER_HOUR * mult)
            self.db.table("users").update({"hunger": new_hunger}).eq(
                "user_id", u["user_id"]).execute()

    @tasks.loop(minutes=10)
    async def farm_maintenance_task(self) -> None:
        """ファームのメンテナンス完了チェック"""
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
        """HP=0 マスのDEFリセット念押し"""
        res = self.db.table("tiles").select("x,y").eq("hp", 0).neq(
            "owner_guild_id", None).execute()
        for tile in (res.data or []):
            self.db.table("tiles").update({"def": CAPTURE_RESET_DEF}).eq(
                "x", tile["x"]).eq("y", tile["y"]).execute()


# ══════════════════════════════════════════════════════════════
# ■ セットアップ
# ══════════════════════════════════════════════════════════════

async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(MMOCog(bot))
