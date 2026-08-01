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
CHUNK_BYTES = int(CHUNK_DURATION * BYTES_PER_SECOND)  # 3840 bytes

OPUS_SILENCE = b"\xf8\xff\xfe"

# 途切れ対策のデフォルト値（多少レイテンシが伸びてもいいので余裕を持たせる）
DEFAULT_TARGET_BUFFER_MS = 100.0   # 再生を開始/再開するのに必要な貯留量
DEFAULT_MAX_BUFFER_MS = 300.0      # これを超えたらクロスフェードしながら間引く
DEFAULT_FADE_MS = 8.0              # 待機突入/復帰・トリム時のクロスフェード長


def we(description: str | None = None, title: str | None = None) -> discord.Embed:
    return discord.Embed(title=title, description=description, color=0x3498DB)


# ============================================================
# 境界クロスフェード付き WSOLA ピッチシフター
# ============================================================
class AdaptiveWSOLAPitchShifter:
    """
    20msパケット単位の WSOLA ピッチシフター。
    無音明けの新しいパケットが来た際に、境界をクロスフェードでなめらかに接続します。
    """
    def __init__(self, sample_rate: int = 48000):
        self.sample_rate = sample_rate
        self.win_size = 256  # 窓幅 (約5.3ms)
        self.prev_tail = np.zeros((self.win_size, CHANNELS), dtype=np.float32)
        self.reset_tail = True  # 長時間無音だった場合のフラグ

    def process(self, pcm_bytes: bytes, semitones: float) -> bytes:
        if len(pcm_bytes) == 0:
            return pcm_bytes

        audio = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32768.0
        audio_stereo = audio.reshape(-1, CHANNELS)
        n_samples = audio_stereo.shape[0]

        if semitones == 0:
            resampled = audio_stereo
        else:
            factor = 2.0 ** (semitones / 12.0)
            new_indices = np.arange(0, n_samples, factor)
            new_indices = new_indices[new_indices < n_samples - 1]

            idx_floor = new_indices.astype(np.int32)
            idx_frac = (new_indices - idx_floor)[:, None]

            resampled = (1.0 - idx_frac) * audio_stereo[idx_floor] + idx_frac * audio_stereo[idx_floor + 1]

        # 無音明けでなければ、前回のパケット末尾とスムーズにクロスフェード接続
        if not self.reset_tail:
            out_len = resampled.shape[0]
            fade_len = min(self.win_size, out_len, self.prev_tail.shape[0])
            if fade_len > 0:
                fade_in = np.linspace(0, 1, fade_len)[:, None]
                fade_out = 1.0 - fade_in
                resampled[:fade_len] = resampled[:fade_len] * fade_in + self.prev_tail[:fade_len] * fade_out
        else:
            self.reset_tail = False

        # 次回接続用に末尾を保持
        if resampled.shape[0] >= self.win_size:
            self.prev_tail = resampled[-self.win_size:].copy()

        # 20ms長に調整
        out_len = resampled.shape[0]
        if out_len >= n_samples:
            final_audio = resampled[:n_samples]
        else:
            final_audio = np.pad(resampled, ((0, n_samples - out_len), (0, 0)), mode='constant')

        int16_audio = (final_audio * 32767.0).clip(-32768, 32767).astype(np.int16)
        return int16_audio.tobytes()

    def mark_gap(self):
        """長時間無音が続いた時にテールをリセット"""
        self.reset_tail = True


