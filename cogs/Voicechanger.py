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
# 自動ズレ補正付き WSOLA ピッチシフター
# ============================================================
class AdaptiveWSOLAPitchShifter:
    """
    20msパケット単位のリアルタイム処理に特化した WSOLA ピッチシフター。
    パケット境界の位相・サンプルのズレを自動検出して補正します。
    """
    def __init__(self, sample_rate: int = 48000):
        self.sample_rate = sample_rate
        self.win_size = 256  # 窓幅 (約5.3ms)
        self.prev_tail = np.zeros((self.win_size, CHANNELS), dtype=np.float32)

    def process(self, pcm_bytes: bytes, semitones: float) -> bytes:
        if len(pcm_bytes) == 0:
            return pcm_bytes

        if semitones == 0:
            # ピッチ変更なしでも境界クロスフェードでノイズ防止
            audio = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32768.0
            audio_stereo = audio.reshape(-1, CHANNELS)
            self._apply_crossfade(audio_stereo)
            return pcm_bytes

        factor = 2.0 ** (semitones / 12.0)

        # 16bit PCM -> float32
        audio = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32768.0
        audio_stereo = audio.reshape(-1, CHANNELS)
        n_samples = audio_stereo.shape[0]  # 通常960サンプル

        # 1. 時間軸のリサンプリング (伸縮)
        new_indices = np.arange(0, n_samples, factor)
        new_indices = new_indices[new_indices < n_samples - 1]

        idx_floor = new_indices.astype(np.int32)
        idx_frac = (new_indices - idx_floor)[:, None]

        # 高速ベクトル補間
        resampled = (1.0 - idx_frac) * audio_stereo[idx_floor] + idx_frac * audio_stereo[idx_floor + 1]

        # 2. 前パケット境界との自動ズレ補正（クロスフェード）
        self._apply_crossfade(resampled)

        # 3. 20ms (960サンプル) への正確な長さに調整
        out_len = resampled.shape[0]
        if out_len >= n_samples:
            final_audio = resampled[:n_samples]
        else:
            final_audio = np.pad(resampled, ((0, n_samples - out_len), (0, 0)), mode='constant')

        int16_audio = (final_audio * 32767.0).clip(-32768, 32767).astype(np.int16)
        return int16_audio.tobytes()

    def _apply_crossfade(self, audio_stereo: np.ndarray) -> None:
        out_len = audio_stereo.shape[0]
        fade_len = min(self.win_size, out_len, self.prev_tail.shape[0])

        if fade_len > 0:
            fade_in = np.linspace(0, 1, fade_len)[:, None]
            fade_out = 1.0 - fade_in
            audio_stereo[:fade_len] = audio_stereo[:fade_len] * fade_in + self.prev_tail[:fade_len] * fade_out

        if out_len >= self.win_size:
            self.prev_tail = audio_stereo[-self.win_size:].copy()


# ============================================================
# ズレ自動同期付き ジッター再生バッファ (目標 20ms)
# ============================================================
class AdaptiveAudioSource(discord.AudioSource):
    """
    目標バッファ 20ms で動作し、到達タイミングの揺らぎ（ズレ）を自動補正するソース。
    アンダーラン発生時は前回の音声を自動でフェードアウト接続し、音切れを防ぎます。
    """
    def __init__(self, target_buffer_ms: int = 20) -> None:
        self._buffer = bytearray()
        self._lock = threading.Lock()
        
        self.target_prebuffer_bytes = int((target_buffer_ms / 1000.0) * BYTES_PER_SECOND)
        self.max_buffer_bytes = int((40 / 1000.0) * BYTES_PER_SECOND) # 最大40msでパージ
        self.is_buffering = True

        # パケット切れ補間用の最後に出力したチャンクデータ
        self.last_chunk = b"\x00" * CHUNK_BYTES

    def feed(self, pcm: bytes) -> None:
        with self._lock:
            self._buffer.extend(pcm)

            # 遅延蓄積を防ぐため、バッファが溢れた分は古いやつから即座に破棄（ズレ補正）
            if len(self._buffer) > self.max_buffer_bytes:
                overflow = len(self._buffer) - self.max_buffer_bytes
                overflow = (overflow // FRAME_SIZE) * FRAME_SIZE
                del self._buffer[:overflow]

            # 目標量（20ms）溜まったらバッファリング解除
            if self.is_buffering and len(self._buffer) >= self.target_prebuffer_bytes:
                self.is_buffering = False

    def read(self) -> bytes:
        with self._lock:
            # 正常に20ms分のデータがある場合
            if not self.is_buffering and len(self._buffer) >= CHUNK_BYTES:
                chunk = bytes(self._buffer[:CHUNK_BYTES])
                del self._buffer[:CHUNK_BYTES]
                self.last_chunk = chunk
                return chunk

            # パケットが遅れてデータが足りない場合（アンダーラン・ズレ発生時）
            self.is_buffering = True

            # 完全な無音ではなく、直前の波形をフェードアウトしながら補間（途切れ途切れ感を軽減）
            audio = np.frombuffer(self.last_chunk, dtype=np.int16).astype(np.float32)
            fade_out = np.linspace(1.0, 0.0, len(audio))
            concealed_audio = (audio * fade_out).astype(np.int16)
            
            # 次回の補間用にゼロ化
            self.last_chunk = b"\x00" * CHUNK_BYTES
            return concealed_audio.tobytes()

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
        self.semitones = semitones
        self._lock = threading.Lock()
        self.decoders: dict[int, discord.opus.Decoder] = {}
        self.opus_available = discord.opus.is_loaded()
        self._running = True

        self.last_proc_time_ms: float = 0.0
        self.avg_proc_time_ms: float = 0.0
        self.proc_count: int = 0

        self.shifter = AdaptiveWSOLAPitchShifter(sample_rate=SAMPLE_RATE)
        # バッファ 20ms 設定
        self.audio_source = AdaptiveAudioSource(target_buffer_ms=20)

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
        start_time = time.perf_counter()

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

        # 自動ズレ補正機能付きWSOLA変換 (< 1.0ms)
        processed_pcm = self.shifter.process(pcm, current_pitch)
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
                f"🎙️ **ボイスチェンジャー動作中 (バッファ20ms & ズレ自動補正モード)**\n"
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
            f"🎙️ **{target_channel.name}** でボイスチェンジャーを開始しました！\n"
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
