"""国づくり MMO（/nation）のフェーズ 2：参加・建国・状態表示。

テーブルは ``docs/sql/nation.sql`` を参照。所持金は /wallet と共通の ``users.balance``。

- Supabase のクライアントは同期なので、呼び出しはすべて ``asyncio.to_thread`` で行う。
- 1 サーバーにつき 1 国（``nation_guilds.guild_id`` が主キー）。1 人が入れる国は 1 つだけ。
- 空腹度は、国民がサーバーで発言すると 5 分に 1 回だけ 1 減る（0 で止まる）。
- /setup で国づくりをオフにしたサーバーでは、建国・参加・空腹の減少をしない。
"""
from __future__ import annotations

import asyncio
import logging
import os
import time

import discord
from discord import app_commands
from discord.ext import commands

from core.emojis import COIN
from core.guild_settings import nation_settings

try:  # テストでは supabase.create_client が差し替えられる
    import supabase as supabase_module
except ImportError:  # pragma: no cover
    supabase_module = None

log = logging.getLogger(__name__)

MAX_HUNGER = 100
SEARCH_RADIUS = 50  # 首都を置く空きマスを原点からこの距離まで探す（nation_found.sql と同じ）
ROLE_NAMES = {"king": "国王", "minister": "大臣", "citizen": "国民"}
# nation_found（SQL）が投げるエラーの目印 → 返信のタイトルと本文
FOUND_ERRORS = {
    "NATION_EXISTS": ("建国済み", "このサーバーの国はもうあります。`/nation status` で確認できます。"),
    "ALREADY_IN_NATION": ("建国できません", "あなたはすでに別の国に所属しています。"),
    "NO_FREE_TILE": ("建国できません", "首都を置ける空き地が見つかりませんでした。"),
}
HUNGER_INTERVAL = 300  # 発言で空腹が減る間隔（秒）。1 人につきこの間隔で 1 回だけ
HUNGER_PER_MESSAGE = 1
COIN_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "Assets", "COIN.png")
DISABLED_TEXT = "このサーバーは国づくりに参加しない設定です。管理者が `/setup` で変えられます。"
COLOR_OK, COLOR_INFO, COLOR_ERROR = 0x2ecc71, 0x3498db, 0xe74c3c


def spiral_coords(radius: int):
    """原点から近い順（チェビシェフ距離のリングごと）に座標を返す。"""
    yield 0, 0
    for r in range(1, radius + 1):
        for x in range(-r, r + 1):
            yield x, -r
            yield x, r
        for y in range(-r + 1, r):
            yield -r, y
            yield r, y


def hunger_bar(hunger: int) -> str:
    filled = max(0, min(10, round(hunger / 10)))
    return "■" * filled + "□" * (10 - filled)


class NationCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.supabase = getattr(bot, "supabase", None)
        if self.supabase is None and supabase_module is not None:
            from core.supabase_client import create_client_from_env
            self.supabase = create_client_from_env()
        self._last_drain: dict[str, float] = {}  # user_id -> 最後に空腹を減らした time.monotonic()

    nation_group = app_commands.Group(name="nation", description="国づくり（共有マップの国家経営）のコマンド一覧",
                                      guild_only=True)

    # --- DB ヘルパー ---

    async def _run(self, build):
        if self.supabase is None:
            raise RuntimeError("Supabase が設定されていません")
        return (await asyncio.to_thread(lambda: build().execute())).data or []

    async def _nation(self, guild_id: str):
        rows = await self._run(lambda: self.supabase.table("nation_guilds").select("*").eq("guild_id", guild_id))
        return rows[0] if rows else None

    async def _player(self, user_id: str):
        rows = await self._run(lambda: self.supabase.table("nation_players").select("*").eq("user_id", user_id))
        return rows[0] if rows else None

    async def _balance(self, user_id: str):
        rows = await self._run(lambda: self.supabase.table("users").select("balance").eq("user_id", user_id))
        return (rows[0].get("balance") or 0) if rows else None

    async def _found_rpc(self, guild_id: str, user_id: str):
        """建国を DB 関数 nation_found（docs/sql/nation_found.sql）で 1 トランザクションで行う。"""
        if self.supabase is None:
            raise RuntimeError("Supabase が設定されていません")
        res = await asyncio.to_thread(
            lambda: self.supabase.rpc("nation_found", {"p_guild_id": guild_id, "p_user_id": user_id}).execute())
        data = res.data
        row = data[0] if isinstance(data, list) else data
        if not row:
            raise RuntimeError("nation_found が首都の座標を返しませんでした")
        return row["capital_x"], row["capital_y"]

    @staticmethod
    def _enabled(guild) -> bool:
        try:
            return bool(nation_settings(guild.id)["enabled"])
        except Exception:  # noqa: BLE001 - 設定が読めないときは既定（参加する）
            log.exception("nation_settings failed")
            return True

    async def drain_hunger(self, user_id: str, amount: int = HUNGER_PER_MESSAGE) -> bool:
        """空腹を amount 減らす（nation_adjust）。国民でない・すでに 0 のときは何もしない。減らしたら True。"""
        if self.supabase is None:
            return False
        try:
            await asyncio.to_thread(lambda: self.supabase.rpc(
                "nation_adjust", {"p_user_id": user_id, "p_coins_delta": 0, "p_hunger_delta": -amount}).execute())
            return True
        except Exception as e:  # noqa: BLE001
            msg = str(e)
            if "player not found" in msg or "insufficient hunger" in msg:
                return False
            log.warning("hunger drain failed: %s", msg)
            return False

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or message.guild is None:
            return
        uid, now = str(message.author.id), time.monotonic()
        last = self._last_drain.get(uid)
        if last is not None and now - last < HUNGER_INTERVAL:
            return
        if not self._enabled(message.guild):
            return
        self._last_drain[uid] = now
        await self.drain_hunger(uid)

    @staticmethod
    def _embed(title, text, color=COLOR_INFO):
        return discord.Embed(title=title, description=text, color=color)

    async def _reply(self, interaction, embed, ephemeral=False, file=None):
        kwargs = {"embed": embed, "ephemeral": ephemeral}
        if file is not None:
            kwargs["file"] = file
        if interaction.response.is_done():
            await interaction.followup.send(**kwargs)
        else:
            await interaction.response.send_message(**kwargs)

    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        log.exception("nation command failed", exc_info=error)
        try:
            await self._reply(interaction, self._embed(
                "エラー", "国づくりのデータを読み書きできませんでした。少し待ってからもう一度試してください。", COLOR_ERROR),
                ephemeral=True)
        except discord.HTTPException:
            pass

    # --- コマンド ---

    @nation_group.command(name="found", description="このサーバーの国を建国します（管理者かオーナーのみ）")
    async def found(self, interaction: discord.Interaction):
        guild, user = interaction.guild, interaction.user
        perms = getattr(user, "guild_permissions", None)
        if not ((perms is not None and perms.administrator) or getattr(guild, "owner_id", None) == user.id):
            await self._reply(interaction, self._embed("建国できません", "建国できるのはサーバーの管理者かオーナーだけです。", COLOR_ERROR), ephemeral=True)
            return
        if not self._enabled(guild):
            await self._reply(interaction, self._embed("建国できません", DISABLED_TEXT, COLOR_ERROR), ephemeral=True)
            return
        gid, uid = str(guild.id), str(user.id)
        try:
            x, y = await self._found_rpc(gid, uid)
        except Exception as e:  # noqa: BLE001 - PostgREST のエラーはメッセージで判別する
            msg = str(e)
            for code, (title, text) in FOUND_ERRORS.items():
                if code in msg:
                    await self._reply(interaction, self._embed(title, text, COLOR_INFO if code == "NATION_EXISTS" else COLOR_ERROR), ephemeral=True)
                    return
            raise
        await self._reply(interaction, self._embed(
            "建国しました", f"**{guild.name}** が建国されました！\n首都: ({x}, {y})\n国王: {user.mention}\n"
            "サーバーのみんなは `/nation join` で国民になれます。", COLOR_OK))

    @nation_group.command(name="join", description="このサーバーの国に国民として参加します")
    async def join(self, interaction: discord.Interaction):
        if not self._enabled(interaction.guild):
            await self._reply(interaction, self._embed("参加できません", DISABLED_TEXT, COLOR_ERROR), ephemeral=True)
            return
        gid, uid = str(interaction.guild.id), str(interaction.user.id)
        if not await self._nation(gid):
            await self._reply(interaction, self._embed("国がありません", "このサーバーにはまだ国がありません。管理者が `/nation found` で建国できます。"), ephemeral=True)
            return
        player = await self._player(uid)
        if player and player.get("guild_id"):
            text = "あなたはもうこの国の国民です。" if player["guild_id"] == gid else "あなたはすでに別の国に所属しています。"
            await self._reply(interaction, self._embed("参加できません", text), ephemeral=True)
            return
        await self._run(lambda: self.supabase.table("nation_players").upsert(
            {"user_id": uid, "guild_id": gid, "role": "citizen", "hunger": MAX_HUNGER}, on_conflict="user_id"))
        await self._reply(interaction, self._embed(
            "参加しました", f"{interaction.user.mention} が **{interaction.guild.name}** の国民になりました！\n空腹度: {MAX_HUNGER}/{MAX_HUNGER}", COLOR_OK))

    @nation_group.command(name="status", description="自分の所属国・役職・所持金・空腹度を表示します")
    async def status(self, interaction: discord.Interaction):
        uid = str(interaction.user.id)
        player = await self._player(uid)
        if not player or not player.get("guild_id"):
            await self._reply(interaction, self._embed("未参加", "まだどの国にも参加していません。`/nation join` で参加できます。"), ephemeral=True)
            return
        balance = await self._balance(uid)
        gid = player["guild_id"]
        g = self.bot.get_guild(int(gid)) if gid.isdigit() else None
        nation_name = g.name if g else (interaction.guild.name if str(interaction.guild.id) == gid else f"サーバー {gid}")
        hunger = player.get("hunger", 0)
        embed = discord.Embed(title=f"{interaction.user.display_name} の国づくり", color=COLOR_INFO)
        embed.add_field(name="所属国", value=nation_name, inline=True)
        embed.add_field(name="役職", value=ROLE_NAMES.get(player.get("role"), player.get("role") or "-"), inline=True)
        embed.add_field(name="所持金", value=f"{COIN} {balance if balance is not None else 0:,} AGO", inline=True)
        embed.add_field(name="空腹度", value=f"{hunger_bar(hunger)} {hunger}/{MAX_HUNGER}", inline=False)
        embed.set_footer(text="空腹度はサーバーで発言すると少しずつ減ります")
        file = None
        if os.path.exists(COIN_PATH):
            file = discord.File(COIN_PATH, filename="COIN.png")
            embed.set_thumbnail(url="attachment://COIN.png")
        await self._reply(interaction, embed, ephemeral=True, file=file)


async def setup(bot: commands.Bot):
    await bot.add_cog(NationCog(bot))
