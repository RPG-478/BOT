import discord
from discord.ext import commands
import asyncio

class vc(commands.Cog):
        def __init__(self, bot):
            self.bot = bot
            voice_client = self.guild.voice_client

        @commands.command()
        async def join(self, ctx):
            #VCに入っていなかったら弾く
            if ctx.author.voice is None:
                await ctx.channel.send("あなたはボイスチャンネルに接続していません。")
                return
            #接続する
            await ctx.author.voice.channel.connect()

            await ctx.channel.send("接続しました。")
        @commands.command()
        async def leave(self, ctx):
            if ctx.author.voice_client is None:
                await ctx.channel.send("接続していません")
                return
            #切断する
            await ctx.guild.voice_client.disconnect()

            await ctx.channel.send("切断しました。")
