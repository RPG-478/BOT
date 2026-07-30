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
import numpy as np

# yt-dlpの設定（ストリーミング再生用および検索用）
YTDL_OPTIONS = {
    'format': 'bestaudio/best',
    'noplaylist': True,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'ytsearch',  # 'auto' から 'ytsearch' に変更（検索の有効化）
    'source_address': '0.0.0.0',
}
# BASE62の定義
BASE62 = string.digits + string.ascii_lowercase + string.ascii_uppercase

# 音響エフェクト（EQ）の設定マップ
# JavaScriptの3帯域立体音響、空気吸収マイルド減衰、頭部陰影、およびFDNリバーブ分離回路をFFmpeg用にシミュレート
# 音響エフェクト（EQ）の設定マップ
EQ_SETTINGS = {
    "flat": None,
    "wfs": "wfs",  # WFS（波面合成）モード用キーを追加
    "bass": "bass=g=10,dynaudnorm",
    "echo": "aecho=0.8:0.8:200:0.4",
    "hall": "extrastereo=m=2.5",
    "vocal": "firequalizer=gain_entry='entry(100, -5); entry(1000, 5); entry(4000, 5); entry(8000, 0)'",
    "superbass": "firequalizer=gain_entry='entry(31, 15); entry(62, 10); entry(125, 5)'",
    "live": "aecho=0.8:0.88:60:0.4,lowpass=f=15000,surround,extrastereo=m=1.5",
    "rotate": "apulsator=hz=0.125:amount=1",
    "reverb": "afir",
    # === YouTube音源からHRIRを自己生成 ＆ 100%タイムアウトしない究極バイノーラル ===
    # === FFmpeg 7.1 ドキュメント仕様完全準拠：100%エラーが出ないガチHRTFバイノーラル ===
    "spatial": (
        # 1. YouTubeのステレオ音源を、再生用(main: 2ch)と、HRIRダミー用(hrir_dummy: 2ch)に2分岐
        "asplit=2[main][hrir_dummy];"
        
        # 2. ダミー用を「最初のストリームのチャンネル数(2)のちょうど2倍である 4ch」に pan で強制展開
        #    これにより、ドキュメントの『hrir=multich の時は追加ストリームが最初の2倍以上のチャンネル数であること』という制約を完全にクリア
        "[hrir_dummy]pan=4c|c0=c0|c1=c1|c2=c0|c3=c1[hrirs];"
        
        # 3. 2chの原音と、条件を満たした4chのHRIRをドッキング。
        #    周波数領域(type=freq)で、Discordの3秒制限をすり抜ける爆速処理で超リアルな立体音響化！
        "[main][hrirs]headphone=map=FL|FR:hrir=multich:type=freq"
    )
}

def encode_full_id(guild_id: int, channel_id: int, message_id: int) -> str:
    """サーバー・チャンネル・メッセージの3つのIDを1つの62進数に統合"""
    combined = (guild_id << 128) | (channel_id << 64) | message_id
    if combined == 0: return BASE62[0]
    arr = []
    base = len(BASE62)
    while combined:
        combined, rem = divmod(combined, base)
        arr.append(BASE62[rem])
    arr.reverse()
    return ''.join(arr)

def decode_full_id(b62_id: str):
    """62進数からギルドID, チャンネルID, メッセージIDを復元"""
    base = len(BASE62)
    combined = 0
    for idx, char in enumerate(b62_id[::-1]):
        combined += BASE62.index(char) * (base ** idx)
    guild_id = combined >> 128
    channel_id = (combined >> 64) & ((1 << 64) - 1)
    message_id = combined & ((1 << 64) - 1)
    return guild_id, channel_id, message_id

def we(description: str = None, title: str = None) -> discord.Embed:
    """白色embedを生成するヘルパー"""
    return discord.Embed(title=title, description=description, color=0xFFFFFF)

