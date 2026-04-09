import discord
from discord.ext import commands
import asyncio
import time
import logging
import configparser

class Voice(commands.Cog):

    def __init__(self, bot):
        self.bot = bot
        self.reaction_enabled = {}
        self.emoji_sounds = {}  # Per guild
        self.log_buffer = bot.log_buffer
        self.eq_filter = None  # Default is None
        self.queue = asyncio.Queue()  # Playback queue
        self.current_ctx = None
        self.is_processing_queue = False # Guard to prevent concurrent queue checks

    @commands.Cog.listener()
    async def on_command_error(self, ctx, error):
        logging.exception("Command error")
        await ctx.send(f"エラー: {error}")

    # =====================
    # CPU / Memory Info
    # =====================
    def get_cpu_usage(self):
        def read_cpu():
            try:
                with open("/proc/stat", "r") as f:
                    line = f.readline()
                    values = list(map(int, line.split()[1:]))
                    idle = values[3]
                    total = sum(values)
                    return idle, total
            except Exception:
                return 0, 1
        
        idle1, total1 = read_cpu()
        time.sleep(0.5)
        idle2, total2 = read_cpu()
        
        idle_delta = idle2 - idle1
        total_delta = total2 - total1
        if total_delta == 0: return 0
        return 100 * (1 - idle_delta / total_delta)

    def get_mem_usage(self):
        try:
            meminfo = {}
            with open("/proc/meminfo") as f:
                for line in f:
                    parts = line.split(":")
                    if len(parts) == 2:
                        key, value = parts
                        meminfo[key] = int(value.split()[0])
            total = meminfo.get("MemTotal", 1)
            free = meminfo.get("MemAvailable", meminfo.get("MemFree", 0))
            used = total - free
            percent = (used / total) * 100
            return percent, used, total
        except Exception:
            return 0, 0, 0

    # =====================
    # VC Control
    # =====================
    @commands.command()
    async def join(self, ctx):
        if ctx.author.voice is None:
            await ctx.send("あなたはボイスチャンネルに接続していません。")
            return

        vc = ctx.voice_client
        if vc is None:
            await ctx.author.voice.channel.connect(timeout=20.0, reconnect=True)
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

        # Clear queue and stop
        while not self.queue.empty():
            self.queue.get_nowait()
        
        await vc.disconnect()
        await ctx.send("切断しました。")

    @commands.command()
    async def eq(self, ctx, mode: str = "flat"):
        """
        高度な音響設定
        modes: bass, echo, hall, vocal, superbass, flat
        """
        eq_settings = {
            # 低音強調 + 音量正規化
            "bass": "bass=g=10,dynaudnorm", 
            # 山びこエフェクト (遅延200ms)
            "echo": "aecho=0.8:0.8:200:0.4", 
            # コンサートホール風 (短い残響 + ステレオ幅拡張)
            "hall": "aecho=0.8:0.88:60:0.4,extrastereo=m=2.5", 
            # 高度なイコライザー (中音域/人の声を強調)
            "vocal": "firequalizer=gain_entry='entry(100, -5); entry(400, 0); entry(1000, 5); entry(4000, 5); entry(8000, 0)'",
            # 超低域 (31Hz-62Hz) をピンポイントで爆上げ
            "superbass": "firequalizer=gain_entry='entry(31, 15); entry(62, 10); entry(125, 5); entry(250, 0)'",
            "flat": None
        }

        if mode not in eq_settings:
            await ctx.send("利用可能なモード: bass, echo, hall, vocal, superbass, flat")
            return

        self.eq_filter = eq_settings[mode]
        await ctx.send(f"音響エフェクトを `{mode}` に変更しました。(次曲から適用)")

    # =====================
    # Playback Logic
    # =====================
    def play_next(self, error=None):
        if error:
            logging.error(f"FFmpeg play_next error: {error}")
        
        self.is_processing_queue = False
        # Schedule next queue check in the event loop
        if self.bot.loop.is_running():
            asyncio.run_coroutine_threadsafe(self.check_queue(), self.bot.loop)

    async def check_queue(self):
        # Prevent multiple instances from running at once
        if self.is_processing_queue or self.current_ctx is None:
            return

        vc = self.current_ctx.voice_client
        if vc is None or not vc.is_connected():
            return

        if self.queue.empty():
            return

        self.is_processing_queue = True

        # Get next item
        url, filename = await self.queue.get()

        # Robust FFmpeg options for streaming stability
        # -reconnect options help with network hiccups
        before_options = (
            "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 "
            "-headers 'User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36'"
        )
        
        # Audio filters and standard output settings
        audio_filters = f" -af {self.eq_filter}" if self.eq_filter else ""
        options = (
            f"{audio_filters} -vn -sn -dn -ar 48000 -ac 2 "
            "-probesize 32M -analyzeduration 32M -loglevel warning"
        )

        try:
            # Short delay to ensure cleanup of previous process
            await asyncio.sleep(0.3)
            
            # Re-check connection before play
            if not vc.is_connected():
                await self.current_ctx.send("接続が切断されたため、再生を中断しました。")
                self.is_processing_queue = False
                return

            source = discord.FFmpegPCMAudio(url, before_options=before_options, options=options)
            vc.play(source, after=self.play_next)
            await self.current_ctx.send(f"再生中: **{filename}**")
        except Exception as e:
            logging.error(f"Playback startup error: {e}")
            await self.current_ctx.send(f"再生開始エラー: {e}")
            self.is_processing_queue = False
            # Try next in queue
            await self.check_queue()

    @commands.command()
    async def play(self, ctx):
        vc = ctx.voice_client
        if vc is None:
            return await ctx.send("先に !join してください。")

        if not ctx.message.attachments:
            return await ctx.send("音声ファイルを添付してコマンドを実行してください。")

        self.current_ctx = ctx
        attachment = ctx.message.attachments[0]
        url = attachment.url
        filename = attachment.filename

        # Support PLS playlist files as single source
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

        # Add to queue
        await self.queue.put((url, filename))

        # Start playback if nothing is playing
        if not vc.is_playing() and not self.is_processing_queue:
            await self.check_queue()
        else:
            await ctx.send(f"キューに追加しました: {filename} (待ち: {self.queue.qsize()}件)")

    @commands.command()
    async def skip(self, ctx):
        vc = ctx.voice_client
        if vc and vc.is_playing():
            vc.stop() # This triggers 'after=play_next'
            await ctx.send("スキップしました。")
        else:
            await ctx.send("現在再生中ではありません。")

    @commands.command()
    async def stop(self, ctx):
        vc = ctx.voice_client
        if vc is None:
            await ctx.send("ボイスチャンネルに接続していません。")
            return

        # Clear queue
        while not self.queue.empty():
            self.queue.get_nowait()
        
        if vc.is_playing():
            vc.stop()
            await ctx.send("再生を停止し、キューをクリアしました。")
        else:
            await ctx.send("キューをクリアしました。")

    # =====================
    # Stats / Diagnostics
    # =====================
    @commands.command()
    async def sysinfo(self, ctx):
        cpu = self.get_cpu_usage()
        mem_percent, used, total = self.get_mem_usage()
        msg = (
            f"**システム情報**\n"
            f"CPU使用率: `{cpu:.1f}%` \n"
            f"メモリ使用率: `{mem_percent:.1f}%` \n"
            f"使用量: `{used/128/128:.1f}MB / {total/128/128:.1f}MB`"
        )
        await ctx.send(msg)

    @commands.command()
    async def logs(self, ctx, lines: int = 10):
        log_buffer = self.bot.log_buffer
        logs = list(log_buffer.logs)[-lines:]
        if not logs:
            await ctx.send("表示するログがありません。")
            return
        text = "\n".join(logs)
        if len(text) > 1900:
            text = text[-1900:]
        await ctx.send(f"```\n{text}\n```")

    @commands.command()
    async def stats(self, ctx):
        guild_count = len(self.bot.guilds)
        total_members = sum(g.member_count for g in self.bot.guilds if g.member_count)
        embed = discord.Embed(title="Bot 稼働統計", color=discord.Color.blue())
        embed.add_field(name="サーバー数", value=f"{guild_count}", inline=True)
        embed.add_field(name="総ユーザー数", value=f"{total_members}", inline=True)
        await ctx.send(embed=embed)

async def setup(bot):
    await bot.add_cog(Voice(bot))
