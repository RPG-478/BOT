import discord
from discord.ext import commands

class Voice(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command()
    async def join(self, ctx):
        #接続していない場合をはじく
        if ctx.author.voice is None:
            await ctx.send("あなたはボイスチャンネルに接続していません。")
            return

        vc = ctx.voice_client
        #接続する
        if vc is None:
            await ctx.author.voice.channel.connect()
            await ctx.send("接続しました。")
        #既に接続していない場合などの処理
        else:
            if vc.channel == ctx.author.voice.channel:
                await ctx.send("すでに接続しています。")
            else:
                await vc.move_to(ctx.author.voice.channel)
                await ctx.send("チャンネルを移動しました。")

    @commands.command()
    async def leave(self, ctx):
        vc = ctx.voice_client
        #接続していない場合
        if vc is None:
            await ctx.send("接続していません。")
            return
        #切断処理
        await vc.disconnect()
        await ctx.send("切断しました。")
    @commands.command()
    async def noise(self, ctx):
        vc = ctx.voice_client
        vc.play(discord.FFmpegPCMAudio(
            "anoisesrc=color=brown:sample_rate=48000",
            before_options="-f lavfi"
        ))

async def setup(bot):
    await bot.add_cog(Voice(bot))
