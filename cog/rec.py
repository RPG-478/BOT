import discord
from discord import app_commands  # ← 追加
from discord.ext import commands
import asyncio
import time
import logging
import configparser
import string
import subprocess
import json
import io
import yt_dlp
import struct
import math  # 追加: Timerクラスのサイン波計算で必要
from discord.ext import voice_recv
import threading
import random
import numpy as np
from scipy import signal
import re
import aiohttp
import wave
import discord.opus
import sys

logger = logging.getLogger(__name__)

# ============================================================
# DAVE (Discord E2EE) 対応パッチ
# ============================================================
# 2026年3月1日以降、Discordはボイスチャンネルでの完全End-to-End暗号化
# (DAVEプロトコル)を必須化しました。discord.py はこれに対応済みですが、
# discord-ext-voice-recv (本コードが使用しているライブラリ) はまだ
# DAVEで暗号化されたOpusフレームの復号に対応しておらず、暗号化された
# ままのバイト列をそのままOpusとしてデコードしようとしてしまいます。
# これが「録音した音声がノイズにしか聞こえない」の直接の原因です。
# (voice_recv公式リポジトリでも既知の未解決issueとして報告されています:
#  https://github.com/imayhaveborkedit/discord-ext-voice-recv/issues/53 )
#
# 対処として、voice_recv標準のPCMデコード経路(wants_opus=False)を使わず、
# 生のOpusフレーム(まだDAVE暗号化されたまま)を受け取り、discord.py が
# 内部に保持しているDAVE復号セッション(VoiceClient._connection.dave_session)
# を直接呼び出して復号してからOpusデコードを行います。
#
# ⚠️ 注意: これは discord.py の非公開の内部実装(_connection.dave_session)
# に依存する非公式の回避策です。discord.py や davey パッケージの将来の
# バージョンアップで動作しなくなる可能性があります。voice_recv側の
# 正式な対応が入り次第、そちらに乗り換えることを推奨します。
# ============================================================


def _patch_voice_client_dave():
    """VoiceRecvClient に DAVE 復号用のヘルパーメソッドを追加する(冪等)"""
    vc_cls = voice_recv.VoiceRecvClient

    if getattr(vc_cls, '_dave_patch_applied', False):
        return
    vc_cls._dave_patch_applied = True

    def dave_decrypt(self, user_id: int, data: bytes):
        """
        DAVEセッションが有効な場合、暗号化されたOpusフレームを復号する。
        セッションが存在しない(DAVE未確立/移行期間中/Stageチャンネル等)場合は
        データをそのまま返す(=DAVEなしの従来どおりの平文Opusとして扱う)。
        """
        connection = getattr(self, '_connection', None)
        session = getattr(connection, 'dave_session', None) if connection else None
        if session is None:
            return data

        # MediaType Enum の所在はライブラリ実装依存のため、
        # dave_session が定義されているモジュールから動的に取得する
        mod = sys.modules.get(type(session).__module__)
        media_type_cls = getattr(mod, 'MediaType', None)
        media_type = getattr(media_type_cls, 'audio', 0) if media_type_cls else 0

        return session.decrypt(user_id, media_type, data)

    def dave_is_active(self) -> bool:
        connection = getattr(self, '_connection', None)
        session = getattr(connection, 'dave_session', None) if connection else None
        return session is not None

    vc_cls.dave_decrypt = dave_decrypt
    vc_cls.dave_is_active = dave_is_active


_patch_voice_client_dave()

# 48kHz / 2ch / 16bit の1秒あたりのバイト数（無音補正の計算に使用）
BYTES_PER_SECOND = 48000 * 2 * 2
# フレーム単位(1サンプルフレーム = 2ch * 2byte = 4byte)
FRAME_SIZE = 4
# 無音ギャップが異常に長くなった場合(切断・長時間退席など)にファイルが
# 膨張しすぎないよう上限を設ける
MAX_GAP_SECONDS = 10


