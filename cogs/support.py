"""サポート系機能を /support に統合する入口。"""
from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from cogs.clear import MAX_CLEAR


SUPPORT_ACTIONS = [
    app_commands.Choice(name="Muted設定", value="muted"),
    app_commands.Choice(name="匿名つぶやきパネル", value="whisper"),
    app_commands.Choice(name="メッセージ削除", value="clear"),
    app_commands.Choice(name="bump/up通知・RTA状態", value="bumprta_status"),
    app_commands.Choice(name="bump/up通知・RTAオン", value="bumprta_on"),
    app_commands.Choice(name="bump/up通知・RTAオフ", value="bumprta_off"),
]


class SupportCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def _missing(self, interaction: discord.Interaction, name: str):
        await interaction.response.send_message(
            f"{name}機能が読み込まれていません。", ephemeral=True
        )

    @app_commands.command(name="support", description="Muted・匿名つぶやき・メッセージ削除・bump/up設定をまとめて操作します")
    @app_commands.choices(action=SUPPORT_ACTIONS)
    @app_commands.describe(
        action="実行するサポート操作",
        target="Muted対象者",
        minutes="Mutedする時間（分）",
        admin_role="Muted管理ロールの設定",
        isolation_channel="Muted対象者の隔離先チャンネル",
        amount=f"削除するメッセージ数（1〜{MAX_CLEAR}）",
        member="削除対象のユーザー（省略可能）",
    )
    @app_commands.guild_only()
    async def support(
        self,
        interaction: discord.Interaction,
        action: app_commands.Choice[str],
        target: discord.Member | None = None,
        minutes: int | None = None,
        admin_role: discord.Role | None = None,
        isolation_channel: discord.TextChannel | None = None,
        amount: int | None = None,
        member: discord.Member | None = None,
    ):
        selected = action.value

        if selected == "muted":
            cog = self.bot.get_cog("Muted")
            if cog is None:
                return await self._missing(interaction, "Muted")
            return await cog.muted_setting(
                interaction, target, minutes, admin_role, isolation_channel
            )

        if selected == "whisper":
            permissions = getattr(interaction, "permissions", None)
            if not getattr(permissions, "manage_channels", False):
                return await interaction.response.send_message(
                    "この操作には「チャンネルの管理」権限が必要です。", ephemeral=True
                )
            cog = self.bot.get_cog("WhisperCog")
            if cog is None:
                return await self._missing(interaction, "匿名つぶやき")
            return await cog.whisper(interaction)

        if selected == "clear":
            if amount is None:
                return await interaction.response.send_message(
                    "メッセージ削除には amount を指定してください。", ephemeral=True
                )
            cog = self.bot.get_cog("ClearCog")
            if cog is None:
                return await self._missing(interaction, "メッセージ削除")
            return await cog.clear(interaction, amount, member)

        cog = self.bot.get_cog("BumpRta")
        if cog is None:
            return await self._missing(interaction, "bump/up通知・RTA")
        bumprta_action = selected.removeprefix("bumprta_")
        return await cog.bumprta_command(
            interaction,
            app_commands.Choice(name=bumprta_action, value=bumprta_action),
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(SupportCog(bot))
