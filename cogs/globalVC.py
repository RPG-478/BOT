from __future__ import annotations

import asyncio
import io
import logging
import sys
import threading
import time
import numpy as np

import discord
import discord.opus
from discord.ext import commands
from discord.ext import voice_recv

logger = logging.getLogger(__name__)

DISCORD_SAMPLE_RATE = 48000
CHANNELS = 2
SAMPLE_WIDTH = 2
FRAME_SIZE = CHANNELS * SAMPLE_WIDTH
FRAME_DURATION = 0.02  # 20ms
FRAME_BYTE_SIZE = int(DISCORD_SAMPLE_RATE * FRAME_DURATION * FRAME_SIZE)  # 3840 bytes

# グローバルルーム管理: { "room_name": [VoiceRecvClient, ...] }
GLOBAL_ROOMS: dict[str, list[voice_recv.VoiceRecvClient]] = {}
# ルームごとの音声混音バッファ
ROOM_AUDIO_BUFFERS: dict[str, collections.deque] = {}


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
# グローバルVC送受信 AudioSink
# ============================================================
class GlobalAudioSink(voice_recv.AudioSink):
    def __init__(self, room_name: str, current_vc: voice_recv.VoiceRecvClient):
        super().__init__()
        self.room_name = room_name
        self.current_vc = current_vc
        self.decoders: dict[int, discord.opus.Decoder] = {}
        self.opus_available = discord.opus.is_loaded()

    def wants_opus(self) -> bool:
        return True

    def write(self, user, data: voice_recv.VoiceData) -> None:
        raw_opus = getattr(data, 'opus', None)
        if not raw_opus or not user:
            return

        user_id = getattr(user, 'id', 0)
        if user_id == 0:
            return

        # DAVE復号処理
        try:
            payload = self.current_vc.dave_decrypt(user_id, bytes(raw_opus))
        except Exception:
            return

        if not payload or not self.opus_available:
            return

        decoder = self.decoders.setdefault(user_id, discord.opus.Decoder())
        try:
            pcm = decoder.decode(payload, fec=False)
        except discord.opus.OpusError:
            return

        # 復号されたPCM音声を他サーバーの送信ストリームに流す処理
        if pcm and self.room_name in GLOBAL_ROOMS:
            for vc in GLOBAL_ROOMS[self.room_name]:
                if vc != self.current_vc and vc.is_connected() and not vc.is_playing():
                    if hasattr(vc, "global_source") and vc.global_source:
                        vc.global_source.write_pcm(pcm)

    def cleanup(self) -> None:
        """AudioSink の停止時に呼ばれるクリーンアップ処理"""
        self.decoders.clear()


class GlobalAudioSource(discord.AudioSource):
    """他サーバーから届いたPCM音声を自サーバーVCに再生するSource"""
    def __init__(self):
        self.buffer = bytearray()
        self._lock = threading.Lock()

    def write_pcm(self, pcm: bytes):
        with self._lock:
            self.buffer.extend(pcm)

    def read(self) -> bytes:
        with self._lock:
            if len(self.buffer) >= FRAME_BYTE_SIZE:
                data = bytes(self.buffer[:FRAME_BYTE_SIZE])
                del self.buffer[:FRAME_BYTE_SIZE]
                return data
        # バッファ不足時は無音パケットを返す
        return b"\x00" * FRAME_BYTE_SIZE

    def is_opus(self) -> bool:
        return False


# ============================================================
# グローバル VC Cog 本体
# ============================================================
class GlobalVCCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.group(name="gvc", invoke_without_command=True)
    async def gvc_group(self, ctx: commands.Context):
        embed = discord.Embed(title="🌐 グローバルVC コマンド一覧", color=0x3498DB)
        embed.description = (
            f"`{ctx.prefix}gvc list` : アクティブなルーム一覧を表示\n"
            f"`{ctx.prefix}gvc join <ルーム名>` : 指定したルームに参加\n"
            f"`{ctx.prefix}gvc leave` : グローバルVCから離脱"
        )
        await ctx.send(embed=embed)

    @gvc_group.command(name="list")
    async def gvc_list(self, ctx: commands.Context):
        if not GLOBAL_ROOMS:
            return await ctx.send("現在作成されているグローバルVCルームはありません。")

        embed = discord.Embed(title="🌐 アクティブなルーム一覧", color=0x2ECC71)
        for room_name, clients in GLOBAL_ROOMS.items():
            servers = [vc.guild.name for vc in clients if vc.guild]
            embed.add_field(
                name=f"🎙️ ルーム: {room_name}",
                value=f"参加サーバー({len(servers)}): {', '.join(servers)}",
                inline=False
            )
        await ctx.send(embed=embed)

    @gvc_group.command(name="join")
    async def gvc_join(self, ctx: commands.Context, room_name: str):
        if not ctx.author.voice or not ctx.author.voice.channel:
            return await ctx.send("⚠️ ボイスチャンネルに参加してから実行してください。")

        guild_id = ctx.guild.id
        vc_channel = ctx.author.voice.channel

        if ctx.voice_client is not None:
            await ctx.voice_client.disconnect(force=True)
            await asyncio.sleep(0.5)

        try:
            vc = await vc_channel.connect(
                cls=voice_recv.VoiceRecvClient,
                timeout=30.0,
                reconnect=True,
                self_deaf=False
            )
        except Exception as e:
            return await ctx.send(f"❌ ボイス接続に失敗しました: `{e}`")

        # 再生用 AudioSource を登録して再生開始
        source = GlobalAudioSource()
        vc.global_source = source
        vc.play(source)

        # 受信 Sink の設定
        sink = GlobalAudioSink(room_name, vc)
        vc.listen(sink)

        # ルーム管理に追加
        GLOBAL_ROOMS.setdefault(room_name, []).append(vc)

        await ctx.send(
            f"🌐 ルーム **{room_name}** に参加しました！\n"
            f"別サーバーの同名ルームと相互接続されています。"
        )

    @gvc_group.command(name="leave")
    async def gvc_leave(self, ctx: commands.Context):
        vc = ctx.voice_client
        if not vc:
            return await ctx.send("現在ボイスチャンネルに接続していません。")

        # ルームから削除
        for room_name, clients in list(GLOBAL_ROOMS.items()):
            if vc in clients:
                clients.remove(vc)
                if not clients:
                    del GLOBAL_ROOMS[room_name]

        try:
            vc.stop_listening()
            await vc.disconnect(force=True)
        except Exception:
            pass

        await ctx.send("🌐 グローバルVCから切断しました。")


async def setup(bot: commands.Bot):
    await bot.add_cog(GlobalVCCog(bot))
