from __future__ import annotations

import asyncio
import logging
import threading
import time
import numpy as np

import discord
import discord.opus
from discord.ext import commands
from discord.ext import voice_recv

from pedalboard import Pedalboard, PitchShift

logger = logging.getLogger(__name__)

# ============================================================
# 定数定義
# ============================================================
SAMPLE_RATE = 48000          # 48kHz
CHANNELS = 2                 # ステレオ
SAMPLE_WIDTH = 2             # 16bit = 2byte
FRAME_SIZE = CHANNELS * SAMPLE_WIDTH
BYTES_PER_SECOND = SAMPLE_RATE * FRAME_SIZE
CHUNK_DURATION = 0.02        # 20ms
CHUNK_BYTES = int(CHUNK_DURATION * BYTES_PER_SECOND) # 3840 bytes

OPUS_SILENCE = b"\xf8\xff\xfe"

def we(description: str | None = None, title: str | None = None) -> discord.Embed:
    return discord.Embed(title=title, description=description, color=0x3498DB)


# ============================================================
# C++ネイティブ高速ピッチシフター (Pedalboard)
# ============================================================
class FastPitchShifter:
    """
    SpotifyのPedalboard (C++バックエンド) を利用した超高速ピッチシフター。
    変換時間 0.2ms 〜 0.5ms を実現します。
    """
    def __init__(self, sample_rate: int = 48000):
        self.sample_rate = sample_rate
        self.current_semitones: float = 0.0
        self.board: Pedalboard | None = None
        self._lock = threading.Lock()

    def set_pitch(self, semitones: float):
        with self._lock:
            if self.current_semitones != semitones:
                self.current_semitones = semitones
                if semitones == 0:
                    self.board = None
                else:
                    # Pedalboard C++ インスタンスの生成
                    self.board = Pedalboard([PitchShift(semitones=semitones)])

    def process(self, pcm_bytes: bytes) -> bytes:
        with self._lock:
            if self.board is None or len(pcm_bytes) == 0:
                return pcm_bytes

            # 16bit PCM -> Float32 (-1.0 〜 1.0)
            audio = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32768.0
            
            # Pedalboard は (CHANNELS, SAMPLES) の形状を期待するため転置
            audio_stereo = audio.reshape(-1, CHANNELS).T

            # C++レベルでの高速ピッチ変換
            processed = self.board(audio_stereo, sample_rate=self.sample_rate)

            # (SAMPLES, CHANNELS) に戻して int16 化
            int16_audio = (processed.T * 32767.0).clip(-32768, 32767).astype(np.int16)
            return int16_audio.tobytes()


