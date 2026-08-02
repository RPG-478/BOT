from __future__ import annotations

import asyncio
import collections
import dataclasses
import io
import logging
import sys
import threading
import time
from typing import Optional

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
MAX_BUFFER_FRAMES = 50  # 送信バッファの上限 (20ms * 50 = 約1秒分)


# ============================================================
# ルーム定義 / 接続管理
# ============================================================
@dataclasses.dataclass
class RoomConfig:
    """`gvc create` で定義されるルームの設定。接続の有無に関わらず存在する。"""
    name: str
    owner_id: int
    owner_guild_id: int
    max_servers: int = 0          # 0 = 無制限
    private: bool = False
    password: str = ""
    description: str = ""
    created_at: float = dataclasses.field(default_factory=time.time)


# ルーム定義: { "room_name": RoomConfig }  ※ gvc create で作成され、gvc delete まで残り続ける
ROOMS: dict[str, RoomConfig] = {}
# ルームごとの実際に接続中の VoiceRecvClient 一覧: { "room_name": [vc, ...] }
GLOBAL_ROOMS: dict[str, list[voice_recv.VoiceRecvClient]] = {}


def _remove_vc_from_rooms(vc: voice_recv.VoiceRecvClient) -> Optional[str]:
    """全ルームの接続中リストから vc を取り除く。所属していたルーム名を返す。"""
    for room_name, clients in list(GLOBAL_ROOMS.items()):
        if vc in clients:
            clients.remove(vc)
            if not clients:
                del GLOBAL_ROOMS[room_name]
            return room_name
    return None


async def _disconnect_and_cleanup(vc: voice_recv.VoiceRecvClient) -> None:
    """listen/play を止めて切断し、ルーム管理からも除去する。"""
    _remove_vc_from_rooms(vc)
    try:
        vc.stop_listening()
    except Exception:
        logger.debug("stop_listening 失敗 (無視)", exc_info=True)
    try:
        await vc.disconnect(force=True)
    except Exception:
        logger.debug("disconnect 失敗 (無視)", exc_info=True)


# ============================================================
# グロチャ (テキストチャット連携) 管理
# ============================================================
@dataclasses.dataclass
class TextLink:
    guild_id: int
    channel_id: int
    webhook: discord.Webhook


# ルームごとに連携中のテキストチャンネル: { "room_name": [TextLink, ...] }
ROOM_TEXT_LINKS: dict[str, list[TextLink]] = {}
# チャンネルID -> ルーム名 の逆引き (on_message での高速判定用)
CHANNEL_TO_ROOM: dict[int, str] = {}


async def _remove_text_link(channel_id: int, *, delete_webhook: bool = True) -> Optional[str]:
    """指定チャンネルのグロチャ連携を解除する。所属していたルーム名を返す。"""
    room_name = CHANNEL_TO_ROOM.pop(channel_id, None)
    if room_name is None:
        return None

    links = ROOM_TEXT_LINKS.get(room_name, [])
    for link in list(links):
        if link.channel_id == channel_id:
            links.remove(link)
            if delete_webhook:
                try:
                    await link.webhook.delete(reason="グロチャ連携解除")
                except Exception:
                    logger.debug("webhook 削除失敗 (無視)", exc_info=True)
    if not links:
        ROOM_TEXT_LINKS.pop(room_name, None)
    return room_name


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
                # キャッシュした MediaType の型自体が合わない -> 候補を再探索
                logger.debug("DAVE decrypt: キャッシュ済み MediaType %r が型不一致。再探索します。", cached)
                _media_type_audio = _UNSET
            except Exception as e:
                # 型は合っていたが復号自体が失敗 (セッションのエポック更新等の可能性)。
                # キャッシュを破棄して候補を再探索する。ここを再探索しないままだと
                # このユーザーの音声が復元されるまで永久に無音になり得る。
                logger.debug(
                    "DAVE decrypt: キャッシュ済み MediaType %r で復号失敗 (%r)。再探索します。",
                    cached, e,
                )
                _media_type_audio = _UNSET

        last_error: Exception | None = None
        for candidate in _media_type_candidates(session):
            try:
                result = session.decrypt(user_id, candidate, data)
            except Exception as e:
                # 元のコードは TypeError しか継続対象にしておらず、それ以外の例外で
                # ループを即座に抜けてしまい他の候補を一切試さないバグがあった。
                # (これが「音声が全く聞こえない」の主要因になり得る)
                last_error = e
                continue
            _media_type_audio = candidate
            logger.debug("DAVE decrypt: MediaType 候補 %r で復号成功", candidate)
            return result

        try:
            return session.decrypt(user_id, data)
        except Exception as e:
            last_error = e

        raise RuntimeError(f"DAVE decrypt 失敗: {last_error!r}")

    vc_cls.dave_is_active = dave_is_active
    vc_cls.dave_decrypt = dave_decrypt


