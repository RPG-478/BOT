# -*- coding: utf-8 -*-
import discord
from discord.ext import commands
from groq import Groq
import config  # 前提としていただいた1つ目のコード(config.py)をインポート

class ReplyAI(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.channel_state = {}

        # ===== エラー防止チェック =====
        if not config.GROQ_API_KEY:
            raise ValueError("GROQ_API_KEYが未設定です。")

        # config.py側でSupabaseが初期化されていない場合の警告
        if config.supabase is None:
            print("WARNING: ReplyAI - Supabaseクライアントが初期化されていません。")

        # ===== クライアント初期化 =====
        # GroqはCog内で初期化（キーはconfigから取得）
        self.groq_client = Groq(api_key=config.GROQ_API_KEY)
        
        # Supabaseはconfig.pyで初期化済みのものをそのまま利用
        self.supabase = config.supabase

    # ===== トグルコマンド =====
    @commands.command(name="oo")
    async def toggle_ai(self, ctx: commands.Context):
        channel_id = ctx.channel.id

        # 現在の状態を取得して反転させる
        state = not self.channel_state.get(channel_id, False)
        self.channel_state[channel_id] = state

        await ctx.send(
            "うおｗAIモードONｗ" if state else "AIモードOFF"
        )

    # ===== テスト用コマンド =====
    @commands.command(name="test")
    async def test(self, ctx: commands.Context):
        await ctx.send("動いてるぞｗ")

# ===== Cogのセットアップ =====
async def setup(bot: commands.Bot):
    await bot.add_cog(ReplyAI(bot))
