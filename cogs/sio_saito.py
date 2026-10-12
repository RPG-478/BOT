# =====================
# SaitoRelay Cog (通話系)
# =====================

import discord
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
import numpy as np


from core.voice_session import VoiceBusy, get_manager


class _RelaySink(voice_recv.AudioSink):
    """受け取った音声 (Opus) をそのまま相手サーバーの VC へ送る。"""

    def __init__(self, dest_vc):
        super().__init__()
        self.dest_vc = dest_vc

    def wants_opus(self) -> bool:
        return True

    def write(self, user, data: voice_recv.VoiceData):
        if self.dest_vc and self.dest_vc.is_connected():
            try:
                self.dest_vc.send_audio_packet(data.data)
            except Exception:
                pass

    def cleanup(self):
        self.dest_vc = None


class SaitoRelay(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.matching_queue = []
        self.voice_sessions = get_manager(bot)
        # 通話中のサーバー同士: { guild_id: 相手の guild_id }
        self.peers: dict[int, int] = {}

    def _cleanup(self, guild_id: int, channel):
        """片方が終わったら（停止・自動退出・外部切断）、相手側も終了する。"""
        def cleanup(reason: str) -> None:
            vc = getattr(channel.guild, "voice_client", None) if channel is not None else None
            if vc is not None:
                try:
                    vc.stop_listening()
                except Exception:
                    pass
            peer_id = self.peers.pop(guild_id, None)
            if peer_id is None:
                return
            self.peers.pop(peer_id, None)
            # 相手サーバーのロックは別なので、タスクにして解放する（同じサーバーの release は待たない）。
            asyncio.get_running_loop().create_task(self.voice_sessions.release(
                peer_id, "match", reason="peer_left", notice="📴 相手のサーバーが通話を終了しました。",
            ))
        return cleanup

    @commands.command()
    async def saito(self, ctx):
        """音声中継マッチング (エンコーダー強制初期化版)"""
        if not ctx.author.voice:
            return await ctx.send("VCに参加してから実行してください。")

        busy = self.voice_sessions.get(ctx.guild.id)
        if busy is not None:
            return await ctx.send(self.voice_sessions.busy_message(busy))
        if ctx.voice_client:
            return await ctx.send("このサーバーでは既に接続中です。")

        # 同じサーバーの古い待ちと、もう VC にいない人の待ちを取り除く
        self.matching_queue = [
            c for c in self.matching_queue
            if c.guild.id != ctx.guild.id and getattr(c.author, "voice", None) and c.author.voice.channel
        ]

        target_peer = None
        for i, peer in enumerate(self.matching_queue):
            if peer.guild.id != ctx.guild.id:
                target_peer = self.matching_queue.pop(i)
                break
        
        if not target_peer:
            self.matching_queue.append(ctx)
            return await ctx.send(f"🔎 相手を探しています... ({ctx.guild.name})")

        await ctx.send(f"🤝 **{target_peer.guild.name}** と接続中...")
        await target_peer.send(f"🤝 **{ctx.guild.name}** と接続中...")

        acquired = []
        try:
            vc1 = await self.voice_sessions.acquire(
                ctx.guild, ctx.author.voice.channel, "match", ctx.author,
                cleanup=self._cleanup(ctx.guild.id, ctx.channel), text_channel=ctx.channel,
            )
            acquired.append(ctx.guild.id)
            vc2 = await self.voice_sessions.acquire(
                target_peer.guild, target_peer.author.voice.channel, "match", target_peer.author,
                cleanup=self._cleanup(target_peer.guild.id, target_peer.channel), text_channel=target_peer.channel,
            )
            acquired.append(target_peer.guild.id)
            self.peers[ctx.guild.id] = target_peer.guild.id
            self.peers[target_peer.guild.id] = ctx.guild.id

            silence_src1 = discord.FFmpegPCMAudio("/dev/null") 
            silence_src2 = discord.FFmpegPCMAudio("/dev/null")
            vc1.play(silence_src1)
            vc2.play(silence_src2)

            vc1.listen(_RelaySink(vc2))
            vc2.listen(_RelaySink(vc1))

            await ctx.send("🎙️ 通話を開始しました。")
            await target_peer.send("🎙️ 通話を開始しました。")

        except VoiceBusy as busy:
            # 待っている間に相手サーバーで別の機能が始まった
            for guild_id in acquired:
                self.peers.pop(guild_id, None)
                await self.voice_sessions.release(guild_id, "match", reason="stop")
            await ctx.send("⚠️ 相手のサーバーで別の機能が始まったため、通話できませんでした。もう一度お試しください。")
            await target_peer.send(str(busy))
        except Exception as e:
            logging.error(f"Saito Match Error: {e}")
            for guild_id in acquired:
                self.peers.pop(guild_id, None)
                await self.voice_sessions.release(guild_id, "match", reason="stop")
            await ctx.send("❌ 通話の接続に失敗しました。")

    @commands.command()
    async def saito_stop(self, ctx):
        if await self.voice_sessions.release(ctx.guild.id, "match", reason="stop"):
            return await ctx.send("通話を終了しました。")
        before = len(self.matching_queue)
        self.matching_queue = [c for c in self.matching_queue if c.guild.id != ctx.guild.id]
        if len(self.matching_queue) != before:
            await ctx.send("相手探しを取り消しました。")

async def setup(bot):
    await bot.add_cog(SaitoRelay(bot))