_patch_voice_recv_client()


class GlobalAudioSink(voice_recv.AudioSink):
    def __init__(self, room_name: str, current_vc: voice_recv.VoiceRecvClient):
        super().__init__()
        self.room_name = room_name
        self.current_vc = current_vc
        self.decoders: dict[int, discord.opus.Decoder] = {}
        self.opus_available = discord.opus.is_loaded()
        self._warned_decrypt = False
        self._warned_decode = False
        if not self.opus_available:
            logger.warning("ルーム %s: libopus がロードされていません。音声を復号できません。", room_name)

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
        except Exception as e:
            if not self._warned_decrypt:
                self._warned_decrypt = True
                logger.warning("ルーム %s: DAVE復号に失敗しました (以後は debug ログのみ出力): %r", self.room_name, e)
            else:
                logger.debug("ルーム %s: DAVE復号失敗: %r", self.room_name, e)
            return

        if not payload or not self.opus_available:
            return

        decoder = self.decoders.get(user_id)
        if decoder is None:
            decoder = discord.opus.Decoder()
            self.decoders[user_id] = decoder

        try:
            pcm = decoder.decode(payload, fec=False)
        except discord.opus.OpusError as e:
            if not self._warned_decode:
                self._warned_decode = True
                logger.warning("ルーム %s: Opusデコードに失敗しました (以後は debug ログのみ出力): %r", self.room_name, e)
            else:
                logger.debug("ルーム %s: Opusデコード失敗: %r", self.room_name, e)
            return

        # 復号されたPCM音声を他サーバーの送信ストリームに流す
        if pcm and self.room_name in GLOBAL_ROOMS:
            for vc in GLOBAL_ROOMS[self.room_name]:
                if vc != self.current_vc and vc.is_connected():
                    source = getattr(vc, "global_source", None)
                    if source:
                        source.write_pcm(pcm)

    def cleanup(self) -> None:
        self.decoders.clear()


class GlobalAudioSource(discord.AudioSource):
    """他サーバーから届いたPCM音声を自サーバーVCに再生するSource"""

    def __init__(self):
        # 固定長フレームの deque を使うことで、bytearray の毎回 del によるO(n)シフトを避ける
        self._frames: collections.deque[bytes] = collections.deque(maxlen=MAX_BUFFER_FRAMES)
        self._pending = bytearray()  # FRAME_BYTE_SIZE 未満の端数
        self._lock = threading.Lock()

    def write_pcm(self, pcm: bytes):
        with self._lock:
            self._pending.extend(pcm)
            while len(self._pending) >= FRAME_BYTE_SIZE:
                frame = bytes(self._pending[:FRAME_BYTE_SIZE])
                del self._pending[:FRAME_BYTE_SIZE]
                # maxlen を超えたら古いフレームから自動的に破棄され、遅延が蓄積しない
                self._frames.append(frame)

    def read(self) -> bytes:
        with self._lock:
            if self._frames:
                return self._frames.popleft()
        # バッファに音声がないときは無音 (PCM 0埋め) パケットを返す
        return b"\x00" * FRAME_BYTE_SIZE

    def is_opus(self) -> bool:
        return False