# ============================================================
# 無音待機 ＆ クロスフェード接続バッファ (目標: 途切れゼロ)
# ============================================================
class WaitAndConnectAudioSource(discord.AudioSource):
    """
    データが足りない場合は「無音へフェードアウトしながら待機」し、
    バッファが目標量まで貯まった瞬間に「フェードインしながら再生を再開する」ソース。

    ラグ（プリバッファ量）を大きめに確保することで、そもそもネットワークジッター
    程度では待機状態に落ちないようにしつつ、やむを得ず待機/再開が発生した場合も
    クロスフェードで繋ぐことで「ブツッ」という切断音自体を無くす。
    """
    def __init__(
        self,
        target_buffer_ms: float = DEFAULT_TARGET_BUFFER_MS,
        max_buffer_ms: float = DEFAULT_MAX_BUFFER_MS,
        fade_ms: float = DEFAULT_FADE_MS,
        shifter: AdaptiveWSOLAPitchShifter = None,
    ) -> None:
        self._buffer = bytearray()
        self._lock = threading.Lock()

        self.target_buffer_ms = target_buffer_ms
        self.max_buffer_ms = max_buffer_ms

        self.target_prebuffer_bytes = self._ms_to_frame_bytes(target_buffer_ms)
        self.max_buffer_bytes = self._ms_to_frame_bytes(max_buffer_ms)

        fade_bytes = self._ms_to_frame_bytes(fade_ms)
        self._fade_frames = max(1, fade_bytes // FRAME_SIZE)

        self.is_waiting_for_data = True
        self.shifter = shifter

        # 直前に出力したチャンクの末尾（フェード接続用）
        self._last_out_tail = np.zeros((self._fade_frames, CHANNELS), dtype=np.float32)
        self._was_playing = False  # 直前フレームが実データを再生していたか

        # デバッグ用の簡易統計
        self.underrun_count = 0

    @staticmethod
    def _ms_to_frame_bytes(ms: float) -> int:
        raw = int((ms / 1000.0) * BYTES_PER_SECOND)
        return max(FRAME_SIZE, (raw // FRAME_SIZE) * FRAME_SIZE)

    def update_settings(self, target_buffer_ms: float | None = None, max_buffer_ms: float | None = None) -> None:
        """!vc buffer コマンドなどからライブでバッファ量を変更する"""
        with self._lock:
            if target_buffer_ms is not None:
                self.target_buffer_ms = target_buffer_ms
                self.target_prebuffer_bytes = self._ms_to_frame_bytes(target_buffer_ms)
            if max_buffer_ms is not None:
                self.max_buffer_ms = max_buffer_ms
                self.max_buffer_bytes = self._ms_to_frame_bytes(max_buffer_ms)

    def feed(self, pcm: bytes) -> None:
        with self._lock:
            self._buffer.extend(pcm)

            # max_buffer_ms を超えて膨らんだ場合のみ、クロスフェードしながら
            # 古いデータを間引いて遅延の際限ない増加を防ぐ（無音の唐突な切り貼りをしない）
            overflow = len(self._buffer) - self.max_buffer_bytes
            if overflow > 0:
                trim_bytes = (overflow // FRAME_SIZE) * FRAME_SIZE
                self._crossfade_trim(trim_bytes)

            # データが目標量まで貯まったら待機状態を解除（read側でフェードインする）
            if self.is_waiting_for_data and len(self._buffer) >= self.target_prebuffer_bytes:
                self.is_waiting_for_data = False

    def _crossfade_trim(self, trim_bytes: int) -> None:
        """trim_bytes 分だけ先頭を間引く。境界をクロスフェードしてクリック音を防ぐ"""
        if trim_bytes <= 0:
            return

        fade_bytes = self._fade_frames * FRAME_SIZE
        fade_bytes = min(fade_bytes, trim_bytes, len(self._buffer) - trim_bytes)

        if fade_bytes <= 0:
            del self._buffer[:trim_bytes]
            return

        pre = np.frombuffer(
            bytes(self._buffer[trim_bytes - fade_bytes:trim_bytes]), dtype=np.int16
        ).astype(np.float32).reshape(-1, CHANNELS)
        post = np.frombuffer(
            bytes(self._buffer[trim_bytes:trim_bytes + fade_bytes]), dtype=np.int16
        ).astype(np.float32).reshape(-1, CHANNELS)

        n = min(len(pre), len(post))
        fade_in = np.linspace(0.0, 1.0, n, dtype=np.float32)[:, None]
        fade_out = 1.0 - fade_in
        blended = (pre[:n] * fade_out + post[:n] * fade_in).clip(-32768, 32767).astype(np.int16)

        del self._buffer[:trim_bytes]
        self._buffer[:blended.nbytes] = blended.tobytes()

    def read(self) -> bytes:
        with self._lock:
            if not self.is_waiting_for_data and len(self._buffer) >= CHUNK_BYTES:
                chunk = bytes(self._buffer[:CHUNK_BYTES])
                del self._buffer[:CHUNK_BYTES]

                out = np.frombuffer(chunk, dtype=np.int16).astype(np.float32).reshape(-1, CHANNELS)

                if not self._was_playing:
                    # 待機明け: 無音 -> 実音声へフェードインしてブツッ音を防ぐ
                    n = min(self._fade_frames, out.shape[0])
                    fade_in = np.linspace(0.0, 1.0, n, dtype=np.float32)[:, None]
                    out[:n] = out[:n] * fade_in

                self._was_playing = True
                if out.shape[0] >= self._fade_frames:
                    self._last_out_tail = out[-self._fade_frames:].copy()
                else:
                    pad = self._fade_frames - out.shape[0]
                    self._last_out_tail = np.pad(out, ((pad, 0), (0, 0)))

                return out.astype(np.int16).tobytes()

            # データ不足 -> 待機状態へ（次のフィードが来るまで無音で繋ぐ）
            if self.shifter:
                self.shifter.mark_gap()

            silence = np.zeros((CHUNK_BYTES // FRAME_SIZE, CHANNELS), dtype=np.float32)

            if self._was_playing:
                # 実音声 -> 無音への切り替わり: 直前の音をフェードアウトして繋ぐ
                self.underrun_count += 1
                n = min(self._fade_frames, silence.shape[0])
                fade_out = np.linspace(1.0, 0.0, n, dtype=np.float32)[:, None]
                silence[:n] = self._last_out_tail[-n:] * fade_out

            self.is_waiting_for_data = True
            self._was_playing = False

            return silence.astype(np.int16).tobytes()

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
        # 無音待機・クロスフェード接続対応ソース（多少ラグが伸びても途切れを無くす方針）
        self.audio_source = WaitAndConnectAudioSource(
            target_buffer_ms=DEFAULT_TARGET_BUFFER_MS,
            max_buffer_ms=DEFAULT_MAX_BUFFER_MS,
            fade_ms=DEFAULT_FADE_MS,
            shifter=self.shifter,
        )

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

        # ピッチ変換 & 接続処理
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
            src = sink.audio_source

            proc_ms = sink.last_proc_time_ms
            avg_ms = sink.avg_proc_time_ms
            buf_ms = src.buffered_ms
            total_est_delay = avg_ms + src.target_buffer_ms

            await ctx.send(embed=we(
                f"🎙️ **ボイスチェンジャー動作中 (無音待機・クロスフェード接続モード)**\n"
                f"🎵 設定ピッチ: `{sink.semitones:+.1f}` 半音\n\n"
                f"📊 **遅延ステータス**\n"
                f"├ ⚡ 変換処理時間: `{proc_ms:.2f} ms` (平均: `{avg_ms:.2f} ms`)\n"
                f"├ 📦 バッファ滞留量: `{buf_ms:.1f} ms`\n"
                f"├ 🎯 目標プリバッファ: `{src.target_buffer_ms:.0f} ms` / 上限: `{src.max_buffer_ms:.0f} ms`\n"
                f"├ ⚠️ アンダーラン回数: `{src.underrun_count}` 回\n"
                f"└ ⏱️ **推定トータル遅延**: `~{total_est_delay:.1f} ms`\n\n"
                f"・ピッチ変更: `{ctx.prefix}vc pitch <半音数>`\n"
                f"・バッファ量調整: `{ctx.prefix}vc buffer <目標ms> [上限ms]`\n"
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
            f"📦 プリバッファ: `{DEFAULT_TARGET_BUFFER_MS:.0f} ms`（途切れ防止のため多少ラグがあります）\n"
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

    @vc_group.command(name="buffer")
    @commands.guild_only()
    async def vc_buffer(self, ctx: commands.Context, target_ms: float, max_ms: float = None):
        """途切れとラグのトレードオフをその場で調整する。max_ms省略時は target_ms*3"""
        session = self.vc_sessions.get(ctx.guild.id)
        if not session:
            return await ctx.send(embed=we("⚠️ ボイスチェンジャーが開始されていません。"))

        if target_ms < 20:
            return await ctx.send(embed=we("⚠️ 目標バッファは20ms以上を指定してください。"))

        resolved_max_ms = max_ms if max_ms is not None else target_ms * 3
        if resolved_max_ms < target_ms:
            return await ctx.send(embed=we("⚠️ 上限バッファは目標バッファ以上にしてください。"))

        sink: VoiceChangerSink = session["sink"]
        sink.audio_source.update_settings(target_buffer_ms=target_ms, max_buffer_ms=resolved_max_ms)
        await ctx.send(embed=we(
            f"📦 バッファ設定を変更しました。\n"
            f"├ 目標プリバッファ: `{target_ms:.0f} ms`\n"
            f"└ 上限バッファ: `{resolved_max_ms:.0f} ms`\n\n"
            f"数値を大きくするほど途切れにくくなりますが、その分ラグが増えます。"
        ))

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
