"""/general: コイン・生存確認系機能の操作パネル。"""
from __future__ import annotations
import discord
from discord import app_commands
from discord.ext import commands

class PayModal(discord.ui.Modal, title="コインを送金"):
    receiver_id = discord.ui.TextInput(label="送金先のユーザーID", max_length=20)
    amount = discord.ui.TextInput(label="送金するAGO", max_length=9)
    def __init__(self, cog):
        super().__init__(); self.cog = cog
    async def on_submit(self, interaction):
        try:
            receiver = await self.cog.bot.fetch_user(int(self.receiver_id.value))
            amount = int(self.amount.value)
        except (ValueError, discord.HTTPException):
            return await interaction.response.send_message("ユーザーIDまたは数量が正しくありません。", ephemeral=True)
        await self.cog.bot.get_cog("WalletCog").pay(interaction, receiver, amount)

class GeneralSelect(discord.ui.Select):
    def __init__(self, cog):
        self.cog = cog
        options = [discord.SelectOption(label=label, value=value) for label, value in [
            ("プレイヤー状況", "status"), ("コイン送金", "pay"), ("ランキング", "leaderboard"),
            ("生存確認: 追跡登録・解除", "fujo_register"), ("生存確認: アクティブ頻度", "fujo_hindo"),
            ("生存確認: ランキング", "fujo_ranking"), ("生存確認: フリーズ", "fujo_freeze"),
            ("生存確認: 失踪警報解除", "fujo_panic_disable")]]
        super().__init__(placeholder="操作を選んでください", options=options)
    async def callback(self, interaction):
        wallet = self.cog.bot.get_cog("WalletCog")
        fujo = self.cog.bot.get_cog("FujoSurvival")
        value = self.values[0]
        if value == "pay": return await interaction.response.send_modal(PayModal(self.cog))
        if value == "status": return await wallet.user_status(interaction)
        if value == "leaderboard": return await wallet.leaderboard(interaction)
        action = value.removeprefix("fujo_")
        await fujo.fujo(interaction, action, None, "active", None, None)

class GeneralPanel(discord.ui.View):
    def __init__(self, cog):
        super().__init__(timeout=300); self.add_item(GeneralSelect(cog))

class GeneralCog(commands.Cog):
    def __init__(self, bot): self.bot = bot
    @app_commands.command(name="general", description="一般機能の操作パネルを表示します")
    async def general(self, interaction: discord.Interaction):
        await interaction.response.send_message(embed=discord.Embed(
            title="一般機能", description="下のメニューから操作を選択してください。", color=0x3498DB),
            view=GeneralPanel(self), ephemeral=True)

async def setup(bot):
    await bot.add_cog(GeneralCog(bot))
