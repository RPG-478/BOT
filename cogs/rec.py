"""
Discord ボイスチャンネル録音 Cog

使用方法 (メインファイル側):
    await bot.load_extension("recording_cog")
    # または
    await bot.add_cog(RecordingCog(bot))

必要なライブラリ:
    pip install -U discord.py discord-ext-voice-recv davey
"""

from __future__ import annotations

import asyncio
import io
import logging
import os
import re
import subprocess
import sys
import threading
import time
import wave
import ctypes.util
import math
import numpy as np
from scipy.signal import find_peaks

import discord
import discord.opus
from discord.ext import commands
from discord.ext import voice_recv

logger = logging.getLogger(__name__)

# ============================================================
# 定数
# ============================================================
SAMPLE_RATE = 48000          # Discord の音声は 48kHz 固定
CHANNELS = 2                 # ステレオ
SAMPLE_WIDTH = 2             # 16bit = 2byte
FRAME_SIZE = CHANNELS * SAMPLE_WIDTH          # 1サンプルフレーム = 4byte
BYTES_PER_SECOND = SAMPLE_RATE * FRAME_SIZE   # 192000 byte/s

# これより短い録音はノイズとみなして出力しない (0.2秒)
MIN_SAVE_BYTES = int(0.2 * BYTES_PER_SECOND)

# ステータスメッセージの更新間隔(秒)。Discord のレートリミット回避。
STATUS_UPDATE_INTERVAL = 5.0

# RTP タイムスタンプ由来の位置と壁時計由来の位置が離れた場合の再同期閾値
RESYNC_THRESHOLD_BYTES = 5 * BYTES_PER_SECOND

# voice_recv が無音パケットの代わりに流してくる Opus フレーム
OPUS_SILENCE = b"\xf8\xff\xfe"


def we(description: str | None = None, title: str | None = None) -> discord.Embed:
    """白色 embed を生成するヘルパー"""
    return discord.Embed(title=title, description=description, color=0xFFFFFF)


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

    def dave_is_ready(self) -> bool:
        connection = getattr(self, "_connection", None)
        if connection is not None:
            state = getattr(connection, "is_e2ee", None)
            if isinstance(state, bool):
                return state
            if callable(state):
                try:
                    return bool(state())
                except Exception:
                    pass
        session = _get_dave_session(self)
        return bool(getattr(session, "ready", False)) if session else False

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

        raise RuntimeError(f"DAVE セッションの decrypt() 呼び出しに失敗しました: {last_error!r}")

    vc_cls.dave_is_active = dave_is_active
    vc_cls.dave_is_ready = dave_is_ready
    vc_cls.dave_decrypt = dave_decrypt


_patch_voice_recv_client()

NOTE_NAMES_SHARP = ["C", "C♯", "D", "D♯", "E", "F", "F♯", "G", "G♯", "A", "A♯", "B"]
NOTE_NAMES_FLAT  = ["C", "D♭", "D", "E♭", "E", "F", "G♭", "G", "A♭", "A", "B♭", "B"]

def midi_to_freq(midi_num: int) -> float:
    return 440.0 * (2.0 ** ((midi_num - 69) / 12.0))

def freq_to_notes(freq: float) -> tuple[str, str, int] | None:
    if freq < 27.5 or freq > 4186.0:  # A0 〜 C8
        return None
    midi_num = int(round(69 + 12 * math.log2(freq / 440.0)))
    idx = midi_num % 12
    octave = (midi_num // 12) - 1
    return NOTE_NAMES_SHARP[idx] + str(octave), NOTE_NAMES_FLAT[idx] + str(octave), midi_num

def analyze_pitch_layers(pcm_bytes: bytes, top_k: int = 4) -> list[tuple[str, str, int]]:
    """PCMから複数音階（和音・倍音層）を検出"""
    if len(pcm_bytes) < 3840:
        return []
    audio_data = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32)
    mono = audio_data[::2]
    windowed = mono * np.hamming(len(mono))
    fft_spectrum = np.abs(np.fft.rfft(windowed))
    freqs = np.fft.rfftfreq(len(mono), d=1.0 / 48000)

    max_val = np.max(fft_spectrum)
    if max_val < 500:
        return []

    peaks, _ = find_peaks(fft_spectrum, height=max_val * 0.18, distance=max(1, int(30 / (48000 / len(mono)))))
    if len(peaks) == 0:
        return []

    sorted_peaks = sorted(peaks, key=lambda p: fft_spectrum[p], reverse=True)[:top_k]
    results, seen_midi = [], set()
    for p in sorted_peaks:
        res = freq_to_notes(freqs[p])
        if res and res[2] not in seen_midi:
            seen_midi.add(res[2])
            results.append(res)
    return results