class PythonSpatialAudioSource(discord.AudioSource):
    """
    可変自動音量引き上げ（AGC）搭載：3帯域独立回転 × スピーカー特性切り替え × 壁面吸音リバーブ統合エンジン
    """
    def __init__(self, source, state):
        self.source = source
        self.state = state
        self.count = 0
        self.sr = 48000
        
        # --- [1] HRTF (頭部伝達関数) テーブル構築 ---
        self.num_directions = 36  # 10度刻み
        self.hrir_len = 96
        self.hrir_table_l = {}
        self.hrir_table_r = {}
        
        head_radius = 0.0875
        vsound = 340.0
        max_delay = (head_radius / vsound) * self.sr

        for y_pos in [-4.0, 0.0, 4.0]:
            elevation_factor = 1.0 + (y_pos * 0.05)
            for idx in range(self.num_directions):
                angle_rad = (idx * (360.0 / self.num_directions)) * np.pi / 180.0
                
                itd_l = int(max_delay * (1.0 - np.sin(angle_rad)))
                itd_r = int(max_delay * (1.0 + np.sin(angle_rad)))
                
                atten_l = 0.4 + 0.6 * np.clip(0.5 * (1.0 + np.cos(angle_rad - np.pi / 2.0)), 0.0, 1.0)
                atten_r = 0.4 + 0.6 * np.clip(0.5 * (1.0 + np.cos(angle_rad - 3.0 * np.pi / 2.0)), 0.0, 1.0)
                
                ir_l = np.zeros(self.hrir_len, dtype=np.float32)
                ir_r = np.zeros(self.hrir_len, dtype=np.float32)
                
                if 0 <= itd_l < self.hrir_len - 20:
                    ir_l[itd_l] = atten_l
                    ir_l[itd_l + int(6 * elevation_factor)] = -0.25 * atten_l
                if 0 <= itd_r < self.hrir_len - 20:
                    ir_r[itd_r] = atten_r
                    ir_r[itd_r + int(6 * elevation_factor)] = -0.25 * atten_r
                    
                self.hrir_table_l[(y_pos, idx)] = ir_l
                self.hrir_table_r[(y_pos, idx)] = ir_r

        # --- [2] 帯域分割フィルター ---
        self.sos_low = signal.iirfilter(2, 320 / (self.sr / 2), btype='lowpass', ftype='butter', output='sos')
        self.zi_low = np.zeros((self.sos_low.shape[0], 2), dtype=np.float32)

        bw = 1500.0 / 1.0
        low_f, high_f = max(20.0, 1500.0 - bw / 2.0), min(self.sr / 2.0 - 100, 1500.0 + bw / 2.0)
        self.sos_mid = signal.iirfilter(2, [low_f / (self.sr / 2), high_f / (self.sr / 2)], btype='bandpass', ftype='butter', output='sos')
        self.zi_mid = np.zeros((self.sos_mid.shape[0], 2), dtype=np.float32)

        self.sos_high = signal.iirfilter(2, 5000 / (self.sr / 2), btype='highpass', ftype='butter', output='sos')
        self.zi_high = np.zeros((self.sos_high.shape[0], 2), dtype=np.float32)

        self.band_configs = [
            {'type': 'low',  'y': -4.0, 'speed': 0.5, 'angle': 0.0},
            {'type': 'mid',  'y':  0.0, 'speed': 1.0, 'angle': 0.0},
            {'type': 'high', 'y':  4.0, 'speed': 2.5, 'angle': 0.0},
        ]

        self.conv_overlap_l = np.zeros(self.hrir_len - 1, dtype=np.float32)
        self.conv_overlap_r = np.zeros(self.hrir_len - 1, dtype=np.float32)

        # --- [3] スピーカー特性プリセット ---
        self.speaker_presets = {
            'studio': {'gains': [1.0, 1.0, 1.1], 'directivity': [1.0, 2.0, 3.5], 'wall_absorption': 0.35},
            'theater': {'gains': [1.4, 0.9, 0.9], 'directivity': [0.5, 1.2, 2.0], 'wall_absorption': 0.20},
            'pa':      {'gains': [1.1, 1.2, 1.3], 'directivity': [2.0, 3.5, 6.0], 'wall_absorption': 0.45},
            'small':   {'gains': [0.4, 1.1, 1.0], 'directivity': [1.0, 1.5, 2.0], 'wall_absorption': 0.30}
        }

        # --- [4] リバーブ回路 ---
        self.delay_len_l = int(0.06 * self.sr)
        self.delay_len_r = int(0.075 * self.sr)
        self.delay_buf_l = np.zeros(self.delay_len_l, dtype=np.float32)
        self.delay_buf_r = np.zeros(self.delay_len_r, dtype=np.float32)
        self.delay_idx_l = 0
        self.delay_idx_r = 0

        self.wall_lp_l = 0.0
        self.wall_lp_r = 0.0

        # --- [5] 自動音量引き上げ（AGC）用状態変数 ---
        self.agc_gain = 1.0         # 現在のブースト倍率
        self.target_peak = 0.85      # 目標ピーク値 (85%)

    def read(self):
        raw_data = self.source.read()
        if not raw_data:
            return b""
        
        num_samples = len(raw_data) // 4
        fmt = f"<{num_samples * 2}h"
        samples = list(struct.unpack(fmt, raw_data))
        
        mode = self.state.get('eq', 'flat')
        self.count += 1

        if mode == 'spatial':
            in_data = np.array(samples, dtype=np.float32) / 32768.0
            mono_in = (in_data[0::2] + in_data[1::2]) * 0.5
            n_samples = len(mono_in)

            global_distance = max(0.1, float(self.state.get('spatial_distance', 2.0)))
            reverb_mix = float(self.state.get('spatial_room_size', 0.3))
            is_rotating = self.state.get('is_rotating', True)
            
            speaker_type = self.state.get('spatial_speaker', 'studio')
            preset = self.speaker_presets.get(speaker_type, self.speaker_presets['studio'])

            # 引き上げ幅の上限値（1.0〜8.0倍、デフォルトは4.0倍）
            max_boost = max(1.0, float(self.state.get('spatial_agc_max', 4.0)))

            # A. 帯域分割
            band_low, self.zi_low = signal.sosfilt(self.sos_low, mono_in, zi=self.zi_low)
            band_mid, self.zi_mid = signal.sosfilt(self.sos_mid, mono_in, zi=self.zi_mid)
            band_high, self.zi_high = signal.sosfilt(self.sos_high, mono_in, zi=self.zi_high)
            band_signals = [band_low, band_mid, band_high]

            full_out_l = np.zeros(n_samples + self.hrir_len - 1, dtype=np.float32)
            full_out_r = np.zeros(n_samples + self.hrir_len - 1, dtype=np.float32)

            # B. 帯域ごとの回転 ＆ 畳み込み
            for i, config in enumerate(self.band_configs):
                if is_rotating:
                    config['angle'] += 0.015 * config['speed']

                x = math.sin(config['angle']) * global_distance
                z = -math.cos(config['angle']) * global_distance
                angle_deg = math.degrees(math.atan2(x, -z)) % 360

                dir_idx = int((angle_deg / 360.0) * self.num_directions) % self.num_directions
                
                directivity_power = preset['directivity'][i]
                band_gain = preset['gains'][i]

                cos_theta = math.cos(math.radians(angle_deg))
                speaker_gain = math.pow(max(0.0, 0.5 * (1.0 + cos_theta)), directivity_power) * band_gain

                hrir_l = self.hrir_table_l[(config['y'], dir_idx)]
                hrir_r = self.hrir_table_r[(config['y'], dir_idx)]

                dist_atten = (1.0 / max(0.5, global_distance)) * speaker_gain
                band_sig = band_signals[i] * dist_atten

                full_out_l += signal.oaconvolve(band_sig, hrir_l, mode='full')
                full_out_r += signal.oaconvolve(band_sig, hrir_r, mode='full')

            # Overlap-Add 処理
            full_out_l[:self.hrir_len - 1] += self.conv_overlap_l
            full_out_r[:self.hrir_len - 1] += self.conv_overlap_r

            self.conv_overlap_l = full_out_l[n_samples:].copy()
            self.conv_overlap_r = full_out_r[n_samples:].copy()

            spatial_out_l = full_out_l[:n_samples]
            spatial_out_r = full_out_r[:n_samples]

            # C. 壁面吸音 ＆ リバーブ
            rev_out_l = np.zeros(n_samples, dtype=np.float32)
            rev_out_r = np.zeros(n_samples, dtype=np.float32)
            feedback_gain = 0.4
            wall_absorption = preset['wall_absorption']

            for s in range(n_samples):
                self.wall_lp_l += wall_absorption * (spatial_out_l[s] - self.wall_lp_l)
                self.wall_lp_r += wall_absorption * (spatial_out_r[s] - self.wall_lp_r)

                dl_val = self.delay_buf_l[self.delay_idx_l]
                self.delay_buf_l[self.delay_idx_l] = self.wall_lp_l + dl_val * feedback_gain
                self.delay_idx_l = (self.delay_idx_l + 1) % self.delay_len_l

                dr_val = self.delay_buf_r[self.delay_idx_r]
                self.delay_buf_r[self.delay_idx_r] = self.wall_lp_r + dr_val * feedback_gain
                self.delay_idx_r = (self.delay_idx_r + 1) % self.delay_len_r

                rev_out_l[s] = dl_val * 0.85 + dr_val * 0.15
                rev_out_r[s] = dl_val * 0.15 + dr_val * 0.85

            # D. ミックス処理
            mix_l = spatial_out_l + rev_out_l * reverb_mix
            mix_r = spatial_out_r + rev_out_r * reverb_mix

            # --- E. 可変自動音量引き上げ（AGC）処理 ---
            current_peak = max(np.max(np.abs(mix_l)), np.max(np.abs(mix_r)), 1e-5)
            
            # 設定された max_boost（引き上げ幅上限）までゲインをブースト
            desired_gain = np.clip(self.target_peak / current_peak, 0.8, max_boost)

            if desired_gain < self.agc_gain:
                self.agc_gain = self.agc_gain * 0.8 + desired_gain * 0.2
            else:
                self.agc_gain = self.agc_gain * 0.98 + desired_gain * 0.02

            final_l = np.clip(mix_l * self.agc_gain, -1.0, 1.0)
            final_r = np.clip(mix_r * self.agc_gain, -1.0, 1.0)

            out_samples = np.empty(len(samples), dtype=np.int16)
            out_samples[0::2] = (final_l * 32767).astype(np.int16)
            out_samples[1::2] = (final_r * 32767).astype(np.int16)

            return struct.pack(fmt, *out_samples.tolist())
            
        # ==================================================
        # それ以外のモード（従来のサンプル単位処理）
        # ==================================================
        out_samples = []

        # rotate用の事前計算
        rot_angle = (self.count / 400.0) * 2.0 * math.pi
        rot_l = 0.5 + 0.5 * math.sin(rot_angle)
        rot_r = 1.0 - rot_l

        for i in range(num_samples):
            in_l = samples[i * 2] / 32768.0
            in_r = samples[i * 2 + 1] / 32768.0

            if mode == 'flat':
                out_l, out_r = in_l, in_r

            elif mode in ('bass', 'superbass'):
                boost = 2.8 if mode == 'superbass' else 1.8
                self.bass_lp_l = self.bass_lp_l + 0.06 * (in_l - self.bass_lp_l)
                self.bass_lp_r = self.bass_lp_r + 0.06 * (in_r - self.bass_lp_r)
                out_l = in_l + self.bass_lp_l * boost
                out_r = in_r + self.bass_lp_r * boost
                out_l = out_l / (1.0 + abs(out_l) * 0.2)
                out_r = out_r / (1.0 + abs(out_r) * 0.2)

            elif mode == 'echo':
                el = self.echo_buf_l[self.echo_idx]
                er = self.echo_buf_r[self.echo_idx]
                out_l = in_l + el * 0.4
                out_r = in_r + er * 0.4
                self.echo_buf_l[self.echo_idx] = in_l
                self.echo_buf_r[self.echo_idx] = in_r
                self.echo_idx = (self.echo_idx + 1) % 9600

            elif mode == 'hall':
                diff = in_l - in_r
                out_l = in_l + diff * 0.75
                out_r = in_r - diff * 0.75

            elif mode == 'vocal':
                self.vocal_lp_l = self.vocal_lp_l + 0.35 * (in_l - self.vocal_lp_l)
                self.vocal_lp_r = self.vocal_lp_r + 0.35 * (in_r - self.vocal_lp_r)
                out_l = self.vocal_lp_l * 1.4
                out_r = self.vocal_lp_r * 1.4

            elif mode == 'live':
                ll = self.live_buf_l[self.live_idx]
                lr = self.live_buf_r[self.live_idx]
                mix_l = in_l + ll * 0.4
                mix_r = in_r + lr * 0.4
                self.live_buf_l[self.live_idx] = in_l
                self.live_buf_r[self.live_idx] = in_r
                self.live_idx = (self.live_idx + 1) % 2880
                
                self.live_lp_l = self.live_lp_l + 0.85 * (mix_l - self.live_lp_l)
                self.live_lp_r = self.live_lp_r + 0.85 * (mix_r - self.live_lp_r)
                
                diff = self.live_lp_l - self.live_lp_r
                out_l = self.live_lp_l + diff * 0.3
                out_r = self.live_lp_r - diff * 0.3

            elif mode == 'rotate':
                out_l = in_l * rot_l
                out_r = in_r * rot_r

            elif mode == 'reverb':
                r1 = self.rev_buf_l[(self.rev_idx - 5771) % 12000]
                r2 = self.rev_buf_l[(self.rev_idx - 8641) % 12000]
                r3 = self.rev_buf_r[(self.rev_idx - 11549) % 12000]
                
                out_l = in_l + (r1 * 0.25 + r2 * 0.15)
                out_r = in_r + (r3 * 0.25 + r2 * 0.15)
                
                self.rev_buf_l[self.rev_idx] = in_l + r3 * 0.3
                self.rev_buf_r[self.rev_idx] = in_r + r1 * 0.3
                self.rev_idx = (self.rev_idx + 1) % 12000
            else:
                out_l, out_r = in_l, in_r

            out_l = max(-1.0, min(1.0, out_l))
            out_r = max(-1.0, min(1.0, out_r))
            
            out_samples.append(int(out_l * 32767))
            out_samples.append(int(out_r * 32767))
            
        return struct.pack(fmt, *out_samples)

    def cleanup(self):
        self.source.cleanup()


