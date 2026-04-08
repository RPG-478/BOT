import discord
from discord.ext import commands
import asyncio
import time
import logging


class Voice(commands.Cog):

    def __init__(self, bot):
        self.bot = bot
        self.reaction_enabled = {}
        self.emoji_sounds = {}  # guildごと
        self.log_buffer = bot.log_buffer  # ← ここ追加
    

    @commands.Cog.listener()
    async def on_command_error(self, ctx, error):
        logging.exception("Command error")
        await ctx.send(f"エラー: {error}")

    # =====================
    # CPU / メモリ
    # =====================
    def get_cpu_usage(self):
        def read_cpu():
            #procからcpu負荷などを参照
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

    def get_mem_usage(self):
        meminfo = {}
        #procからメモリ使用率を参照
        with open("/proc/meminfo") as f:
            for line in f:
                key, value = line.split(":")
                meminfo[key] = int(value.split()[0])

        total = meminfo["MemTotal"]
        free = meminfo["MemAvailable"]

        used = total - free
        percent = used / total * 100

        return percent, used, total

    # =====================
    # VC
    # =====================
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

    #イコライザーコマンド
    @commands.command()
    async def eq(self, ctx, mode: str = "flat"):
        #プリセット
        eq_settings = {
            "bass": "bass=g=10",
            "treble": "treble=g=8",
            "vocal": "equalizer=f=1000:width_type=o:width=2:g=5",
            "flat": None
        }

        if mode not in eq_settings:
            await ctx.send("mode: bass / treble / vocal / flat")
            return

        self.eq_filter = eq_settings[mode]

        await ctx.send(f"EQ設定を {mode} にしました")

    # =====================
    # ノイズ
    # =====================
    @commands.command()
    async def noise(self, ctx, noisetype: str = "brown"):
        vc = ctx.voice_client

        if vc is None:
            await ctx.send("先に !join してください。")
            return

        if vc.is_playing():
            vc.stop()

        vc.play(discord.FFmpegPCMAudio(
            f"anoisesrc=color={noisetype}:sample_rate=48000",
            before_options="-f lavfi"
        ))

        await ctx.send(f"{noisetype}ノイズ再生開始")

    @commands.command()
    async def stop(self, ctx):
        vc = ctx.voice_client

        if vc is None:
            await ctx.send("接続していません。")
            return

        if not vc.is_playing():
            await ctx.send("現在再生していません。")
            return

        vc.stop()
        await ctx.send("再生を停止しました。")

    # =====================
    # 添付再生
    # =====================
    @commands.command()
    async def play(self, ctx):
        vc = ctx.voice_client

        if vc is None:
            await ctx.send("先に !join してください。")
            return

        if not ctx.message.attachments:
            await ctx.send("音声ファイルを添付してください。")
            return

        attachment = ctx.message.attachments[0]
        url = attachment.url

        if vc.is_playing():
            vc.stop()

        vc.play(discord.FFmpegPCMAudio(
            url,
            options=f"-af {self.eq_filter}" if self.eq_filter else None
        ))
        await ctx.send("再生開始")

    # =====================
    # システム情報
    # =====================
    @commands.command()
    async def sysinfo(self, ctx):
        cpu = self.get_cpu_usage()
        mem_percent, used, total = self.get_mem_usage()

        msg = (
            f"CPU使用率: {cpu:.1f}%\n"
            f"メモリ使用率: {mem_percent:.1f}%\n"
            f"使用中: {used/1024/1024:.2f}GB / {total/1024/1024:.2f}GB"
        )
        
    @commands.command()
    async def logs(self, ctx, lines: int = 10):
        logs = list(self.log_buffer.logs)[-lines:]

        if not logs:
            await ctx.send("ログはありません。")
            return

        text = "\n".join(logs)

        if len(text) > 1900:
            text = text[-1900:]

        await ctx.send(f"```{text}```")
        await ctx.send(msg)

async def setup(bot):
    await bot.add_cog(Voice(bot))
