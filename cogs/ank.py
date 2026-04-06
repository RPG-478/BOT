import discord
from discord.ext import commands
import asyncio

class Ank(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command()
    async def ank(self, ctx, target: int):
        # 1未満の指定や数値以外は無視
        if target <= 0:
            return

        def check(m):
            # コマンドが打たれたチャンネルと同じ場所、かつBot以外の発言をカウント
            return m.channel == ctx.channel and not m.author.bot

        count = 0
        try:
            # 指定された回数分、メッセージが送られてくるのを待機
            while count < target:
                # タイムアウトを180秒（3分）に設定
                msg = await self.bot.wait_for('message', check=check, timeout=180.0)
                count += 1

                # 指定されたコメ数に到達したらリアクションを付けて終了
                if count == target:
                    await msg.add_reaction("<a:BAKUHATU:1490259644717993995>")
                    break
                    
        except asyncio.TimeoutError:
            # 3分間発言がなかった場合は静かに終了
            pass

async def setup(bot):
    await bot.add_cog(Ank(bot))