"""国づくり MMO（/nation）のフェーズ 2：参加・建国・状態表示。

テーブルは ``docs/sql/nation.sql`` を参照。所持金は /wallet と共通の ``users.balance``。

- Supabase のクライアントは同期なので、呼び出しはすべて ``asyncio.to_thread`` で行う。
- 1 サーバーにつき 1 国（``nation_guilds.guild_id`` が主キー）。1 人が入れる国は 1 つだけ。
- 空腹度の自然減少はフェーズ 3 で実装する（ここでは参加時に 100 で作るだけ）。
"""
from __future__ import annotations

import asyncio
import logging
import os

import discord
from discord import app_commands
from discord.ext import commands

try:  # テストでは supabase.create_client が差し替えられる
    import supabase as supabase_module
except ImportError:  # pragma: no cover
    supabase_module = None

log = logging.getLogger(__name__)

COIN = "🪙"
MAX_HUNGER = 100
SEARCH_RADIUS = 50  # 首都を置く空きマスを原点からこの距離まで探す（nation_found.sql と同じ）
ROLE_NAMES = {"king": "国王", "minister": "大臣", "citizen": "国民"}
# nation_found（SQL）が投げるエラーの目印 → 返信のタイトルと本文
FOUND_ERRORS = {
    "NATION_EXISTS": ("建国済み", "このサーバーの国はもうあります。`/nation status` で確認できます。"),
    "ALREADY_IN_NATION": ("建国できません", "あなたはすでに別の国に所属しています。"),
    "NO_FREE_TILE": ("建国できません", "首都を置ける空き地が見つかりませんでした。"),
}
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
    def _embed(title, text, color=COLOR_INFO):
        return discord.Embed(title=title, description=text, color=color)

    async def _reply(self, interaction, embed, ephemeral=False):
        if interaction.response.is_done():
            await interaction.followup.send(embed=embed, ephemeral=ephemeral)
        else:
            await interaction.response.send_message(embed=embed, ephemeral=ephemeral)

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
        await self._reply(interaction, embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(NationCog(bot))
