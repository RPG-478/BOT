import os
import subprocess
import sys
from discord.ext import commands

def auto_install():
    current_dir = os.path.dirname(os.path.abspath(__file__))
    req_path = os.path.join(current_dir, "..", "requirements.txt")
    if os.path.exists(req_path):
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", req_path])
        except Exception:
            pass

auto_install()

# インストール後にインポートする
from google import genai

class Gemini(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # APIキーは環境変数から読み込むか、ここに直接記述してください
        self.api_key = os.getenv("GEMINI_API_KEY", "YOUR_API_KEY")
        # クライアントの初期化
        self.client = genai.Client(api_key=self.api_key)

    @commands.command()
    async def chat(self, ctx, *, message: str):
        # discord.pyの動作を妨げないよう非同期（client.aio）で呼び出します
        try:
            response = await self.client.aio.models.generate_content(
                model='gemini-2.5-flash',
                contents=message,
            )
            await ctx.send(response.text)
        except Exception as e:
            await ctx.send(f"エラーが発生しました: {e}")

async def setup(bot):
    await bot.add_cog(Gemini(bot))
