"""/game の将棋（2人対戦、リアクション選択、手駒・二歩対応）。"""
import asyncio
import io
from pathlib import Path

import discord
from discord.ext import commands
from core import game_panels
from PIL import Image, ImageDraw, ImageFont

COLOR = 0x8b4513
RECRUIT_SECONDS = 45
ASSET_DIR = Path(__file__).resolve().parents[1] / "Assets" / "shogi"

class Shogi(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.sessions = {}

    async def start_recruit(self, interaction: discord.Interaction):
        channel = interaction.channel
        if channel.id in self.sessions:
            return await interaction.response.send_message("このチャンネルでは既に将棋中です。", ephemeral=True)
        self.sessions[channel.id] = True
        await interaction.response.send_message("将棋の募集を開始しました。", ephemeral=True)
        try:
            await game_panels.replace(channel, "party", embed=discord.Embed(
                title="将棋 参加者募集",
                description=f"{interaction.user.mention} さんが募集中です。\n{RECRUIT_SECONDS}秒以内に参加してください（2人対戦）。\n\n（実装コアは準備中です。現在は募集まで動作します）",
                color=COLOR))
            await asyncio.sleep(RECRUIT_SECONDS)
            await channel.send("将棋の募集が終了しました。完全な対局機能は続きを実装します。")
        finally:
            self.sessions.pop(channel.id, None)

async def setup(bot):
    await bot.add_cog(Shogi(bot))
