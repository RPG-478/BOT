import discord
from discord.ext import commands, tasks
import asyncio
import random
import io
import os
from PIL import Image, ImageDraw

# --- Configuration & Assets ---
# 実際のファイル名に基づいたアセット構成
# 0: 通常(default), 1~4: 異変画像として割り当て
ASSETS_CONFIG = {
    0: {
        "name": "BATHROOM",
        "default": "assets/rooms/Bath0.png",
        "Displacement": "assets/rooms/Bath1.png",
        "Flaw": "assets/rooms/Bath2.png",
        "Alternate": "assets/rooms/Bath3.png",
        "Presence": "assets/rooms/Bath4.png"
    },
    1: {
        "name": "BASEMENT",
        "default": "assets/rooms/Base0.png",
        "Displacement": "assets/rooms/Base1.png",
        "Alternate": "assets/rooms/Base2.png"
    },
    2: {
        "name": "LIVING ROOM",
        "default": "assets/rooms/Living0.png",
        # Livingに異変画像がない場合は通常画像が表示される(報告は可能)
    },
    3: {
        "name": "PARKING",
        "default": "assets/rooms/Parking0.png",
    }
}

# 音響アセット
SOUND_ASSETS = {
    "ambient": "assets/sounds/ambient_loop.mp3",
    "anomaly_spawn": "assets/sounds/anomaly_detected.mp3",
    "correct": "assets/sounds/fix_success.mp3",
    "wrong": "assets/sounds/fix_error.mp3",
    "gameover": "assets/sounds/game_over.mp3"
}

ANOMALY_TYPES = ["Displacement", "Flaw", "Alternate", "Presence"]
MAX_ANOMALIES = 5

