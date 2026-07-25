import asyncio
import os
import subprocess
import sys
from discord.ext import commands

class TempInstaller(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.bot.loop.create_task(self.install_deps())

    async def install_deps(self):
        await self.bot.wait_until_ready()
        req_path = "requirements.txt"
        if not os.path.exists(req_path):
            return

        def run_pip():
            return subprocess.run(
                [sys.executable, "-m", "pip", "install", "-r", req_path],
                capture_output=True,
                text=True
            )

        try:
            res = await asyncio.to_thread(run_pip)
            if res.returncode == 0:
                for guild in self.bot.guilds:
                    for channel in guild.text_channels:
                        if channel.permissions_for(guild.me).send_messages:
                            await channel.send("lightgbm and scikit-learn installation completed.")
                            break
                    break
        except Exception as e:
            print(f"Installation error: {e}")

async def setup(bot: commands.Bot):
    await bot.add_cog(TempInstaller(bot))

