from __future__ import annotations

import asyncio
import io
import logging
import os
import sys
import threading
import time
import collections
import numpy as np
from scipy import signal

import discord
import discord.opus
from discord.ext import commands
from discord.ext import voice_recv

# 高速・軽量な Whisper エンジン
from faster_whisper import WhisperModel

logger = logging.getLogger(__name__)

# ============================================================
# 定数設定
# ============================================================
DISCORD_SAMPLE_RATE = 48000  # Discord 音声 (48kHz)
WHISPER_SAMPLE_RATE = 16000  # Whisper 入力用 (16kHz)
CHANNELS = 2
SAMPLE_WIDTH = 2
FRAME_SIZE = CHANNELS * SAMPLE_WIDTH

# 無音判定の閾値（秒）: 発話後、この時間だけ無音が続いたら文字起こしを実行
SILENCE_THRESHOLD_SEC = 1.0
# 音量判定の閾値（16bit int PCMのRMS値）
RMS_SILENCE_THRESHOLD = 400

# voice_recv が無音時に渡してくる Opus パケット
OPUS_SILENCE = b"\xf8\xff\xfe"


def we(description: str | None = None, title: str | None = None) -> discord.Embed:
    return discord.Embed(title=title, description=description, color=0x2ECC71)


# ============================================================
# DAVE (Discord E2EE) 対応パッチ
# ============================================================
try:
    import davey  # type: ignore
except Exception:
    davey = None  # type: ignore[assignment]

_UNSET = object()
_media_type_audio = _UNSET


def _media_type_classes(session=None) -> list:
    found: list = []
    def _add(cls) -> None:
        if cls is not None and not any(cls is f for f in found):
            found.append(cls)

    if davey is not None:
        _add(getattr(davey, "MediaType", None))
    if session is not None:
        mod = sys.modules.get(type(session).__module__)
        if mod is not None:
            _add(getattr(mod, "MediaType", None))
    for name, mod in list(sys.modules.items()):
        if mod is None or "dave" not in name.lower():
            continue
        _add(getattr(mod, "MediaType", None))
    return found


def _media_type_candidates(session=None) -> list:
    candidates: list = []
    seen: set = set()
    def _add(value) -> None:
        if value is None:
            return
        key = (id(type(value)), repr(value))
        if key in seen:
            return
        seen.add(key)
        candidates.append(value)

    for cls in _media_type_classes(session):
        for attr in ("audio", "Audio", "AUDIO"):
            _add(getattr(cls, attr, None))
        try:
            _add(cls(0))
        except Exception:
            pass
    _add(0)
    return candidates


def _patch_voice_recv_client() -> None:
    vc_cls = voice_recv.VoiceRecvClient
    if getattr(vc_cls, "_dave_patch_applied", False):
        return
    vc_cls._dave_patch_applied = True

    def _get_dave_session(self):
        connection = getattr(self, "_connection", None)
        return getattr(connection, "dave_session", None) if connection else None

    def dave_is_active(self) -> bool:
        return _get_dave_session(self) is not None

    def dave_decrypt(self, user_id: int, data: bytes) -> bytes:
        global _media_type_audio
        session = _get_dave_session(self)
        if session is None:
            return data

        cached = _media_type_audio
        if cached is not _UNSET:
            try:
                return session.decrypt(user_id, cached, data)
            except TypeError:
                _media_type_audio = _UNSET

        last_error: Exception | None = None
        for candidate in _media_type_candidates(session):
            try:
                result = session.decrypt(user_id, candidate, data)
            except TypeError as e:
                last_error = e
                continue
            _media_type_audio = candidate
            return result

        try:
            return session.decrypt(user_id, data)
        except TypeError as e:
            last_error = e

        raise RuntimeError(f"DAVE decrypt 失敗: {last_error!r}")

    vc_cls.dave_is_active = dave_is_active
    vc_cls.dave_decrypt = dave_decrypt


_patch_voice_recv_client()