class AudioSink(voice_recv.AudioSink):
    def __init__(self, bot, vc, update_callback=None):
        super().__init__()
        self.bot = bot
        self.vc = vc  # DAVE復号のためVoiceRecvClientへの参照を保持
        self.buffers = {}
        self.user_start_time = {}  # ユーザーごとの録音開始時刻(壁時計基準)
        # Opusはステートフル(フレーム間の予測)なコーデックのため、
        # ユーザー(SSRC)ごとにデコーダーインスタンスを使い回して継続性を保つ
        self.decoders = {}
        self.packet_count = 0
        self.update_callback = update_callback
        self.last_update_time = 0

        # --- 診断用カウンタ ---
        self.write_call_count = 0
        self.dave_error_count = 0
        self.opus_error_count = 0
        self.total_frame_count = 0

    def wants_opus(self) -> bool:
        # voice_recv標準のPCMデコード経路(DAVE非対応)は使わず、
        # 生のOpusフレームを受け取って自前で DAVE復号 → Opusデコードする
        return True

    def write(self, user, data: voice_recv.VoiceData):
        try:
            self._write_inner(user, data)
        except Exception as e:
            # ここに来る例外は DAVE復号/Opusデコード以外の想定外のバグ。
            # voice_recv 側が write() の例外を握りつぶすことがあるため、
            # 必ず自分でログに出して見えるようにしておく。
            logger.error(f"[REC] AudioSink.write() で予期せぬエラー: {e!r}", exc_info=True)

    def _write_inner(self, user, data: voice_recv.VoiceData):
        # write() が実際に呼ばれているかどうかを独立してカウント
        # (opusデータの有無に関わらず、呼び出された時点でカウントする)
        self.write_call_count += 1

        raw_opus = getattr(data, 'opus', None)
        if not raw_opus:
            return

        if user is not None:
            user_key = f"{user.name}_{user.id}"
            user_id = user.id
        elif hasattr(data, 'ssrc') and data.ssrc:
            user_key = f"Speaker_{data.ssrc}"
            user_id = data.ssrc
        else:
            user_key = "Unknown_Speaker"
            user_id = 0

        self.total_frame_count += 1

        # --- 1. DAVE(E2EE)復号 ---
        try:
            payload = self.vc.dave_decrypt(user_id, bytes(raw_opus))
        except Exception as e:
            self.dave_error_count += 1
            if self.dave_error_count <= 3:
                # logger設定(ハンドラ未設定/レベル抑制)に依存せず、
                # 確実にコンソールへ出すため print + traceback を使う
                import traceback
                print(f"[REC-DEBUG] DAVE decrypt failed for {user_key}: {e!r}", flush=True)
                traceback.print_exc()
            return

        # --- 2. Opusデコード(ユーザーごとにデコーダーを使い回す) ---
        if user_key not in self.decoders:
            self.decoders[user_key] = discord.opus.Decoder()
        try:
            pcm = self.decoders[user_key].decode(payload, fec=False)
        except discord.opus.OpusError as e:
            self.opus_error_count += 1
            logger.debug(f"Opus decode skipped corrupted packet: {e}")
            return

        if not pcm:
            return

        now = time.time()
        if user_key not in self.buffers:
            self.buffers[user_key] = bytearray()
            self.user_start_time[user_key] = now

        # --- 3. 無音区間のゼロ埋め補正 ---
        # Discordは無音区間(VAD/DTX)ではパケットを送信しないため、
        # 受信したPCMをただ連結するだけだと発話同士が押し詰められて
        # しまう。壁時計を基準に本来あるべきバッファ長を計算し、
        # 不足分を無音(ゼロ)で埋めてから新しいPCMを追加する。
        elapsed = now - self.user_start_time[user_key]
        expected_len = int(elapsed * BYTES_PER_SECOND)
        expected_len -= expected_len % FRAME_SIZE

        current_len = len(self.buffers[user_key])
        if expected_len > current_len:
            gap = expected_len - current_len
            max_gap_bytes = int(MAX_GAP_SECONDS * BYTES_PER_SECOND)
            if gap > max_gap_bytes:
                gap = max_gap_bytes
                self.user_start_time[user_key] = now - (current_len + gap) / BYTES_PER_SECOND
            self.buffers[user_key].extend(b'\x00' * gap)

        self.buffers[user_key].extend(pcm)
        self.packet_count += 1

        # 3秒以上経過した場合のみメッセージ編集を呼び出す（レートリミット回避）
        if now - self.last_update_time >= 3.0 and self.update_callback:
            self.last_update_time = now
            asyncio.run_coroutine_threadsafe(
                self.update_callback(self.packet_count),
                self.bot.loop
            )

    def cleanup(self):
        # 注意: voice_recv は listen 終了時にこの cleanup() を
        # ファイナライザとして自動的に呼び出す(AudioSource.cleanup()と同様の仕様)。
        # そのため stop_listening() を呼んだ後では buffers はすでに空になっている。
        self.buffers.clear()
        self.user_start_time.clear()
        self.decoders.clear()


