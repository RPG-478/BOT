import io
import subprocess
import discord
from discord.ext import commands

class LogsCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="logs")
    async def logs(self, ctx):
        try:
            result = subprocess.run(
                ["journalctl", "--no-pager"],
                capture_output=True,
                text=True,
                check=True
            )
            log_data = result.stdout

            if not log_data:
                await ctx.send("ログを取得できませんでした。")
                return

            file_bytes = io.BytesIO(log_data.encode("utf-8"))
            await ctx.send(file=discord.File(file_bytes, filename="raspberrypi_logs.txt"))
        except Exception as e:
            await ctx.send(f"ログの取得中にエラーが発生しました: {e}")

async def setup(bot):
    await bot.add_cog(LogsCog(bot))
