# -*- coding: utf-8 -*-
import discord
from discord.ext import commands
import defining as df

class AutoReply(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.enabled = True  # 初期状態はオン

    @commands.command(name="oo")
    async def toggle_oo(self, ctx):
        """自動返信のオン/オフを切り替えるコマンド"""
        self.enabled = not self.enabled
        status = "オン" if self.enabled else "オフ"
        await ctx.send(f"自動返信機能を{status}にしました。")

    @commands.Cog.listener()
    async def on_message(self, message):
        # ボット自身のメッセージには反応しない
        if message.author == self.bot.user:
            return

        # 機能がオフの場合は何もしない
        if not self.enabled:
            return

        # コマンド実行（!oo）自体に反応しないようにする
        if message.content.startswith(self.bot.command_prefix):
            return

        # --- 判定処理 ---
        # replyではなくchannel.sendを使うことで、引用返信（メンション）なしの通常送信になります。

        if message.content == "うぉw":
            print(df.format_log(f"Reply to 'うぉw' from {message.author}"))
            await message.channel.send("冷笑しててうぉw")
            return

        if message.content == "これはおおだろ":
            print(df.format_log(f"Reply to 'これはおおだろ' from {message.author}"))
            await message.channel.send("おおじゃないが")
            return

        if message.content == "おおじゃないが":
            print(df.format_log(f"Reply to 'おおじゃないが' from {message.author}"))
            await message.channel.send("おお？")
            return

        if message.content == "おおだが":
            print(df.format_log(f"Reply to 'おおだが' from {message.author}"))
            await message.channel.send("おおだったか")
            return

        if message.content == "おお":
            print(df.format_log(f"Reply to 'おお' from {message.author}"))
            await message.channel.send("おおじゃないが")
            return

async def setup(bot):
    await bot.add_cog(AutoReply(bot))
