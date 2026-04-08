# -*- coding: utf-8 -*-
import discord
from discord.ext import commands
from groq import Groq
import config  # 前提コード1 (config.py) を参照

class ReplyAI(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.channel_state = {}

        # config.py から取得
        groq_key = config.GROQ_API_KEY
        
        if not groq_key:
            print("ERROR: GROQ_API_KEY が config.py から取得できません。")
            # 起動を止めないためにダミーをいれるか、Noneのままにする
            self.groq_client = None
        else:
            self.groq_client = Groq(api_key=groq_key)

        # config.py で初期化済みの supabase を利用
        self.supabase = config.supabase

    @commands.command(name="oo")
    async def toggle_ai(self, ctx: commands.Context):
        channel_id = ctx.channel.id
        state = not self.channel_state.get(channel_id, False)
        self.channel_state[channel_id] = state

        await ctx.send(
            "うおｗAIモードONｗ" if state else "AIモードOFF"
        )

    @commands.command(name="test")
    async def test(self, ctx: commands.Context):
        await ctx.send("動いてるぞｗ")

async def setup(bot: commands.Bot):
    # main.py の setup_hook から呼び出される
    await bot.add_cog(ReplyAI(bot))
