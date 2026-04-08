import os
import discord
from discord.ext import commands
from supabase import create_client, Client
from groq import Groq

class ReplyAI(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.channel_state = {}

        # ===== 環境変数取得 =====
        groq_key = os.getenv("GROQ_API_KEY")
        url = os.getenv("SUPABASE_URL")
        key = os.getenv("SUPABASE_KEY")

        # ===== エラー防止チェック =====
        if not groq_key:
            raise ValueError("GROQ_API_KEYが未設定")

        if not url or not key:
            raise ValueError("SUPABASEの設定が未設定")

        # ===== クライアント初期化 =====
        self.groq_client = Groq(api_key=groq_key)
        self.supabase: Client = create_client(url, key)

    # ===== トグルコマンド =====
    @commands.command(name="oo")
    async def toggle_ai(self, ctx: commands.Context):
        channel_id = ctx.channel.id

        state = not self.channel_state.get(channel_id, False)
        self.channel_state[channel_id] = state

        await ctx.send(
            "うおｗAIモードONｗ" if state else "AIモードOFF"
        )

    # ===== テスト用コマンド =====
    @commands.command(name="test")
    async def test(self, ctx):
        await ctx.send("動いてるぞｗ")

# ===== これ絶対必要 =====
async def setup(bot):
    await bot.add_cog(ReplyAI(bot))