# ============================================================
# ルームオプション (gvc create で指定するフラグ)
# ============================================================
class RoomOptions(commands.FlagConverter, prefix="--", delimiter=" ", case_insensitive=True):
    max: int = commands.flag(default=0, description="最大参加サーバー数 (0=無制限)")
    private: bool = commands.flag(default=False, description="非公開ルームにする (参加時にパスワードが必要)")
    password: str = commands.flag(default="", description="非公開ルームのパスワード")
    desc: str = commands.flag(default="", description="ルームの説明")


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
            f"`{ctx.prefix}gvc create <ルーム名> [--max 5] [--private] [--password xxxx] [--desc 説明]` "
            f": 新しいルームを作成\n"
            f"`{ctx.prefix}gvc join <ルーム名> [パスワード]` : 指定したルームに参加 (要ボイスチャンネル在室)\n"
            f"`{ctx.prefix}gvc list` : ルーム一覧を表示\n"
            f"`{ctx.prefix}gvc info <ルーム名>` : ルームの詳細設定を表示\n"
            f"`{ctx.prefix}gvc delete <ルーム名>` : ルームを削除 (作成者のみ)\n"
            f"`{ctx.prefix}gvc leave` : グローバルVCから離脱 (ルーム自体は残ります)\n"
            f"`{ctx.prefix}gvc chat connect <ルーム名> [パスワード]` : このチャンネルをグロチャに接続\n"
            f"`{ctx.prefix}gvc chat disconnect` : このチャンネルのグロチャ接続を解除\n\n"
            f"ルーム名にスペースを含める場合は `\"\"` で囲んでください。"
        )
        await ctx.send(embed=embed)

    @gvc_group.command(name="create")
    async def gvc_create(self, ctx: commands.Context, room_name: str, *, options: RoomOptions = None):
        # フラグが一切指定されなかった場合、discord.py は空文字列を RoomOptions に変換して
        # 各フラグのデフォルト値を持つインスタンスを渡してくる。念のため None の場合の保険も入れる。
        if room_name in ROOMS:
            return await ctx.send(f"⚠️ ルーム **{room_name}** はすでに存在します。")

        max_servers = options.max if options else 0
        private = options.private if options else False
        password = options.password if options else ""
        description = options.desc if options else ""

        if private and not password:
            return await ctx.send("⚠️ 非公開ルームにする場合は `--password` でパスワードを指定してください。")
        if max_servers < 0:
            return await ctx.send("⚠️ `--max` は 0 以上の値を指定してください。")

        ROOMS[room_name] = RoomConfig(
            name=room_name,
            owner_id=ctx.author.id,
            owner_guild_id=ctx.guild.id,
            max_servers=max_servers,
            private=private,
            password=password,
            description=description,
        )

        embed = discord.Embed(title=f"🌐 ルーム **{room_name}** を作成しました", color=0x2ECC71)
        embed.add_field(name="最大参加サーバー数", value="無制限" if max_servers == 0 else str(max_servers))
        embed.add_field(name="公開設定", value="🔒 非公開" if private else "🌍 公開")
        if description:
            embed.add_field(name="説明", value=description, inline=False)
        embed.set_footer(text=f"{ctx.prefix}gvc join {room_name} で参加できます")
        await ctx.send(embed=embed)

    @gvc_group.command(name="join")
    async def gvc_join(self, ctx: commands.Context, room_name: str, password: str = None):
        if not ctx.author.voice or not ctx.author.voice.channel:
            return await ctx.send("⚠️ ボイスチャンネルに参加してから実行してください。")

        room = ROOMS.get(room_name)
        if room is None:
            return await ctx.send(
                f"❌ ルーム **{room_name}** は存在しません。"
                f"先に `{ctx.prefix}gvc create {room_name}` で作成してください。"
            )

        if room.private and password != room.password:
            return await ctx.send("🔒 このルームは非公開です。正しいパスワードを指定してください。")

        current_members = GLOBAL_ROOMS.get(room_name, [])
        if room.max_servers and len(current_members) >= room.max_servers:
            return await ctx.send(f"⚠️ ルーム **{room_name}** は満員です ({room.max_servers}サーバーまで)。")

        if any(vc.guild and vc.guild.id == ctx.guild.id for vc in current_members):
            return await ctx.send(f"⚠️ このサーバーはすでにルーム **{room_name}** に参加しています。")

        vc_channel = ctx.author.voice.channel

        if ctx.voice_client is not None:
            # 既存の接続を正しくルーム管理から除去してから切断する
            # (元のコードはここで disconnect のみ行い GLOBAL_ROOMS に古い参照が残るバグがあった)
            await _disconnect_and_cleanup(ctx.voice_client)
            await asyncio.sleep(0.5)

        try:
            vc = await vc_channel.connect(
                cls=voice_recv.VoiceRecvClient,
                timeout=30.0,
                reconnect=True,
                self_deaf=False,
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

    @gvc_group.command(name="list")
    async def gvc_list(self, ctx: commands.Context):
        if not ROOMS:
            return await ctx.send("現在作成されているグローバルVCルームはありません。")

        embed = discord.Embed(title="🌐 ルーム一覧", color=0x2ECC71)
        for room_name, room in ROOMS.items():
            clients = GLOBAL_ROOMS.get(room_name, [])
            servers = [vc.guild.name for vc in clients if vc.guild]
            lock = "🔒" if room.private else "🌍"
            cap = "無制限" if room.max_servers == 0 else f"{len(servers)}/{room.max_servers}"
            chat_count = len(ROOM_TEXT_LINKS.get(room_name, []))
            value = f"{lock} VC参加サーバー数: {cap} / グロチャ接続数: {chat_count}"
            if servers:
                value += f"\n接続中: {', '.join(servers)}"
            if room.description:
                value += f"\n説明: {room.description}"
            embed.add_field(name=f"🎙️ {room_name}", value=value, inline=False)
        await ctx.send(embed=embed)

    @gvc_group.command(name="info")
    async def gvc_info(self, ctx: commands.Context, room_name: str):
        room = ROOMS.get(room_name)
        if room is None:
            return await ctx.send(f"❌ ルーム **{room_name}** は存在しません。")

        clients = GLOBAL_ROOMS.get(room_name, [])
        servers = [vc.guild.name for vc in clients if vc.guild]

        text_links = ROOM_TEXT_LINKS.get(room_name, [])
        chat_channels = []
        for link in text_links:
            channel = self.bot.get_channel(link.channel_id)
            if channel:
                chat_channels.append(f"#{channel.name} ({channel.guild.name})")

        embed = discord.Embed(title=f"🌐 ルーム情報: {room_name}", color=0x3498DB)
        embed.add_field(name="公開設定", value="🔒 非公開" if room.private else "🌍 公開")
        embed.add_field(name="最大参加サーバー数", value="無制限" if room.max_servers == 0 else str(room.max_servers))
        embed.add_field(name="現在の参加サーバー数(VC)", value=str(len(servers)))
        if servers:
            embed.add_field(name="接続中のサーバー(VC)", value=", ".join(servers), inline=False)
        embed.add_field(name="グロチャ接続数", value=str(len(chat_channels)))
        if chat_channels:
            embed.add_field(name="グロチャ接続チャンネル", value="\n".join(chat_channels), inline=False)
        if room.description:
            embed.add_field(name="説明", value=room.description, inline=False)
        embed.add_field(name="作成日時", value=f"<t:{int(room.created_at)}:R>", inline=False)
        await ctx.send(embed=embed)

    @gvc_group.command(name="delete")
    async def gvc_delete(self, ctx: commands.Context, room_name: str):
        room = ROOMS.get(room_name)
        if room is None:
            return await ctx.send(f"❌ ルーム **{room_name}** は存在しません。")

        is_owner = ctx.author.id == room.owner_id
        has_perm = ctx.author.guild_permissions.manage_guild if ctx.guild else False
        if not (is_owner or has_perm):
            return await ctx.send("⚠️ このルームを削除できるのは作成者、またはサーバー管理権限を持つユーザーのみです。")

        for vc in list(GLOBAL_ROOMS.get(room_name, [])):
            await _disconnect_and_cleanup(vc)

        for link in list(ROOM_TEXT_LINKS.get(room_name, [])):
            await _remove_text_link(link.channel_id)

        GLOBAL_ROOMS.pop(room_name, None)
        ROOM_TEXT_LINKS.pop(room_name, None)
        del ROOMS[room_name]
        await ctx.send(f"🗑️ ルーム **{room_name}** を削除しました (VC・グロチャの連携もすべて解除)。")

    @gvc_group.command(name="leave")
    async def gvc_leave(self, ctx: commands.Context):
        vc = ctx.voice_client
        if not vc:
            return await ctx.send("現在ボイスチャンネルに接続していません。")

        await _disconnect_and_cleanup(vc)
        await ctx.send("🌐 グローバルVCから切断しました。ルーム自体は残っています。")

    # ------------------------------------------------------------
    # グロチャ (テキストチャット連携)
    # ------------------------------------------------------------
    @gvc_group.group(name="chat", invoke_without_command=True)
    async def gvc_chat_group(self, ctx: commands.Context):
        embed = discord.Embed(title="🌐 グロチャ コマンド一覧", color=0x3498DB)
        embed.description = (
            f"`{ctx.prefix}gvc chat connect <ルーム名> [パスワード]` : このチャンネルを指定ルームのグロチャに接続\n"
            f"`{ctx.prefix}gvc chat disconnect` : このチャンネルのグロチャ接続を解除"
        )
        await ctx.send(embed=embed)

    @gvc_chat_group.command(name="connect")
    async def gvc_chat_connect(self, ctx: commands.Context, room_name: str, password: str = None):
        room = ROOMS.get(room_name)
        if room is None:
            return await ctx.send(
                f"❌ ルーム **{room_name}** は存在しません。"
                f"先に `{ctx.prefix}gvc create {room_name}` で作成してください。"
            )

        if room.private and password != room.password:
            return await ctx.send("🔒 このルームは非公開です。正しいパスワードを指定してください。")

        if ctx.channel.id in CHANNEL_TO_ROOM:
            current_room = CHANNEL_TO_ROOM[ctx.channel.id]
            return await ctx.send(
                f"⚠️ このチャンネルはすでにルーム **{current_room}** のグロチャに接続されています。"
                f"先に `{ctx.prefix}gvc chat disconnect` してください。"
            )

        if any(link.guild_id == ctx.guild.id for link in ROOM_TEXT_LINKS.get(room_name, [])):
            return await ctx.send(f"⚠️ このサーバーはすでに別のチャンネルでルーム **{room_name}** のグロチャに接続済みです。")

        perms = ctx.channel.permissions_for(ctx.guild.me)
        if not perms.manage_webhooks:
            return await ctx.send("⚠️ このチャンネルで Webhook を管理する権限がボットにありません。")

        try:
            webhook = await ctx.channel.create_webhook(
                name=f"グロチャ: {room_name}", reason="グローバルチャット連携"
            )
        except Exception as e:
            return await ctx.send(f"❌ Webhook の作成に失敗しました: `{e}`")

        link = TextLink(guild_id=ctx.guild.id, channel_id=ctx.channel.id, webhook=webhook)
        ROOM_TEXT_LINKS.setdefault(room_name, []).append(link)
        CHANNEL_TO_ROOM[ctx.channel.id] = room_name

        await ctx.send(
            f"🌐 このチャンネルをルーム **{room_name}** のグロチャに接続しました！\n"
            f"以降、このチャンネルの発言は同ルームに接続中の他サーバーへ、送信者の名前とアイコンで中継されます。"
        )

    @gvc_chat_group.command(name="disconnect")
    async def gvc_chat_disconnect(self, ctx: commands.Context):
        room_name = await _remove_text_link(ctx.channel.id)
        if room_name is None:
            return await ctx.send("このチャンネルはグロチャに接続されていません。")
        await ctx.send(f"🌐 ルーム **{room_name}** のグロチャ接続を解除しました。")

    @commands.Cog.listener("on_message")
    async def on_message(self, message: discord.Message):
        # webhook からの中継メッセージ自身には反応しない (無限ループ防止)
        if message.webhook_id is not None:
            return
        if message.author.bot:
            return
        if not message.guild:
            return

        room_name = CHANNEL_TO_ROOM.get(message.channel.id)
        if room_name is None:
            return

        if not message.content and not message.attachments:
            return

        links = ROOM_TEXT_LINKS.get(room_name, [])
        if len(links) <= 1:
            return  # 他に接続チャンネルがなければ中継不要

        # 添付ファイルは一度だけ読み込み、送信先ごとに新しい File として使い回す
        # (discord.File は一度送信すると再利用できないため)
        attachment_payloads: list[tuple[bytes, str]] = []
        for attachment in message.attachments:
            try:
                data = await attachment.read()
                attachment_payloads.append((data, attachment.filename))
            except Exception:
                logger.debug("グロチャ: 添付ファイル取得失敗 (%s)", attachment.filename, exc_info=True)

        content = (message.content or "")[:2000]
        username = f"{message.author.display_name} [{message.guild.name}]"[:80] or "unknown"
        avatar_url = message.author.display_avatar.url

        for link in links:
            if link.channel_id == message.channel.id:
                continue

            files = [discord.File(io.BytesIO(data), filename=name) for data, name in attachment_payloads]
            try:
                await link.webhook.send(
                    content=content if content else None,
                    username=username,
                    avatar_url=avatar_url,
                    files=files if files else discord.utils.MISSING,
                    allowed_mentions=discord.AllowedMentions.none(),
                )
            except discord.NotFound:
                # webhook が手動で削除された等 -> このチャンネルの連携を自動解除
                logger.warning(
                    "ルーム %s: webhook が見つかりません。連携を解除します (channel_id=%s)",
                    room_name, link.channel_id,
                )
                await _remove_text_link(link.channel_id, delete_webhook=False)
            except Exception as e:
                logger.warning(
                    "ルーム %s: グロチャ中継に失敗しました (channel_id=%s): %r",
                    room_name, link.channel_id, e,
                )

    @commands.Cog.listener("on_guild_channel_delete")
    async def on_guild_channel_delete(self, channel: discord.abc.GuildChannel):
        if channel.id in CHANNEL_TO_ROOM:
            # チャンネル自体が消えているので webhook 削除は試みない
            await _remove_text_link(channel.id, delete_webhook=False)


async def setup(bot: commands.Bot):
    await bot.add_cog(GlobalVCCog(bot))
