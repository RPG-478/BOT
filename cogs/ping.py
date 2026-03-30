# -*- coding: utf-8 -*-
import discord
from discord.ext import commands
import config
import defining as df

class System(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # 1. プレフィックスコマンド (!ping など)
    @commands.command(name="ping")
    async def ping_command(self, ctx):
        """ボットの応答速度を確認します"""
        latency = round(self.bot.latency * 1000) # ミリ秒換算
        
        # defining.py の関数を使ってログ出力
        print(df.format_log(f"Ping command executed by {ctx.author}"))
        
        await ctx.send(f"Pong! 応答速度: {latency}ms")

    # 2. スラッシュコマンド (/ping)
    @discord.app_commands.command(name="ping", description="ボットの応答速度を表示します")
    async def ping_slash(self, interaction: discord.Interaction):
        latency = round(self.bot.latency * 1000)
        
        print(df.format_log(f"Slash Ping executed by {interaction.user}"))
        
        await interaction.response.send_message(f"Pong! 応答速度: {latency}ms")

# Main.py の setup_hook から呼ばれる関数
async def setup(bot):
    await bot.add_cog(System(bot))
