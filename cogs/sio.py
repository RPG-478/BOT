import discord
from discord.ext import commands
import asyncio
import time
import logging
import configparser

class Voice(commands.Cog):

    def __init__(self, bot):
        self.bot = botimport discord
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
        eq_settings = {
            "bass": "bass=g=10",
            "treble": "treble=g=8",
            "vocal": "equalizer=f=1000:width_type=o:width=2:g=5",
            "flat": None
        }

        if mode not in eq_settings:
            await ctx.send("利用可能なモード: bass, treble, vocal, flat")
            return

        self.eq_filter = eq_settings[mode]
        await ctx.send(f"EQ設定を {mode} に変更しました。")

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
            "-probesize 32 -analyzeduration 0 -loglevel warning"
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
            f"使用量: `{used/1024/1024:.1f}MB / {total/1024/1024:.1f}MB`"
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
        self.reaction_enabled = {}
        self.emoji_sounds = {}  # guildごと
        self.log_buffer = bot.log_buffer
        self.eq_filter = None  # 初期値はNone
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
    # VC 制御
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
        # キューをクリア
        while not self.queue.empty():
            self.queue.get_nowait()
        await ctx.send("切断しました。")

    @commands.command()
    async def eq(self, ctx, mode: str = "flat"):
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
    # 再生ロジック (キュー機能)
    # =====================
    def play_next(self, error=None):
        if error:
            logging.error(f"FFmpeg error: {error}")
        # 非同期ループでキューの確認を実行
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
        # -re を維持し、再接続オプションとUser-Agentを設定
        before_options = (
            "-re -reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 "
            "-user_agent 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36'"
        )
        
        audio_filters = f" -af {self.eq_filter}" if self.eq_filter else ""
        # 終了コード8対策: probesize/analyzedurationを標準的な値(2M)に設定
        options = f"{audio_filters} -vn -sn -dn -ar 48000 -probesize 2000000 -analyzeduration 2000000"

        try:
            # プロセス競合回避のための微小待機
            await asyncio.sleep(0.5)
            
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
            return await ctx.send("音声ファイルまたはPLSファイルを添付してください。")

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
                    return await ctx.send("PLSファイル内にFile1(URL)が見つかりませんでした。")
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
            vc.stop() # これにより after=play_next が走り次が再生される
            await ctx.send("スキップしました。")

    @commands.command()
    async def stop(self, ctx):
        vc = ctx.voice_client
        if vc is None:
            await ctx.send("接続していません。")
            return

        # キューを空にする
        while not self.queue.empty():
            self.queue.get_nowait()
        
        if vc.is_playing():
            vc.stop()
            await ctx.send("再生を停止し、キューをクリアしました。")
        else:
            await ctx.send("現在再生していません。")

    @commands.command()
    async def noise(self, ctx, noisetype: str = "brown"):
        vc = ctx.voice_client
        if vc is None:
            await ctx.send("先に !join してください。")
            return

        if vc.is_playing():
            vc.stop()

        # ノイズ再生（キューとは別枠の即時再生）
        vc.play(discord.FFmpegPCMAudio(
            f"anoisesrc=color={noisetype}:sample_rate=48000",
            before_options="-f lavfi"
        ))
        await ctx.send(f"{noisetype}ノイズ再生開始")

    # =====================
    # システム情報 & ログ
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

    @commands.command()
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
        guild_count = len(self.bot.guilds)
        user_count = sum(g.member_count for g in self.bot.guilds if g.member_count)
        embed = discord.Embed(title="stats")
        embed.add_field(name="総サーバー数", value=f"{guild_count}")
        embed.add_field(name="総ユーザー数", value=f"{user_count}")
        await ctx.send(embed=embed)

async def setup(bot):
    await bot.add_cog(Voice(bot))
