import discord
from discord.ext import commands
import asyncio
import time
import logging
import io
import configparser


class Voice(commands.Cog):

    def __init__(self, bot):
        self.bot = bot
        self.reaction_enabled = {}
        self.emoji_sounds = {}  # guildごと
        self.log_buffer = bot.log_buffer  # ← ここ追加
        self.eq_filter = "flat"
        self.queue = asyncio.Queue()  # 再生待ち行列
        self.current_ctx = None
    

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

    # キュー

    def play_next(self, error=None):
        """再生終了時に呼ばれるコールバック"""
        if error:
            logging.error(f"Player error: {error}")
        
        # 同期関数の中から非同期のcheck_queueを安全に呼び出す
        asyncio.run_coroutine_threadsafe(self.check_queue(), self.bot.loop)

    async def check_queue(self):
        """キューを確認して再生する"""
        vc = self.current_ctx.voice_client
        if vc is None or self.queue.empty():
            return

        # キューから次の曲を取得
        url, filename = await self.queue.get()

        # ストリーミングの安定性を高める設定
        # -user_agent を追加してサーバー拒否を防ぐ
        before_options = (
            "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 "
            "-user_agent 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36'"
        )
        audio_filters = f" -af {self.eq_filter}" if self.eq_filter else ""
        options = f"{audio_filters} -vn -sn -dn -ar 48000"

        try:
            vc.play(discord.FFmpegPCMAudio(
                url,
                before_options=before_options,
                options=options
            ), after=self.play_next)
            await self.current_ctx.send(f"再生中: **{filename}**")
        except Exception as e:
            await self.current_ctx.send(f"再生エラー: {e}")
            self.play_next() # エラー時は次へ

    # =====================
    # 添付再生
    # =====================
    @commands.command()
    async def play(self, ctx):
        vc = ctx.voice_client
        if vc is None:
            return await ctx.send("先に !join してください。")

        if not ctx.message.attachments:
            return await ctx.send("音声ファイルまたはPLSファイルを添付してください。")

        self.current_ctx = ctx
        attachment = ctx.message.attachments[0]
        url = attachment.url
        filename = attachment.filename

        # PLSファイル解析
        if filename.endswith('.pls'):
            try:
                content = await attachment.read()
                config = configparser.ConfigParser()
                config.read_string(content.decode('utf-8'))
                if 'playlist' in config and 'File1' in config['playlist']:
                    url = config['playlist']['File1']
                else:
                    return await ctx.send("PLS解析失敗: File1が見つかりません。")
            except Exception as e:
                return await ctx.send(f"PLS読み込みエラー: {e}")

        # キューに追加
        await self.queue.put((url, filename))

        # 何も再生していなければ再生開始
        if not vc.is_playing():
            await self.check_queue()
        else:
            await ctx.send(f"キューに追加しました: {filename} (現在 {self.queue.qsize()} 件待ち)")

    @commands.command()
    async def skip(self, ctx):
        """現在の曲をスキップ"""
        vc = ctx.voice_client
        if vc and vc.is_playing():
            vc.stop() # これで自動的に after=play_next が呼ばれる
            await ctx.send("スキップしました。")
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
        await ctx.send(msg)
    @commands.command()          # ← クラス内に戻す（インデント修正）
    async def logs(self, ctx, lines: int = 10):
        log_buffer = self.bot.log_buffer
        logs = list(log_buffer.logs)[-lines:]
        if not logs:
            await ctx.send("ログはありません。")
            return
        text = "\n".join(logs)
        if len(text) > 1900:
            text = text[-1900:]
        await ctx.send(f"```\n{text}\n```")

    @commands.command()
    async def stats(self, ctx):
        guild_count = len(ctx.bot.guilds)
        user_count = sum(g.member_count for g in ctx.bot.guilds if g.member_count)

        embed = discord.Embed(
            title="stats"
        )
        embed.add_field(name="総サーバー数",value=f"{guild_count}")
        embed.add_field(name="総ユーザー数",value=f"{user_count}")
        
        await ctx.send(embed=embed)
async def setup(bot):
    await bot.add_cog(Voice(bot))