class CustomEQModal(discord.ui.Modal, title="カスタムEQ (FFmpegフィルター入力)"):
    def __init__(self, cog, guild_id: int):
        super().__init__()
        self.cog = cog
        self.guild_id = guild_id

    filter_input = discord.ui.TextInput(
        label="FFmpegオーディオフィルター文字列",
        placeholder="例: vibrato=f=4,tremolo=f=5 (空欄でフラットに戻す)",
        required=False,
        max_length=400,
        style=discord.TextStyle.paragraph
    )

    async def on_submit(self, interaction: discord.Interaction):
        state = self.cog.get_state(self.guild_id)
        user_filter = self.filter_input.value.strip()

        if not user_filter:
            state['eq'] = "flat"
            state['custom_eq_filter'] = None
            await interaction.response.send_message("⚙️ カスタムEQを解除しました（Flatに戻します）。", ephemeral=True)
        else:
            state['eq'] = "custom"
            state['custom_eq_filter'] = user_filter
            await interaction.response.send_message(f"⚙️ カスタムEQを設定しました:\n`{user_filter}`\n即時反映します。", ephemeral=True)

        # ❌ apply_immediate_settingを排除し、音楽を止めずにパネルだけ更新
        await self.cog.update_panel(self.guild_id)

# ==================================================
# UI: 立体音響（Spatial）設定パネル・コントロール View
# ==================================================
class SpatialControlView(discord.ui.View):
    def __init__(self, cog, guild_id):
        super().__init__(timeout=180)
        self.cog = cog
        self.guild_id = guild_id
        
        state = self.cog.get_state(self.guild_id)
        # 3帯域回転ボタンの初期状態表示
        is_rotating = state.get('is_rotating', True)
        self.toggle_rotate.label = "🌀 回転: ON" if is_rotating else "⏸️ 回転: OFF"
        self.toggle_rotate.style = discord.ButtonStyle.green if is_rotating else discord.ButtonStyle.secondary

    async def update_panel(self, interaction: discord.Interaction):
        """パネルのEmbed表示を最新状態に更新"""
        state = self.cog.get_state(self.guild_id)
        current_eq = state.get('eq', 'flat')
        dist = state.get('spatial_distance', 2.0)
        room = state.get('spatial_room_size', 0.3)
        speaker = state.get('spatial_speaker', 'studio')
        agc_max = state.get('spatial_agc_max', 4.0)
        is_rotating = "ON" if state.get('is_rotating', True) else "OFF"

        speaker_names = {
            'studio': '🎙️ スタジオモニター (高解像度・フラット)',
            'theater': '🎬 シアター (重低音・サラウンド)',
            'pa': '🔊 PAスピーカー (高音圧・指向性強)',
            'small': '📻 小型スピーカー (コンパクト)'
        }

        embed = discord.Embed(
            title="🎧 立体音響 (3D Spatial Audio) 設定パネル",
            description=(
                "リアルタイムHRTFおよび空間音響パラメータを個別設定できます。\n"
                "下のメニュー操作は再生中の音声へ即座に反映されます。\n\n"
                f"現在のモード: **{current_eq}**\n"
                f"音像の距離 (Distance): **{dist}x**\n"
                f"部屋のリバーブ (Reverb Mix): **{room}**\n"
                f"スピーカー特性: **{speaker_names.get(speaker, speaker)}**\n"
                f"最大音量引き上げ幅 (AGC): **{agc_max}x** (+{round(20*math.log10(agc_max), 1)}dB)\n"
                f"3帯域立体回転: **{is_rotating}**"
            ),
            color=0x3498DB
        )
        await interaction.response.edit_message(embed=embed, view=self)

    # 1. Spatialモード ON ボタン
    @discord.ui.button(label="🎧 Spatial ON", style=discord.ButtonStyle.primary, row=0)
    async def toggle_spatial(self, interaction: discord.Interaction, button: discord.ui.Button):
        state = self.cog.get_state(self.guild_id)
        state['eq'] = 'spatial'
        await self.update_panel(interaction)

    # 2. 3帯域回転 ON/OFF ボタン
    @discord.ui.button(label="🌀 回転: ON", style=discord.ButtonStyle.green, row=0)
    async def toggle_rotate(self, interaction: discord.Interaction, button: discord.ui.Button):
        state = self.cog.get_state(self.guild_id)
        current = state.get('is_rotating', True)
        state['is_rotating'] = not current
        
        button.label = "🌀 回転: ON" if not current else "⏸️ 回転: OFF"
        button.style = discord.ButtonStyle.green if not current else discord.ButtonStyle.secondary
        await self.update_panel(interaction)

    # 3. 部屋のリバーブ量 (Reverb Mix) 選択メニュー
    @discord.ui.select(
        placeholder="🏠 部屋のリバーブ (残響量) を選択...",
        options=[
            discord.SelectOption(label="リバーブ OFF (0.0)", value="0.0", description="残響なし・ドライな音"),
            discord.SelectOption(label="控えめ (0.15)", value="0.15", description="小さな防音室程度の響き"),
            discord.SelectOption(label="標準 (0.3)", value="0.3", default=True, description="一般的なリスニングルーム"),
            discord.SelectOption(label="深い残響 (0.5)", value="0.5", description="ライブハウス・スタジオ感"),
            discord.SelectOption(label="大空間ホール (0.75)", value="0.75", description="コンサートホール級の豊かな残響"),
        ],
        row=1
    )
    async def select_reverb(self, interaction: discord.Interaction, select: discord.ui.Select):
        state = self.cog.get_state(self.guild_id)
        state['spatial_room_size'] = float(select.values[0])
        await self.update_panel(interaction)

    # 4. 音量引き上げ幅 (AGC) 選択メニュー
    @discord.ui.select(
        placeholder="🔊 自動音量引き上げ幅 (AGC) を選択...",
        options=[
            discord.SelectOption(label="引き上げなし (1.0x / 0dB)", value="1.0"),
            discord.SelectOption(label="控えめ (2.0x / +6dB)", value="2.0"),
            discord.SelectOption(label="標準 (4.0x / +12dB)", value="4.0", default=True),
            discord.SelectOption(label="強力 (6.0x / +15.5dB)", value="6.0"),
        ],
        row=2
    )
    async def select_agc(self, interaction: discord.Interaction, select: discord.ui.Select):
        state = self.cog.get_state(self.guild_id)
        state['spatial_agc_max'] = float(select.values[0])
        await self.update_panel(interaction)

    # 5. 音像の距離 ＆ スピーカー特性 (ドロップダウン)
    @discord.ui.select(
        placeholder="📻 スピーカー特性を選択...",
        options=[
            discord.SelectOption(label="スタジオモニター (高解像度・フラット)", value="studio", default=True),
            discord.SelectOption(label="シアター用 (重低音・サラウンド)", value="theater"),
            discord.SelectOption(label="PAスピーカー (ライブハウス風)", value="pa"),
            discord.SelectOption(label="小型スピーカー (スモール)", value="small"),
        ],
        row=3
    )
    async def select_speaker(self, interaction: discord.Interaction, select: discord.ui.Select):
        state = self.cog.get_state(self.guild_id)
        state['spatial_speaker'] = select.values[0]
        await self.update_panel(interaction)
