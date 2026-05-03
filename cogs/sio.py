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
import yt_dlp
from discord.ext import voice_recv
import threading
import random
# yt-dlpの設定（ストリーミング再生用）
YTDL_OPTIONS = {
    'format': 'bestaudio/best',
    'noplaylist': True,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'auto',
    'source_address': '0.0.0.0',
}
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
        self.states = {} # サーバーごとのデータを格納
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
        self.default_volume = 1.0
        self.default_speed = 1.0

    def get_state(self, guild_id: int):
        """サーバーごとの状態を取得。音量と倍速の設定を保持"""
        if guild_id not in self.states:
            self.states[guild_id] = {
                'queue': asyncio.Queue(),
                'current_ctx': None,
                'is_processing_queue': False,
                'current_track': None,
                'start_time': 0,
                'elapsed_offset': 0,
                'retry_count': 0,
                'volume': self.default_volume, # サーバーごとの音量
                'speed': self.default_speed     # サーバーごとの倍速
            }
        return self.states[guild_id]

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
        
    @commands.command()
    async def volume(self, ctx, vol: float):
        """音量を変更 (0.1 ～ 2.0) ※サーバー個別保存"""
        if not 0.1 <= vol <= 2.0:
            return await ctx.send(embed=we("音量は 0.1 から 2.0 の間で指定してください。"))
        
        state = self.get_state(ctx.guild.id)
        state['volume'] = vol
        await ctx.send(embed=we(f"🔊 このサーバーの音量を `{vol}` に設定しました。\n(次回の再生から適用されます)"))

    @commands.command()
    async def speed(self, ctx, speed: float):
        """再生速度を変更 (0.5 ～ 2.0) ※サーバー個別保存"""
        if not 0.5 <= speed <= 2.0:
            return await ctx.send(embed=we("速度は 0.5 から 2.0 の間で指定してください。"))
        
        state = self.get_state(ctx.guild.id)
        state['speed'] = speed
        await ctx.send(embed=we(f"⚡ このサーバーの再生速度を `{speed}` 倍に設定しました。\n(次回の再生から適用されます)"))

    async def get_yt_info(self, url):
        """yt-dlpを使用して動画情報とストリームURLを取得"""
        loop = asyncio.get_event_loop()
        with yt_dlp.YoutubeDL(YTDL_OPTIONS) as ydl:
            # ネットワークI/Oをブロックしないよう別スレッドで実行
            data = await loop.run_in_executor(None, lambda: ydl.extract_info(url, download=False))
            return {
                'url': data.get('url'),
                'title': data.get('title'),
                'duration': data.get('duration', 0)
            }
    
    # =====================
    # Playback Logic
    # =====================
    async def check_queue(self, guild_id: int):
        state = self.get_state(guild_id)
        
        if state['is_processing_queue'] or state['current_ctx'] is None:
            return
        
        ctx = state['current_ctx']
        vc = ctx.voice_client
        if vc is None or not vc.is_connected():
            state['is_processing_queue'] = False
            return

        # キュー処理（既存ロジック）
        if state['current_track'] is None:
            if state['queue'].empty():
                state['is_processing_queue'] = False
                return
            
            target_input, filename, b62_id, is_yt = await state['queue'].get() 
            
            if is_yt:
                try:
                    info = await self.get_yt_info(target_input)
                    state['current_track'] = (info['url'], info['title'], info['duration'], b62_id)
                except Exception as e:
                    logging.error(f"YouTube解析失敗: {e}")
                    await ctx.send(embed=we(f"❌ 解析失敗: {e}"))
                    state['is_processing_queue'] = False
                    return await self.check_queue(guild_id)
            else:
                duration = await self.get_duration(target_input)
                state['current_track'] = (target_input, filename, duration, b62_id) 

        url, filename, duration, b62_id = state['current_track']
        state['is_processing_queue'] = True

        # --- FFmpeg オプションの構築 ---
        before_options = f'-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5'
        if b62_id:
            before_options += f' -headers "User-Agent: Mozilla/5.0\r\n"'
        
        if state['elapsed_offset'] > 0:
            before_options += f" -ss {state['elapsed_offset']}"

        # サーバーごとの設定をFFmpegフィルター(af)に反映
        filters = []
        
        # 1. 倍速 (atempo)
        if state.get('speed', 1.0) != 1.0:
            filters.append(f"atempo={state['speed']}")
        
        # 2. 音量 (volume)
        if state.get('volume', 1.0) != 1.0:
            filters.append(f"volume={state['volume']}")
        
        # 3. 既存のEQエフェクト (Cog共通変数を使用している場合)
        if self.eq_filter:
            filters.append(self.eq_filter)

        af_string = f"-af {','.join(filters)}" if filters else ""
        options = f"{af_string} -vn -ar 48000 -ac 2"

        try:
            source = discord.FFmpegPCMAudio(url, before_options=before_options, options=options)
            state['start_time'] = time.time()
            
            vc.play(source, after=lambda e: self.bot.loop.call_soon_threadsafe(self.play_next, guild_id, e))
            
            if state['elapsed_offset'] < 1:
                status = f"Speed: {state['speed']}x / Vol: {state['volume']}"
                await ctx.send(embed=we(f"🎵 再生中: **{filename}**\n`{status}`"))
        
        except Exception as e:
            logging.error(f"Playback error: {e}")
            state['is_processing_queue'] = False
            state['current_track'] = None
            await self.check_queue(guild_id)
            
    def play_next(self, guild_id: int, error=None):
        """再生終了後の処理。guild_idからstateを特定する"""
        state = self.get_state(guild_id) # ここで state を定義！
        
        if error:
            logging.error(f"Player error: {error}")

        actual_played = time.time() - state['start_time']
        state['elapsed_offset'] += actual_played
        
        track = state['current_track']
        duration = track[2] if track else 0
        is_interrupted = (duration - state['elapsed_offset']) > 5
        
        state['is_processing_queue'] = False

        if is_interrupted and state['retry_count'] < 3 and state['current_track']:
            state['retry_count'] += 1
            asyncio.run_coroutine_threadsafe(self.check_queue(guild_id), self.bot.loop)
        else:
            state['current_track'] = None
            state['elapsed_offset'] = 0
            state['retry_count'] = 0
            asyncio.run_coroutine_threadsafe(self.check_queue(guild_id), self.bot.loop)
            
    @commands.command()
    async def play(self, ctx, *, input_str: str = None):
        if not ctx.voice_client: 
            return await ctx.send("先に !join してください。")

        # サーバー個別の状態を取得
        state = self.get_state(ctx.guild.id)
        state['current_ctx'] = ctx
        
        is_yt = False
        url, filename, final_id = None, None, None

        # YouTube解析ロジック (yt-dlpを使用)
        if input_str and ("youtube.com" in input_str or "youtu.be" in input_str):
            await ctx.send("⏳ YouTubeを解析中...")
            try:
                info = await self.get_yt_info(input_str)
                url, filename, is_yt = input_str, info['title'], True
            except Exception as e:
                return await ctx.send(f"❌ 解析失敗: {e}")

        # 添付ファイルがある場合
        elif ctx.message.attachments:
            attachment = ctx.message.attachments[0]
            url, filename = attachment.url, attachment.filename
            final_id = encode_full_id(ctx.guild.id, ctx.channel.id, ctx.message.id)
        
        # IDが指定された場合
        elif input_str:
            url, filename = await self.get_attachment_info(input_str)
            final_id = input_str
        
        else:
            return await ctx.send(embed=we("ファイル添付、ID、またはYouTube URLを指定してください。"))

        if not url:
            return await ctx.send(embed=we("情報の取得に失敗しました。"))

        # キューに追加 (4つの要素を渡す)
        await state['queue'].put((url, filename, final_id, is_yt))

        if not ctx.voice_client.is_playing() and not state['is_processing_queue']:
            await self.check_queue(ctx.guild.id)
        else:
            await ctx.send(f"✅ キューに追加: **{filename}**")

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