# ============================================================
# ユーザー別音声バッファ ＆ VAD
# ============================================================
class UserAudioBuffer:
    def __init__(self, user_id: int, display_name: str):
        self.user_id = user_id
        self.display_name = display_name
        self.buffer = bytearray()
        self.last_speech_time = time.time()
        self.is_speaking = False

    def append(self, pcm_data: bytes):
        audio_np = np.frombuffer(pcm_data, dtype=np.int16)
        if len(audio_np) == 0:
            return

        rms = np.sqrt(np.mean(audio_np.astype(np.float32) ** 2))

        if rms > RMS_SILENCE_THRESHOLD:
            self.is_speaking = True
            self.last_speech_time = time.time()
            self.buffer.extend(pcm_data)
        elif self.is_speaking:
            self.buffer.extend(pcm_data)

    def should_transcribe(self) -> bool:
        if self.is_speaking and (time.time() - self.last_speech_time > SILENCE_THRESHOLD_SEC):
            return len(self.buffer) > 0
        return False

    def pop_audio_for_whisper(self) -> np.ndarray | None:
        if len(self.buffer) == 0:
            return None

        pcm = bytes(self.buffer)
        self.buffer.clear()
        self.is_speaking = False

        audio_16bit = np.frombuffer(pcm, dtype=np.int16)
        if len(audio_16bit) == 0:
            return None

        # ステレオ -> モノラル
        audio_stereo = audio_16bit.reshape(-1, CHANNELS)
        audio_mono = audio_stereo.mean(axis=1)

        # 48kHz -> 16kHz リサンプル
        num_target_samples = int(len(audio_mono) * WHISPER_SAMPLE_RATE / DISCORD_SAMPLE_RATE)
        resampled_audio = signal.resample(audio_mono, num_target_samples)

        # float32 ( -1.0 〜 1.0 ) に規格化
        return (resampled_audio / 32768.0).astype(np.float32)


# ============================================================
# 文字起こし統合 AudioSink
# ============================================================
class TranscriptionSink(voice_recv.AudioSink):
    def __init__(
        self,
        bot: commands.Bot,
        vc: voice_recv.VoiceRecvClient,
        whisper_model: WhisperModel,
        callback_coro
    ):
        super().__init__()
        self.bot = bot
        self.vc = vc
        self.whisper_model = whisper_model
        self.callback_coro = callback_coro

        self.user_buffers: dict[int, UserAudioBuffer] = {}
        self.decoders: dict[int, discord.opus.Decoder] = {}
        self._lock = threading.Lock()
        self.opus_available = discord.opus.is_loaded()
        self._running = True

        # バックグラウンドで無音状態を監視するスレッド
        self.monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self.monitor_thread.start()

    def wants_opus(self) -> bool:
        # DAVE(E2EE) 環境でも自前復号・デコードを行うため True
        return True

    def write(self, user, data: voice_recv.VoiceData) -> None:
        raw_opus = getattr(data, 'opus', None)
        if not raw_opus:
            return

        user_id = getattr(user, 'id', 0) if user else 0
        display_name = getattr(user, 'display_name', None) or getattr(user, 'name', f"User_{user_id}")
        if user_id == 0:
            return

        pcm = self._decode_opus(user_id, bytes(raw_opus))
        if not pcm:
            return

        with self._lock:
            if user_id not in self.user_buffers:
                self.user_buffers[user_id] = UserAudioBuffer(user_id, display_name)
            self.user_buffers[user_id].append(pcm)

    def _decode_opus(self, user_id: int, raw_opus: bytes) -> bytes | None:
        if not self.opus_available:
            return None

        if raw_opus != OPUS_SILENCE:
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

    def _monitor_loop(self):
        while self._running:
            time.sleep(0.2)
            with self._lock:
                for user_id, ubuf in list(self.user_buffers.items()):
                    if ubuf.should_transcribe():
                        audio_data = ubuf.pop_audio_for_whisper()
                        if audio_data is not None and len(audio_data) > WHISPER_SAMPLE_RATE * 0.4:
                            # 0.4秒以上の音声データを文字起こし処理へ委譲
                            threading.Thread(
                                target=self._run_whisper,
                                args=(ubuf.display_name, audio_data),
                                daemon=True
                            ).start()

    def _run_whisper(self, display_name: str, audio: np.ndarray):
        try:
            segments, _ = self.whisper_model.transcribe(
                audio,
                language="ja",
                beam_size=5,
                vad_filter=True
            )
            text = "".join([segment.text for segment in segments]).strip()

            if text:
                asyncio.run_coroutine_threadsafe(
                    self.callback_coro(display_name, text),
                    self.bot.loop
                )
        except Exception as e:
            logger.error(f"[Whisper Error] {e}")

    def cleanup(self):
        self._running = False


