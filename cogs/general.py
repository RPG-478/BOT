"""/general: コイン・生存確認・ランキング系機能の操作パネル。"""
from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands
from core.panel_v2 import as_panel_v2


GENERAL_GENRES = {
    "economy": ("コイン・ランキング", "所持状況、送金、コインや bump/up のランキング"),
    "survival": ("生存確認", "追跡、アクティブ頻度、フリーズ、失踪警報"),
}
GENERAL_ACTIONS = {
    "economy": [
        ("プレイヤー状況", "status"),
        ("コイン送金", "pay"),
        ("コイン保有ランキング", "coin_leaderboard"),
        ("bump RTAランキング", "bump_leaderboard"),
        ("up RTAランキング", "up_leaderboard"),
    ],
    "survival": [
        ("追跡登録・解除", "fujo_register"),
        ("アクティブ頻度", "fujo_hindo"),
        ("生存確認ランキング", "fujo_ranking"),
        ("フリーズ", "fujo_freeze"),
        ("失踪警報解除", "fujo_panic_disable"),
    ],
}


class PayModal(discord.ui.Modal, title="コインを送金"):
    receiver_id = discord.ui.TextInput(label="送金先のユーザーID", max_length=20)
    amount = discord.ui.TextInput(label="送金するAGO", max_length=9)

    def __init__(self, cog):
        super().__init__()
        self.cog = cog

    async def on_submit(self, interaction):
        try:
            receiver = await self.cog.bot.fetch_user(int(self.receiver_id.value))
            amount = int(self.amount.value)
        except (ValueError, discord.HTTPException):
            return await interaction.response.send_message("ユーザーIDまたは数量が正しくありません。", ephemeral=True)
        await self.cog.bot.get_cog("WalletCog").pay(interaction, receiver, amount)


class GeneralGenreSelect(discord.ui.Select):
    def __init__(self, cog, selected: str | None = None):
        self.cog = cog
        super().__init__(
            placeholder="ジャンルを選択してください",
            options=[discord.SelectOption(label=label, description=description, value=value,
                                          default=value == selected)
                     for value, (label, description) in GENERAL_GENRES.items()],
            row=0,
        )

    async def callback(self, interaction):
        view: GeneralPanel = self.view
        view.genre = self.values[0]
        view.refresh()
        await interaction.response.edit_message(embed=view.embed(), view=view)


class GeneralActionSelect(discord.ui.Select):
    def __init__(self, cog, genre: str):
        self.cog = cog
        self.genre = genre
        super().__init__(
            placeholder="機能を選択してください",
            options=[discord.SelectOption(label=label, value=value) for label, value in GENERAL_ACTIONS[genre]],
            row=1,
        )

    async def callback(self, interaction):
        view: GeneralPanel = self.view
        await self.cog.dispatch_general(interaction, self.values[0])


class GeneralPanel(discord.ui.View):
    def __init__(self, cog, genre: str | None = None):
        super().__init__(timeout=300)
        self.cog = cog
        self.genre = genre
        self.refresh()

    def refresh(self):
        self.clear_items()
        self.add_item(GeneralGenreSelect(self.cog, self.genre))
        if self.genre:
            self.add_item(GeneralActionSelect(self.cog, self.genre))

    def embed(self):
        description = "ジャンルを選ぶと、その中の機能を選択できます。"
        if self.genre:
            description = f"**{GENERAL_GENRES[self.genre][0]}** の機能を選択してください。"
        return discord.Embed(title="一般機能", description=description, color=0x3498DB)


class GeneralCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="general", description="一般機能の操作パネルを表示します")
    async def general(self, interaction: discord.Interaction):
        view = GeneralPanel(self)
        await interaction.response.send_message(view=as_panel_v2(view), ephemeral=True)

    async def dispatch_general(self, interaction: discord.Interaction, value: str):
        wallet = self.bot.get_cog("WalletCog")
        fujo = self.bot.get_cog("FujoSurvival")
        if value == "pay":
            return await interaction.response.send_modal(PayModal(self))
        if value == "status":
            return await wallet.user_status(interaction)
        if value == "coin_leaderboard":
            return await wallet.leaderboard(interaction)
        if value in {"bump_leaderboard", "up_leaderboard"}:
            event_type = value.removesuffix("_leaderboard")
            return await wallet.leaderboard(interaction, app_commands.Choice(name=event_type, value=event_type))
        action = value.removeprefix("fujo_")
        return await fujo.fujo(interaction, action, None, "active", None, None)


async def setup(bot):
    await bot.add_cog(GeneralCog(bot))
