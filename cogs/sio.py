import discord
from discord.ext import commands
import asyncio
import time
import logging
import configparser
import string
import subprocess
import json

# BASE62の定義
BASE62 = string.digits + string.ascii_lowercase + string.ascii_uppercase

def encode_full_id(guild_id: int, channel_id: int, message_id: int) -> str:
    """サーバー・チャンネル・メッセージの3つのIDを1つの62進数に統合"""
    combined = (guild_id << 128) | (channel_id << 64) | message_id
    if combined == 0: return BASE62[0]
    arr = []
    base = len(BASE62)
    while combined:
        combined, rem = divmod(combined, base)
        arr.append(BASE62[rem])
    arr.reverse()
    return ''.join(arr)

def decode_full_id(b62_id: str):
    """62進数からギルドID, チャンネルID, メッセージIDを復元"""
    base = len(BASE62)
    combined = 0
    for idx, char in enumerate(b62_id[::-1]):
        combined += BASE62.index(char) * (base ** idx)
    guild_id = combined >> 128
    channel_id = (combined >> 64) & ((1 << 64) - 1)
    message_id = combined & ((1 << 64) - 1)
    return guild_id, channel_id, message_id

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
        self.current_track = None  # (url, filename, total_duration)
        self.start_time = 0        # 再生開始時刻の記録
        self.elapsed_offset = 0    # 再生済みの秒数
        self.retry_count = 0
        self.MAX_RETRIES = 3

    @commands.Cog.listener()
    async def on_command_error(self, ctx, error):
        logging.exception("Command error")
        await ctx.send(f"エラー: {error}")
    
    async def get_duration(self, url):
        """ffprobeを使用して音声の長さを取得"""
        try:
            cmd = [
                'ffprobe', '-v', 'quiet', '-print_format', 'json',
                '-show_format', '-show_streams', url
            ]
            proc = await asyncio.create_subprocess_exec(
                *cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE
            )
            stdout, _ = await proc.communicate()
            data = json.loads(stdout)
            return float(data['format']['duration'])
        except Exception as e:
            logging.error(f"Duration取得エラー: {e}")
            return 0

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



            
    async def get_attachment_info(self, b62_id: str):
        """統合された62進数IDから添付ファイル情報を取得 (他サーバー対応)"""
        try:
            guild_id, channel_id, message_id = decode_full_id(b62_id)
            
            # ギルドの取得
            guild = self.bot.get_guild(guild_id) or await self.bot.fetch_guild(guild_id)
            # チャンネルの取得
            channel = guild.get_channel(channel_id) or await guild.fetch_channel(channel_id)
            # メッセージの取得
            msg = await channel.fetch_message(message_id)
            
            if msg.attachments:
                return msg.attachments[0].url, msg.attachments[0].filename
        except Exception as e:
            logging.error(f"Universal ID取得エラー ({b62_id}): {e}")
            return None, None
        return None, None


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
        """音響エフェクト設定 (bass/echo/hall/vocal/superbass/flat)"""
        eq_settings = {
            "bass": "bass=g=10,dynaudnorm",
            "echo": "aecho=0.8:0.8:200:0.4",
            "hall": "aecho=0.8:0.88:60:0.4,extrastereo=m=2.5",
            "vocal": "firequalizer=gain_entry='entry(100, -5); entry(1000, 5); entry(4000, 5); entry(8000, 0)'",
            "superbass": "firequalizer=gain_entry='entry(31, 15); entry(62, 10); entry(125, 5)'",
            "flat": None
        }
        if mode not in eq_settings:
            return await ctx.send("利用可能なモード: bass, echo, hall, vocal, superbass, flat")
        self.eq_filter = eq_settings[mode]
        await ctx.send(f"エフェクトを `{mode}` に変更しました。")


    # =====================
    # Playback Logic
    # =====================
    async def check_queue(self):
        if self.is_processing_queue or self.current_ctx is None: return
        vc = self.current_ctx.voice_client
        if vc is None or not vc.is_connected(): return

        if self.current_track is None:
            if self.queue.empty(): return
            url, filename = await self.queue.get()
            duration = await self.get_duration(url)
            self.current_track = (url, filename, duration)
            self.elapsed_offset = 0
            self.retry_count = 0
        
        url, filename, duration = self.current_track
        self.is_processing_queue = True

        before_options = (
            f"-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 "
            f"-ss {self.elapsed_offset} "
            f"-headers 'User-Agent: Mozilla/5.0'"
        )
        af = f" -af {self.eq_filter}" if self.eq_filter else ""
        options = f"{af} -vn -sn -dn -ar 48000 -ac 2 -probesize 32M -analyzeduration 32M"

        try:
            await asyncio.sleep(0.5)
            source = discord.FFmpegPCMAudio(url, before_options=before_options, options=options)
            self.start_time = time.time()
            vc.play(source, after=self.play_next)
            
            if self.elapsed_offset == 0:
                await self.current_ctx.send(f"🎵 再生開始: **{filename}** ({int(duration)}s)")
            else:
                await self.current_ctx.send(f"🔄 再開({self.retry_count}): **{filename}** {int(self.elapsed_offset)}s付近")
        except Exception as e:
            logging.error(f"Playback error: {e}")
            self.is_processing_queue = False
            self.current_track = None
            await self.check_queue()

    def play_next(self, error=None):
        actual_played = time.time() - self.start_time
        self.elapsed_offset += actual_played
        
        url, filename, duration = self.current_track if self.current_track else (None, None, 0)
        is_interrupted = (duration - self.elapsed_offset) > 5
        self.is_processing_queue = False

        if is_interrupted and self.retry_count < self.MAX_RETRIES and self.current_track:
            self.retry_count += 1
            logging.warning(f"再生中断検知: {filename} を再開します。")
            asyncio.run_coroutine_threadsafe(self.check_queue(), self.bot.loop)
        else:
            self.current_track = None
            self.elapsed_offset = 0
            self.retry_count = 0
            asyncio.run_coroutine_threadsafe(self.check_queue(), self.bot.loop)
            
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
    async def stop(self, ctx):
        vc = ctx.voice_client
        if vc:
            self.current_track = None
            while not self.queue.empty(): self.queue.get_nowait()
            vc.stop()
            await ctx.send("再生を停止し、キューをクリアしました。")

    @commands.command()
    async def skip(self, ctx):
        vc = ctx.voice_client
        if vc and vc.is_playing():
            self.current_track = None
            vc.stop()
            await ctx.send("スキップしました。")