# ============================================================
# 文字起こし Cog 本体
# ============================================================
class TranscriptionCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.sessions: dict[int, dict] = {}

        logger.info("Whisper モデルをロード中...")
        # CPUの場合は "base" / "small" と compute_type="int8" が高速
        # GPU利用時は device="cuda", compute_type="float16"
        self.whisper_model = WhisperModel(
            "base",
            device="cpu",
            compute_type="int8"
        )
        logger.info("Whisper モデルのロードが完了しました。")

    @commands.group(name="stt", invoke_without_command=True)
    @commands.guild_only()
    async def stt_group(self, ctx: commands.Context):
        session = self.sessions.get(ctx.guild.id)
        if session:
            await ctx.send(embed=we(
                f"🎙️ **文字起こし実行中**\n"
                f"チャンネル: **{session['channel_name']}**\n"
                f"停止コマンド: `{ctx.prefix}stt stop`"
            ))
        else:
            await ctx.send(embed=we(f"⏸️ 文字起こし停止中 (`{ctx.prefix}stt start` で開始)"))

    @stt_group.command(name="start")
    @commands.guild_only()
    async def stt_start(self, ctx: commands.Context):
        if not ctx.author.voice or not ctx.author.voice.channel:
            return await ctx.send(embed=we("⚠️ ボイスチャンネルに参加してから実行してください。"))

        guild_id = ctx.guild.id
        if guild_id in self.sessions:
            return await ctx.send(embed=we("⚠️ 既に文字起こしが実行中です。"))

        target_channel = ctx.author.voice.channel
        text_channel = ctx.channel

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

        # 文字起こし完了時にDiscordへ送信する非同期関数
        async def on_transcribed(display_name: str, text: str):
            embed = discord.Embed(description=text, color=0x3498DB)
            embed.set_author(name=f"🗣️ {display_name}")
            await text_channel.send(embed=embed)

        sink = TranscriptionSink(
            bot=self.bot,
            vc=vc,
            whisper_model=self.whisper_model,
            callback_coro=on_transcribed
        )
        vc.listen(sink)

        self.sessions[guild_id] = {
            "sink": sink,
            "vc": vc,
            "channel_name": target_channel.name
        }

        await ctx.send(embed=we(
            f"🎙️ **{target_channel.name}** でリアルタイム文字起こしを開始しました！\n"
            f"発言が途切れたタイミングでこのテキストチャンネルに文字起こし結果が送信されます。"
        ))

    @stt_group.command(name="stop")
    @commands.guild_only()
    async def stt_stop(self, ctx: commands.Context):
        session = self.sessions.pop(ctx.guild.id, None)
        if not session:
            return await ctx.send(embed=we("⚠️ 現在文字起こしは実行されていません。"))

        sink: TranscriptionSink = session["sink"]
        vc: voice_recv.VoiceRecvClient = session["vc"]

        sink.cleanup()
        try:
            vc.stop_listening()
            await vc.disconnect(force=True)
        except Exception:
            pass

        await ctx.send(embed=we("🛑 文字起こしを停止しました。"))


async def setup(bot: commands.Bot):
    await bot.add_cog(TranscriptionCog(bot))
