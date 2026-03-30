# -*- coding: utf-8 -*-
import discord
from discord.ext import commands
import defining as df

class AutoReply(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message):
        # ボット自身のメッセージには反応しない（無限ループ防止）
        if message.author == self.bot.user:
            return

        # 「おおだが」に反応（「おお」より先に判定する必要があります）
        if message.content == "おおだが":
            print(df.format_log(f"Reply to 'おおだが' from {message.author}"))
            await message.reply("おおだったか", mention_author=True)
            return # 判定が一致したら終了

        # 「おお」に反応
        if message.content == "おお":
            print(df.format_log(f"Reply to 'おお' from {message.author}"))
            await message.reply("おおじゃないが", mention_author=True)
            return

async def setup(bot):
    await bot.add_cog(AutoReply(bot))