# --- 3. クラス内の list, id, plist コマンドを置き換え ---
    @commands.command()
    async def list(self, ctx, limit: int = 20):
        """このチャンネルの音声をスキャンし、他サーバーでも使える統合IDを表示"""
        embed = discord.Embed(title="🎵 チャンネル内音声リスト", color=discord.Color.blue())
        description = "これらのIDは全サーバー共通で利用可能です\n" + "─" * 20 + "\n"
        found = False
        async for message in ctx.channel.history(limit=limit):
            if message.attachments:
                found = True
                # ギルド・チャンネル・メッセージを統合したIDを生成
                b62_id = encode_full_id(ctx.guild.id, ctx.channel.id, message.id)
                filename = message.attachments[0].filename
                description += f"`{b62_id}` : **{filename}**\n"
        
        if not found: description = "音声が見つかりませんでした。"
        embed.description = description
        await ctx.send(embed=embed)

    @commands.command()
    async def id(self, ctx):
        """直近の音声のユニバーサルIDを表示"""
        async for message in ctx.channel.history(limit=10):
            if message.attachments:
                b62 = encode_full_id(ctx.guild.id, ctx.channel.id, message.id)
                embed = discord.Embed(title="🆔 ユニバーサルID発行", color=discord.Color.green())
                embed.add_field(name="ファイル", value=message.attachments[0].filename, inline=False)
                embed.add_field(name="ID (全サーバー共通)", value=f"`{b62}`", inline=False)
                embed.set_footer(text="このIDをコピーして他サーバーの !plist で使用できます")
                return await ctx.send(embed=embed)
        await ctx.send("添付ファイルが見つかりませんでした。")

    @commands.command()
    async def plist(self, ctx, *, ids_str: str):
        """統合IDを並べて再生 (サーバーを跨いで利用可能)"""
        if not ctx.voice_client: return await ctx.send("先に !join してください。")
        self.current_ctx = ctx
        tokens = ids_str.replace(',', ' ').split()
        added = 0
        for token in tokens:
            url, fname = await self.get_attachment_info(token)
            if url:
                await self.queue.put((url, fname))
                added += 1
        await ctx.send(f"{added} 件の音声をキューに追加しました。")
        if not ctx.voice_client.is_playing() and not self.is_processing_queue:
            await self.check_queue()


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
            f"使用量: `{used/10.24/102.4:.1f}MB / {total/10.24/102.4:.1f}MB`"
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
