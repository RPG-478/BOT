# -*- coding: utf-8 -*-
import discord
from discord.ext import commands
import defining as df

class AutoReply(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # チャンネル/スレッドIDをキーにして、オンオフ状態(bool)を保持する辞書
        # 初期状態をオフにするため、明示的に登録されていないIDはオフとして扱います
        self.enabled_channels = {}

    @commands.command(name="oo")
    async def toggle_oo(self, ctx):
        """現在のチャンネルまたはスレッドで自動返信のオン/オフを切り替える"""
        channel_id = ctx.channel.id
        
        # 現在の状態を取得（辞書になければFalse = オフ）
        current_status = self.enabled_channels.get(channel_id, False)
        
        # 状態を反転させる
        new_status = not current_status
        self.enabled_channels[channel_id] = new_status
        
        status_text = "オン" if new_status else "オフ"
        await ctx.send(f"この場所での自動返信機能を **{status_text}** にしました。")

    @commands.Cog.listener()
    async def on_message(self, message):
        # ボット自身のメッセージには反応しない
        if message.author == self.bot.user:
            return

        # 現在のチャンネル/スレッドが「オン」に設定されているか確認
        # 登録されていない場合はデフォルトで False (オフ)
        if not self.enabled_channels.get(message.channel.id, False):
            return

        # コマンド実行（!oo）自体に反応しないようにする
        if message.content.startswith(self.bot.command_prefix):
            return

        # --- 判定処理 ---
        content = message.content

        if content == "うぉw":
            print(df.format_log(f"Reply to 'うぉw' from {message.author} in {message.channel}"))
            await message.channel.send("冷笑しててうぉw")
            return

        if content == "これはおおだろ":
            print(df.format_log(f"Reply to 'これはおおだろ' from {message.author} in {message.channel}"))
            await message.channel.send("おおじゃないが")
            return

        if content == "おおじゃないが":
            print(df.format_log(f"Reply to 'おおじゃないが' from {message.author} in {message.channel}"))
            await message.channel.send("おお？")
            return

        if content == "おおだが":
            print(df.format_log(f"Reply to 'おおだが' from {message.author} in {message.channel}"))
            await message.channel.send("おおだったか")
            return

        if content == "おお":
            print(df.format_log(f"Reply to 'おお' from {message.author} in {message.channel}"))
            await message.channel.send("おおじゃないが")
            return

async def setup(bot):
    await bot.add_cog(AutoReply(bot))
