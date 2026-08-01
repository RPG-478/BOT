from __future__ import annotations

import asyncio
import collections
import io
import logging
import threading
import time
import numpy as np
import scipy.ndimage

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
# ピッチ変換処理 (リサンプリング方式)
# ============================================================
def pitch_shift_pcm(pcm_bytes: bytes, semitones: float) -> bytes:
    """
    PCM (16bit stereo 48kHz) のピッチ（半音単位）を変更する。
    1. リサンプリングで伸縮
    2. 元の長さ(20ms分)に合わせて切り詰め・パディング
    """
    if semitones == 0 or len(pcm_bytes) == 0:
        return pcm_bytes

    # ピッチ倍率計算 (例: +12半音で2.0倍、-12半音で0.5倍)
    factor = 2.0 ** (semitones / 12.0)

    # PCM bytes -> int16 (2ch)
    audio = np.frombuffer(pcm_bytes, dtype=np.int16).reshape(-1, CHANNELS)
    num_samples = audio.shape[0]

    # 時間軸（軸0）に沿ってリサンプリング（線形補間: order=1）
    # factor > 1.0 (高音) -> サンプル数が減る（再生速度が速くなる）
    # factor < 1.0 (低音) -> サンプル数が増える（再生速度が遅くなる）
    new_length = int(num_samples / factor)
    if new_length <= 0:
        return pcm_bytes

    # チップごとに補間処理
    shifted_ch0 = scipy.ndimage.zoom(audio[:, 0], 1.0 / factor, order=1)
    shifted_ch1 = scipy.ndimage.zoom(audio[:, 1], 1.0 / factor, order=1)
    shifted_audio = np.column_stack((shifted_ch0, shifted_ch1)).astype(np.int16)

    # リアルタイム再生の周期を保つため元のサンプル数に整える
    current_length = shifted_audio.shape[0]
    if current_length > num_samples:
        shifted_audio = shifted_audio[:num_samples]
    elif current_length < num_samples:
        pad_width = num_samples - current_length
        shifted_audio = np.pad(shifted_audio, ((0, pad_width), (0, 0)), mode='constant')

    return shifted_audio.tobytes()

# ============================================================
# リアルタイム再生ソース (EchoAudioSource の発展形)
# ============================================================
class VoiceChangerAudioSource(discord.AudioSource):
    """
    20ms毎にポーリングされ、バッファされた変換後PCMを出力するソース。
    バッファが切れても無音を返すことで再生ストリームを停止させない。
    """
    def __init__(self) -> None:
        self._buffer = bytearray()
        self._lock = threading.Lock()

    def feed(self, pcm: bytes) -> None:
        with self._lock:
            self._buffer.extend(pcm)

    def read(self) -> bytes:
        with self._lock:
            if len(self._buffer) >= CHUNK_BYTES:
                chunk = bytes(self._buffer[:CHUNK_BYTES])
                del self._buffer[:CHUNK_BYTES]
                return chunk
        # データ不足時は無音を出力してストリームを維持
        return b"\x00" * CHUNK_BYTES

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

        # 再生ソースの生成と初期化
        self.audio_source = VoiceChangerAudioSource()
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

        # ピッチシフト適用
        with self._lock:
            current_pitch = self.semitones

        processed_pcm = pitch_shift_pcm(pcm, current_pitch)

        # リアルタイム再生バッファへ投入
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
        """!vc ステータスを表示"""
        session = self.vc_sessions.get(ctx.guild.id)
        if session:
            sink: VoiceChangerSink = session["sink"]
            await ctx.send(embed=we(
                f"🎙️ **ボイスチェンジャー動作中**\n"
                f"🎵 設定ピッチ: `{sink.semitones:+.1f}` 半音\n\n"
                f"・ピッチ変更: `{ctx.prefix}vc pitch <半音数>` (例: +4, -3)\n"
                f"・女声風: `{ctx.prefix}vc female` | 男声風: `{ctx.prefix}vc male`\n"
                f"・停止: `{ctx.prefix}vc stop`"
            ))
        else:
            await ctx.send(embed=we(f"⏸️ ボイスチェンジャー停止中 (`{ctx.prefix}vc start` で開始)"))

    @vc_group.command(name="start")
    @commands.guild_only()
    async def vc_start(self, ctx: commands.Context, pitch: float = 0.0):
        """!vc start [半音数] : ボイスチェンジャーを開始"""
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
        """!vc pitch <半音数> : ピッチをリアルタイム変更 (+12で1オクターブ上、-12で1オクターブ下)"""
        session = self.vc_sessions.get(ctx.guild.id)
        if not session:
            return await ctx.send(embed=we("⚠️ ボイスチェンジャーが開始されていません。"))

        sink: VoiceChangerSink = session["sink"]
        sink.set_semitones(semitones)
        await ctx.send(embed=we(f"🎵 ピッチを `{semitones:+.1f}` 半音に変更しました。"))

    @vc_group.command(name="female")
    @commands.guild_only()
    async def vc_female(self, ctx: commands.Context):
        """!vc female : 高音化プリセット (+3.5半音)"""
        await self.vc_pitch(ctx, 3.5)

    @vc_group.command(name="male")
    @commands.guild_only()
    async def vc_male(self, ctx: commands.Context):
        """!vc male : 低音化プリセット (-3.5半音)"""
        await self.vc_pitch(ctx, -3.5)

    @vc_group.command(name="stop")
    @commands.guild_only()
    async def vc_stop(self, ctx: commands.Context):
        """!vc stop : ボイスチェンジャーを停止"""
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
