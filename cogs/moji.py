import discord
from discord.ext import commands
from discord import app_commands
from discord.ext import voice_recv
import speech_recognition as sr
import asyncio
import io
import wave
import time
import struct
import math

# ----------------------------------------------------
# 1. 音声受信・雑音カット・文字起こし用Sink
# ----------------------------------------------------
class SpeechToTextSink(voice_recv.AudioSink):
    def __init__(self, bot, text_channel_id, threshold=800):
        self.bot = bot
        self.channel_id = text_channel_id
        self.threshold = threshold  # 雑音カットの音量しきい値
        self.buffers = {}
        self.last_spoken = {}
        self.active_users = set()
        self.recognizer = sr.Recognizer()
        self.webhook = None  # Webhookのキャッシュ用
        
        self.SILENCE_TIMEOUT = 0.8  # 無音と判定する時間（秒）
        self.monitor_task = asyncio.create_task(self.monitor_silence())

    def calculate_rms(self, pcm_data):
        """PCMデータの音量（RMS）を計算"""
        count = len(pcm_data) // 2
        if count == 0:
            return 0
        shorts = struct.unpack(f"{count}h", pcm_data)
        sum_squares = sum(s * s for s in shorts)
        return math.sqrt(sum_squares / count)

    def write(self, user, data):
        if user is None:
            return
        
        # 雑音処理：計算した音量が設定値未満なら録音しない
        if self.calculate_rms(data.pcm) < self.threshold:
            return
        
        user_id = user.id
        if user_id not in self.buffers:
            self.buffers[user_id] = io.BytesIO()
            
        self.buffers[user_id].write(data.pcm)
        self.last_spoken[user_id] = time.time()
        self.active_users.add(user_id)

    async def monitor_silence(self):
        """バックグラウンドで無音状態を監視"""
        while True:
            await asyncio.sleep(0.1)
            now = time.time()
            for user_id in list(self.active_users):
                if now - self.last_spoken.get(user_id, 0) > self.SILENCE_TIMEOUT:
                    self.active_users.remove(user_id)
                    asyncio.create_task(self.process_audio(user_id))

    async def process_audio(self, user_id):
        pcm_data = self.buffers[user_id].getvalue()
        self.buffers[user_id] = io.BytesIO()  # バッファリセット
        
        if not pcm_data:
            return

        wav_data = self.pcm_to_wav(pcm_data)
        
        with sr.AudioFile(io.BytesIO(wav_data)) as source:
            audio = self.recognizer.record(source)

        try:
            loop = asyncio.get_running_loop()
            text = await loop.

# ----------------------------------------------------
# 2. Cog形式のメイン実装 (スラッシュコマンド)
# ----------------------------------------------------
class MojiokosiCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.active_sinks = {}  # サーバーごとのSink管理用 {guild_id: sink}

    @app_commands.command(name="mojiokosi", description="文字起こし機能のオン/オフを切り替えます")
    @app_commands.choices(status=[
        app_commands.Choice(name="オン (開始)", value="on"),
        app_commands.Choice(name="オフ (終了)", value="off")
    ])
    async def mojiokosi(self, interaction: discord.Interaction, status: str):
        guild = interaction.guild
        if not guild:
            await interaction.response.send_message("このコマンドはサーバー内でのみ実行できます。", ephemeral=True)
            return

        # --------------------
        # オン (開始) の処理
        # --------------------
        if status == "on":
            if interaction.user.voice is None:
                await interaction.response.send_message("先にボイスチャンネルに入室してください。", ephemeral=True)
                return
            
            voice_channel = interaction.user.voice.channel
            
            # 【修正】interaction.voice_client から interaction.guild.voice_client に変更
            if interaction.guild.voice_client:
                if interaction.guild.voice_client.channel.id == voice_channel.id:
                    await interaction.response.send_message("既にこのチャンネルで文字起こしが有効です。", ephemeral=True)
                    return
                else:
                    # 別のVCにいる場合は移動
                    await interaction.guild.voice_client.move_to(voice_channel)
            else:
                # 新規接続
                await voice_channel.connect(cls=voice_recv.VoiceClient)

            # 古いセッションが残っていればタスクをクリーンアップ
            if guild.id in self.active_sinks:
                self.active_sinks[guild.id].cleanup()

            # 新しいSinkを作成
            sink = SpeechToTextSink(self.bot, interaction.channel_id, threshold=800)
            self.active_sinks[guild.id] = sink
            
            # 【修正】音声受信を開始
            interaction.guild.voice_client.listen(sink)
            await interaction.response.send_message(
                f"🎤 **{voice_channel.name}** で文字起こしを開始しました！\nこのチャンネル（<#{interaction.channel_id}>）に発言を送信します。",
                ephemeral=False
            )

        # --------------------
        # オフ (終了) の処理
        # --------------------
        elif status == "off":
            # 【修正】ボットがVCに参加しているか確認
            if not interaction.guild.voice_client:
                await interaction.response.send_message("ボットはボイスチャンネルに参加していません。", ephemeral=True)
                return
            
            # メモリ解放と切断
            if guild.id in self.active_sinks:
                self.active_sinks[guild.id].cleanup()
                del self.active_sinks[guild.id]
                
            # 【修正】切断処理
            await interaction.guild.voice_client.disconnect()
            await interaction.response.send_message("🛑 文字起こしを終了し、ボイスチャンネルから切断しました。", ephemeral=False)

# Cogの登録
async def setup(bot):
    await bot.add_cog(MojiokosiCog(bot))