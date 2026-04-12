# -*- coding: utf-8 -*-
import discord
from discord.ext import commands
from groq import Groq
import config  # 前提コード1 (config.py) を参照

# クラス名を ReplyAI から AIConfig に変更（機能実態に合わせました）
class AIConfig(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.channel_state = {}

        # config.py から取得
        groq_key = config.GROQ_API_KEY
        
        if not groq_key:
            print("ERROR: GROQ_API_KEY が config.py から取得できません。")
            self.groq_client = None
        else:
            self.groq_client = Groq(api_key=groq_key)

        # config.py で初期化済みの supabase を利用
        self.supabase = config.supabase

    # コマンド名を oo から ai_chat に変更（用途が分かりやすくなります）
    @commands.command(name="ai_chat")
    async def toggle_ai(self, ctx: commands.Context):
        channel_id = ctx.channel.id
        state = not self.channel_state.get(channel_id, False)
        self.channel_state[channel_id] = state

        msg = "AIモードON" if state else "AIモードOFF"
        embed = discord.Embed(description=msg, color=0xFFFFFF)
        await ctx.send(embed=embed)

    # コマンド名とメソッド名が test で重複していたため、メソッド名を check_status に変更
    @commands.command(name="test")
    async def check_status(self, ctx: commands.Context):
        embed = discord.Embed(description="動いてるぞ", color=0xFFFFFF)
        await ctx.send(embed=embed)

async def setup(bot: commands.Bot):
    # 修正したクラス名に合わせて変更
    await bot.add_cog(AIConfig(bot))