def synthesize_piano_chord(midi_list: list[int], duration_sec: float = 0.25) -> bytes:
    """検出MIDIからピアノ波形(PCM 16bit stereo 48kHz)を生成"""
    num_samples = int(48000 * duration_sec)
    t = np.linspace(0, duration_sec, num_samples, endpoint=False)
    mixed_signal = np.zeros(num_samples, dtype=np.float32)

    for midi_num in midi_list:
        f0 = midi_to_freq(midi_num)
        note_wave = np.sin(2 * np.pi * f0 * t) + 0.5 * np.sin(2 * np.pi * f0 * 2 * t) + 0.25 * np.sin(2 * np.pi * f0 * 3 * t)
        decay = np.exp(-6.0 * t) * np.minimum(t / 0.005, 1.0)
        mixed_signal += note_wave * decay

    if len(midi_list) > 0:
        mixed_signal /= math.sqrt(len(midi_list))

    audio_int16 = (mixed_signal * 12000).clip(-32768, 32767).astype(np.int16)
    return np.column_stack((audio_int16, audio_int16)).flatten().tobytes()
# ============================================================
# 録音 Sink
# ============================================================
class RecordingSink(voice_recv.AudioSink):
    """録音とやまびこ（Echo）再生を1つのクラスで両立するSink"""

    def __init__(self, bot: commands.Bot, vc: voice_recv.VoiceRecvClient, update_callback=None, is_echo: bool = False, echo_delay: float = 2.0):
        super().__init__()
        self.bot = bot
        self.vc = vc
        self.update_callback = update_callback

        # やまびこ用設定
        self.is_echo = is_echo
        self.echo_delay = echo_delay
        self.packet_queue: list[tuple[float, bytes]] = []

        try:
            self.manual_decode = bool(vc.dave_is_active())
        except Exception:
            self.manual_decode = False

        self.opus_available = discord.opus.is_loaded()
        self.start_time = time.perf_counter()
        self._lock = threading.Lock()

        self.buffers: dict[int, bytearray] = {}
        self.labels: dict[int, str] = {}
        self.decoders: dict[int, discord.opus.Decoder] = {}
        self._first_ts: dict[int, int | None] = {}
        self._base_offset: dict[int, int] = {}

        self.write_call_count = 0
        self.total_frame_count = 0
        self.packet_count = 0
        self.dave_error_count = 0
        self.opus_error_count = 0
        self._last_update_time = 0.0

    def set_echo_delay(self, delay: float) -> None:
        """動的に遅延時間を変更する"""
        self.echo_delay = float(delay)
    
    def wants_opus(self) -> bool:
        return self.manual_decode

    def write(self, user, data) -> None:
        try:
            self._write_inner(user, data)
        except Exception as e:
            logger.error("[REC] AudioSink.write() エラー: %r", e, exc_info=True)

    def cleanup(self) -> None:
        self.decoders.clear()
        self.packet_queue.clear()

    def _write_inner(self, user, data) -> None:
        self.write_call_count += 1
        key, label, user_id = self._identify(user, data)

        pcm = getattr(data, "pcm", None)
        if self.manual_decode or not pcm:
            raw_opus = getattr(data, "opus", None)
            if not raw_opus:
                return
            pcm = self._decode_opus(key, user_id, bytes(raw_opus))
            if not pcm:
                return

        if not pcm:
            return

        self.total_frame_count += 1
        now = time.perf_counter()
        position = self._resolve_position(key, data, now)
        self._store(key, label, position, pcm)

        self.packet_count += 1

        # ★ やまびこモードが有効な場合はキューに追加して再生処理
        if self.is_echo:
            play_at = time.time() + self.echo_delay
            self.packet_queue.append((play_at, pcm))
            self._process_echo()

        self._maybe_notify(now)

    def _process_echo(self) -> None:
        """再生予定時刻（遅延時間）を過ぎたパケットを VC へ再生"""
        if not self.packet_queue:
            return

        now = time.time()
        play_at, pcm_to_play = self.packet_queue[0]

        if now >= play_at:
            self.packet_queue.pop(0)
            if self.vc and self.vc.is_connected() and not self.vc.is_playing():
                audio_source = discord.PCMAudio(io.BytesIO(pcm_to_play))
                self.vc.play(audio_source)

    def _identify(self, user, data) -> tuple[int, str, int]:
        if user is not None:
            name = getattr(user, "display_name", None) or getattr(user, "name", "user")
            return user.id, f"{name}_{user.id}", user.id

        packet = getattr(data, "packet", None)
        ssrc = getattr(packet, "ssrc", None) or getattr(data, "ssrc", None)
        if ssrc:
            return int(ssrc), f"Speaker_{ssrc}", int(ssrc)

        return 0, "Unknown_Speaker", 0

    def _decode_opus(self, key: int, user_id: int, raw_opus: bytes) -> bytes | None:
        if not self.opus_available:
            return None

        if self.manual_decode and raw_opus != OPUS_SILENCE:
            try:
                payload = self.vc.dave_decrypt(user_id, raw_opus)
            except Exception as e:
                self.dave_error_count += 1
                if self.dave_error_count <= 3:
                    logger.error("[REC] DAVE decrypt 失敗 (key=%s): %r", key, e)
                return None
        else:
            payload = raw_opus

        if not payload:
            return None

        decoder = self.decoders.get(key)
        if decoder is None:
            decoder = discord.opus.Decoder()
            self.decoders[key] = decoder

        try:
            return decoder.decode(payload, fec=False)
        except discord.opus.OpusError as e:
            self.opus_error_count += 1
            if self.opus_error_count <= 3:
                logger.debug("[REC] Opus decode スキップ (key=%s): %s", key, e)
            return None

    def _resolve_position(self, key: int, data, now: float) -> int:
        wall_pos = int((now - self.start_time) * BYTES_PER_SECOND)
        wall_pos -= wall_pos % FRAME_SIZE
        wall_pos = max(0, wall_pos)

        packet = getattr(data, "packet", None)
        ts = getattr(packet, "timestamp", None)

        if key not in self._base_offset:
            self._base_offset[key] = wall_pos
            self._first_ts[key] = int(ts) if ts is not None else None
            return wall_pos

        first_ts = self._first_ts.get(key)
        if ts is None or first_ts is None:
            return wall_pos

        delta = (int(ts) - first_ts) & 0xFFFFFFFF
        if delta >= 0x80000000:
            delta = 0

        pos = self._base_offset[key] + delta * FRAME_SIZE

        if abs(pos - wall_pos) > RESYNC_THRESHOLD_BYTES:
            self._base_offset[key] = wall_pos
            self._first_ts[key] = int(ts)
            return wall_pos

        return max(0, pos)

    def _store(self, key: int, label: str, position: int, pcm: bytes) -> None:
        position -= position % FRAME_SIZE
        with self._lock:
            buf = self.buffers.get(key)
            if buf is None:
                buf = bytearray()
                self.buffers[key] = buf
                self.labels[key] = label

            end = position + len(pcm)
            if position >= len(buf):
                buf.extend(b"\x00" * (position - len(buf)))
                buf.extend(pcm)
            else:
                if end > len(buf):
                    buf.extend(b"\x00" * (end - len(buf)))
                buf[position:end] = pcm

    def _maybe_notify(self, now: float) -> None:
        if not self.update_callback:
            return
        if now - self._last_update_time < STATUS_UPDATE_INTERVAL:
            return
        self._last_update_time = now
        try:
            asyncio.run_coroutine_threadsafe(
                self.update_callback(self.packet_count), self.bot.loop
            )
        except Exception:
            pass

    def snapshot(self) -> dict[str, bytes]:
        with self._lock:
            data = {self.labels.get(k, str(k)): bytes(v) for k, v in self.buffers.items()}

        if not data:
            return {}

        total = max(len(v) for v in data.values())
        total -= total % FRAME_SIZE

        result: dict[str, bytes] = {}
        for name, pcm in data.items():
            if len(pcm) < total:
                pcm = pcm + b"\x00" * (total - len(pcm))
            result[name] = pcm[:total]
        return result


