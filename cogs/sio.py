import discord
from discord.ext import commands

class Voice(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command()
    async def join(self, ctx):
        if ctx.author.voice is None:
            await ctx.send("あなたはボイスチャンネルに接続していません。")
            return

        vc = ctx.voice_client

        if vc is None:
            await ctx.author.voice.channel.connect()
            await ctx.send("接続しました。")
        else:
            if vc.channel == ctx.author.voice.channel:
                await ctx.send("すでに接続しています。")
            else:
                await vc.move_to(ctx.author.voice.channel)
                await ctx.send("チャンネルを移動しました。")

    @commands.command()
    async def leave(self, ctx):
        vc = ctx.voice_client

        if vc is None:
            await ctx.send("接続していません。")
            return

        await vc.disconnect()
        await ctx.send("切断しました。")


async def setup(bot):
    await bot.add_cog(Voice(bot))
