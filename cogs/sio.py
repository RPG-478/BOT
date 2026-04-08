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
    async def noise(self, ctx, type: str):
        noisetype = ""
        if type is None:
            noisetype = "brown"
        else:
            noisetype = type
        vc = ctx.voice_client
        vc.play(discord.FFmpegPCMAudio(
            f"anoisesrc=color={noisetype}:sample_rate=48000",
            before_options="-f lavfi"
        ))
    @commands.command()
    async def stop(self, ctx):
        vc = ctx.voice_client

        # VC未接続
            
        if vc is None:
            await ctx.send("接続していません。")
            return

    # 再生していない
        if not vc.is_playing():
            await ctx.send("現在再生していません。")
            return

        vc.stop()
        await ctx.send("再生を停止しました。")
    @commands.command()
    async def play(self, ctx):
        vc = ctx.voice_client

        # VC未接続
        if vc is None:
            await ctx.send("先に !join してください。")
            return

        # 添付ファイルがない
        if not ctx.message.attachments:
            await ctx.send("音声ファイルを添付してください。")
            return

        attachment = ctx.message.attachments[0]
        url = attachment.url  # ← これが重要

        # 再生中チェック
        if vc.is_playing():
            vc.stop()

        vc.play(discord.FFmpegPCMAudio(url))

        await ctx.send("再生開始")

async def setup(bot):
    await bot.add_cog(Voice(bot))
