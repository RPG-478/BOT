import discord
from discord.ext import commands
import time

class Voice(commands.Cog):
    def get_cpu_usage():
        def read_cpu():
            with open("/proc/stat", "r") as f:
                line = f.readline()
                values = list(map(int, line.split()[1:]))
                idle = values[3]
                total = sum(values)
                return idle, total

        idle1, total1 = read_cpu()
        time.sleep(1)
        idle2, total2 = read_cpu()

        idle_delta = idle2 - idle1
        total_delta = total2 - total1

        return 100 * (1 - idle_delta / total_delta)
    def get_mem_usage():
        meminfo = {}
        with open("/proc/meminfo") as f:
            for line in f:
                key, value = line.split(":")
                meminfo[key] = int(value.split()[0])
    
        total = meminfo["MemTotal"]
        free = meminfo["MemAvailable"]

        used = total - free
        percent = used / total * 100

        return percent, used, total
        
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
    @commands.command()
    async def sysinfo(self, ctx):
        cpu = get_cpu_usage()
        mem_percent, used, total = get_mem_usage()

        msg = (
            f"CPU使用率: {cpu:.1f}%\n"
            f"メモリ使用率: {mem_percent:.1f}%\n"
            f"使用中: {used/1024/1024:.2f}GB / {total/1024/1024:.2f}GB"
        )

    await ctx.send(msg)
        
async def setup(bot):
    await bot.add_cog(Voice(bot))
