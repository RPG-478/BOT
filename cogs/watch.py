import discord
from discord.ext import commands, tasks
import asyncio
import random
import io
import os
import time
from PIL import Image, ImageDraw, ImageFont

# ─────────────────────────────────────────────────────────────────────────────
# 定数 / Configuration
# ─────────────────────────────────────────────────────────────────────────────
MAX_ANOMALIES  = 3      # 3件溜まるとゲームオーバー
GAME_DURATION  = 600    # リアル秒数: 10分 = ゲーム内 6:00
GAME_HOURS     = 6      # ゲーム内時間幅 (0:00 ～ 6:00)

# ────── 部屋アセット ──────
# Sound 異変には2種類ある:
#   type="room"   … そのカメラを表示しているときのみ音が流れる (発見のヒントが少ない)
#   type="global" … どのカメラを見ていても音が流れる (場所の特定が鍵)
Assets_CONFIG = {
    0: {
        "name":         "BATHROOM",
        "default":      "Assets/rooms/Bath3.PNG",
        "Displacement": "Assets/rooms/Bath1.PNG",
        "Flaw":         "Assets/rooms/Bath2.PNG",
        "Alternate":    "Assets/rooms/Bath0.PNG",
        "Presence":     "Assets/rooms/Bath4.PNG",
        # 部屋専用 Sound 異変: このカメラを見ているときのみ再生
        "Sound": {"type": "room", "audio": "Assets/sounds/bath_sound.mp3"},
    },
    1: {
        "name":         "BASEMENT",
        "default":      "Assets/rooms/Base0.PNG",
        "Displacement": "Assets/rooms/Base1.PNG",
        "Flaw":         "Assets/rooms/Base2.PNG",
        "Presence":     "Assets/rooms/Base4.PNG",
        # グローバル Sound 異変: どのカメラを見ていても再生 (場所不明)
        "Sound": {"type": "global", "audio": "Assets/sounds/base_sound.mp3"},
    },
    2: {
        "name":    "LIVING ROOM",
        "default": "Assets/rooms/Living0.PNG",
        # 部屋専用
        "Sound": {"type": "room", "audio": "Assets/sounds/living_sound.mp3"},
    },
    3: {
        "name":    "PARKING",
        "default": "Assets/rooms/Parking0.PNG",
        # グローバル
        "Sound": {"type": "global", "audio": "Assets/sounds/parking_sound.mp3"},
    },
}

# ────── サウンドアセット ──────
SOUND_Assets = {
    "ambient":       "Assets/sounds/ambient_loop.mp3",
    "anomaly_spawn": "Assets/sounds/anomaly_detected.mp3",
    "correct":       "Assets/sounds/fix_success.mp3",
    "wrong":         "Assets/sounds/fix_error.mp3",
    "gameover":      "Assets/sounds/game_over.mp3",
    "clear":         "Assets/sounds/game_clear.mp3",
}

# ────── Report UI 用画像アセット ──────
REPORT_Assets = {
    "reporting":  "Assets/rooms/Anomaly.PNG",
    "removed":    "Assets/rooms/Anomaly_Removed.PNG",
    "not_found":  "Assets/rooms/Anomaly_NotFound.PNG",
}

# プレイヤーが選択できる異変タイプ
ANOMALY_TYPES = ["Displacement", "Flaw", "Alternate", "Presence", "Sound"]