# ============================================================
# 超低遅延・安定再生ソース
# ============================================================
class VoiceChangerAudioSource(discord.AudioSource):
    """
    目標バッファ 15ms〜20ms で動作するジッターバッファ
    """
    def __init__(self, target_buffer_ms: int = 15) -> None:
        self._buffer = bytearray()
        self._lock = threading.Lock()
        self.target_prebuffer_bytes = int((target_buffer_ms / 1000.0) * BYTES_PER_SECOND)
        self.max_buffer_bytes = int((35 / 1000.0) * BYTES_PER_SECOND) # 最大35msでパージ
        self.is_buffering = True

    def feed(self, pcm: bytes) -> None:
        with self._lock:
            self._buffer.extend(pcm)

            # 遅延が蓄積しないよう溢れた分を即座に破棄
            if len(self._buffer) > self.max_buffer_bytes:
                overflow = len(self._buffer) - self.max_buffer_bytes
                overflow = (overflow // FRAME_SIZE) * FRAME_SIZE
                del self._buffer[:overflow]

            if self.is_buffering and len(self._buffer) >= self.target_prebuffer_bytes:
                self.is_buffering = False

    def read(self) -> bytes:
        with self._lock:
            if self.is_buffering or len(self._buffer) < CHUNK_BYTES:
                self.is_buffering = True
                return b"\x00" * CHUNK_BYTES

            chunk = bytes(self._buffer[:CHUNK_BYTES])
            del self._buffer[:CHUNK_BYTES]
            return chunk

    @property
    def buffered_ms(self) -> float:
        with self._lock:
            return (len(self._buffer) / BYTES_PER_SECOND) * 1000.0

    def is_opus(self) -> bool:
        return False


# ============================================================
# 音声受信 & 変換 Sink
# ============================================================
class VoiceChangerSink(voice_recv.AudioSink):
    def __init__(self, bot: commands.Bot, vc: voice_recv.VoiceRecvClient, semitones: float = 0.0):
        super().__init__()
        self.bot = bot
        self.vc = vc
        self.decoders: dict[int, discord.opus.Decoder] = {}
        self.opus_available = discord.opus.is_loaded()
        self._running = True

        self.last_proc_time_ms: float = 0.0
        self.avg_proc_time_ms: float = 0.0
        self.proc_count: int = 0

        self.shifter = FastPitchShifter(sample_rate=SAMPLE_RATE)
        self.shifter.set_pitch(semitones)

        self.audio_source = VoiceChangerAudioSource(target_buffer_ms=15)
        if self.vc and self.vc.is_connected():
            try:
                self.vc.play(self.audio_source)
            except Exception as e:
                logger.error("[VC_CHANGER] play() 開始失敗: %r", e)

    def set_semitones(self, semitones: float) -> None:
        self.shifter.set_pitch(semitones)

    @property
    def semitones(self) -> float:
        return self.shifter.current_semitones

    def wants_opus(self) -> bool:
        return True

    def write(self, user, data: voice_recv.VoiceData) -> None:
        start_time = time.perf_counter()

        raw_opus = getattr(data, 'opus', None)
        if not raw_opus:
            return
        raw_opus = bytes(raw_opus)

        user_id = getattr(user, 'id', 0) if user else 0
        pcm = self._decode_opus(user_id, raw_opus)
        if not pcm:
            return

        # Pedalboard C++ピッチ変換 (0.2〜0.5ms)
        processed_pcm = self.shifter.process(pcm)
        self.audio_source.feed(processed_pcm)

        proc_time = (time.perf_counter() - start_time) * 1000.0
        self.last_proc_time_ms = proc_time
        self.proc_count += 1
        self.avg_proc_time_ms += (proc_time - self.avg_proc_time_ms) / min(self.proc_count, 50)

    def _decode_opus(self, user_id: int, raw_opus: bytes) -> bytes | None:
        if not self.opus_available:
            return None

        if raw_opus != OPUS_SILENCE and hasattr(self.vc, "dave_decrypt"):
            try:
                payload = self.vc.dave_decrypt(user_id, raw_opus)
            except Exception:
                return None
        else:
            payload = raw_opus

        if not payload:
            return None

        decoder = self.decoders.get(user_id)
        if decoder is None:
            decoder = discord.opus.Decoder()
            self.decoders[user_id] = decoder

        try:
            return decoder.decode(payload, fec=False)
        except discord.opus.OpusError:
            return None

    def cleanup(self) -> None:
        self._running = False


# ============================================================
# ボイスチェンジャー Cog 本体
# ============================================================
class VoiceChangerCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.vc_sessions: dict[int, dict] = {}

    @commands.group(name="vc", invoke_without_command=True)
    @commands.guild_only()
    async def vc_group(self, ctx: commands.Context):
        session = self.vc_sessions.get(ctx.guild.id)
        if session:
            sink: VoiceChangerSink = session["sink"]

            proc_ms = sink.last_proc_time_ms
            avg_ms = sink.avg_proc_time_ms
            buf_ms = sink.audio_source.buffered_ms
            total_est_delay = avg_ms + buf_ms + 20.0

            await ctx.send(embed=we(
                f"🎙️ **ボイスチェンジャー動作中 (Pedalboard C++ モード)**\n"
                f"🎵 設定ピッチ: `{sink.semitones:+.1f}` 半音\n\n"
                f"📊 **遅延ステータス (数値)**\n"
                f"├ ⚡ 変換処理時間: `{proc_ms:.2f} ms` (平均: `{avg_ms:.2f} ms`)\n"
                f"├ 📦 バッファ滞留量: `{buf_ms:.1f} ms`\n"
                f"└ ⏱️ **推定トータル遅延**: `~{total_est_delay:.1f} ms`\n\n"
                f"・ピッチ変更: `{ctx.prefix}vc pitch <半音数>`\n"
                f"・停止: `{ctx.prefix}vc stop`"
            ))
        else:
            await ctx.send(embed=we(f"⏸️ ボイスチェンジャー停止中 (`{ctx.prefix}vc start` で開始)"))

    @vc_group.command(name="start")
    @commands.guild_only()
    async def vc_start(self, ctx: commands.Context, pitch: float = 0.0):
        if not ctx.author.voice or not ctx.author.voice.channel:
            return await ctx.send(embed=we("⚠️ ボイスチャンネルに参加してから実行してください。"))

        guild_id = ctx.guild.id
        if guild_id in self.vc_sessions:
            return await ctx.send(embed=we("⚠️ 既にボイスチェンジャーが実行中です。"))

        target_channel = ctx.author.voice.channel

        try:
            if ctx.voice_client is not None:
                await ctx.voice_client.disconnect(force=True)
                await asyncio.sleep(1.0)

            vc = await target_channel.connect(
                cls=voice_recv.VoiceRecvClient,
                timeout=30.0,
                reconnect=True,
                self_deaf=False
            )
        except Exception as e:
            return await ctx.send(embed=we(f"❌ ボイス接続に失敗しました: `{e}`"))

        sink = VoiceChangerSink(bot=self.bot, vc=vc, semitones=pitch)
        vc.listen(sink)

        self.vc_sessions[guild_id] = {"sink": sink, "vc": vc}
        await ctx.send(embed=we(
            f"🎙️ **{target_channel.name}** で超低遅延ボイスチェンジャーを開始しました！\n"
            f"🎵 ピッチ: `{pitch:+.1f}` 半音\n"
            f"📊 `!vc` で遅延数値を確認できます。"
        ))

    @vc_group.command(name="pitch")
    @commands.guild_only()
    async def vc_pitch(self, ctx: commands.Context, semitones: float):
        session = self.vc_sessions.get(ctx.guild.id)
        if not session:
            return await ctx.send(embed=we("⚠️ ボイスチェンジャーが開始されていません。"))

        sink: VoiceChangerSink = session["sink"]
        sink.set_semitones(semitones)
        await ctx.send(embed=we(f"🎵 ピッチを `{semitones:+.1f}` 半音に変更しました。"))

    @vc_group.command(name="stop")
    @commands.guild_only()
    async def vc_stop(self, ctx: commands.Context):
        session = self.vc_sessions.pop(ctx.guild.id, None)
        if not session:
            return await ctx.send(embed=we("⚠️ ボイスチェンジャーは実行されていません。"))

        vc: voice_recv.VoiceRecvClient = session["vc"]
        try:
            vc.stop_listening()
            vc.stop()
            await vc.disconnect(force=True)
        except Exception:
            pass

        await ctx.send(embed=we("🛑 ボイスチェンジャーを停止しました。"))

async def setup(bot: commands.Bot):
    await bot.add_cog(VoiceChangerCog(bot))
