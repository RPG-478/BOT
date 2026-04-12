import discord
from discord.ext import commands
import asyncio
import time
import logging
import configparser
import string
import subprocess
import json
import io

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

def we(description: str = None, title: str = None) -> discord.Embed:
    """白色embedを生成するヘルパー"""
    return discord.Embed(title=title, description=description, color=0xFFFFFF)

class Voice(commands.Cog):

    def __init__(self, bot):
        self.bot = bot
        self.reaction_enabled = {}
        self.emoji_sounds = {}
        self.log_buffer = bot.log_buffer
        self.eq_filter = None
        self.queue = asyncio.Queue()
        self.current_ctx = None
        self.is_processing_queue = False
        self.current_track = None  # (url, filename, total_duration, b62_id)
        self.start_time = 0
        self.elapsed_offset = 0
        self.retry_count = 0
        self.MAX_RETRIES = 3
        self.supabase = getattr(bot, "supabase", None)
        self.ir_l_id = "d424KTRkAlaetACCuFZOCjUtFNjho1t5" 
        self.ir_r_id = "d424KTRkAlaetACCuFZOCjUtFO0p0TMN"

    @commands.Cog.listener()
    async def on_command_error(self, ctx, error):
        logging.exception("Command error")
        await ctx.send(embed=we(f"エラー: {error}"))
    
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
        except Exception:
            return 0

    # =====================
    # CPU / Memory Info (省略せず保持)
    # =====================
    def get_cpu_usage(self):
        def read_cpu():
            try:
                with open("/proc/stat", "r") as f:
                    line = f.readline()
                    values = list(map(int, line.split()[1:]))
                    return values[3], sum(values)
            except: return 0, 1
        i1, t1 = read_cpu()
        time.sleep(0.5)
        i2, t2 = read_cpu()
        if t2 - t1 == 0: return 0
        return 100 * (1 - (i2 - i1) / (t2 - t1))

    def get_mem_usage(self):
        try:
            mem = {}
            with open("/proc/meminfo") as f:
                for line in f:
                    parts = line.split(":")
                    if len(parts) == 2: mem[parts[0]] = int(parts[1].split()[0])
            total = mem.get("MemTotal", 1)
            used = total - mem.get("MemAvailable", mem.get("MemFree", 0))
            return (used / total) * 100, used, total
        except: return 0, 0, 0
            
    async def get_attachment_info(self, b62_id: str):
        """ユニバーサルIDから情報を取得"""
        try:
            guild_id, channel_id, message_id = decode_full_id(b62_id)
            guild = self.bot.get_guild(guild_id) or await self.bot.fetch_guild(guild_id)
            channel = guild.get_channel(channel_id) or await guild.fetch_channel(channel_id)
            msg = await channel.fetch_message(message_id)
            if msg.attachments:
                return msg.attachments[0].url, msg.attachments[0].filename
        except Exception as e:
            logging.error(f"Universal ID error ({b62_id}): {e}")
        return None, None

    # =====================
    # VC Control & 3D EQ
    # =====================
    @commands.command()
    async def join(self, ctx):
        if ctx.author.voice is None:
            return await ctx.send(embed=we("ボイスチャンネルに接続してください。"))
        vc = ctx.voice_client
        if vc is None:
            await ctx.author.voice.channel.connect(timeout=20.0, reconnect=True)
            await ctx.send(embed=we("接続しました。"))
        else:
            await vc.move_to(ctx.author.voice.channel)
            await ctx.send(embed=we("移動しました。"))

    @commands.command()
    async def leave(self, ctx):
        vc = ctx.voice_client
        if vc:
            while not self.queue.empty(): self.queue.get_nowait()
            await vc.disconnect()
            await ctx.send(embed=we("切断しました。"))

    @commands.command()
    async def eq(self, ctx, mode: str = "flat"):
        """音響エフェクト設定"""
        eq_settings = {
            "bass": "bass=g=10,dynaudnorm",
            "echo": "aecho=0.8:0.8:200:0.4",
            "hall": "extrastereo=m=2.5",
            "vocal": "firequalizer=gain_entry='entry(100, -5); entry(1000, 5); entry(4000, 5); entry(8000, 0)'",
            "superbass": "firequalizer=gain_entry='entry(31, 15); entry(62, 10); entry(125, 5)'",
            "live": "aecho=0.8:0.88:60:0.4,lowpass=f=15000,surround,extrastereo=m=1.5",
            "rotate": "apulsator=hz=0.125:amount=1",
            "reverb": "afir", # 内部処理用フラグ
            "flat": None
        }
        if mode not in eq_settings:
            return await ctx.send(embed=we(f"利用可能: {', '.join(eq_settings.keys())}"))
        self.eq_filter = eq_settings[mode]
        await ctx.send(embed=we(f"エフェクトを `{mode}` に変更しました。"))

    # =====================
    # Playback Logic
    # =====================
    async def check_queue(self):
        if self.is_processing_queue or self.current_ctx is None:
            return
        
        vc = self.current_ctx.voice_client
        if vc is None or not vc.is_connected():
            self.is_processing_queue = False
            return

        if self.current_track is None:
            if self.queue.empty():
                self.is_processing_queue = False
                return
            url, filename, b62_id = await self.queue.get() 
            duration = await self.get_duration(url)
            self.current_track = (url, filename, duration, b62_id) 
            self.elapsed_offset = 0
            self.retry_count = 0

        url, filename, duration, b62_id = self.current_track
        self.is_processing_queue = True

        # 1. 接続オプションの構築
        headers_val = "User-Agent: Mozilla/5.0\r\n"
        before_options = f'-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 -headers "{headers_val}"'
        if self.elapsed_offset > 0:
            before_options += f" -ss {self.elapsed_offset}"

        # 2. フィルターと追加入力の構築
        # 修正後のフィルター構築部分
        if self.eq_filter == "afir":
            url_l, name_l = await self.get_attachment_info(self.ir_l_id)
            url_r, name_r = await self.get_attachment_info(self.ir_r_id)
    
            if not url_l or not url_r:
                self.is_processing_queue = False
                return await self.current_ctx.send("❌ IRファイルの取得に失敗しました。")

            # [0:a] = メイン音声(url)
            # [1:a] = url_l
            # [2:a] = url_r
            options = (
                f"-i \"{url_l}\" -i \"{url_r}\" "
                f"-filter_complex \"[1:a][2:a]join=inputs=2:channel_layout=stereo[ir]; "
                f"[0:a][ir]afir=dry=1:wet=1[out]\" "
                f"-map \"[out]\" -vn -ar 48000 -ac 2"
            )
        else:
            af = f" -af {self.eq_filter}" if self.eq_filter else ""
            options = f"{af} -vn -ar 48000 -ac 2"

        try:
            # 3. 再生実行
            # stderr をキャプチャしたい場合は、FFmpegPCMAudioをラップするか、
            # 実行時のログ出力を確認する必要があります。
            source = discord.FFmpegPCMAudio(url, before_options=before_options, options=options)
            self.start_time = time.time()
            vc.play(source, after=lambda e: self.bot.loop.call_soon_threadsafe(self.play_next, e))
        
        except Exception as e:
            logging.error(f"FFmpeg Launch Error: {e}")
            
            if self.elapsed_offset < 1:
                await self.current_ctx.send(embed=we(f"🎵 再生開始: **{filename}**"))
        except Exception as e:
            logging.error(f"Playback error: {e}")
            self.is_processing_queue = False
            self.current_track = None
            await self.check_queue()
            
    def play_next(self, error=None):
        actual_played = time.time() - self.start_time
        self.elapsed_offset += actual_played
        
        _, filename, duration, _ = self.current_track if self.current_track else (None, None, 0, None)
        is_interrupted = (duration - self.elapsed_offset) > 5
        self.is_processing_queue = False

        if is_interrupted and self.retry_count < self.MAX_RETRIES and self.current_track:
            self.retry_count += 1
            logging.warning(f"再開: {filename} ({self.retry_count})")
            asyncio.run_coroutine_threadsafe(self.check_queue(), self.bot.loop)
        else:
            self.current_track = None
            self.elapsed_offset = 0
            self.retry_count = 0
            asyncio.run_coroutine_threadsafe(self.check_queue(), self.bot.loop)
            
    @commands.command()
    async def play(self, ctx, *, b62_id: str = None):
        """ファイルを添付して再生、またはIDを指定して再生"""
        if not ctx.voice_client: 
            return await ctx.send("先に !join してください。")

        self.current_ctx = ctx
        url, filename, final_id = None, None, None

        # 1. ファイルが添付されている場合
        if ctx.message.attachments:
            attachment = ctx.message.attachments[0]
            url, filename = attachment.url, attachment.filename
            # このメッセージ自体のIDを生成して保存
            final_id = encode_full_id(ctx.guild.id, ctx.channel.id, ctx.message.id)
        
        # 2. 引数としてIDが渡された場合
        elif b62_id:
            url, filename = await self.get_attachment_info(b62_id)
            final_id = b62_id
        
        else:
            return await ctx.send("音声ファイルを添付するか、IDを入力してください。")

        if not url:
            return await ctx.send("音声情報の取得に失敗しました。")

        # キューに追加 (url, filename, b62_id)
        await self.queue.put((url, filename, final_id))

        if not ctx.voice_client.is_playing() and not self.is_processing_queue:
            await self.check_queue()
        else:
            await ctx.send(f"✅ キューに追加しました: {filename}")

    @commands.command()
    async def stop(self, ctx):
        vc = ctx.voice_client
        if vc:
            self.current_track = None
            while not self.queue.empty(): self.queue.get_nowait()
            vc.stop()
            await ctx.send(embed=we("停止しました。"))

    @commands.command()
    async def skip(self, ctx):
        vc = ctx.voice_client
        if vc and vc.is_playing():
            self.current_track = None
            vc.stop()
            await ctx.send(embed=we("スキップしました。"))

    @commands.command()
    async def list(self, ctx, limit: int = 20):
        embed = we(title="チャンネル内音声リスト")
        desc = "ユニバーサルID（全サーバー共通）\n" + "─" * 20 + "\n"
        async for msg in ctx.channel.history(limit=limit):
            if msg.attachments:
                b62 = encode_full_id(ctx.guild.id, ctx.channel.id, msg.id)
                desc += f"`{b62}` : **{msg.attachments[0].filename}**\n"
        embed.description = desc
        await ctx.send(embed=embed)

    @commands.command()
    async def id(self, ctx):
        async for msg in ctx.channel.history(limit=10):
            if msg.attachments:
                b62 = encode_full_id(ctx.guild.id, ctx.channel.id, msg.id)
                embed = we(title="ユニバーサルID発行")
                embed.add_field(name="ファイル", value=msg.attachments[0].filename)
                embed.add_field(name="ID", value=f"`{b62}`")
                return await ctx.send(embed=embed)

    @commands.command()
    async def plist(self, ctx, *, input_data: str = None):
        """DB名、JSONファイル、またはIDリストから再生"""
        if not ctx.voice_client: 
            return await ctx.send("先に !join してください。")

        self.current_ctx = ctx
        tokens = []

        # 1. ファイル添付がある場合 (JSONファイルを読み込む)
        if ctx.message.attachments:
            attachment = ctx.message.attachments[0]
            try:
                content = await attachment.read()
                tokens = json.loads(content.decode('utf-8'))
                if not isinstance(tokens, list):
                    tokens = [str(tokens)]
            except Exception as e:
                return await ctx.send(f"JSON解析エラー: {e}")

        # 2. 引数がある場合
        elif input_data:
            # DBにその名前のプレイリストがあるか確認
            if self.bot.supabase:
                try:
                    res = self.bot.supabase.table("playlists").select("ids").eq("name", input_data).execute()
                    if res.data:
                        tokens = res.data[0]["ids"]
                    else:
                        # DBになければIDの羅列(スペース区切り)として扱う
                        tokens = input_data.replace(',', ' ').split()
                except Exception:
                    tokens = input_data.replace(',', ' ').split()
            else:
                tokens = input_data.replace(',', ' ').split()
        
        else:
            return await ctx.send("プレイリスト名、ID、またはJSONファイルを指定してください。")

        # 再生処理
        added = 0
        for token in tokens:
            url, fname = await self.get_attachment_info(token)
            if url:
                await self.queue.put((url, fname, token))
                added += 1
        
        if added > 0:
            await ctx.send(f"✅ {added} 件をキューに追加しました。")
            if not ctx.voice_client.is_playing() and not self.is_processing_queue:
                await self.check_queue()
        else:
            await ctx.send("有効なIDが見つかりませんでした。")
            
    @commands.command()
    async def save_plist(self, ctx, name: str):
        """添付されたJSONを名前を付けてSupabaseに保存"""
        if not self.bot.supabase: return await ctx.send("DB未設定です。")
        if not ctx.message.attachments: return await ctx.send("JSONファイルを添付してください。")

        try:
            content = await ctx.message.attachments[0].read()
            ids = json.loads(content.decode('utf-8'))
            self.bot.supabase.table("playlists").upsert({"name": name, "ids": ids}).execute()
            await ctx.send(f"✅ DBにプレイリスト `{name}` を保存しました。")
        except Exception as e:
            await ctx.send(f"エラー: {e}")

    @commands.command()
    async def save_current(self, ctx, name: str):
        """現在のキューをそのままDBに保存"""
        if not self.bot.supabase: return await ctx.send("DB未設定です。")
        
        ids = []
        if self.current_track: ids.append(self.current_track[3])
        
        # キューの中身を回収
        temp = []
        while not self.queue.empty():
            item = await self.queue.get()
            temp.append(item)
            ids.append(item[2])
        for item in temp: await self.queue.put(item)

        if not ids: return await ctx.send("キューが空です。")

        try:
            self.bot.supabase.table("playlists").upsert({"name": name, "ids": ids}).execute()
            await ctx.send(f"✅ 現在のキューを `{name}` として保存しました。")
        except Exception as e:
            await ctx.send(f"エラー: {e}")
            
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
    async def sysinfo(self, ctx):
        cpu = self.get_cpu_usage()
        m_p, used, total = self.get_mem_usage()
        desc = f"CPU: `{cpu:.1f}%` / Mem: `{m_p:.1f}%` ({used/1024:.0f}/{total/1024:.0f}MB)"
        await ctx.send(embed=we(desc))

async def setup(bot):
    await bot.add_cog(Voice(bot))