# ─────────────────────────────────────────────────────────────────────────────
# Cog
# ─────────────────────────────────────────────────────────────────────────────
class Watch(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._reset_state()

    def _reset_state(self):
        self.current_room_index = 0
        self.active_anomalies   = {i: None for i in Assets_CONFIG}
        self.anomaly_count      = 0
        self.is_game_over       = False
        self.is_cleared         = False
        self.is_reporting       = False
        self.voice_client       = None
        self.game_msg           = None
        self.game_start_time    = None
        # 統計
        self.anomaly_spawn_times: dict[int, float] = {}  # room_id -> spawn timestamp
        self.report_stats:        list[float]       = []  # 各報告の応答時間 (秒)

    def cog_unload(self):
        self.anomaly_generator.cancel()
        self.time_updater.cancel()

    # ─────────────────────────────── 時刻計算 ───────────────────────────────
    def _elapsed(self) -> float:
        if self.game_start_time is None:
            return 0.0
        return time.time() - self.game_start_time

    def get_game_time_str(self) -> str:
        """リアル経過秒 → ゲーム内 H:MM 文字列 (0:00 ～ 6:00)"""
        ratio       = min(self._elapsed() / GAME_DURATION, 1.0)
        total_mins  = ratio * GAME_HOURS * 60          # 0 ～ 360 ゲーム分
        g_hour      = int(total_mins // 60)
        g_min       = int(total_mins % 60)
        return f"{g_hour}:{g_min:02d}"

    # ─────────────────────────────── 音声制御 ───────────────────────────────
    def play_audio(self, sound_key: str):
        path = SOUND_Assets.get(sound_key)
        self._play_path(path, loop_to_ambient=(sound_key != "ambient"))

    def _play_path(self, path: str | None, loop_to_ambient: bool = True):
        if not (self.voice_client and self.voice_client.is_connected()):
            return
        if not path or not os.path.exists(path):
            return
        if self.voice_client.is_playing():
            self.voice_client.stop()
        source = discord.FFmpegPCMAudio(path)
        after  = (lambda e: self.play_audio("ambient")) if loop_to_ambient else None
        self.voice_client.play(source, after=after)

    def refresh_room_audio(self):
        """カメラ切り替え時に音声を更新する。
        - room 型 Sound 異変があれば再生
        - global 型は異変発生時に既に流れているので何もしない
        - それ以外はアンビエント継続
        """
        rid    = self.current_room_index
        a_type = self.active_anomalies[rid]
        if a_type == "Sound":
            cfg = Assets_CONFIG[rid].get("Sound", {})
            if cfg.get("type") == "room":
                self._play_path(cfg.get("audio"), loop_to_ambient=True)
                return
        # global Sound が他部屋でアクティブでも ambient で上書きしない
        for r_id, a in self.active_anomalies.items():
            if a == "Sound":
                if Assets_CONFIG[r_id].get("Sound", {}).get("type") == "global":
                    return  # グローバル音が再生中 → そのままにする
        self.play_audio("ambient")

    # ─────────────────────────────── 画像生成 ───────────────────────────────
    def _load_img(self, path: str) -> Image.Image:
        try:
            return Image.open(path).convert("RGBA").resize((640, 360))
        except Exception as e:
            print(f"[Watch] Image Load Error ({path}): {e}")
            return Image.new("RGBA", (640, 360), (10, 10, 15))

    def generate_noise_gif(self, image_path: str) -> io.BytesIO:
        """画像にCRTノイズ・走査線を合成してGIFを返す"""
        base_img = self._load_img(image_path)
        frames = []
        for _ in range(3):
            frame       = base_img.copy()
            noise_layer = Image.new("RGBA", frame.size, (0, 0, 0, 0))
            draw        = ImageDraw.Draw(noise_layer)
            for _ in range(1500):
                x, y = random.randint(0, 639), random.randint(0, 359)
                draw.point((x, y), fill=(255, 255, 255, random.randint(15, 55)))
            for y in range(0, 360, 4):
                draw.line([(0, y), (640, y)], fill=(0, 0, 0, 25), width=1)
            frames.append(Image.alpha_composite(frame, noise_layer))

        buf = io.BytesIO()
        frames[0].save(buf, format="GIF", save_all=True,
                       append_images=frames[1:], duration=100, loop=0)
        buf.seek(0)
        return buf

    def generate_result_image(self, cleared: bool) -> io.BytesIO:
        """Pillow でリザルト画面を生成"""
        W, H = 860, 520
        img  = Image.new("RGB", (W, H), (6, 6, 10))
        draw = ImageDraw.Draw(img)

        # グリッド背景
        for x in range(0, W, 40):
            draw.line([(x, 0), (x, H)], fill=(18, 18, 28), width=1)
        for y in range(0, H, 40):
            draw.line([(0, y), (W, y)], fill=(18, 18, 28), width=1)

        # フォント (なければデフォルト)
        FONT_PATHS = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationMono-Bold.ttf",
        ]
        def try_font(size):
            for fp in FONT_PATHS:
                try:
                    return ImageFont.truetype(fp, size)
                except Exception:
                    pass
            return ImageFont.load_default()

        f_xl    = try_font(66)
        f_label = try_font(26)
        f_value = try_font(52)
        f_foot  = try_font(20)

        # タイトル
        title       = "SHIFT COMPLETE" if cleared else "SYSTEM FAILURE"
        title_color = (80, 255, 140) if cleared else (255, 70, 70)
        tw = draw.textlength(title, font=f_xl)
        draw.text(((W - tw) // 2, 32), title, fill=title_color, font=f_xl)

        # 区切り線
        draw.line([(50, 125), (W - 50, 125)], fill=(50, 50, 75), width=2)

        # 統計
        avg_time    = (sum(self.report_stats) / len(self.report_stats)
                       if self.report_stats else 0.0)
        game_time   = self.get_game_time_str()
        reports_ok  = len(self.report_stats)

        stats = [
            ("ANOMALIES REPORTED",   str(reports_ok)),
            ("AVG RESPONSE TIME",    f"{avg_time:.1f}s"),
            ("TIME OF INCIDENT",     game_time),
        ]

        ROW_H  = 108
        y0     = 148
        for label, value in stats:
            # ラベル (小さめ・グレー)
            draw.text((60, y0), label, fill=(110, 110, 145), font=f_label)
            # 値 (大きめ・右寄せ)
            vw = draw.textlength(value, font=f_value)
            draw.text((W - 60 - vw, y0 - 6), value, fill=(210, 215, 255), font=f_value)
            # 薄い区切り
            draw.line([(60, y0 + ROW_H - 8), (W - 60, y0 + ROW_H - 8)],
                      fill=(28, 28, 42), width=1)
            y0 += ROW_H

        # フッター
        footer = "ALTERNATE WATCH  //  END OF SHIFT REPORT"
        fw = draw.textlength(footer, font=f_foot)
        draw.text(((W - fw) // 2, H - 38), footer, fill=(40, 40, 60), font=f_foot)

        # スキャンライン仕上げ
        for scan_y in range(0, H, 3):
            draw.line([(0, scan_y), (W, scan_y)], fill=(0, 0, 0, 18), width=1)

        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        return buf

    # ─────────────────────────────── メッセージ更新 ───────────────────────────
    def _build_embed(self, room_id: int, title_suffix: str = "",
                     description: str | None = None,
                     color: discord.Color | None = None) -> discord.Embed:
        room_data = Assets_CONFIG[room_id]
        embed = discord.Embed(
            title=f"LIVE FEED: {room_data['name']}{title_suffix}",
            color=color or discord.Color.from_rgb(20, 20, 25),
        )
        if description:
            embed.description = description
        embed.set_image(url="attachment://feed.gif")
        embed.set_footer(text=f"🕐  {self.get_game_time_str()}   |   CAM {room_id:02d}")
        return embed

    async def update_monitor_message(self,
                                     interaction: discord.Interaction | None = None,
                                     description: str | None = None,
                                     custom_image: str | None = None):
        """監視画面を更新 (通常フロー用)"""
        if self.is_game_over or self.is_cleared:
            return

        rid       = self.current_room_index
        room_data = Assets_CONFIG[rid]
        anomaly   = self.active_anomalies[rid]

        if custom_image:
            img_path = custom_image
        elif anomaly and anomaly != "Sound":
            img_path = room_data.get(anomaly, room_data["default"])
        else:
            img_path = room_data["default"]

        gif_buf = self.generate_noise_gif(img_path)
        file    = discord.File(gif_buf, filename="feed.gif")
        embed   = self._build_embed(rid, description=description)
        view    = CameraControlView(self)

        if interaction:
            if interaction.response.is_done():
                await interaction.edit_original_response(
                    embed=embed, attachments=[file], view=view)
            else:
                await interaction.response.edit_message(
                    embed=embed, attachments=[file], view=view)
        elif self.game_msg:
            try:
                await self.game_msg.edit(embed=embed, attachments=[file], view=view)
            except Exception:
                pass

    # ─────────────────────────── ゲーム終了処理 ────────────────────────────
    async def end_game(self, cleared: bool):
        """タスクを停止しリザルト画面を表示"""
        self.anomaly_generator.cancel()
        self.time_updater.cancel()

        if self.voice_client and self.voice_client.is_connected():
            self.play_audio("clear" if cleared else "gameover")
            await asyncio.sleep(3)
            await self.voice_client.disconnect()
            self.voice_client = None

        result_buf = self.generate_result_image(cleared)
        file       = discord.File(result_buf, filename="result.png")
        color      = (discord.Color.from_rgb(50, 200, 100) if cleared
                      else discord.Color.from_rgb(200, 50, 50))
        embed = discord.Embed(
            title="SHIFT COMPLETE" if cleared else "SYSTEM FAILURE",
            color=color,
        )
        embed.set_image(url="attachment://result.png")

        if self.game_msg:
            try:
                await self.game_msg.edit(embed=embed, attachments=[file], view=None)
            except Exception:
                pass

    # ──────────────────────────── Report シーケンス ──────────────────────────
    async def run_report_sequence(self, selected_type: str):
        """10秒 Reporting アニメーション → 判定 → 結果表示"""
        self.is_reporting = True
        rid        = self.current_room_index
        room_data  = Assets_CONFIG[rid]
        spawn_time = self.anomaly_spawn_times.get(rid, time.time())

        report_img = (REPORT_Assets["reporting"]
                      if os.path.exists(REPORT_Assets["reporting"])
                      else room_data["default"])

        # ── 10秒 Reporting アニメーション (game_msg を直接編集) ──
        dot_cycle = [".", "..", "..."]
        for i in range(10):
            dots    = dot_cycle[i % 3]
            gif_buf = self.generate_noise_gif(report_img)
            file    = discord.File(gif_buf, filename="feed.gif")
            embed   = self._build_embed(rid, description=f"**Reporting{dots}**")
            embed.set_image(url="attachment://feed.gif")
            view    = ReportingInProgressView()
            try:
                await self.game_msg.edit(embed=embed, attachments=[file], view=view)
            except Exception:
                pass
            await asyncio.sleep(1)

        # ── Phase 1: "Anomaly" のみ表示 ──
        gif_buf = self.generate_noise_gif(report_img)
        file    = discord.File(gif_buf, filename="feed.gif")
        embed   = self._build_embed(rid, description="**Anomaly**")
        embed.set_image(url="attachment://feed.gif")
        try:
            await self.game_msg.edit(embed=embed, attachments=[file],
                                     view=ReportingInProgressView())
        except Exception:
            pass

        await asyncio.sleep(1)

        # ── 判定 ──
        correct    = self.active_anomalies[rid]
        is_correct = (selected_type == correct)

        response_time = time.time() - spawn_time

        if is_correct:
            self.active_anomalies[rid] = None
            self.anomaly_count        -= 1
            self.report_stats.append(response_time)
            self.anomaly_spawn_times.pop(rid, None)
            self.play_audio("correct")
            result_img_key = "removed"
            result_text    = "Anomaly\nRemoved"
            result_color   = discord.Color.from_rgb(18, 32, 18)
        else:
            self.play_audio("wrong")
            result_img_key = "not_found"
            result_text    = "Anomaly\nNot Found"
            result_color   = discord.Color.from_rgb(32, 14, 14)

        # ── Phase 2: 結果画像 + "Anomaly\n~~~" ──
        res_img_path = (REPORT_Assets[result_img_key]
                        if os.path.exists(REPORT_Assets[result_img_key])
                        else room_data["default"])
        gif_buf = self.generate_noise_gif(res_img_path)
        file    = discord.File(gif_buf, filename="feed.gif")
        embed   = self._build_embed(rid, description=f"**{result_text}**",
                                    color=result_color)
        embed.set_image(url="attachment://feed.gif")
        try:
            await self.game_msg.edit(embed=embed, attachments=[file],
                                     view=ReportingInProgressView())
        except Exception:
            pass

        await asyncio.sleep(3)

        self.is_reporting = False

        if not self.is_game_over and not self.is_cleared:
            await self.update_monitor_message()

    # ─────────────────────────────── タスク ────────────────────────────────
    @tasks.loop(seconds=15)
    async def anomaly_generator(self):
        """異変を発生させるバックグラウンドタスク (出現率高め)"""
        if self.is_game_over or self.is_cleared:
            return

        candidates = [i for i in Assets_CONFIG
                      if i != self.current_room_index
                      and self.active_anomalies[i] is None]

        if candidates and random.random() < 0.65:   # 旧: 0.35 → 0.65
            rid      = random.choice(candidates)
            possible = [k for k in Assets_CONFIG[rid]
                        if k not in ("name", "default")]
            if possible:
                chosen = random.choice(possible)
                self.active_anomalies[rid]   = chosen
                self.anomaly_count          += 1
                self.anomaly_spawn_times[rid] = time.time()

                # Sound 異変の音声制御
                if chosen == "Sound":
                    cfg        = Assets_CONFIG[rid].get("Sound", {})
                    sound_type = cfg.get("type", "room")
                    audio_path = cfg.get("audio", "")
                    if sound_type == "global":
                        # どのカメラでも聞こえる → 即再生
                        self._play_path(audio_path, loop_to_ambient=False)
                    else:
                        # 部屋専用 → 今そのカメラを見ているときのみ再生
                        if self.current_room_index == rid:
                            self._play_path(audio_path, loop_to_ambient=False)
                        else:
                            # 他部屋では SE のみ (プレイヤーへのヒントなし)
                            pass
                else:
                    self.play_audio("anomaly_spawn")

        # ゲームオーバー判定
        if self.anomaly_count >= MAX_ANOMALIES and not self.is_game_over:
            self.is_game_over = True
            await self.end_game(cleared=False)

    @tasks.loop(seconds=10)
    async def time_updater(self):
        """時刻表示の定期更新 & クリア判定"""
        if self.is_game_over or self.is_cleared or self.is_reporting:
            return

        # 6:00 到達でクリア
        if self.game_start_time and self._elapsed() >= GAME_DURATION:
            self.is_cleared = True
            await self.end_game(cleared=True)
            return

        await self.update_monitor_message()

    # ─────────────────────────────── コマンド ───────────────────────────────
    @commands.command(name="watch")
    async def start_watch(self, ctx: commands.Context):
        """ゲーム開始 (VC参加必須)"""
        if not ctx.author.voice:
            return await ctx.send(
                "エラー: ボイスチャンネルに参加してからコマンドを打ってください。")

        self._reset_state()
        self.game_start_time = time.time()

        if ctx.voice_client:
            await ctx.voice_client.move_to(ctx.author.voice.channel)
            self.voice_client = ctx.voice_client
        else:
            self.voice_client = await ctx.author.voice.channel.connect()

        self.play_audio("ambient")

        if not self.anomaly_generator.is_running():
            self.anomaly_generator.start()
        if not self.time_updater.is_running():
            self.time_updater.start()

        room_data = Assets_CONFIG[0]
        gif_buf   = self.generate_noise_gif(room_data["default"])
        file      = discord.File(gif_buf, filename="feed.gif")
        embed     = discord.Embed(
            title=f"LIVE FEED: {room_data['name']}",
            color=discord.Color.from_rgb(20, 20, 25),
        )
        embed.set_image(url="attachment://feed.gif")
        embed.set_footer(text="🕐  0:00   |   CAM 00")

        self.game_msg = await ctx.send(
            embed=embed, file=file, view=CameraControlView(self))


# ─────────────────────────────────────────────────────────────────────────────
# Views
# ─────────────────────────────────────────────────────────────────────────────

class CameraControlView(discord.ui.View):
    """通常監視画面のボタン"""
    def __init__(self, cog: Watch):
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(label="◀", style=discord.ButtonStyle.secondary)
    async def prev_cam(self, interaction: discord.Interaction,
                       button: discord.ui.Button):
        if self.cog.is_game_over or self.cog.is_reporting:
            return await interaction.response.defer()
        self.cog.current_room_index = (
            (self.cog.current_room_index - 1) % len(Assets_CONFIG))
        self.cog.refresh_room_audio()
        await self.cog.update_monitor_message(interaction)

    @discord.ui.button(label="REPORT", style=discord.ButtonStyle.danger)
    async def report_btn(self, interaction: discord.Interaction,
                         button: discord.ui.Button):
        if self.cog.is_game_over or self.cog.is_reporting:
            return await interaction.response.defer()
        # メインパネルをセレクト画面に切り替え (エフェメラルなし)
        rid       = self.cog.current_room_index
        room_data = Assets_CONFIG[rid]
        gif_buf   = self.cog.generate_noise_gif(room_data["default"])
        file      = discord.File(gif_buf, filename="feed.gif")
        embed     = discord.Embed(
            title=f"LIVE FEED: {room_data['name']}",
            description="**異変タイプを選択 :**",
            color=discord.Color.from_rgb(20, 20, 25),
        )
        embed.set_image(url="attachment://feed.gif")
        embed.set_footer(
            text=f"🕐  {self.cog.get_game_time_str()}   |   CAM {rid:02d}")
        await interaction.response.edit_message(
            embed=embed, attachments=[file], view=ReportSelectView(self.cog))

    @discord.ui.button(label="▶", style=discord.ButtonStyle.secondary)
    async def next_cam(self, interaction: discord.Interaction,
                       button: discord.ui.Button):
        if self.cog.is_game_over or self.cog.is_reporting:
            return await interaction.response.defer()
        self.cog.current_room_index = (
            (self.cog.current_room_index + 1) % len(Assets_CONFIG))
        self.cog.refresh_room_audio()
        await self.cog.update_monitor_message(interaction)


class ReportingInProgressView(discord.ui.View):
    """Report 処理中に表示する無効化ビュー"""
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="◀", style=discord.ButtonStyle.secondary, disabled=True)
    async def _prev(self, i: discord.Interaction, b: discord.ui.Button):
        pass

    @discord.ui.button(label="REPORTING...", style=discord.ButtonStyle.danger, disabled=True)
    async def _rep(self, i: discord.Interaction, b: discord.ui.Button):
        pass

    @discord.ui.button(label="▶", style=discord.ButtonStyle.secondary, disabled=True)
    async def _next(self, i: discord.Interaction, b: discord.ui.Button):
        pass


class ReportSelectView(discord.ui.View):
    """REPORT ボタン後に表示する異変タイプ選択 View (メインパネル内、非エフェメラル)"""
    def __init__(self, cog: Watch):
        super().__init__(timeout=30)
        self.cog = cog

        select = discord.ui.Select(
            placeholder="異変タイプを選択...",
            options=[discord.SelectOption(label=t, value=t) for t in ANOMALY_TYPES],
        )
        select.callback = self.on_select
        self.add_item(select)

        cancel = discord.ui.Button(label="キャンセル",
                                   style=discord.ButtonStyle.secondary)
        cancel.callback = self.on_cancel
        self.add_item(cancel)

    async def on_select(self, interaction: discord.Interaction):
        selected = interaction.data["values"][0]

        # まず interaction を確定 (Reporting. の最初のフレームに切り替える)
        rid       = self.cog.current_room_index
        room_data = Assets_CONFIG[rid]
        report_img = (REPORT_Assets["reporting"]
                      if os.path.exists(REPORT_Assets["reporting"])
                      else room_data["default"])
        gif_buf = self.cog.generate_noise_gif(report_img)
        file    = discord.File(gif_buf, filename="feed.gif")
        embed   = discord.Embed(
            title=f"LIVE FEED: {room_data['name']}",
            description="**Reporting.**",
            color=discord.Color.from_rgb(20, 20, 25),
        )
        embed.set_image(url="attachment://feed.gif")
        embed.set_footer(
            text=f"🕐  {self.cog.get_game_time_str()}   |   CAM {rid:02d}")
        # ← interaction を使って最初のフレームを確定させる
        await interaction.response.edit_message(
            embed=embed, attachments=[file], view=ReportingInProgressView())

        # 残り 9秒 + 判定 は game_msg を直接叩くバックグラウンドタスクへ
        asyncio.create_task(self.cog._report_continue(selected))

    async def on_cancel(self, interaction: discord.Interaction):
        await self.cog.update_monitor_message(interaction)

    async def on_timeout(self):
        if not self.cog.is_game_over and not self.cog.is_cleared:
            await self.cog.update_monitor_message()


# ─────────────────────────────────────────────────────────────────────────────
# Watch._report_continue  (ReportSelectView.on_select から呼び出す)
# ─────────────────────────────────────────────────────────────────────────────
async def _report_continue(self: Watch, selected_type: str):
    """interaction 確定後の Reporting アニメーション本体 (残り 9秒)"""
    self.is_reporting = True
    rid       = self.current_room_index
    room_data = Assets_CONFIG[rid]
    spawn_time = self.anomaly_spawn_times.get(rid, time.time())

    report_img = (REPORT_Assets["reporting"]
                  if os.path.exists(REPORT_Assets["reporting"])
                  else room_data["default"])

    dot_cycle = [".", "..", "..."]
    # 最初のフレーム (Reporting.) は on_select で送信済み → i=1 から
    for i in range(1, 10):
        await asyncio.sleep(1)
        dots    = dot_cycle[i % 3]
        gif_buf = self.generate_noise_gif(report_img)
        file    = discord.File(gif_buf, filename="feed.gif")
        embed   = self._build_embed(rid, description=f"**Reporting{dots}**")
        embed.set_image(url="attachment://feed.gif")
        try:
            await self.game_msg.edit(embed=embed, attachments=[file],
                                     view=ReportingInProgressView())
        except Exception:
            pass

    # Phase 1: "Anomaly" のみ
    gif_buf = self.generate_noise_gif(report_img)
    file    = discord.File(gif_buf, filename="feed.gif")
    embed   = self._build_embed(rid, description="**Anomaly**")
    embed.set_image(url="attachment://feed.gif")
    try:
        await self.game_msg.edit(embed=embed, attachments=[file],
                                 view=ReportingInProgressView())
    except Exception:
        pass

    await asyncio.sleep(1)

    # 判定
    correct    = self.active_anomalies[rid]
    is_correct = (selected_type == correct)
    response_time = time.time() - spawn_time

    if is_correct:
        self.active_anomalies[rid]  = None
        self.anomaly_count         -= 1
        self.report_stats.append(response_time)
        self.anomaly_spawn_times.pop(rid, None)
        self.play_audio("correct")
        result_key  = "removed"
        result_text = "Anomaly\nRemoved"
        res_color   = discord.Color.from_rgb(18, 32, 18)
    else:
        self.play_audio("wrong")
        result_key  = "not_found"
        result_text = "Anomaly\nNot Found"
        res_color   = discord.Color.from_rgb(32, 14, 14)

    # Phase 2: 結果画像 + テキスト
    res_path = (REPORT_Assets[result_key]
                if os.path.exists(REPORT_Assets[result_key])
                else room_data["default"])
    gif_buf = self.generate_noise_gif(res_path)
    file    = discord.File(gif_buf, filename="feed.gif")
    embed   = self._build_embed(rid, description=f"**{result_text}**",
                                color=res_color)
    embed.set_image(url="attachment://feed.gif")
    try:
        await self.game_msg.edit(embed=embed, attachments=[file],
                                 view=ReportingInProgressView())
    except Exception:
        pass

    await asyncio.sleep(3)

    self.is_reporting = False

    if not self.is_game_over and not self.is_cleared:
        await self.update_monitor_message()


# メソッドを Cog に動的に追加 (バックグラウンドタスク用)
Watch._report_continue = _report_continue  # type: ignore


async def setup(bot: commands.Bot):
    await bot.add_cog(Watch(bot))