def _pcm_to_wav(pcm: bytes) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(SAMPLE_WIDTH)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(pcm)
    return buf.getvalue()


# ============================================================
# 録音 Cog 本体
# ============================================================
class RecordingCog(commands.Cog):
    """ギルドごとの録音セッションを管理する Cog"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.sessions: dict[int, dict] = {}
        self.echo_sessions: dict[int, dict] = {}
        self._ffmpeg_available: bool | None = None

    async def cog_unload(self) -> None:
        """Cog アンロード時に全セッションを停止"""
        for guild_id in list(self.sessions):
            session = self.sessions.pop(guild_id, None)
            vc = session.get("vc") if session else None
            if vc is None:
                continue
            try:
                vc.stop_listening()
            except Exception:
                pass
            try:
                await vc.disconnect(force=True)
            except Exception:
                pass

    # --------------------------------------------------
    # コマンドグループ: !rec [start|stop|status]
    # --------------------------------------------------
    @commands.group(name="rec", invoke_without_command=True)
    @commands.guild_only()
    async def rec_group(self, ctx: commands.Context):
        """!rec 単体で実行された場合はステータスを表示"""
        await self.status_command(ctx)

    @rec_group.command(name="start")
    @commands.guild_only()
    async def rec_start(self, ctx: commands.Context):
        """!rec start : 録音を開始"""
        await self.start_command(ctx)

    @rec_group.command(name="stop")
    @commands.guild_only()
    async def rec_stop(self, ctx: commands.Context):
        """!rec stop : 録音を停止してファイルを送信"""
        await self.stop_command(ctx)

    @rec_group.command(name="status")
    @commands.guild_only()
    async def rec_status(self, ctx: commands.Context):
        """!rec status : 録音状況を表示"""
        await self.status_command(ctx)

    @rec_group.command(name="pitch")
    @commands.guild_only()
    async def rec_pitch(self, ctx: commands.Context):
        """!rec pitch : 直近の音声からリアルタイムでピアノ音階（単音/和音/声の倍音層）を解析"""
        guild_id = ctx.guild.id
        session = self.sessions.get(guild_id)

        if not session:
            return await ctx.send(embed=we("⚠️ 現在録音中ではありません。`!rec start` で開始してください。"))

        sink: RecordingSink = session["sink"]
        audio_snapshot = sink.snapshot()

        if not audio_snapshot:
            return await ctx.send(embed=we("🎵 音声データがまだ蓄積されていません。話してから実行してください。"))

        embed = discord.Embed(title="🎹 リアルタイム音階解析 (Pitch Detection)", color=0x3498DB)

        found_any = False
        for speaker_label, pcm in audio_snapshot.items():
            # 直近 0.5 秒分のデータ（192000 * 0.5 = 96000 bytes）を取り出して解析
            recent_pcm = pcm[-96000:] if len(pcm) > 96000 else pcm
            
            # 周波数解析を行って音階群を取得
            detected = analyze_pitch_layers(recent_pcm, top_k=4)

            if detected_notes:
                found_any = True
                notes_str = " / ".join([f"`{n}`" for n in detected_notes])
                embed.add_field(
                    name=f"🎙️ {speaker_label}",
                    value=f"検出音階（層）: {notes_str}",
                    inline=False
                )

        if not found_any:
            embed.description = "現在明確なピッチ（音階）は検出されませんでした。"

        await ctx.send(embed=embed)

    
    # --------------------------------------------------
    # やまびこコマンドグループ: !echo
    # --------------------------------------------------
    @commands.group(name="echo", invoke_without_command=True)
    @commands.guild_only()
    async def echo_group(self, ctx: commands.Context):
        """!echo 単体で実行された場合の状態表示"""
        session = self.echo_sessions.get(ctx.guild.id)
        if session:
            sink: RecordingSink = session["sink"]
            await ctx.send(embed=we(
                f"🗣️ **やまびこ動作中**\n"
                f"⏱️ 遅延時間: `{sink.echo_delay}`秒\n"
                f"遅延変更: `{ctx.prefix}echo delay <秒数>`\n"
                f"停止: `{ctx.prefix}echo stop`"
            ))
        else:
            await ctx.send(embed=we(f"⏸️ やまびこ停止中 (`{ctx.prefix}echo start` で開始)"))

    @echo_group.command(name="start")
    @commands.guild_only()
    async def echo_start(self, ctx: commands.Context, delay: float = 2.0):
        """!echo start [秒数] : やまびこを開始"""
        if not ctx.author.voice or not ctx.author.voice.channel:
            return await ctx.send(embed=we("⚠️ ボイスチャンネルに参加してから実行してください。"))

        guild_id = ctx.guild.id
        if guild_id in self.sessions or guild_id in self.echo_sessions:
            return await ctx.send(embed=we("⚠️ 既に録音またはやまびこが実行中です。"))

        target_channel = ctx.author.voice.channel

        try:
            vc = ctx.voice_client
            if vc is None or not isinstance(vc, voice_recv.VoiceRecvClient):
                if vc: await vc.disconnect(force=True)
                vc = await target_channel.connect(cls=voice_recv.VoiceRecvClient)
            elif vc.channel != target_channel:
                await vc.move_to(target_channel)
        except Exception as e:
            return await ctx.send(embed=we(f"❌ VC接続失敗: `{e}`"))

        # 統合 RecordingSink を is_echo=True でインスタンス化
        sink = RecordingSink(bot=self.bot, vc=vc, is_echo=True, echo_delay=delay)
        vc.listen(sink)

        self.echo_sessions[guild_id] = {
            "sink": sink, "vc": vc, "start": time.time()
        }
        await ctx.send(embed=we(
            f"🗣️ **{target_channel.name}** でやまびこを開始しました！\n"
            f"⏱️ 遅延時間: `{delay}`秒\n"
            f"遅延変更: `{ctx.prefix}echo delay 3.0` | 停止: `{ctx.prefix}echo stop`"
        ))

    @echo_group.command(name="delay")
    @commands.guild_only()
    async def echo_delay(self, ctx: commands.Context, delay: float):
        """!echo delay <秒数> : 動作中にリアルタイムで遅延時間を変更"""
        session = self.echo_sessions.get(ctx.guild.id)
        if not session:
            return await ctx.send(embed=we("⚠️ 現在やまびこは実行されていません。"))

        if delay <= 0:
            return await ctx.send(embed=we("⚠️ 遅延時間は 0 秒より大きく設定してください。"))

        sink: RecordingSink = session["sink"]
        sink.set_echo_delay(delay)

        await ctx.send(embed=we(f"⏱️ やまびこの遅延時間を `{delay}` 秒に変更しました。"))

    @echo_group.command(name="stop")
    @commands.guild_only()
    async def echo_stop(self, ctx: commands.Context):
        """!echo stop : やまびこを停止"""
        session = self.echo_sessions.pop(ctx.guild.id, None)
        if not session:
            return await ctx.send(embed=we("⚠️ 現在やまびこは実行されていません。"))

        vc: voice_recv.VoiceRecvClient = session["vc"]
        sink: RecordingSink = session["sink"]

        try:
            vc.stop_listening()
        except Exception:
            pass

        await ctx.send(embed=we("🛑 やまびこを停止しました。"))
    # --------------------------------------------------
    # コマンド処理の実装
    # --------------------------------------------------
    async def start_command(self, ctx: commands.Context):
        if not ctx.author.voice or not ctx.author.voice.channel:
            return await ctx.send(embed=we("⚠️ ボイスチャンネルに参加してから実行してください。"))

        guild_id = ctx.guild.id
        if guild_id in self.sessions:
            return await ctx.send(embed=we(
                f"⚠️ 既にこのサーバーで録音中です。`{ctx.prefix}rec stop` で停止してください。"
            ))

        if not discord.opus.is_loaded():
            return await ctx.send(embed=we(
                "❌ Opus ライブラリがロードされていません。サーバーに libopus をインストールしてください。"
            ))

        target_channel = ctx.author.voice.channel

        try:
            vc = ctx.voice_client
            if vc is None:
                vc = await target_channel.connect(cls=voice_recv.VoiceRecvClient)
            elif not isinstance(vc, voice_recv.VoiceRecvClient):
                await vc.disconnect(force=True)
                vc = await target_channel.connect(cls=voice_recv.VoiceRecvClient)
            elif vc.channel != target_channel:
                await vc.move_to(target_channel)
        except Exception as e:
            return await ctx.send(embed=we(f"❌ ボイスチャンネルへの接続に失敗しました: `{e}`"))

        try:
            if vc.is_listening():
                vc.stop_listening()
        except Exception:
            pass

        await asyncio.sleep(1.0)

        negotiated_mode = getattr(vc, "mode", "不明")
        dave_active = vc.dave_is_active() if hasattr(vc, "dave_is_active") else False
        dave_ready = vc.dave_is_ready() if hasattr(vc, "dave_is_ready") else dave_active

        if dave_active:
            dave_text = "有効" if dave_ready else "有効(鍵交換中)"
        else:
            dave_text = "無効"

        status_msg = await ctx.send(embed=we(
            f"🎙️ **{target_channel.name}** で録音を開始しました。\n"
            f"🔐 暗号化: `{negotiated_mode}` / DAVE(E2EE): `{dave_text}`\n"
            f"📦 受信パケット数: `0` 個\n"
            f"停止するには `{ctx.prefix}rec stop` を実行してください。"
        ))

        prefix = ctx.prefix

        # --------------------------------------------------
        # rec_start 内の on_packet_update (コールバック) を差し替え
        # --------------------------------------------------
        async def on_packet_update(count: int, notes: list[str]) -> None:
            try:
                notes_str = " / ".join([f"`{n}`" for n in notes]) if notes else "`解析中/発聲待機...`"
                await status_msg.edit(embed=we(
                    f"🔴 **リアルタイム音階演奏中...**\n"
                    f"🎙️ チャンネル: **{target_channel.name}**\n"
                    f"🎹 リアルタイム検出音階: {notes_str}\n"
                    f"📦 パケット数: `{count}` | 停止: `{prefix}rec stop`"
                ))
            except Exception:
                pass

        sink = RecordingSink(bot=self.bot, vc=vc, update_callback=on_packet_update)

        try:
            vc.listen(sink)
        except Exception as e:
            return await ctx.send(embed=we(f"❌ 録音の開始に失敗しました: `{e}`"))

        self.sessions[guild_id] = {
            "sink": sink,
            "vc": vc,
            "start": time.time(),
            "channel_name": target_channel.name,
            "status_msg": status_msg,
        }

    async def stop_command(self, ctx: commands.Context):
        session = self.sessions.pop(ctx.guild.id, None)
        if session is None:
            return await ctx.send(embed=we("⚠️ 現在録音は行われていません。"))

        sink: RecordingSink = session["sink"]
        vc = session["vc"]

        try:
            vc.stop_listening()
        except Exception as e:
            logger.error("[REC] stop_listening error: %r", e)

        audio = sink.snapshot()

        elapsed = int(time.time() - session["start"])
        total = sink.total_frame_count
        dave_rate = (sink.dave_error_count / total * 100) if total else 0.0
        opus_rate = (sink.opus_error_count / total * 100) if total else 0.0

        await ctx.send(embed=we(
            f"💾 録音を停止しました（録音時間: `{self.format_time(elapsed)}`）。ファイルを生成中...\n"
            f"🩺 診断: write() `{sink.write_call_count}` / 有効フレーム `{total}` / "
            f"DAVE復号失敗 `{sink.dave_error_count}` (`{dave_rate:.1f}%`) / "
            f"Opusデコード失敗 `{sink.opus_error_count}` (`{opus_rate:.1f}%`)"
        ))

        if not audio:
            return await ctx.send(embed=we(
                "❌ 音声バッファが空でした。（発言が検知されなかったか、パケットが届いていません）"
            ))

        limit = getattr(ctx.guild, "filesize_limit", 8 * 1024 * 1024)
        files, skipped = await self.build_files(audio, limit)

        if not files:
            note = "⚠️ 送信可能な録音データがありませんでした。"
            if skipped:
                note += "\n" + "\n".join(
                    f"・`{name}` はファイルサイズ超過 ({size / 1024 / 1024:.1f}MB) のため送信できません。"
                    for name, size in skipped
                )
            return await ctx.send(embed=we(note))

        for i in range(0, len(files), 10):
            chunk = files[i:i + 10]
            await ctx.send(
                content=f"🎵 **録音データ出力 ({i + 1}〜{i + len(chunk)}件 / 全{len(files)}件)**",
                files=chunk,
            )

        if skipped:
            await ctx.send(embed=we(
                "⚠️ 以下はサイズ超過のため送信できませんでした:\n" + "\n".join(
                    f"・`{name}` ({size / 1024 / 1024:.1f}MB)" for name, size in skipped
                )
            ))

    async def status_command(self, ctx: commands.Context):
        session = self.sessions.get(ctx.guild.id)

        if session:
            sink: RecordingSink = session["sink"]
            elapsed = int(time.time() - session["start"])
            embed = discord.Embed(
                title="🎙️ 録音中",
                description=(
                    f"チャンネル: **{session['channel_name']}**\n"
                    f"経過時間: **{self.format_time(elapsed)}**\n"
                    f"受信パケット数: **{sink.packet_count}** 個\n"
                    f"録音中の話者数: **{len(sink.buffers)}** 人"
                ),
                color=0x2ECC71,
            )
        else:
            embed = discord.Embed(
                title="⏸️ 待機中",
                description=(
                    "現在このサーバーで録音は行われていません。\n"
                    f"`{ctx.prefix}rec start` で開始できます。"
                ),
                color=0x95A5A6,
            )

        await ctx.send(embed=embed)



    # --------------------------------------------------
    # エンコード処理
    # --------------------------------------------------
    async def build_files(self, audio: dict[str, bytes], limit: int):
        stamp = int(time.time())
        files: list[discord.File] = []
        skipped: list[tuple[str, int]] = []

        for label in sorted(audio):
            pcm = audio[label]
            if len(pcm) < MIN_SAVE_BYTES:
                continue

            data, ext = await self.encode(pcm)
            if data is None:
                continue

            safe = re.sub(r'[\\/*?:"<>|\s]+', "_", label)[:60] or "speaker"

            if len(data) > limit:
                skipped.append((safe, len(data)))
                continue

            files.append(discord.File(io.BytesIO(data), filename=f"rec_{safe}_{stamp}.{ext}"))

        return files, skipped

    async def encode(self, pcm: bytes) -> tuple[bytes | None, str]:
        mp3 = await self.to_mp3(pcm)
        if mp3:
            return mp3, "mp3"

        loop = asyncio.get_running_loop()
        wav = await loop.run_in_executor(None, _pcm_to_wav, pcm)
        return wav, "wav"

    async def to_mp3(self, pcm: bytes) -> bytes | None:
        if self._ffmpeg_available is False:
            return None

        cmd = [
            "ffmpeg", "-hide_banner", "-loglevel", "error",
            "-f", "s16le", "-ar", str(SAMPLE_RATE), "-ac", str(CHANNELS), "-i", "pipe:0",
            "-ac", "1", "-ar", "48000", "-c:a", "libmp3lame", "-b:a", "64k",
            "-f", "mp3", "pipe:1",
        ]

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        except FileNotFoundError:
            self._ffmpeg_available = False
            logger.warning("[REC] ffmpeg が見つからないため WAV で出力します。")
            return None
        except Exception as e:
            logger.warning("[REC] ffmpeg 起動失敗: %r", e)
            return None

        try:
            stdout, stderr = await proc.communicate(input=pcm)
        except Exception as e:
            logger.warning("[REC] ffmpeg 実行失敗: %r", e)
            return None

        if proc.returncode != 0 or not stdout:
            logger.warning(
                "[REC] ffmpeg 変換失敗 (rc=%s): %s",
                proc.returncode,
                stderr.decode("utf-8", errors="ignore")[:300],
            )
            return None

        self._ffmpeg_available = True
        return stdout

    @staticmethod
    def format_time(seconds: int) -> str:
        m, s = divmod(int(seconds), 60)
        h, m = divmod(m, 60)
        return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


# ラズパイ等で Opus が手動ロードされていない場合に自動検出・読み込みを行う関数
def ensure_opus():
    if discord.opus.is_loaded():
        return True

    # 1. OS標準のライブラリ検索
    opus_path = ctypes.util.find_library("opus")
    if opus_path:
        try:
            discord.opus.load_opus(opus_path)
            return True
        except Exception:
            pass

    # 2. ラズパイOS (ARM64 / ARM32 / x86_64) の一般的なパスを順番に試す
    possible_paths = [
        "libopus.so.0",
        "libopus.so",
        "/usr/lib/aarch64-linux-gnu/libopus.so.0",  # Raspberry Pi OS 64-bit
        "/usr/lib/arm-linux-gnueabihf/libopus.so.0", # Raspberry Pi OS 32-bit
        "/usr/lib/x86_64-linux-gnu/libopus.so.0",
    ]

    for path in possible_paths:
        try:
            discord.opus.load_opus(path)
            return True
        except Exception:
            continue

    return False

# Cog登録時の setup 関数で実行
async def setup(bot: commands.Bot):
    ensure_opus()  # Cog追加前に Opus をロード
    await bot.add_cog(RecordingCog(bot))
