# -*- coding: utf-8 -*-
import discord
from discord.ext import commands
import defining as df

class AutoReply(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message):
        # ボット自身のメッセージには反応しない
        if message.author == self.bot.user:
            return

        # --- 追加分 ---

        if message.content == "うぉw":
            print(df.format_log(f"Reply to 'うぉw' from {message.author}"))
            await message.reply("冷笑しててうぉw", mention_author=True)
            return

        if message.content == "これはおおだろ":
            print(df.format_log(f"Reply to 'これはおおだろ' from {message.author}"))
            await message.reply("おおじゃないが", mention_author=True)
            return

        if message.content == "おおじゃないが":
            print(df.format_log(f"Reply to 'おおじゃないが' from {message.author}"))
            await message.reply("おお？", mention_author=True)
            return

        # --- 既存分 ---

        if message.content == "おおだが":
            print(df.format_log(f"Reply to 'おおだが' from {message.author}"))
            await message.reply("おおだったか", mention_author=True)
            return

        if message.content == "おお":
            print(df.format_log(f"Reply to 'おお' from {message.author}"))
            await message.reply("おおじゃないが", mention_author=True)
            return

async def setup(bot):
    await bot.add_cog(AutoReply(bot))
