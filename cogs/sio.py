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
        if error:
            logging.error(f"FFmpeg error: {error}")
        # 再生終了後にキューを確認
        asyncio.run_coroutine_threadsafe(self.check_queue(), self.bot.loop)

    async def check_queue(self):
        if self.current_ctx is None or self.queue.empty():
            return

        vc = self.current_ctx.voice_client
        if vc is None:
            return

        # キューからURLとファイル名を取得
        url, filename = await self.queue.get()

        # ストリーミングと通常のファイル両方に対応する安定設定
        # -re を維持しつつ、再接続とエージェント偽装を追加
        before_options = (
            "-re -reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 "
            "-user_agent 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36'"
        )
        
        audio_filters = f" -af {self.eq_filter}" if self.eq_filter else ""
        # 安定性を高めるためのバッファ設定
        options = f"{audio_filters} -vn -sn -dn -ar 48000 -probesize 10M -analyzeduration 10M"

        try:
            # URLをシングルクォートで囲むことで特殊文字によるエラーを防ぐ
            source = discord.FFmpegPCMAudio(url, before_options=before_options, options=options)
            vc.play(source, after=self.play_next)
            await self.current_ctx.send(f"再生中: **{filename}**")
        except Exception as e:
            logging.error(f"Playback error: {e}")
            await self.current_ctx.send(f"再生エラー: {e}")
            self.play_next()

    @commands.command()
    async def play(self, ctx):
        vc = ctx.voice_client
        if vc is None:
            return await ctx.send("先に !join してください。")

        if not ctx.message.attachments:
            return await ctx.send("ファイルを添付してください。")

        self.current_ctx = ctx
        attachment = ctx.message.attachments[0]
        url = attachment.url
        filename = attachment.filename

        # --- PLSファイルの解析 ---
        if filename.lower().endswith('.pls'):
            try:
                content = await attachment.read()
                pls_content = content.decode('utf-8')
                config = configparser.ConfigParser()
                config.read_string(pls_content)
                
                if 'playlist' in config and 'File1' in config['playlist']:
                    url = config['playlist']['File1']
                else:
                    return await ctx.send("PLSファイル内に有効なURLが見つかりませんでした。")
            except Exception as e:
                return await ctx.send(f"PLS解析エラー: {e}")

        # キューに追加
        await self.queue.put((url, filename))

        # 再生中でなければ開始
        if not vc.is_playing():
            await self.check_queue()
        else:
            await ctx.send(f"キューに追加しました: {filename} (待ち: {self.queue.qsize()}件)")

    @commands.command()
    async def skip(self, ctx):
        vc = ctx.voice_client
        if vc and vc.is_playing():
            vc.stop()
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