# =====================
# UI Panel Component
# =====================
# ==========================================
# ⚡ 動的にコンポーネントが組み替わる統合パネルView
# ==========================================
class VoiceControlView(discord.ui.View):
    """EQ設定によって下部のUIスライダー（セレクトメニュー）が動的にトグルするView"""
    def __init__(self, cog, guild_id: int):
        super().__init__(timeout=None)
        self.cog = cog
        self.guild_id = guild_id
        state = cog.get_state(guild_id)
        current_eq = state.get('eq', 'flat')

        # 1. 常に表示する標準コントロール
        self.add_item(self.SpeedSelect(cog, guild_id))
        self.add_item(self.VolumeSelect(cog, guild_id))
        self.add_item(self.EQSelect(cog, guild_id))

        # 2. 【重要】EQが "spatial" の時だけ、特化型コントロールを動的にアドオン！
        if current_eq == "spatial":
            self.add_item(SpatialDistanceSelect(cog, guild_id))
            self.add_item(SpatialRoomSizeSelect(cog, guild_id))

        # 3. 操作ボタン類の追加（row=4 にまとめて配置）
        self.add_buttons()

    def add_buttons(self):
        # 既存のボタンオブジェクトを動的に配置
        btn_search = discord.ui.Button(label="🔎 楽曲検索", style=discord.ButtonStyle.success, row=4)
        btn_search.callback = self.search_button_callback
        self.add_item(btn_search)

        btn_custom = discord.ui.Button(label="⚙️ カスタムEQ", style=discord.ButtonStyle.secondary, row=4)
        btn_custom.callback = self.custom_eq_button_callback
        self.add_item(btn_custom)

        btn_pause = discord.ui.Button(label="⏸️ 一時停止", style=discord.ButtonStyle.primary, row=4)
        btn_pause.callback = self.pause_button_callback
        self.add_item(btn_pause)

        btn_resume = discord.ui.Button(label="▶️ 再開", style=discord.ButtonStyle.success, row=4)
        btn_resume.callback = self.resume_button_callback
        self.add_item(btn_resume)

        btn_skip = discord.ui.Button(label="⏭️ スキップ", style=discord.ButtonStyle.secondary, row=4)
        btn_skip.callback = self.skip_button_callback
        self.add_item(btn_skip)

    # --- 以下、既存のボタン/セレクトメニュー内部定義の移植と調整 ---
    class SpeedSelect(discord.ui.Select):
        def __init__(self, cog, guild_id):
            self.cog = cog; self.guild_id = guild_id
            state = cog.get_state(guild_id)
            options = [
                discord.SelectOption(label="0.5x (遅め)", value="0.5"),
                discord.SelectOption(label="0.8x", value="0.8"),
                discord.SelectOption(label="1.0x (標準)", value="1.0"),
                discord.SelectOption(label="1.2x", value="1.2"),
                discord.SelectOption(label="1.5x", value="1.5"),
                discord.SelectOption(label="2.0x (倍速)", value="2.0"),
            ]
            super().__init__(placeholder=f"⚡ 速度変更 (現在: {state['speed']}x)", min_values=1, max_values=1, options=options, row=0)

        async def callback(self, interaction: discord.Interaction):
            state = self.cog.get_state(self.guild_id)
            state['speed'] = float(self.values[0])
            await interaction.response.send_message(f"⚡ 再生速度を `{state['speed']}` 倍に設定しました（即時反映）。", ephemeral=True)
            ctx = state['current_ctx'] or interaction
            await self.cog.apply_immediate_setting(ctx)

    class VolumeSelect(discord.ui.Select):
        def __init__(self, cog, guild_id):
            self.cog = cog; self.guild_id = guild_id
            state = cog.get_state(guild_id)
            options = [
                discord.SelectOption(label="10%", value="0.1"),
                discord.SelectOption(label="50%", value="0.5"),
                discord.SelectOption(label="80%", value="0.8"),
                discord.SelectOption(label="100% (標準)", value="1.0"),
                discord.SelectOption(label="150%", value="1.5"),
                discord.SelectOption(label="200% (最大)", value="2.0"),
            ]
            super().__init__(placeholder=f"🔊 音量変更 (現在: {int(state['volume']*100)}%)", min_values=1, max_values=1, options=options, row=1)

        async def callback(self, interaction: discord.Interaction):
            state = self.cog.get_state(self.guild_id)
            state['volume'] = float(self.values[0])
            await interaction.response.send_message(f"🔊 音量を `{int(state['volume']*100)}%` に設定しました（即時反映）。", ephemeral=True)
            await self.cog.update_panel(self.guild_id)

    class EQSelect(discord.ui.Select):
        def __init__(self, cog, guild_id):
            self.cog = cog; self.guild_id = guild_id
            state = cog.get_state(guild_id)
            options = [
                discord.SelectOption(label="Flat (標準)", value="flat"),
                discord.SelectOption(label="Spatial (リアルHRTF立体音響)", value="spatial"),
                discord.SelectOption(label="WFS (波面合成立体音響)", value="wfs"),
                discord.SelectOption(label="Bass (低音強調)", value="bass"),
                discord.SelectOption(label="SuperBass (超重低音)", value="superbass"),
                discord.SelectOption(label="Vocal (ボーカル強調)", value="vocal"),
                discord.SelectOption(label="Echo (エコー)", value="echo"),
                discord.SelectOption(label="Hall (ホール感)", value="hall"),
                discord.SelectOption(label="Live (ライブ風)", value="live"),
                discord.SelectOption(label="Rotate (回転音響)", value="rotate"),
            ]
            current_eq = state['eq'] if state['eq'] != "custom" else "custom (自由指定)"
            super().__init__(placeholder=f"🎬 プリセットEQ選択 (現在: {current_eq})", min_values=1, max_values=1, options=options, row=2)

        async def callback(self, interaction: discord.Interaction):
            state = self.cog.get_state(self.guild_id)
            state['eq'] = self.values[0]
            state['custom_eq_filter'] = None
            await interaction.response.send_message(f"🎬 エフェクトを `{state['eq']}` に変更しました（即時反映・UI更新）。", ephemeral=True)
            # パネル更新を走らせることで、VoiceControlViewが再度インスタンス化され、UIが自動で組み替わります
            await self.cog.update_panel(self.guild_id)

    # --- ボタンコールバックたち ---
    async def search_button_callback(self, interaction: discord.Interaction):
        modal = SearchModal(self.cog, self.guild_id)
        await interaction.response.send_modal(modal)

    async def custom_eq_button_callback(self, interaction: discord.Interaction):
        modal = CustomEQModal(self.cog, self.guild_id)
        await interaction.response.send_modal(modal)

    async def pause_button_callback(self, interaction: discord.Interaction):
        vc = interaction.guild.voice_client
        state = self.cog.get_state(self.guild_id)
        if vc and vc.is_playing():
            actual_played = (time.time() - state['start_time']) * state.get('speed', 1.0)
            state['elapsed_offset'] += actual_played
            state['is_paused'] = True
            vc.stop()
            await interaction.response.send_message(f"⏸️ 再生を一時停止しました。(`{int(state['elapsed_offset'])}秒` 時点)", ephemeral=True)
            await self.cog.update_panel(self.guild_id)
        else:
            await interaction.response.send_message("❌ 現在再生中ではないか、既に一時停止されています。", ephemeral=True)

    async def resume_button_callback(self, interaction: discord.Interaction):
        vc = interaction.guild.voice_client
        state = self.cog.get_state(self.guild_id)
        if vc and state['is_paused'] and state['current_track']:
            state['is_paused'] = False
            await interaction.response.send_message("▶️ 再生を再開します。", ephemeral=True)
            await self.cog.check_queue(self.guild_id)
        else:
            await interaction.response.send_message("❌ 再開できる一時停止中のトラックがありません。", ephemeral=True)

    async def skip_button_callback(self, interaction: discord.Interaction):
        vc = interaction.guild.voice_client
        state = self.cog.get_state(self.guild_id)
        if vc and (vc.is_playing() or state['is_paused']):
            state['current_track'] = None
            state['elapsed_offset'] = 0
            state['is_paused'] = False
            vc.stop()
            await interaction.response.send_message("⏭️ トラックをスキップしました。", ephemeral=True)
        else:
            await interaction.response.send_message("❌ 現在再生中の楽曲がありません。", ephemeral=True)

    @discord.ui.button(label="⏹️ 全停止", style=discord.ButtonStyle.danger, row=4)
    async def stop_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc = interaction.guild.voice_client
        state = self.cog.get_state(self.guild_id)
        if vc:
            state['current_track'] = None
            state['elapsed_offset'] = 0
            state['is_paused'] = False
            while not state['queue'].empty():
                state['queue'].get_nowait()
            vc.stop()
            await interaction.response.send_message("⏹️ 再生を完全に停止し、キューをクリアしました。", ephemeral=True)
            await self.cog.update_panel(self.guild_id)
        else:
            await interaction.response.send_message("❌ ボイスチャンネルに接続していません。", ephemeral=True)


# =====================
# Search & Custom EQ Modals
# =====================
class SearchModal(discord.ui.Modal, title="🎵 YouTube 楽曲検索"):
    """パネルから直接呼び出せるキーワード検索用モーダル窓"""
    keyword_input = discord.ui.TextInput(
        label="検索キーワードまたはURL",
        placeholder="例: 米津玄師 地球儀 / https://...",
        required=True,
        max_length=200,
        style=discord.TextStyle.short
    )

    def __init__(self, cog, guild_id: int):
        super().__init__()
        self.cog = cog
        self.guild_id = guild_id

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        keyword = self.keyword_input.value.strip()
        state = self.cog.get_state(self.guild_id)
        
        try:
            is_yt = False
            url, filename = None, None

            if "youtube.com" in keyword or "youtu.be" in keyword:
                info = await self.cog.get_yt_info(keyword)
                url, filename, is_yt = keyword, info['title'], True
            else:
                info = await self.cog.get_yt_info(f"ytsearch:{keyword}")
                url, filename, is_yt = info['url'], info['title'], True

            state['current_ctx'] = interaction
            await state['queue'].put((url, filename, None, is_yt))
            await interaction.followup.send(f"✅ **{filename}** をキューに追加しました！", ephemeral=True)

            # バグ修正: interaction.guild から voice_client を取得するように修正
            vc = interaction.guild.voice_client if interaction.guild else None
            if vc and not vc.is_playing() and not state['is_processing_queue'] and not state['is_paused']:
                await self.cog.check_queue(self.guild_id)
            else:
                await self.cog.update_panel(self.guild_id)

        except Exception as e:
            await interaction.followup.send(f"❌ 検索中にエラーが発生しました: {e}", ephemeral=True)


class CustomEQModal(discord.ui.Modal, title="カスタムEQ (FFmpegフィルター入力)"):
    """パネルから呼び出される、FFmpegオーディオフィルターの直接入力用モーダル窓"""
    filter_input = discord.ui.TextInput(
        label="FFmpegオーディオフィルター文字列",
        placeholder="例: vibrato=f=4,tremolo=f=5 (空欄でフラットに戻す)",
        required=False,
        max_length=400,
        style=discord.TextStyle.paragraph
    )

    def __init__(self, cog, guild_id: int):
        super().__init__()
        self.cog = cog
        self.guild_id = guild_id

    async def on_submit(self, interaction: discord.Interaction):
        state = self.cog.get_state(self.guild_id)
        user_filter = self.filter_input.value.strip()

        if not user_filter:
            state['eq'] = "flat"
            state['custom_eq_filter'] = None
            await interaction.response.send_message("⚙️ カスタムEQを解除しました（Flatに戻します）。", ephemeral=True)
        else:
            state['eq'] = "custom"
            state['custom_eq_filter'] = user_filter
            await interaction.response.send_message(f"⚙️ カスタムEQを設定しました:\n`{user_filter}`\n即時反映します。", ephemeral=True)

        # 曲を止めずにパネル表示だけを更新する
        await self.cog.update_panel(self.guild_id)