# =====================
# SaitoRelay Cog (通話系)
# =====================
# SaitoRelayクラス内の修正・変更箇所のみ

# SaitoRelayクラスの修正版

class SaitoRelay(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.matching_queue = [] 

    @commands.command()
    async def saito(self, ctx):
        """音声中継マッチング (エンコーダー強制初期化版)"""
        if not ctx.author.voice:
            return await ctx.send("VCに参加してから実行してください。")

        if ctx.voice_client:
            return await ctx.send("このサーバーでは既に接続中です。")

        # サーバー単位の待機キャンセル
        self.matching_queue = [c for c in self.matching_queue if c.guild.id != ctx.guild.id]

        target_peer = None
        for i, peer in enumerate(self.matching_queue):
            if peer.guild.id != ctx.guild.id:
                target_peer = self.matching_queue.pop(i)
                break
        
        if not target_peer:
            self.matching_queue.append(ctx)
            return await ctx.send(f"🔎 相手を探しています... ({ctx.guild.name})")

        await ctx.send(f"🤝 **{target_peer.guild.name}** と接続中...")
        await target_peer.send(f"🤝 **{ctx.guild.name}** と接続中...")

        try:
            # VoiceRecvClientを使用して接続
            vc1 = await ctx.author.voice.channel.connect(cls=voice_recv.VoiceRecvClient)
            vc2 = await target_peer.author.voice.channel.connect(cls=voice_recv.VoiceRecvClient)

            # --- 重要: エンコーダーを初期化するために無音を再生する ---
            # これを行わないと send_audio_packet 時にエンコーダー未初期化エラーが出ます
            silence_src1 = discord.FFmpegPCMAudio("/dev/null") # Linux環境
            silence_src2 = discord.FFmpegPCMAudio("/dev/null")
            vc1.play(silence_src1)
            vc2.play(silence_src2)

            class RelaySink(voice_recv.AudioSink):
                def __init__(self, dest_vc):
                    super().__init__()
                    self.dest_vc = dest_vc

                def wants_opus(self) -> bool:
                    # 受信したパケットをそのまま送るためTrue
                    return True

                def write(self, user, data: voice_recv.VoiceData):
                    # data.packet は RTPヘッダーを含む生データ
                    # data.data は 純粋なOpusペイロード
                    if self.dest_vc and self.dest_vc.is_connected():
                        try:
                            # エンコーダーが初期化されていれば、data.data(Opus)を送信可能
                            self.dest_vc.send_audio_packet(data.data)
                        except Exception:
                            pass

                def cleanup(self):
                    self.dest_vc = None

            # 相互リレー開始
            vc1.listen(RelaySink(vc2))
            vc2.listen(RelaySink(vc1))

            await ctx.send("🎙️ 通話を開始しました。")
            await target_peer.send("🎙️ 通話を開始しました。")

        except Exception as e:
            logging.error(f"Saito Match Error: {e}")
            if ctx.voice_client: await ctx.voice_client.disconnect()
            if target_peer.voice_client: await target_peer.voice_client.disconnect()

    @commands.command()
    async def saito_stop(self, ctx):
        if ctx.voice_client:
            await ctx.voice_client.disconnect()
            await ctx.send("通話を終了しました。")
            
class Timer(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.active_timers = {} 
        self.work_stats = {}
        # ベースURLの定義
        self.base_ambient_url = "https://www.soundjay.com/nature_c2026/sounds/"
        # 通知音（終了時）のURL
        self.notify_url = "https://www.soundjay.com/buttons/sounds/beep-06.mp3"

    def format_time(self, seconds: int) -> str:
        """秒数を時:分:秒の形式にフォーマット"""
        m, s = divmod(seconds, 60)
        h, m = divmod(m, 60)
        return f"{h:02d}:{m:02d}:{s:02d}" if h > 0 else f"{m:02d}:{s:02d}"

    async def notify_triple(self, ctx, text: str):
        """通知メッセージを送信し、音声を3回キューに追加する"""
        await ctx.send(embed=we(description=f"🔔 **{text}**"))
        
        voice_cog = self.bot.get_cog("Voice")
        if voice_cog and ctx.voice_client:
            # 不要な を削除し、インデントを整理
            state = voice_cog.get_state(ctx.guild.id)
            
            # 3回連続で再生キューに追加
            for i in range(3):
                await state['queue'].put((self.notify_url, f"Notification-{i+1}", None, False))
            
            # 再生中でなければ再生を開始
            if not ctx.voice_client.is_playing() and not state['is_processing_queue']:
                await voice_cog.check_queue(ctx.guild.id)

    @commands.command()
    async def pomo(self, ctx, work: int = 25, rest: int = 5):
        """ポモドーロタイマー開始"""
        guild_id = ctx.guild.id
        if guild_id in self.active_timers:
            return await ctx.send("既にタイマーが稼働中です。`!pomo_stop` で停止してください。")

        async def pomodoro_loop():
            try:
                while True:
                    await self.notify_triple(ctx, f"作業開始！ ({work}分間)")
                    await asyncio.sleep(work * 60)
                    
                    await self.notify_triple(ctx, f"休憩時間です。お疲れ様でした！ ({rest}分間)")
                    await asyncio.sleep(rest * 60)
            except asyncio.CancelledError:
                await ctx.send(embed=we("ポモドーロタイマーを終了しました。"))

        self.active_timers[guild_id] = self.bot.loop.create_task(pomodoro_loop())
        await ctx.send(embed=we(f"⏳ ポモドーロを開始しました: 作業{work}分 / 休憩{rest}分"))

    @commands.command()
    async def pomo_stop(self, ctx):
        """ポモドーロタイマーを停止"""
        task = self.active_timers.pop(ctx.guild.id, None)
        if task:
            task.cancel()
        else:
            await ctx.send("稼働中のタイマーはありません。")

    @commands.command()
    async def ambient(self, ctx, mode: str = "rain"):
        """環境音を再生 (再生が終わっても通知は鳴りません)"""
        if not ctx.voice_client:
            return await ctx.send("先に !join してください。")

        voice_cog = self.bot.get_cog("Voice")
        if not voice_cog: return

        target_url = ""
        display_name = ""

        if mode == "rain":
            num = str(random.randint(1, 7)).zfill(2)
            target_url = f"{self.base_ambient_url}rain-{num}.mp3"
            display_name = f"Rain {num}"
        else:
            target_url = f"{self.base_ambient_url}{mode}-01.mp3"
            display_name = mode

        state = voice_cog.get_state(ctx.guild.id)
        state['current_ctx'] = ctx
        
        # キューに追加 (is_yt=False)。
        # Voice.play_next がシンプルであれば、これの終了時に通知が鳴ることはありません。
        await state['queue'].put((target_url, display_name, None, False))
        
        if not ctx.voice_client.is_playing() and not state['is_processing_queue']:
            await voice_cog.check_queue(ctx.guild.id)
            await ctx.send(embed=we(f"🎧 環境音 `{display_name}` を再生します。"))
        else:
            await ctx.send(embed=we(f"✅ キューに `{display_name}` を追加しました。"))

    @commands.command()
    async def work_start(self, ctx):
        """作業計測開始"""
        uid = ctx.author.id
        if uid not in self.work_stats:
            self.work_stats[uid] = {'total_seconds': 0}
        self.work_stats[uid]['last_start'] = time.time()
        await ctx.send(embed=we(f"📝 {ctx.author.display_name} さんの作業計測を開始しました。"))

    @commands.command()
    async def work_end(self, ctx):
        """作業計測終了"""
        uid = ctx.author.id
        if uid not in self.work_stats or 'last_start' not in self.work_stats[uid]:
            return await ctx.send("計測が開始されていません。")

        elapsed = int(time.time() - self.work_stats[uid]['last_start'])
        self.work_stats[uid]['total_seconds'] += elapsed
        del self.work_stats[uid]['last_start']

        await ctx.send(embed=we(
            title="計測終了",
            description=f"今回の作業: `{self.format_time(elapsed)}` / 累計: `{self.format_time(self.work_stats[uid]['total_seconds'])}`"
        ))

    @commands.command()
    async def stats(self, ctx):
        """現在の累計作業時間を表示"""
        uid = ctx.author.id
        data = self.work_stats.get(uid, {'total_seconds': 0})
        total_str = self.format_time(data['total_seconds'])
        
        status = " (現在計測中)" if 'last_start' in data else ""
        await ctx.send(embed=we(f"📊 {ctx.author.display_name} さんの累計作業時間: `{total_str}`{status}"))

async def setup(bot):
    await bot.add_cog(Voice(bot))
    await bot.add_cog(SaitoRelay(bot))
    await bot.add_cog(Timer(bot))
