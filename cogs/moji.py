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
# 0. 【修正】安全なパッチ適用処理（Cogの読み込みエラーを完全に防止）
# ----------------------------------------------------
try:
    import discord.ext.voice_recv.opus as vr_opus
    # ライブラリのバージョンによるクラス名（VoiceDecoder または Decoder）のブレを自動吸収
    DecoderClass = getattr(vr_opus, 'VoiceDecoder', getattr(vr_opus, 'Decoder', None))
    
    if DecoderClass and hasattr(DecoderClass, 'pop_data'):
        _original_pop_data = DecoderClass.pop_data

        def _patched_pop_data(self):
            try:
                return _original_pop_data(self)
            except Exception as e:
                # 'corrupted stream'（破損パケット）が発生してもログに残して安全にスルー
                print(f"[音声パッチ] 破損パケットをスキップしました: {e}")
                return None

        DecoderClass.pop_data = _patched_pop_data
        print("[音声パッチ] クラッシュ回避パッチが正常に適用されました。")
    else:
        print("[音声パッチ警告] 対象のデコーダクラスが見つかりませんでした。パッチをスキップします。")
except Exception as e:
    # 万が一パッチ処理自体が失敗しても、Cog（コマンド）の読み込みは絶対に止めない
    print(f"[音声パッチエラー] パッチ処理で問題が発生しました（Cogの読み込みは続行します）: {e}")


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

    def wants_opus(self) -> bool:
        """Opus形式ではなく、デコードされたPCMデータを受け取るためFalseを返す"""
        return False

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
            text = await loop.run_in_executor(
                None, 
                lambda: self.recognizer.recognize_google(audio, language="ja-JP")
            )
            
            if text:
                channel = self.bot.get_channel(self.channel_id)
                if not channel:
                    return

                # Webhookの取得または作成（初回のみ実行）
                if not self.webhook:
                    try:
                        webhooks = await channel.webhooks()
                        self.webhook = discord.utils.get(webhooks, name="Mojiokosi Webhook")
                        if not self.webhook:
                            self.webhook = await channel.create_webhook(name="Mojiokosi Webhook")
                    except discord.Forbidden:
                        print("[エラー] ボットに『ウェブフックの管理』権限がありません。")
                        user = channel.guild.get_member(user_id) or self.bot.get_user(user_id)
                        username = user.display_name if user else f"User_{user_id}"
                        await channel.send(f"**{username}** [VCで発言しました]: {text}")
                        return

                # 発言したメンバーの情報をサーバー内から正確に取得
                guild = channel.guild
                member = guild.get_member(user_id)
                if not member:
                    try:
                        member = await guild.fetch_member(user_id)
                    except Exception:
                        member = None

                # 名前とアイコンURLの確定
                if member:
                    username = member.display_name
                    avatar_url = member.display_avatar.url
                else:
                    user = self.bot.get_user(user_id)
                    username = user.display_name if user else f"User_{user_id}"
                    avatar_url = user.display_avatar.url if user else None

                # [VCで発言しました] を先頭に付与し、Webhookで送信
                formatted_text = f"[VCで発言しました] {text}"
                await self.webhook.send(
                    content=formatted_text,
                    username=username,
                    avatar_url=avatar_url
                )

        except sr.UnknownValueError:
            pass  # 認識不可（ため息やノイズなど）はスルー
        except Exception as e:
            print(f"[文字起こしエラー] {e}")

    def pcm_to_wav(self, pcm_data):
        wav_buf = io.BytesIO()
        with wave.open(wav_buf, "wb") as wav_file:
            wav_file.setnchannels(2)
            wav_file.setsampwidth(2)
            wav_file.setframerate(48000)
            wav_file.writeframes(pcm_data)
        return wav_buf.getvalue()

    def cleanup(self):
        """監視タスクの終了処理"""
        self.monitor_task.cancel()


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
            # タイムアウトを防ぐため先に「考え中...」の応答を返す
            await interaction.response.defer(ephemeral=False)

            if interaction.user.voice is None:
                await interaction.followup.send("先にボイスチャンネルに入室してください。")
                return
            
            voice_channel = interaction.user.voice.channel
            
            # ボットが既にどこかのVCに接続しているか確認
            if interaction.guild.voice_client:
                if interaction.guild.voice_client.channel.id == voice_channel.id:
                    await interaction.followup.send("既にこのチャンネルで文字起こしが有効です。")
                    return
                else:
                    # 別のVCにいる場合は移動
                    await interaction.guild.voice_client.move_to(voice_channel)
            else:
                # 接続クライアントを指定してVCへ参加
                await voice_channel.connect(cls=voice_recv.VoiceRecvClient)

            # 接続完了から音声受信開始までに1.5秒待つ（同期ズレ防止）
            await asyncio.sleep(1.5)

            # 古いセッションが残っていればタスクをクリーンアップ
            if guild.id in self.active_sinks:
                self.active_sinks[guild.id].cleanup()

            # 新しいSinkを作成
            sink = SpeechToTextSink(self.bot, interaction.channel_id, threshold=800)
            self.active_sinks[guild.id] = sink
            
            # 音声受信を開始
            interaction.guild.voice_client.listen(sink)
            await interaction.followup.send(
                f"🎤 **{voice_channel.name}** で文字起こしを開始しました！\nこのチャンネル（<#{interaction.channel_id}>）に発言を送信します。"
            )

        # --------------------
        # オフ (終了) の処理
        # --------------------
        elif status == "off":
            if not interaction.guild.voice_client:
                await interaction.response.send_message("ボットはボイスチャンネルに参加していません。", ephemeral=True)
                return
            
            # メモリ解放と切断
            if guild.id in self.active_sinks:
                self.active_sinks[guild.id].cleanup()
                del self.active_sinks[guild.id]
                
            await interaction.guild.voice_client.disconnect()
            await interaction.response.send_message("🛑 文字起こしを終了し、ボイスチャンネルから切断しました。", ephemeral=False)

# Cogの登録
async def setup(bot):
    await bot.add_cog(MojiokosiCog(bot))