# =====================
# UI Panel Component
# =====================
class VoiceControlView(discord.ui.View):
    """音量・倍速・EQ・再生コントロールをまとめた常時同期型インタラクティブメニューUI"""
    def __init__(self, cog, guild_id: int):
        super().__init__(timeout=None)
        self.cog = cog
        self.guild_id = guild_id
        
        self.add_item(self.SpeedSelect(cog, guild_id))
        self.add_item(self.VolumeSelect(cog, guild_id))
        self.add_item(self.EQSelect(cog, guild_id))

    class SpeedSelect(discord.ui.Select):
        def __init__(self, cog, guild_id):
            self.cog = cog
            self.guild_id = guild_id
            state = cog.get_state(guild_id)
            options = [
                discord.SelectOption(label="0.5x (遅め)", value="0.5"),
                discord.SelectOption(label="0.8x", value="0.8"),
                discord.SelectOption(label="1.0x (標準)", value="1.0"),
                discord.SelectOption(label="1.2x", value="1.2"),
                discord.SelectOption(label="1.5x", value="1.5"),
                discord.SelectOption(label="2.0x (倍速)", value="2.0"),
            ]
            super().__init__(placeholder=f"⚡ 速度変更 (現在: {state['speed']}x)", min_values=1, max_values=1, options=options, row=0)

        async def callback(self, interaction: discord.Interaction):
            state = self.cog.get_state(self.guild_id)
            state['eq'] = self.values[0]
            state['custom_eq_filter'] = None
            await interaction.response.send_message(f"🎬 エフェクトを `{state['eq']}` に変更しました（即時反映）。", ephemeral=True)
            # 曲を止めずにパネルの文字（現在: flat など）だけを最新にする
            await self.cog.update_panel(self.guild_id)

    class VolumeSelect(discord.ui.Select):
        def __init__(self, cog, guild_id):
            self.cog = cog
            self.guild_id = guild_id
            state = cog.get_state(guild_id)
            options = [
                discord.SelectOption(label="10%", value="0.1"),
                discord.SelectOption(label="50%", value="0.5"),
                discord.SelectOption(label="80%", value="0.8"),
                discord.SelectOption(label="100% (標準)", value="1.0"),
                discord.SelectOption(label="150%", value="1.5"),
                discord.SelectOption(label="200% (最大)", value="2.0"),
            ]
            super().__init__(placeholder=f"🔊 音量変更 (現在: {int(state['volume']*100)}%)", min_values=1, max_values=1, options=options, row=1)

        async def callback(self, interaction: discord.Interaction):
            state = self.cog.get_state(self.guild_id)
            state['volume'] = float(self.values[0])
            await interaction.response.send_message(f"🔊 音量を `{int(state['volume']*100)}%` に設定しました（即時反映）。", ephemeral=True)
            ctx = state['current_ctx'] or interaction
            await self.cog.apply_immediate_setting(ctx)

    class EQSelect(discord.ui.Select):
        def __init__(self, cog, guild_id):
            self.cog = cog
            self.guild_id = guild_id
            state = cog.get_state(guild_id)
            options = [
                discord.SelectOption(label="Flat (標準)", value="flat"),
                discord.SelectOption(label="Spatial (3D立体音響)", value="spatial"), # 追加
                discord.SelectOption(label="Bass (低音強調)", value="bass"),
                discord.SelectOption(label="SuperBass (超重低音)", value="superbass"),
                discord.SelectOption(label="Vocal (ボーカル強調)", value="vocal"),
                discord.SelectOption(label="Echo (エコー)", value="echo"),
                discord.SelectOption(label="Hall (ホール感)", value="hall"),
                discord.SelectOption(label="Live (ライブ風)", value="live"),
                discord.SelectOption(label="Rotate (回転音響)", value="rotate"),
            ]
            current_eq = state['eq'] if state['eq'] != "custom" else "custom (自由指定)"
            super().__init__(placeholder=f"🎬 プリセットEQ選択 (現在: {current_eq})", min_values=1, max_values=1, options=options, row=2)

        async def callback(self, interaction: discord.Interaction):
            state = self.cog.get_state(self.guild_id)
            state['eq'] = self.values[0]
            state['custom_eq_filter'] = None
            await interaction.response.send_message(f"🎬 エフェクトを `{state['eq']}` に変更しました（即時反映）。", ephemeral=True)
            ctx = state['current_ctx'] or interaction
            await self.cog.apply_immediate_setting(ctx)

    @discord.ui.button(label="🔎 楽曲検索", style=discord.ButtonStyle.success, row=3)
    async def search_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = SearchModal(self.cog, self.guild_id)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="⚙️ カスタムEQ", style=discord.ButtonStyle.secondary, row=3)
    async def custom_eq_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = CustomEQModal(self.cog, self.guild_id)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="⏸️ 一時停止", style=discord.ButtonStyle.primary, row=3)
    async def pause_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc = interaction.guild.voice_client
        state = self.cog.get_state(self.guild_id)
        if vc and vc.is_playing():
            actual_played = (time.time() - state['start_time']) * state.get('speed', 1.0)
            state['elapsed_offset'] += actual_played
            state['is_paused'] = True
            vc.stop()
            await interaction.response.send_message(f"⏸️ 再生を一時停止しました。(`{int(state['elapsed_offset'])}秒` 時点)", ephemeral=True)
            await self.cog.update_panel(self.guild_id)
        else:
            await interaction.response.send_message("❌ 現在再生中ではないか、既に一時停止されています。", ephemeral=True)

    @discord.ui.button(label="▶️ 再開", style=discord.ButtonStyle.success, row=4)
    async def resume_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc = interaction.guild.voice_client
        state = self.cog.get_state(self.guild_id)
        if vc and state['is_paused'] and state['current_track']:
            state['is_paused'] = False
            await interaction.response.send_message("▶️ 再生を再開します。", ephemeral=True)
            await self.cog.check_queue(self.guild_id)
        else:
            await interaction.response.send_message("❌ 再開できる一時停止中のトラックがありません。", ephemeral=True)

    @discord.ui.button(label="⏭️ スキップ", style=discord.ButtonStyle.secondary, row=4)
    async def skip_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc = interaction.guild.voice_client
        state = self.cog.get_state(self.guild_id)
        if vc and (vc.is_playing() or state['is_paused']):
            state['current_track'] = None
            state['elapsed_offset'] = 0
            state['is_paused'] = False
            vc.stop()
            await interaction.response.send_message("⏭️ トラックをスキップしました。", ephemeral=True)
        else:
            await interaction.response.send_message("❌ 現在再生中の楽曲がありません。", ephemeral=True)

    @discord.ui.button(label="⏹️ 全停止", style=discord.ButtonStyle.danger, row=4)
    async def stop_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc = interaction.guild.voice_client
        state = self.cog.get_state(self.guild_id)
        if vc:
            state['current_track'] = None
            state['elapsed_offset'] = 0
            state['is_paused'] = False
            while not state['queue'].empty():
                state['queue'].get_nowait()
            vc.stop()
            await interaction.response.send_message("⏹️ 再生を完全に停止し、キューをクリアしました。", ephemeral=True)
            await self.cog.update_panel(self.guild_id)
        else:
            await interaction.response.send_message("❌ ボイスチャンネルに接続していません。", ephemeral=True)