class RecordingCog(commands.Cog):
    """
    ボイスチャンネル録音機能を管理するCog（! プレフィックスコマンド版）
    """
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    def get_state(self, guild_id: int) -> dict:
        """
        メインCog/Bot側の get_state と互換性を持つステート管理
        """
        if hasattr(self.bot, 'get_state'):
            return self.bot.get_state(guild_id)

        if not hasattr(self.bot, 'states'):
            self.bot.states = {}
        if guild_id not in self.bot.states:
            self.bot.states[guild_id] = {
                'queue': None,
                'current_ctx': None,
                'is_processing_queue': False,
                'current_track': None,
                'start_time': 0,
                'elapsed_offset': 0,
                'retry_count': 0,
                'volume': 1.0,
                'speed': 1.0,
                'eq': 'flat',
                'custom_eq_filter': None,
                'is_paused': False,
                'is_changing_setting': False,
                'panel_message': None,
                # --- 録音用ステート ---
                'is_recording': False,
                'rec_start_time': 0,
                'sink': None
            }
        return self.bot.states[guild_id]

    # --------------------------------------------------
    # コマンドグループ: !rec [start|stop|status]
    # --------------------------------------------------
    @commands.group(name="rec", invoke_without_command=True)
    async def rec_group(self, ctx: commands.Context):
        """!rec 単体で実行された場合はステータスを表示"""
        await self.rec_status(ctx)

    @rec_group.command(name="start")
    async def rec_start(self, ctx: commands.Context):
        """!rec start : 録音を開始"""
        if not ctx.author.voice or not ctx.author.voice.channel:
            return await ctx.send(embed=we("⚠️ ボイスチャンネルに参加してから実行してください。"))

        target_channel = ctx.author.voice.channel
        guild_id = ctx.guild.id
        state = self.get_state(guild_id)
        vc = ctx.voice_client

        if state.get('is_recording'):
            return await ctx.send(embed=we("⚠️ 既にこのサーバーで録音処理が実行中です。"))

        # VC接続の制御
        try:
            if vc is None:
                vc = await target_channel.connect(cls=voice_recv.VoiceRecvClient)
            elif not isinstance(vc, voice_recv.VoiceRecvClient):
                await vc.disconnect(force=True)
                vc = await target_channel.connect(cls=voice_recv.VoiceRecvClient)
            elif vc.channel != target_channel:
                await vc.move_to(target_channel)
        except Exception as e:
            return await ctx.send(embed=we(f"❌ ボイスチャンネルへの接続に失敗しました: `{e}`"))

        # --- 診断: 暗号化モード・DAVE(E2EE)有効状況をログ出力 ---
        negotiated_mode = getattr(vc, 'mode', '不明')
        # DAVEセッションの確立には少し時間がかかることがあるため少し待ってから確認
        await asyncio.sleep(1.0)
        dave_active = vc.dave_is_active() if hasattr(vc, 'dave_is_active') else False
        logger.info(f"[REC] Voice encryption mode: {negotiated_mode} / DAVE(E2EE) active: {dave_active}")

        # 最初のお知らせメッセージを送信（これを後で編集します）
        status_msg = await ctx.send(
            embed=we(f"🎙️ **{target_channel.name}** で録音を開始しました。\n"
                     f"🔐 暗号化モード: `{negotiated_mode}` / DAVE(E2EE): `{'有効' if dave_active else '無効'}`\n"
                     f"📦 受信パケット数: `0` 個\n"
                     f"停止するには `!rec stop` を実行してください。")
        )

        # 一定時間(3秒)ごとにメッセージを更新する非同期関数(レートリミット回避)
        async def on_packet_update(count: int):
            try:
                # パケット数に応じてアイコンを交互に変更させて動作中であることを分かりやすく表現
                indicator = "🔴 録音中..." if (count // 10) % 2 == 0 else "⭕ 録音中..."
                await status_msg.edit(
                    embed=we(f"{indicator}\n"
                             f"🎙️ チャンネル: **{target_channel.name}**\n"
                             f"📦 受信パケット数: `{count}` 個")
                )
            except Exception:
                pass  # メッセージ削除時などのエラー対策

        # Sink に bot / vc とコールバックを渡して開始
        sink = AudioSink(bot=self.bot, vc=vc, update_callback=on_packet_update)
        vc.listen(sink)

        # ステート更新
        state['is_recording'] = True
        state['rec_start_time'] = time.time()
        state['sink'] = sink
        state['status_msg'] = status_msg
        # ※ 開始通知は status_msg 1通のみ。以前あった重複送信(2通目)は削除しました。

    @rec_group.command(name="stop")
    async def rec_stop(self, ctx: commands.Context):
        """!rec stop : 録音を停止してWAVファイルを送信"""
        guild_id = ctx.guild.id
        state = self.get_state(guild_id)
        vc = ctx.voice_client
        sink: AudioSink = state.get('sink')

        if not state.get('is_recording') or not vc or not isinstance(vc, voice_recv.VoiceRecvClient) or not sink:
            return await ctx.send(embed=we("⚠️ 現在録音は行われていません。"))

        # ★最重要修正★
        # voice_recv は stop_listening() (リスニング終了)のタイミングで
        # sink.cleanup() をファイナライザとして自動的に呼び出す仕様のため、
        # 何もしないと stop_listening() 実行後には sink.buffers が
        # 空になってしまう。そのため「停止処理を呼ぶ前」に
        # 録音データを別変数へ複製(退避)しておく。
        captured_buffers = {key: bytes(pcm) for key, pcm in sink.buffers.items()}
        captured_packet_count = sink.packet_count
        # 診断用カウンタも退避
        write_calls = sink.write_call_count
        dave_errors = sink.dave_error_count
        opus_errors = sink.opus_error_count
        total_frames = sink.total_frame_count

        # 1. 録音停止
        try:
            vc.stop_listening()
        except Exception as e:
            logger.error(f"Stop listening error: {e}")

        # 明示的にもクリーンアップを呼んでおく(ライブラリ側で既に呼ばれていても
        # self.buffers.clear() は冪等なので二重に呼んでも問題ない)
        try:
            sink.cleanup()
        except Exception:
            pass

        # ステートの解除
        state['is_recording'] = False
        state['sink'] = None

        # --- 診断結果を表示 ---
        dave_rate = (dave_errors / total_frames * 100) if total_frames else 0
        opus_rate = (opus_errors / total_frames * 100) if total_frames else 0
        await ctx.send(embed=we(
            "💾 録音を停止しました。ファイルを生成中です...\n"
            f"🩺 診断: write()呼び出し `{write_calls}` / 総フレーム(opusあり) `{total_frames}` / "
            f"DAVE復号失敗 `{dave_errors}` (`{dave_rate:.1f}%`) "
            f"/ Opusデコード失敗 `{opus_errors}` (`{opus_rate:.1f}%`)"
        ))

        # 2. データの存在確認
        if not captured_buffers:
            return await ctx.send(embed=we(
                f"❌ 音声バッファが空でした。（発言が検知されなかったかパケットが届いていません。受信パケット数: `{captured_packet_count}`）"
            ))

        files_to_send = []

        # 3. ユーザー/SSRCごとにWAV化
        for user_key, pcm_data in captured_buffers.items():
            # あまりにデータが短い場合（1920バイト未満）はノイズとみなしてスキップ
            if len(pcm_data) < 1920:
                continue

            wav_buf = io.BytesIO()
            with wave.open(wav_buf, 'wb') as wf:
                wf.setnchannels(2)        # 2ch ステレオ
                wf.setsampwidth(2)        # 16-bit (2 byte)
                wf.setframerate(48000)    # 48kHz
                wf.writeframes(pcm_data)

            wav_buf.seek(0)

            # ファイル名に使えない記号を除去しておく(念のため)
            safe_key = re.sub(r'[\\/*?:"<>|]', '_', user_key)
            file_item = discord.File(
                fp=wav_buf,
                filename=f"rec_{safe_key}_{int(time.time())}.wav"
            )
            files_to_send.append(file_item)

        if not files_to_send:
            return await ctx.send(embed=we("⚠️ 送信可能な長さの録音データがありませんでした。"))

        # 4. 添付ファイル上限(10個ずつ)に分けて送信
        #    ※ 以前あった「未定義の chunk_idx を使った二重送信」のバグを削除・修正済み
        for i in range(0, len(files_to_send), 10):
            chunk = files_to_send[i:i + 10]
            await ctx.send(
                content=f"🎵 **録音データ出力 ({i + 1}〜{i + len(chunk)}件)**",
                files=chunk
            )

    @rec_group.command(name="status")
    async def rec_status(self, ctx: commands.Context):
        """!rec status : 現在の録音状況を確認します"""
        guild_id = ctx.guild.id
        state = self.get_state(guild_id)
        is_rec = state.get('is_recording', False)

        if is_rec:
            elapsed = int(time.time() - state.get('rec_start_time', time.time()))
            m, s = divmod(elapsed, 60)
            h, m = divmod(m, 60)
            time_str = f"{h:02d}:{m:02d}:{s:02d}" if h > 0 else f"{m:02d}:{s:02d}"

            embed = discord.Embed(
                title="🎙️ 録音中",
                description=f"現在の経過時間: **{time_str}**",
                color=0x2ECC71
            )
        else:
            embed = discord.Embed(
                title="⏸️ 待機中",
                description="現在このサーバーで録音は行われていません。",
                color=0x95A5A6
            )

        await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(RecordingCog(bot))
