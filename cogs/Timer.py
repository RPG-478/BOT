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


# =====================
# Timer Cog
# =====================
class Timer(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.active_timers = {}
        self.ambient_running = {}
        self.sample_rate = 48000
        self.work_stats = {}  

    def format_time(self, seconds: int) -> str:
        m, s = divmod(seconds, 60)
        h, m = divmod(m, 60)
        return f"{h:02d}:{m:02d}:{s:02d}" if h > 0 else f"{m:02d}:{s:02d}"

    async def notify_triple(self, ctx, text: str):
        """通知音（Beep）を3回生成して再生"""
        await ctx.send(embed=we(description=f"🔔 **{text}**"))
        if ctx.voice_client:
            samples = int(self.sample_rate * 0.15)
            beep = bytearray()
            for i in range(samples):
                v = int(32767.0 * math.sin(2.0 * math.pi * 880.0 * i / self.sample_rate))
                beep.extend(struct.pack('<hh', v, v)) 
            
            for _ in range(3):
                if ctx.voice_client:
                    source = discord.PCMAudio(io.BytesIO(bytes(beep)))
                    ctx.voice_client.play(source)
                await asyncio.sleep(0.3)

    @commands.command()
    async def ambient(self, ctx):
        """ブラウンノイズを生成して再生"""
        if not ctx.voice_client:
            return await ctx.send("先に !join してください。")

        if ctx.voice_client.is_playing():
            ctx.voice_client.stop()
        
        ctx.voice_client.play(await discord.FFmpegOpusAudio.from_probe('anoisesrc=d=0:c=brown:r=48000:a=0.5,pan=stereo|c0=c0|c1=c0', method='fallback', before_options='-f lavfi'))
        await ctx.send(embed=we("🌊 FFmpeg純正機能でブラウンノイズを再生中..."))

    @commands.command()
    async def pomo(self, ctx, work: int = 25, rest: int = 5):
        """ポモドーロ開始"""
        guild_id = ctx.guild.id
        if guild_id in self.active_timers:
            return await ctx.send("既にタイマーが稼働中です。")

        async def pomodoro_loop():
            try:
                while True:
                    await self.notify_triple(ctx, f"作業開始！ ({work}分間)")
                    await asyncio.sleep(work * 60)
                    await self.notify_triple(ctx, f"休憩時間です！ ({rest}分間)")
                    await asyncio.sleep(rest * 60)
            except asyncio.CancelledError:
                pass

        self.active_timers[guild_id] = self.bot.loop.create_task(pomodoro_loop())
        await ctx.send(embed=we(f"⏳ ポモドーロを開始しました。"))

    @commands.command()
    async def stop_pomo(self, ctx):
        """タイマーと環境音をすべて停止"""
        task = self.active_timers.pop(ctx.guild.id, None)
        if task: task.cancel()
        if ctx.voice_client: ctx.voice_client.stop()
        await ctx.send(embed=we("すべての機能を停止しました。"))
        
    @commands.command()
    async def work_start(self, ctx):
        """作業計測開始"""
        uid = ctx.author.id
        if uid not in self.work_stats:
            self.work_stats[uid] = {'total_seconds': 0}
        self.work_stats[uid]['last_start'] = time.time()
        await ctx.send(embed=we(f"📝 {ctx.author.display_name} さんの作業計測を開始しました。"))

    @commands.command()
    async def work_end(self, ctx):
        """作業計測終了"""
        uid = ctx.author.id
        if uid not in self.work_stats or 'last_start' not in self.work_stats[uid]:
            return await ctx.send("計測が開始されていません。")

        elapsed = int(time.time() - self.work_stats[uid]['last_start'])
        self.work_stats[uid]['total_seconds'] += elapsed
        del self.work_stats[uid]['last_start']

        await ctx.send(embed=we(
            title="計測終了",
            description=f"今回の作業: `{self.format_time(elapsed)}` / 累計: `{self.format_time(self.work_stats[uid]['total_seconds'])}`"
        ))

    @commands.command()
    async def stats(self, ctx):
        """現在の累計作業時間を表示"""
        uid = ctx.author.id
        data = self.work_stats.get(uid, {'total_seconds': 0})
        total_str = self.format_time(data['total_seconds'])
        
        status = " (現在計測中)" if 'last_start' in data else ""
        await ctx.send(embed=we(f"📊 {ctx.author.display_name} さんの累計作業時間: `{total_str}`{status}"))