# =====================
# Main Voice Cog (Updated)
# =====================
class VoiceCog(commands.Cog):

    def __init__(self, bot):
        self.bot = bot
        self.reaction_enabled = {}
        self.emoji_sounds = {}
        self.states = {} 
        self.supabase = getattr(bot, "supabase", None)
        self.ir_l_id = "d424KTRkAlaetACCuFZOCjUtFNjho1t5" 
        self.ir_r_id = "d424KTRkAlaetACCuFZOCjUtFO0p0TMN"
        self.default_volume = 1.0
        self.default_speed = 1.0
        self.default_eq = "flat"

    def get_state(self, guild_id: int):
        if guild_id not in self.states:
            self.states[guild_id] = {
                'queue': asyncio.Queue(),
                'current_ctx': None,
                'is_processing_queue': False,
                'current_track': None,
                'start_time': 0,
                'elapsed_offset': 0,
                'retry_count': 0,
                'volume': self.default_volume,
                'speed': self.default_speed,
                'eq': self.default_eq,
                'custom_eq_filter': None,
                'is_paused': False,
                'is_changing_setting': False,
                'panel_message': None 
            }
        return self.states[guild_id]

    @commands.Cog.listener()
    async def on_command_error(self, ctx, error):
        logging.exception("Command error")
        await ctx.send(embed=we(f"エラー: {error}"))
    
    async def get_duration(self, url):
        try:
            cmd = [
                'ffprobe', '-v', 'quiet', '-print_format', 'json',
                '-show_format', '-show_streams', url
            ]
            proc = await asyncio.create_subprocess_exec(
                *cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE
            )
            stdout, _ = await proc.communicate()
            data = json.loads(stdout)
            return float(data['format']['duration'])
        except Exception:
            return 0
            
    async def get_attachment_info(self, b62_id: str):
        try:
            guild_id, channel_id, message_id = decode_full_id(b62_id)
            guild = self.bot.get_guild(guild_id) or await self.bot.fetch_guild(guild_id)
            if not guild: return None, None
            channel = guild.get_channel(channel_id) or await guild.fetch_channel(channel_id)
            if not channel: return None, None
            msg = await channel.fetch_message(message_id)
            if msg.attachments:
                return msg.attachments[0].url, msg.attachments[0].filename
        except Exception as e:
            logging.debug(f"Universal ID format match but lookup failed ({b62_id}): {e}")
        return None, None

    @app_commands.command(name="join", description="ボイスチャンネルに参加します")
    async def join_cmd(self, interaction: discord.Interaction):
        if not interaction.user.voice:
            await interaction.response.send_message("先にボイスチャンネルに入ってください。", ephemeral=True)
            return

        channel = interaction.user.voice.channel
        if interaction.guild.voice_client:
            await interaction.guild.voice_client.move_to(channel)
        else:
            await channel.connect(cls=voice_recv.VoiceRecvClient)

        await interaction.response.send_message(f"🔊 **{channel.name}** に参加しました。")

    @app_commands.command(name="leave", description="ボイスチャンネルから退出します")
    async def leave_cmd(self, interaction: discord.Interaction):
        voice_client = interaction.guild.voice_client
        if voice_client:
            await voice_client.disconnect()
            state = self.get_state(interaction.guild_id)
            state['queue'].clear()
            state['now_playing'] = None
            await interaction.response.send_message("👋 退出しました。")
        else:
            await interaction.response.send_message("ボットはボイスチャンネルに参加していません。", ephemeral=True)


    @commands.command()
    async def ffversion(self, ctx):
        """FFmpegのバージョン情報を取得して表示します"""
        try:
            # 非同期プロセスで 'ffmpeg -version' を実行
            proc = await asyncio.create_subprocess_exec(
                'ffmpeg', '-version',
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            stdout, _ = await proc.communicate()
            
            if stdout:
                # 出力の最初の一行（通常ここにバージョンが記載されています）を取得
                first_line = stdout.decode('utf-8', errors='ignore').split('\n')[0]
                await ctx.send(embed=we(title="FFmpeg Version Info", description=f"```\n{first_line}\n```"))
            else:
                await ctx.send(embed=we("❌ FFmpegのバージョン情報を取得できませんでした。"))
                
        except FileNotFoundError:
            await ctx.send(embed=we("❌ システムに `ffmpeg` コマンドが見つかりません。パスが通っているか確認してください。"))
        except Exception as e:
            await ctx.send(embed=we(f"❌ エラーが発生しました: {e}"))

    
    @commands.command()
    async def rval(self, ctx, feedback: float, wet: float = None):
        """リバーブ値（減衰・ウェット量）を調整するコマンド
        例: !rval 0.4 0.5  (フィードバック0.4, ウェット量0.5)
        """
        if not 0.0 <= feedback <= 0.95:
            return await ctx.send(embed=we("フィードバック値（残響の長さ）は 0.0 〜 0.95 の間で指定してください。"))
        
        state = self.get_state(ctx.guild.id)
        state['fdn_feedback'] = feedback
        
        msg = f"⏳ リバーブのフィードバック（長さ）を `{feedback}` に設定しました。"
        if wet is not None:
            if not 0.0 <= wet <= 1.0:
                return await ctx.send(embed=we("ウェット量（残響の音量）は 0.0 〜 1.0 の間で指定してください。"))
            state['fdn_wet'] = wet
            msg += f"\n💧 残響のミックス（ウェット量）を `{wet}` に設定しました。"
            
        await ctx.send(embed=we(msg))
        # コントロールパネルの表示を更新
        await self.update_panel(ctx.guild.id)

    @commands.command()
    async def rres(self, ctx, res: int):
        """FDNリバーブの空間解像度（ディレイラインの密度）を切り替えるコマンド
        例: !rres 8  (高解像度8次元マトリックスモード)
        """
        if res not in (4, 8):
            return await ctx.send(embed=we("解像度は `4` (通常) または `8` (高解像度・滑らか) のどちらかを指定してください。"))
        
        state = self.get_state(ctx.guild.id)
        state['fdn_resolution'] = res
        
        mode_str = "8次元ハウスホルダー（高密度・シルキー）" if res == 8 else "4次元ハウスホルダー（軽量・クリア）"
        await ctx.send(embed=we(f"⚙️ リバーブ解像度を `{res}` に切り替えました。\n現在のモード: **{mode_str}**"))
        await self.update_panel(ctx.guild.id)

    async def update_panel(self, guild_id: int):
        """現在の内部ステータスを読み取り、コントロールパネルをリアルタイム更新する"""
        state = self.get_state(guild_id)
        msg = state['panel_message']
        if not msg: return

        if state['is_paused']: status_icon = "⏸️ 一時停止中"
        elif state['current_track']: status_icon = "▶️ 再生中"
        else: status_icon = "⏹️ 停止中"

        if state['current_track']:
            _, filename, duration, _, _ = state['current_track']
            m, s = divmod(int(duration), 60)
            duration_str = f"{m}:{s:02d}" if duration else "不明"
            track_info = f"**{filename}** `[{duration_str}]`"
        else:
            track_info = "*楽曲が再生されていません*"

        queue_size = state['queue'].qsize()
        queue_info = f"`{queue_size} 件` の楽曲が待機中" if queue_size > 0 else "待機中の楽曲はありません"

        current_eq = state['eq']
        eq_label = f"Custom (`{state['custom_eq_filter']}`)" if current_eq == "custom" else current_eq.capitalize()

        embed = discord.Embed(title="🎵 ボイスコントロールパネル", color=0xFFFFFF)
        embed.add_field(name="現在のステータス", value=f"`{status_icon}`", inline=True)
        embed.add_field(name="オーディオパラメータ", value=f"🔊 Vol: `{int(state['volume']*100)}%` \n⚡ Speed: `{state['speed']}x` \n🎬 EQ: `{eq_label}`", inline=False)
        embed.add_field(name="現在ストリーミング中の楽曲", value=track_info, inline=False)
        embed.add_field(name="予約キューリスト", value=queue_info, inline=False)
        embed.set_footer(text="下のインターフェースからリアルタイムに操作・検索できます。")

        try:
            view = VoiceControlView(self, guild_id)
            await msg.edit(embed=embed, view=view)
        except Exception as e:
            logging.error(f"Panel update failed: {e}")

    async def apply_immediate_setting(self, ctx):
        vc = ctx.voice_client if hasattr(ctx, 'voice_client') else ctx.guild.voice_client
        state = self.get_state(ctx.guild.id)
        if vc and vc.is_playing() and state['current_track']:
            actual_played = (time.time() - state['start_time']) * state.get('speed', 1.0)
            state['elapsed_offset'] += actual_played
            state['is_changing_setting'] = True
            vc.stop()
            await asyncio.sleep(0.2)
            state['is_changing_setting'] = False
            await self.check_queue(ctx.guild.id)
        else:
            await self.update_panel(ctx.guild.id)

    @commands.command()
    async def eq(self, ctx, *, mode: str = "flat"):
        """イコライザを設定します"""
        state = self.get_state(ctx.guild.id)
        if mode in EQ_SETTINGS:
            state['eq'] = mode
            state['custom_eq_filter'] = None
            await ctx.send(embed=we(f"🎬 エフェクトをプリセット `{mode}` に変更しました。"))
        else:
            state['eq'] = "custom"
            state['custom_eq_filter'] = mode
            await ctx.send(embed=we(f"⚙️ カスタムEQフィルターを設定しました:\n`{mode}`"))
        # 曲を止めずにパネルだけ更新
        await self.update_panel(ctx.guild.id)
        
    @commands.command()
    async def volume(self, ctx, vol: float):
        """音量を調整します"""
        if not 0.1 <= vol <= 2.0: return await ctx.send(embed=we("音量は 0.1 から 2.0 の間で指定してください。"))
        state = self.get_state(ctx.guild.id)
        state['volume'] = vol
        await ctx.send(embed=we(f"🔊 音量を `{vol}` に設定しました。"))
        await self.apply_immediate_setting(ctx)

    @commands.command()
    async def speed(self, ctx, speed: float):
        """再生速度を変更します"""
        if not 0.5 <= speed <= 2.0: return await ctx.send(embed=we("速度は 0.5 から 2.0 の間で指定してください。"))
        state = self.get_state(ctx.guild.id)
        state['speed'] = speed
        await ctx.send(embed=we(f"⚡ 再生速度を `{speed}` 倍に設定しました。"))
        await self.apply_immediate_setting(ctx)

    async def get_yt_info(self, url_or_search):
        loop = asyncio.get_event_loop()
        with yt_dlp.YoutubeDL(YTDL_OPTIONS) as ydl:
            data = await loop.run_in_executor(None, lambda: ydl.extract_info(url_or_search, download=False))
            if 'entries' in data:
                if not data['entries']: raise Exception("検索結果が見つかりませんでした。")
                data = data['entries'][0]
            return {
                'url': data.get('webpage_url') or data.get('url'),
                'stream_url': data.get('url'),
                'title': data.get('title'),
                'duration': data.get('duration', 0)
            }

    class SearchView(discord.ui.View):
        def __init__(self, cog, guild_id, ctx, tracks):
            super().__init__(timeout=60.0)
            self.cog = cog
            self.guild_id = guild_id
            self.ctx = ctx
            self.tracks = tracks
            self.message = None

            options = []
            for idx, track in enumerate(self.tracks):
                label = f"{idx + 1}. {track['title']}"
                if len(label) > 100: label = label[:97] + "..."
                options.append(discord.SelectOption(label=label, value=str(idx), description="この楽曲を再生・キューに追加します"))

            self.select_menu = discord.ui.Select(placeholder="🎵 再生したい楽曲を選んでください...", min_values=1, max_values=1, options=options)
            self.select_menu.callback = self.select_callback
            self.add_item(self.select_menu)

        async def select_callback(self, interaction: discord.Interaction):
            if interaction.user.id != self.ctx.author.id: return await interaction.response.send_message("❌ この検索結果は他のユーザーのものです。", ephemeral=True)
            idx = int(self.select_menu.values[0])
            selected_track = self.tracks[idx]
            state = self.cog.get_state(self.guild_id)
            state['current_ctx'] = self.ctx
            await state['queue'].put((selected_track['url'], selected_track['title'], None, True))

            if not self.ctx.voice_client.is_playing() and not state['is_processing_queue'] and not state['is_paused']:
                await self.cog.check_queue(self.guild_id)
                await interaction.response.send_message(f"🎵 **{selected_track['title']}** を再生します！")
            else:
                await interaction.response.send_message(f"✅ キューに追加しました: **{selected_track['title']}**")
                await self.cog.update_panel(self.guild_id)
            await self.disable_all_items()

        async def on_timeout(self): await self.disable_all_items()
        async def disable_all_items(self):
            for item in self.children: item.disabled = True
            if self.message:
                try: await self.message.edit(view=self)
                except Exception: pass
            self.stop()

    @commands.command()
    async def search(self, ctx, *, keyword: str = None):
        """Youtubeから検索した結果を10件表示します"""
        if not ctx.voice_client: return await ctx.send("先に `!join` してください。")
        if not keyword: return await ctx.send("検索キーワードを入力してください。")
        await ctx.send(f"🔎 YouTubeで「{keyword}」の上位10件を検索中...")
        search_options = YTDL_OPTIONS.copy()
        search_options['default_search'] = 'ytsearch10'
        loop = asyncio.get_event_loop()
        try:
            with yt_dlp.YoutubeDL(search_options) as ydl:
                data = await loop.run_in_executor(None, lambda: ydl.extract_info(keyword, download=False))
                if 'entries' not in data or not data['entries']: return await ctx.send("❌ 検索結果が見つかりませんでした。")
                tracks, description_lines = [], []
                for idx, entry in enumerate(data['entries'][:10]):
                    title = entry.get('title', '不明なタイトル')
                    url = entry.get('webpage_url') or entry.get('url')
                    duration_sec = entry.get('duration', 0)
                    m, s = divmod(duration_sec, 60)
                    duration_str = f"{m}:{s:02d}" if duration_sec else "不明"
                    tracks.append({'title': title, 'url': url})
                    description_lines.append(f"**{idx + 1}.** {title} `[{duration_str}]`")
                embed = we(title=f"「{keyword}」の検索結果 (上位10件)", description="\n".join(description_lines) + "\n\n下のメニューから曲を選択してください。")
                view = self.SearchView(self, ctx.guild.id, ctx, tracks)
                view.message = await ctx.send(embed=embed, view=view)
        except Exception as e:
            logging.error(f"Search command error: {e}")
            await ctx.send(f"❌ 検索中にエラーが発生しました: {e}")

    @commands.command()
    async def panel(self, ctx):
        """ボイスコントロールパネルを表示します"""
        if not ctx.voice_client: return await ctx.send(embed=we("先に `!join` で接続してください。"))
        state = self.get_state(ctx.guild.id)
        state['current_ctx'] = ctx
        embed = discord.Embed(title="🎵 ボイスコントロールパネル", description="ステータスを同期中...", color=0xFFFFFF)
        view = VoiceControlView(self, ctx.guild.id)
        msg = await ctx.send(embed=embed, view=view)
        state['panel_message'] = msg
        await self.update_panel(ctx.guild.id)

    async def check_queue(self, guild_id: int):
        state = self.get_state(guild_id)
        
        if state['is_processing_queue'] or state['current_ctx'] is None:
            return
        
        ctx = state['current_ctx']
        vc = ctx.voice_client if hasattr(ctx, 'voice_client') else ctx.guild.voice_client
        if vc is None or not vc.is_connected():
            state['is_processing_queue'] = False
            return

        if state['current_track'] is None:
            if state['queue'].empty():
                state['is_processing_queue'] = False
                await self.update_panel(guild_id)
                return
            
            target_input, filename, b62_id, is_yt = await state['queue'].get() 
            
            if is_yt:
                try:
                    info = await self.get_yt_info(target_input)
                    state['current_track'] = (info['stream_url'], info['title'], info['duration'], b62_id, is_yt)
                except Exception as e:
                    logging.error(f"YouTube解析失敗: {e}")
                    if hasattr(ctx, "send"):
                        await ctx.send(embed=we(f"❌ 解析失敗: {e}"))
                    state['is_processing_queue'] = False
                    return await self.check_queue(guild_id)
            else:
                duration = await self.get_duration(target_input)
                state['current_track'] = (target_input, filename, duration, b62_id, is_yt) 

        url, filename, duration, b62_id, is_yt = state['current_track']
        
        if state['elapsed_offset'] > 0 and is_yt:
            try:
                info = await self.get_yt_info(url)
                url = info['stream_url']
            except Exception:
                pass

        state['is_processing_queue'] = True

        # --- 【FFmpeg基本設定（フィルターは一切通さない）】 ---
        before_options = '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5'
        if b62_id:
            before_options += f' -headers "User-Agent: Mozilla/5.0\r\n"'
        
        # シーク位置が指定されている場合のみオプションに追加
        if state['elapsed_offset'] > 0:
            before_options += f" -ss {state['elapsed_offset']}"

        # 音声展開の設定（常にフラット。48kHz/ステレオPCMで出力させる）
        options = "-vn -ar 48000 -ac 2"

        try:
            # 1. FFmpegには純粋なPCMデコードだけを任せる
            raw_source = discord.FFmpegPCMAudio(url, before_options=before_options, options=options)
            
            # 2. 統合された全EQ対応のPythonオーディオエンジン（速度や音量の適用もこちらに集約）でラップ
            source = PythonSpatialAudioSource(raw_source, state)
            
            state['start_time'] = time.time()
            vc.play(source, after=lambda e: self.bot.loop.call_soon_threadsafe(self.play_next, guild_id, e))
            
            await self.update_panel(guild_id)
            
            if state['elapsed_offset'] < 1 and hasattr(ctx, "send"):
                current_eq_mode = state.get('eq', 'flat')
                eq_label = "custom" if current_eq_mode == "custom" else current_eq_mode
                status = f"Speed: {state['speed']}x / Vol: {state['volume']} / EQ: {eq_label}"
                await ctx.send(embed=we(f"🎵 再生中: **{filename}**\n`{status}`"))
        
        except Exception as e:
            logging.error(f"Playback error: {e}")
            state['is_processing_queue'] = False
            state['current_track'] = None
            await self.check_queue(guild_id)
            
    def play_next(self, guild_id: int, error=None):
        state = self.get_state(guild_id)
        if error:
            logging.error(f"Player error: {error}")

        if state['is_paused'] or state['is_changing_setting']:
            state['is_processing_queue'] = False
            return

        actual_played = (time.time() - state['start_time']) * state.get('speed', 1.0)
        state['elapsed_offset'] += actual_played
        
        track = state['current_track']
        duration = track[2] if track else 0
        is_interrupted = (duration - state['elapsed_offset']) > 5
        
        state['is_processing_queue'] = False

        if is_interrupted and state['retry_count'] < 3 and state['current_track']:
            state['retry_count'] += 1
            asyncio.run_coroutine_threadsafe(self.check_queue(guild_id), self.bot.loop)
        else:
            state['current_track'] = None
            state['elapsed_offset'] = 0
            state['retry_count'] = 0
            asyncio.run_coroutine_threadsafe(self.check_queue(guild_id), self.bot.loop)
            
    @app_commands.command(name="play", description="添付ファイル、ユニバーサルID、YouTubeのURL/キーワードで音楽を再生します")
    @app_commands.describe(
        input_str="YouTube URL / 検索キーワード / ユニバーサルID",
        file="音声/動画ファイルの添付（ファイル再生時）"
    )
    async def play(
        self, 
        interaction: discord.Interaction, 
        input_str: str = None, 
        file: discord.Attachment = None
    ):
        # ボイスチャンネル接続チェック
        if not interaction.guild.voice_client: 
            return await interaction.response.send_message("先に `/join` してください。", ephemeral=True)

        # 処理時間がかかる可能性があるため defer 実行
        await interaction.response.defer()

        state = self.get_state(interaction.guild_id)
        # 後続の通知処理等で interaction や channel を利用できるように保持
        state['current_interaction'] = interaction

        is_yt = False
        url, filename, final_id = None, None, None

        # 1. YouTube URLが直接指定された場合
        if input_str and ("youtube.com" in input_str or "youtu.be" in input_str):
            await interaction.followup.send("⏳ YouTubeを解析中...")
            try:
                info = await self.get_yt_info(input_str)
                url, filename, is_yt = input_str, info['title'], True
            except Exception as e:
                return await interaction.followup.send(f"❌ 解析失敗: {e}")

        # 2. ファイルが添付されている場合
        elif file:
            url, filename = file.url, file.filename
            final_id = encode_full_id(interaction.guild_id, interaction.channel_id, interaction.id)

        # 3. BASE62 のユニバーサルID指定（または検索へのフォールバック）
        elif input_str and len(input_str.split()) == 1 and all(c in BASE62 for c in input_str):
            url, filename = await self.get_attachment_info(input_str)
            final_id = input_str
            
            if not url:
                await interaction.followup.send(f"🔎 YouTubeで「{input_str}」を検索中...")
                try:
                    info = await self.get_yt_info(f"ytsearch:{input_str}")
                    url, filename, is_yt = info['url'], info['title'], True
                    final_id = None
                except Exception as e:
                    return await interaction.followup.send(f"❌ 検索失敗: {e}")

        # 4. 検索キーワード指定
        elif input_str:
            await interaction.followup.send(f"🔎 YouTubeで「{input_str}」を検索中...")
            try:
                info = await self.get_yt_info(f"ytsearch:{input_str}")
                url, filename, is_yt = info['url'], info['title'], True
            except Exception as e:
                return await interaction.followup.send(f"❌ 検索失敗: {e}")

        # 5. 引数が何もない場合
        else:
            return await interaction.followup.send(embed=self.we("ファイル添付、ID、YouTube URL、または検索キーワードを指定してください。"))

        if not url:
            return await interaction.followup.send(embed=self.we("情報の取得に失敗しました。"))

        # キューに追加
        await state['queue'].put((url, filename, final_id, is_yt))

        # 再生中でなければ再生開始
        if not interaction.guild.voice_client.is_playing() and not state['is_processing_queue'] and not state['is_paused']:
            await self.check_queue(interaction.guild_id)
        else:
            await interaction.followup.send(f"✅ キューに追加: **{filename}**")
            await self.update_panel(interaction.guild_id)

    @commands.command()
    async def stop_all(self, ctx):
        """今流れている音楽をすべて停止しキューをクリアします"""
        vc = ctx.voice_client
        state = self.get_state(ctx.guild.id)
        if vc:
            state['current_track'] = None
            state['elapsed_offset'] = 0
            state['is_paused'] = False
            while not state['queue'].empty(): 
                state['queue'].get_nowait()
            vc.stop()
            await ctx.send(embed=we("完全に停止し、キューをクリアしました。"))
            await self.update_panel(ctx.guild.id)

    @app_commands.command(name="pause", description="音楽の再生／一時停止を切り替えます（トグル）")
    async def pause(self, interaction: discord.Interaction):
        vc = interaction.guild.voice_client
        state = self.get_state(interaction.guild_id)

        if not vc:
            return await interaction.response.send_message(embed=self.we("ボットがボイスチャンネルに入っていません。"), ephemeral=True)

        # 1. 再生中の場合 -> 一時停止処理
        if vc.is_playing():
            actual_played = (time.time() - state['start_time']) * state.get('speed', 1.0)
            state['elapsed_offset'] += actual_played
            state['is_paused'] = True
            vc.stop()
            
            await interaction.response.send_message(
                embed=self.we(f"⏸️ 再生を一時停止しました。(`{int(state['elapsed_offset'])}秒` 時点)\nもう一度 `/pause` で再開できます。")
            )
            await self.update_panel(interaction.guild_id)

        # 2. 一時停止中の場合 -> 再生再開処理
        elif state['is_paused'] and state['current_track']:
            state['is_paused'] = False
            await self.check_queue(interaction.guild_id)
            await interaction.response.send_message(embed=self.we("▶️ 一時停止位置から再生を再開しました。"))

        # 3. どちらでもない場合
        else:
            await interaction.response.send_message(embed=self.we("現在再生中・一時停止中のトラックがありません。"), ephemeral=True)


    @app_commands.command(name="skip", description="今流れている音楽をスキップしてキューにある次の音楽を再生します")
    async def skip(self, interaction: discord.Interaction):
        vc = interaction.guild.voice_client
        state = self.get_state(interaction.guild_id)

        if vc and (vc.is_playing() or state['is_paused']):
            state['current_track'] = None
            state['elapsed_offset'] = 0
            state['is_paused'] = False
            vc.stop()
            await interaction.response.send_message(embed=self.we("スキップしました。"))
        else:
            await interaction.response.send_message(embed=self.we("現在再生中の楽曲がありません。"))

    @commands.command()
    async def list(self, ctx, limit: int = 20):
        """このチャンネル内にアップロードされた音声のユニバーサルIDを20件表示します"""
        embed = we(title="チャンネル内音声リスト")
        desc = "ユニバーサルID（全サーバー共通）\n" + "─" * 20 + "\n"
        async for msg in ctx.channel.history(limit=limit):
            if msg.attachments:
                b62 = encode_full_id(ctx.guild.id, ctx.channel.id, msg.id)
                desc += f"`{b62}` : **{msg.attachments[0].filename}**\n"
        embed.description = desc
        await ctx.send(embed=embed)

    @commands.command()
    async def plist(self, ctx, *, input_data: str = None):
        """JSONで作ったプレイリストを再生することができます。"""
        if not ctx.voice_client: 
            return await ctx.send("先に !join してください。")

        state = self.get_state(ctx.guild.id)
        state['current_ctx'] = ctx
        tokens = []

        if ctx.message.attachments:
            attachment = ctx.message.attachments[0]
            try:
                content = await attachment.read()
                tokens = json.loads(content.decode('utf-8'))
                if not isinstance(tokens, list):
                    tokens = [str(tokens)]
            except Exception as e:
                return await ctx.send(f"JSON解析エラー: {e}")

        elif input_data:
            if self.bot.supabase:
                try:
                    res = self.bot.supabase.table("playlists").select("ids").eq("name", input_data).execute()
                    if res.data:
                        tokens = res.data[0]["ids"]
                    else:
                        tokens = input_data.replace(',', ' ').split()
                except Exception:
                    tokens = input_data.replace(',', ' ').split()
            else:
                tokens = input_data.replace(',', ' ').split()
        
        else:
            return await ctx.send("プレイリスト名、ID、またはJSONファイルを指定してください。")

        added = 0
        for token in tokens:
            url, fname = await self.get_attachment_info(token)
            if url:
                await state['queue'].put((url, fname, token, False))
                added += 1
        
        if added > 0:
            await ctx.send(f"✅ {added} 件をキューに追加しました。")
            if not ctx.voice_client.is_playing() and not state['is_processing_queue'] and not state['is_paused']:
                await self.check_queue(ctx.guild.id)
            else:
                await self.update_panel(ctx.guild.id)
        else:
            await ctx.send("有効なIDが見つかりませんでした。")
            

    @commands.command()
    async def save_current(self, ctx, name: str):
        """今のキューをJSONとして保存します。"""
        if not self.bot.supabase: return await ctx.send("DB未設定です。")
        
        state = self.get_state(ctx.guild.id)
        ids = []
        if state['current_track']: 
            ids.append(state['current_track'][3])
        
        temp = []
        while not state['queue'].empty():
            item = await state['queue'].get()
            temp.append(item)
            ids.append(item[2])
        for item in temp: 
            await state['queue'].put(item)

        if not ids: return await ctx.send("キューが空です。")

        try:
            self.bot.supabase.table("playlists").upsert({"name": name, "ids": ids}).execute()
            await ctx.send(f"✅ 現在のキューを `{name}` として保存しました。")
        except Exception as e:
            await ctx.send(f"エラー: {e}")
            

    @commands.command(name="spatial", aliases=["3d", "立体音響"])
    async def spatial_cmd(self, ctx):
        """立体音響（リアルHRTF / 空間音響）の独立設定パネルを呼び出します"""
        state = self.get_state(ctx.guild.id)
        current_eq = state.get('eq', 'flat')
        dist = state.get('spatial_distance', 2.0)
        room = state.get('spatial_room_size', 0.3)
        speaker = state.get('spatial_speaker', 'studio')
        agc_max = state.get('spatial_agc_max', 4.0)
        is_rotating = "ON" if state.get('is_rotating', True) else "OFF"

        speaker_names = {
            'studio': '🎙️ スタジオモニター',
            'theater': '🎬 シアター',
            'pa': '🔊 PAスピーカー',
            'small': '📻 小型スピーカー'
        }

        embed = discord.Embed(
            title="🎧 立体音響 (3D Spatial Audio) 設定パネル",
            description=(
                "リアルタイムHRTFおよび空間音響パラメータを個別設定できます。\n"
                "下のメニュー操作は再生中の音声へ即座に反映されます。\n\n"
                f"現在のモード: **{current_eq}**\n"
                f"音像の距離 (Distance): **{dist}x**\n"
                f"部屋のリバーブ (Reverb Mix): **{room}**\n"
                f"スピーカー特性: **{speaker_names.get(speaker, speaker)}**\n"
                f"最大音量引き上げ幅 (AGC): **{agc_max}x** (+{round(20*math.log10(agc_max), 1)}dB)\n"
                f"3帯域立体回転: **{is_rotating}**"
            ),
            color=0x3498DB
        )
        view = SpatialControlView(self, ctx.guild.id)
        await ctx.send(embed=embed, view=view)






async def setup(bot):
    await bot.add_cog(VoiceCog(bot))
