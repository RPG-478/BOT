import logging
from collections import deque
from discord.ext import commands

class LogBuffer(commands.Cog, logging.Handler):
    def __init__(self, bot, maxlen=100):
        commands.Cog.__init__(self)
        logging.Handler.__init__(self)

        self.bot = bot
        self.logs = deque(maxlen=maxlen)

    def emit(self, record):
        log_entry = self.format(record)
        self.logs.append(log_entry)

    # ログ取得コマンド（ついでにここに入れられる）
    @commands.command()
    async def logs(self, ctx, lines: int = 10):
        logs = list(self.logs)[-lines:]

        if not logs:
            await ctx.send("ログはありません。")
            return

        text = "\n".join(logs)

        if len(text) > 1900:
            text = text[-1900:]

        await ctx.send(f"```{text}```")