class Watch(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.current_room_index = 0
        self.active_anomalies = {i: None for i in ASSETS_CONFIG.keys()}
        self.anomaly_count = 0
        self.is_game_over = False
        self.voice_client = None
        self.game_msg = None

    def cog_unload(self):
        self.anomaly_generator.cancel()

    def play_audio(self, sound_key):
        """FFmpegを使用してボイスチャンネルで音声を再生"""
        if self.voice_client and self.voice_client.is_connected():
            path = SOUND_ASSETS.get(sound_key)
            if path and os.path.exists(path):
                if self.voice_client.is_playing() and sound_key != "ambient":
                    self.voice_client.stop()
                
                source = discord.FFmpegPCMAudio(path)
                self.voice_client.play(
                    source, 
                    after=lambda e: self.play_audio("ambient") if sound_key != "ambient" else None
                )

    def generate_noise_gif(self, image_path):
        """画像にライブ感のあるノイズ加工を施してGIFを生成"""
        try:
            base_img = Image.open(image_path).convert("RGBA").resize((640, 360))
        except Exception as e:
            print(f"Image Load Error ({image_path}): {e}")
            base_img = Image.new("RGBA", (640, 360), (10, 10, 15))

        frames = []
        for _ in range(3):
            frame = base_img.copy()
            noise_layer = Image.new("RGBA", frame.size, (0, 0, 0, 0))
            draw = ImageDraw.Draw(noise_layer)
            
            # ピクセルノイズ
            for _ in range(1500):
                x, y = random.randint(0, 639), random.randint(0, 359)
                draw.point((x, y), fill=(255, 255, 255, random.randint(15, 55)))
            
            # 走査線
            for y in range(0, 360, 4):
                draw.line([(0, y), (640, y)], fill=(0, 0, 0, 25), width=1)

            frames.append(Image.alpha_composite(frame, noise_layer))

        buffer = io.BytesIO()
        frames[0].save(buffer, format='GIF', save_all=True, append_images=frames[1:], duration=100, loop=0)
        buffer.seek(0)
        return buffer

    async def update_monitor_message(self, interaction=None, overlay_text=None):
        """監視画面のメッセージを更新"""
        room_id = self.current_room_index
        room_data = ASSETS_CONFIG[room_id]
        anomaly = self.active_anomalies[room_id]

        # 異変があれば異変用画像、なければ通常画像(default)を使用
        img_path = room_data.get(anomaly, room_data["default"])
        gif_buf = self.generate_noise_gif(img_path)
        
        file = discord.File(gif_buf, filename="feed.gif")
        embed = discord.Embed(
            title=f"LIVE FEED: {room_data['name']}", 
            color=discord.Color.from_rgb(20, 20, 25)
        )
        if overlay_text:
            embed.description = f"**{overlay_text}**"
        
        embed.set_image(url="attachment://feed.gif")
        embed.set_footer(text=f"Anomaly Count: {self.anomaly_count}/{MAX_ANOMALIES} | CAM: {room_id}")

        view = CameraControlView(self)
        
        if interaction:
            if interaction.response.is_done():
                await interaction.edit_original_response(embed=embed, attachments=[file], view=view)
            else:
                await interaction.response.edit_message(embed=embed, attachments=[file], view=view)
        elif self.game_msg:
            try:
                await self.game_msg.edit(embed=embed, attachments=[file], view=view)
            except:
                pass

    @tasks.loop(seconds=25)
    async def anomaly_generator(self):
        """非表示の部屋に異変を発生させるタスク"""
        if self.is_game_over:
            return

        candidates = [i for i in ASSETS_CONFIG.keys() if i != self.current_room_index and self.active_anomalies[i] is None]
        
        if candidates and random.random() < 0.35:
            room_id = random.choice(candidates)
            # その部屋で定義されている異変タイプを選択
            possible = [k for k in ASSETS_CONFIG[room_id].keys() if k not in ["name", "default"]]
            if possible:
                self.active_anomalies[room_id] = random.choice(possible)
                self.anomaly_count += 1
                self.play_audio("anomaly_spawn")

        if self.anomaly_count >= MAX_ANOMALIES:
            self.is_game_over = True
            self.play_audio("gameover")
            await self.update_monitor_message(overlay_text="CRITICAL FAILURE: SYSTEM HACKED")

    @commands.command(name="watch")
    async def start_watch(self, ctx):
        """ゲーム開始。VC接続が必須。"""
        if not ctx.author.voice:
            return await ctx.send("エラー: ボイスチャンネルに参加してからコマンドを打ってください。")

        self.current_room_index = 0
        self.active_anomalies = {i: None for i in ASSETS_CONFIG.keys()}
        self.anomaly_count = 0
        self.is_game_over = False

        if ctx.voice_client:
            await ctx.voice_client.move_to(ctx.author.voice.channel)
            self.voice_client = ctx.voice_client
        else:
            self.voice_client = await ctx.author.voice.channel.connect()

        self.play_audio("ambient")
        
        if not self.anomaly_generator.is_running():
            self.anomaly_generator.start()

        room_data = ASSETS_CONFIG[0]
        gif_buf = self.generate_noise_gif(room_data["default"])
        file = discord.File(gif_buf, filename="feed.gif")
        
        embed = discord.Embed(title=f"LIVE FEED: {room_data['name']}", color=discord.Color.from_rgb(20, 20, 25))
        embed.set_image(url="attachment://feed.gif")
        
        self.game_msg = await ctx.send(embed=embed, file=file, view=CameraControlView(self))

class CameraControlView(discord.ui.View):
    def __init__(self, cog):
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(label="◀", style=discord.ButtonStyle.secondary)
    async def prev_cam(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.cog.is_game_over: return
        self.cog.current_room_index = (self.cog.current_room_index - 1) % len(ASSETS_CONFIG)
        await self.cog.update_monitor_message(interaction)

    @discord.ui.button(label="REPORT", style=discord.ButtonStyle.danger)
    async def report_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.cog.is_game_over: return
        await interaction.response.send_message(
            "異変の種類を選択:", 
            view=ReportSelectView(self.cog), 
            ephemeral=True
        )

    @discord.ui.button(label="▶", style=discord.ButtonStyle.secondary)
    async def next_cam(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.cog.is_game_over: return
        self.cog.current_room_index = (self.cog.current_room_index + 1) % len(ASSETS_CONFIG)
        await self.cog.update_monitor_message(interaction)

class ReportSelectView(discord.ui.View):
    def __init__(self, cog):
        super().__init__(timeout=60)
        self.cog = cog
        
        select = discord.ui.Select(placeholder="異変を選択...")
        for a_type in ANOMALY_TYPES:
            select.add_option(label=a_type, value=a_type)
        select.callback = self.on_select
        self.add_item(select)

    async def on_select(self, interaction: discord.Interaction):
        selected = interaction.data['values'][0]
        room_id = self.cog.current_room_index
        correct = self.cog.active_anomalies[room_id]

        if selected == correct:
            self.cog.active_anomalies[room_id] = None
            self.cog.anomaly_count -= 1
            self.cog.play_audio("correct")
            await self.cog.update_monitor_message(interaction, overlay_text="REPORT SUCCESS: SIGNAL RESTORED")
        else:
            self.cog.play_audio("wrong")
            await self.cog.update_monitor_message(interaction, overlay_text="REPORT ERROR: NO ANOMALY DETECTED")
        
        await asyncio.sleep(4)
        if not self.cog.is_game_over:
            await self.cog.update_monitor_message()

async def setup(bot):
    await bot.add_cog(Watch(bot))