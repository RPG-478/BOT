from __future__ import annotations

import asyncio
import collections
import io
import logging
import threading
import time
import numpy as np
import scipy.signal

import discord
import discord.opus
from discord.ext import commands
from discord.ext import voice_recv

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
# 軽量・高速ピッチ変換処理 (多項式リサンプリング)
# ============================================================
def pitch_shift_pcm(pcm_bytes: bytes, semitones: float) -> bytes:
    """
    リサンプリングによる超軽量ピッチチェンジ。
    `scipy.signal.resample_poly` を使用して計算負荷を削減し、
    バッファの途切れを回避します。
    """
    if semitones == 0 or len(pcm_bytes) == 0:
        return pcm_bytes

    # ピッチ倍率の計算 (例: +12半音で2.0倍、-12半音で0.5倍)
    factor = 2.0 ** (semitones / 12.0)

    # 近似分数表現に変換して高速リサンプリング (up/down)
    # 例: factor 1.25 -> up=5, down=4
    from fractions import Fraction
    frac = Fraction(factor).limit_denominator(20)
    up, down = frac.numerator, frac.denominator

    # PCM bytes -> float32 (-1.0 ~ 1.0)
    audio = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32768.0
    audio_stereo = audio.reshape(-1, CHANNELS)

    # チャンネルごとに高速ポリフェーズリサンプリング
    # 音質維持と軽量化を両立
    shifted_ch0 = scipy.signal.resample_poly(audio_stereo[:, 0], down, up)
    shifted_ch1 = scipy.signal.resample_poly(audio_stereo[:, 1], down, up)

    shifted_audio = np.column_stack((shifted_ch0, shifted_ch1))
    
    # int16 にクリッピング変換
    int16_audio = (shifted_audio * 32767.0).clip(-32768, 32767).astype(np.int16)
    return int16_audio.tobytes()


# ============================================================
# ジッターバッファ付きリアルタイム再生ソース
# ============================================================
class VoiceChangerAudioSource(discord.AudioSource):
    """
    受信データの揺らぎ（ジッター）を吸収するためのジッターバッファを備えたソース。
    一定量のデータが溜まるまで再生開始を調整することでプチプチ音を大幅に軽減します。
    """
    def __init__(self, buffer_ms: int = 100) -> None:
        self._buffer = bytearray()
        self._lock = threading.Lock()
        # 初期ジッターバッファ量 (100ms分)
        self.target_prebuffer_bytes = int((buffer_ms / 1000.0) * BYTES_PER_SECOND)
        self.is_buffering = True

    def feed(self, pcm: bytes) -> None:
        with self._lock:
            self._buffer.extend(pcm)
            # 初回または枯渇後はバッファが一定量溜まるまで待機解除しない
            if self.is_buffering and len(self._buffer) >= self.target_prebuffer_bytes:
                self.is_buffering = False

    def read(self) -> bytes:
        with self._lock:
            # バッファリング中、またはデータが足りない場合
            if self.is_buffering or len(self._buffer) < CHUNK_BYTES:
                self.is_buffering = True
                # 無音（ゼロ埋め）を出力して再生ストリームの維持とバッファ確保を行う
                return b"\x00" * CHUNK_BYTES

            chunk = bytes(self._buffer[:CHUNK_BYTES])
            del self._buffer[:CHUNK_BYTES]
            return chunk

    def is_opus(self) -> bool:
        return False


# ============================================================
# 音声受信・ピッチ変換 Sink
# ============================================================
class VoiceChangerSink(voice_recv.AudioSink):
    def __init__(self, bot: commands.Bot, vc: voice_recv.VoiceRecvClient, semitones: float = 0.0):
        super().__init__()
        self.bot = bot
        self.vc = vc
        self.semitones = semitones
        self._lock = threading.Lock()
        self.decoders: dict[int, discord.opus.Decoder] = {}
        self.opus_available = discord.opus.is_loaded()
        self._running = True

        # ジッターバッファ(100ms)を持たせた再生ソースを生成
        self.audio_source = VoiceChangerAudioSource(buffer_ms=100)
        if self.vc and self.vc.is_connected():
            try:
                self.vc.play(self.audio_source)
            except Exception as e:
                logger.error("[VC_CHANGER] play() 開始失敗: %r", e)

    def set_semitones(self, semitones: float) -> None:
        with self._lock:
            self.semitones = float(semitones)

    def wants_opus(self) -> bool:
        return True

    def write(self, user, data: voice_recv.VoiceData) -> None:
        """受信パケットを復号・ピッチ変換しバッファへ供給"""
        raw_opus = getattr(data, 'opus', None)
        if not raw_opus:
            return
        raw_opus = bytes(raw_opus)

        user_id = getattr(user, 'id', 0) if user else 0
        pcm = self._decode_opus(user_id, raw_opus)
        if not pcm:
            return

        with self._lock:
            current_pitch = self.semitones

        # 高速ピッチシフト適用
        processed_pcm = pitch_shift_pcm(pcm, current_pitch)

        # 再生バッファへ投入
        self.audio_source.feed(processed_pcm)

    def _decode_opus(self, user_id: int, raw_opus: bytes) -> bytes | None:
        if not self.opus_available:
            return None

        # DAVE(E2EE) 復号
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
            await ctx.send(embed=we(
                f"🎙️ **ボイスチェンジャー動作中**\n"
                f"🎵 設定ピッチ: `{sink.semitones:+.1f}` 半音\n\n"
                f"・ピッチ変更: `{ctx.prefix}vc pitch <半音数>`\n"
                f"・女声風: `{ctx.prefix}vc female` | 男声風: `{ctx.prefix}vc male`\n"
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
            f"🎙️ **{target_channel.name}** でボイスチェンジャーを開始しました！\n"
            f"🎵 ピッチ: `{pitch:+.1f}` 半音\n"
            f"ピッチ変更: `{ctx.prefix}vc pitch 3.0` | 停止: `{ctx.prefix}vc stop`"
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

    @vc_group.command(name="female")
    @commands.guild_only()
    async def vc_female(self, ctx: commands.Context):
        await self.vc_pitch(ctx, 3.0)

    @vc_group.command(name="male")
    @commands.guild_only()
    async def vc_male(self, ctx: commands.Context):
        await self.vc_pitch(ctx, -3.0)

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
