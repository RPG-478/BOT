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

import aiohttp
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

# 日本語の文脈・表記を補正するためのプロンプト
INITIAL_PROMPT = "こんにちは。Discordのボイスチャットの文字起こしです。日本語で正しく句読点を含めて文字起こししてください。"

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
# 前処理関数 (ノイズ除去・ノーマライズ)
# ============================================================
def preprocess_audio(audio_mono: np.ndarray) -> np.ndarray:
    """音声の前処理（低周波ノイズカット ＆ 音量ノーマライズ）を行って精度を高める"""
    if len(audio_mono) == 0:
        return audio_mono

    # 1. 80Hz以下の環境ノイズ（マイクの重低音ノイズ等）をハイパスフィルターで除去
    b, a = signal.butter(2, 80 / (DISCORD_SAMPLE_RATE / 2), btype='high')
    filtered_audio = signal.filtfilt(b, a, audio_mono)

    # 2. 48kHz -> 16kHz リサンプル
    num_target_samples = int(len(filtered_audio) * WHISPER_SAMPLE_RATE / DISCORD_SAMPLE_RATE)
    resampled_audio = signal.resample(filtered_audio, num_target_samples)

    # 3. 音量ノーマライズ (Peak Normalization)
    max_val = np.max(np.abs(resampled_audio))
    if max_val > 0:
        resampled_audio = (resampled_audio / max_val) * 0.95

    return resampled_audio.astype(np.float32)


# ============================================================
# ユーザー別音声バッファ ＆ VAD
# ============================================================
class UserAudioBuffer:
    def __init__(self, user_id: int, display_name: str, avatar_url: str | None = None):
        self.user_id = user_id
        self.display_name = display_name
        self.avatar_url = avatar_url
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

        # 音声前処理を適用
        return preprocess_audio(audio_mono)


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

        self.monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self.monitor_thread.start()

    def wants_opus(self) -> bool:
        return True

    def write(self, user, data: voice_recv.VoiceData) -> None:
        raw_opus = getattr(data, 'opus', None)
        if not raw_opus:
            return

        user_id = getattr(user, 'id', 0) if user else 0
        display_name = getattr(user, 'display_name', None) or getattr(user, 'name', f"User_{user_id}")
        avatar_url = str(user.display_avatar.url) if user and hasattr(user, 'display_avatar') else None

        if user_id == 0:
            return

        pcm = self._decode_opus(user_id, bytes(raw_opus))
        if not pcm:
            return

        with self._lock:
            if user_id not in self.user_buffers:
                self.user_buffers[user_id] = UserAudioBuffer(user_id, display_name, avatar_url)
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
                            threading.Thread(
                                target=self._run_whisper,
                                args=(ubuf.display_name, ubuf.avatar_url, audio_data),
                                daemon=True
                            ).start()

    def _run_whisper(self, display_name: str, avatar_url: str | None, audio: np.ndarray):
        try:
            # 高精度推論パラメータの設定
            segments, _ = self.whisper_model.transcribe(
                audio,
                language="ja",
                beam_size=5,             # 探索幅（精度優先）
                best_of=5,               # 候補生成数
                temperature=0.0,         # 確定的な推論結果（誤字低減）
                initial_prompt=INITIAL_PROMPT,  # プロンプト付与による表記揺れ防ぎ
                vad_filter=True,         # 音声区間検知を有効化
                vad_parameters=dict(
                    min_silence_duration_ms=500
                )
            )
            text = "".join([segment.text for segment in segments]).strip()

            if text:
                asyncio.run_coroutine_threadsafe(
                    self.callback_coro(display_name, avatar_url, text),
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

        logger.info("Whisper 高精度モデルをロード中...")
        # モデルを "small" に引き上げ (PCスペックやGPU環境に応じて "large-v3-turbo" も選択可能)
        # GPUが使用できる環境の場合は device="cuda", compute_type="float16" に調整してください
        self.whisper_model = WhisperModel(
            "small",
            device="cpu",
            compute_type="int8"
        )
        logger.info("Whisper モデルのロードが完了しました。")

    async def _get_or_create_webhook(self, channel: discord.TextChannel) -> discord.Webhook:
        webhooks = await channel.webhooks()
        for wh in webhooks:
            if wh.token:
                return wh

        return await channel.create_webhook(name="STT-Transcriber")

    @commands.group(name="stt", invoke_without_command=True)
    @commands.guild_only()
    async def stt_group(self, ctx: commands.Context):
        session = self.sessions.get(ctx.guild.id)
        if session:
            await ctx.send(embed=we(
                f"🎙️ **高精度文字起こし実行中**\n"
                f"ボイスチャンネル: **{session['vc_channel_name']}**\n"
                f"送信先チャンネル: {session['target_channel_mention']}\n"
                f"停止コマンド: `{ctx.prefix}stt stop`"
            ))
        else:
            await ctx.send(embed=we(f"⏸️ 文字起こし停止中 (`{ctx.prefix}stt start` で開始)"))

    @stt_group.command(name="start")
    @commands.guild_only()
    async def stt_start(
        self,
        ctx: commands.Context,
        target_channel: discord.TextChannel | None = None
    ):
        if not ctx.author.voice or not ctx.author.voice.channel:
            return await ctx.send(embed=we("⚠️ ボイスチャンネル（または聞き専VC）に参加してから実行してください。"))

        guild_id = ctx.guild.id
        if guild_id in self.sessions:
            return await ctx.send(embed=we("⚠️ 既に文字起こしが実行中です。"))

        vc_channel = ctx.author.voice.channel
        send_channel: discord.TextChannel = target_channel or ctx.channel

        try:
            webhook = await self._get_or_create_webhook(send_channel)
        except discord.Forbidden:
            return await ctx.send(embed=we(f"❌ Botに {send_channel.mention} の `ウェブフックの管理 (Manage Webhooks)` 権限がありません。"))
        except Exception as e:
            return await ctx.send(embed=we(f"❌ Webhookの取得に失敗しました: `{e}`"))

        try:
            if ctx.voice_client is not None:
                await ctx.voice_client.disconnect(force=True)
                await asyncio.sleep(1.0)

            vc = await vc_channel.connect(
                cls=voice_recv.VoiceRecvClient,
                timeout=30.0,
                reconnect=True,
                self_deaf=False
            )
        except Exception as e:
            return await ctx.send(embed=we(f"❌ ボイス接続に失敗しました: `{e}`"))

        async def send_webhook(display_name: str, avatar_url: str | None, text: str):
            async with aiohttp.ClientSession() as session:
                wh_obj = discord.Webhook.from_url(webhook.url, session=session)
                try:
                    await wh_obj.send(
                        content=text,
                        username=display_name,
                        avatar_url=avatar_url
                    )
                except Exception as ex:
                    logger.error(f"[Webhook Send Error] {ex}")

        sink = TranscriptionSink(
            bot=self.bot,
            vc=vc,
            whisper_model=self.whisper_model,
            callback_coro=send_webhook
        )
        vc.listen(sink)

        self.sessions[guild_id] = {
            "sink": sink,
            "vc": vc,
            "vc_channel_name": vc_channel.name,
            "target_channel_mention": send_channel.mention
        }

        await ctx.send(embed=we(
            f"🎙️ **{vc_channel.name}** で高精度文字起こしを開始しました！\n"
            f"🤖 結果を {send_channel.mention} へ送信します。"
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
