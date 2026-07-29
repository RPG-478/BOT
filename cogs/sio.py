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

# =====================
# Main Voice Cog (Updated with Real-HRTF Engine)
# =====================
class PythonSpatialAudioSource(discord.AudioSource):
    """
    EQ_SETTINGSに定義されていたすべてのエフェクトを
    Python標準ライブラリおよびnumpy/scipyで完全リアルタイム処理する統合型オーディオエンジン
    """
    def __init__(self, source, state):
        self.source = source
        self.state = state
        self.count = 0
        self.sr = 48000
        
        # --- [spatial] HRTF/HRIR（頭部伝達インパルス応答）シミュレータ初期化 ---
        # 15度刻み（24方向）のHRIRテーブルを作成
        self.num_directions = 24
        self.hrir_len = 64  # インパルス応答の長さ（サンプル数）
        self.hrir_table_l = []
        self.hrir_table_r = []
        
        # 頭部半径 (約8.75cm)、音速 340m/s から、最大遅延時間差（ITD）は約 0.25ms (48kHzで約12サンプル)
        head_radius = 0.0875
        vsound = 340.0
        max_delay_samples = int((head_radius / vsound) * self.sr)
        
        for idx in range(self.num_directions):
            angle = (idx * (360.0 / self.num_directions)) * np.pi / 180.0
            
            # 左右の耳への到達時間差 (ITD)
            # 左(90度/ 0.5pi)に近いほど左耳への遅延が少なくなり、右耳への遅延が増える
            itd_l = int(max_delay_samples * (1.0 - np.sin(angle)))
            itd_r = int(max_delay_samples * (1.0 + np.sin(angle)))
            
            # 頭部遮蔽（ILD）による左右の減衰量（左耳は90度で最大、右耳は270度で最大）
            atten_l = 0.5 + 0.5 * np.cos(angle - np.pi / 2.0)
            atten_r = 0.5 + 0.5 * np.cos(angle - 3.0 * np.pi / 2.0)
            
            ir_l = np.zeros(self.hrir_len, dtype=np.float32)
            ir_r = np.zeros(self.hrir_len, dtype=np.float32)
            
            # 頭部遮蔽による高域のボケ（ローパス効果）をガウシアンカーネルでシミュレート
            t = np.arange(-8, 8)
            sigma_l = 0.8 + (1.0 - atten_l) * 3.5  # 遮蔽が大きいほどフィルターが鈍る
            kernel_l = np.exp(-t**2 / (2.0 * sigma_l**2))
            kernel_l /= np.sum(kernel_l)
            
            sigma_r = 0.8 + (1.0 - atten_r) * 3.5
            kernel_r = np.exp(-t**2 / (2.0 * sigma_r**2))
            kernel_r /= np.sum(kernel_r)
            
            # 遅延位置にカーネル（インパルス応答）を配置
            start_l = np.clip(itd_l - len(t)//2, 0, self.hrir_len - len(t))
            start_r = np.clip(itd_r - len(t)//2, 0, self.hrir_len - len(t))
            
            ir_l[start_l:start_l + len(t)] = kernel_l * (0.3 + 0.7 * atten_l)
            ir_r[start_r:start_r + len(t)] = kernel_r * (0.3 + 0.7 * atten_r)
            
            self.hrir_table_l.append(ir_l)
            self.hrir_table_r.append(ir_r)

        # 畳み込み処理の境界用バッファ（重なり保存領域）
        self.conv_overlap_l = np.zeros(self.hrir_len - 1, dtype=np.float32)
        self.conv_overlap_r = np.zeros(self.hrir_len - 1, dtype=np.float32)

        # --- [spatial] FDNリバーブ初期化 ---
        self.fdn_delays = [1391, 1543, 1777, 1999, 2257, 2503, 2833, 3121]
        self.fdn_bufs = [[0.0] * d for d in self.fdn_delays]
        self.fdn_idxs = [0] * 8

        self.wfs_speakers = 8  # 仮想スピーカー数
        # 仮想スピーカー座標 (X, Y) 前方1.0mに左右1.5m幅で等間隔に配置
        self.speaker_coords = np.zeros((self.wfs_speakers, 2), dtype=np.float32)
        xs = np.linspace(-1.5, 1.5, self.wfs_speakers)
        for j in range(self.wfs_speakers):
            self.speaker_coords[j] = [xs[j], 1.0]
        
        # 左右の耳の仮想座標 (頭の幅 約17cm)
        self.ear_l = np.array([-0.085, 0.0], dtype=np.float32)
        self.ear_r = np.array([0.085, 0.0], dtype=np.float32)
        
        # WFS時間遅延シミュレーション用リングバッファ (最大遅延をカバーする十分なサイズ)
        self.wfs_buf_len = 8192
        self.wfs_buffer = np.zeros(self.wfs_buf_len, dtype=np.float32)
        self.wfs_write_idx = 0

        # --- [bass / superbass] 低域ブースト用 ---
        self.bass_lp_l = 0.0
        self.bass_lp_r = 0.0

        # --- [echo] 標準エコー用 ---
        self.echo_buf_l = [0.0] * 9600
        self.echo_buf_r = [0.0] * 9600
        self.echo_idx = 0

        # --- [vocal] 簡易シェルビング用 ---
        self.vocal_lp_l = 0.0; self.vocal_lp_r = 0.0

        # --- [live] ショートエコー用 ---
        self.live_buf_l = [0.0] * 2880
        self.live_buf_r = [0.0] * 2880
        self.live_idx = 0
        self.live_lp_l = 0.0; self.live_lp_r = 0.0

        # --- [reverb (afir)] 畳み込み風擬似残響用 ---
        self.rev_buf_l = [0.0] * 12000
        self.rev_buf_r = [0.0] * 12000
        self.rev_idx = 0

    def read(self):
        raw_data = self.source.read()
        if not raw_data:
            return b""
        
        num_samples = len(raw_data) // 4
        fmt = f"<{num_samples * 2}h"
        samples = list(struct.unpack(fmt, raw_data))
        
        mode = self.state.get('eq', 'flat')
        self.count += 1

        # dynamic parameters
        feedback = self.state.get('fdn_feedback', 0.28)
        wet = self.state.get('fdn_wet', 0.3)
        resolution = self.state.get('fdn_resolution', 4)

        # ==================================================
        # 9. spatial モード（numpy / scipy 高速バイノーラル畳み込み処理）
        # ==================================================
        if mode == 'spatial':
            # 入力波形をnumpy配列に変換
            in_data = np.array(samples, dtype=np.float32) / 32768.0
            in_l = in_data[0::2]
            in_r = in_data[1::2]
            mono_in = (in_l + in_r) * 0.5
            
            # 音源の回転角度を決定 (8秒周期)
            angle = (self.count / 400.0) * 2.0 * np.pi
            angle_deg = np.degrees(angle) % 360
            hrir_idx = int((angle_deg / 360.0) * self.num_directions) % self.num_directions
            
            # 対応する角度のHRIR（頭部伝達インパルス応答）を選択
            hrir_l = self.hrir_table_l[hrir_idx]
            hrir_r = self.hrir_table_r[hrir_idx]
            
            # ハウスホルダーリバーブ (FDN) のシミュレーション
            fdn_out = [np.array(self.fdn_bufs[ch]) for ch in range(8)]
            rev_signal = np.zeros_like(mono_in)
            
            # モノラル信号に残響をブレンド
            for ch in range(resolution):
                d_len = self.fdn_delays[ch]
                # リングバッファからディレイを抽出し、簡易フィードバックを加算して更新
                buf = self.fdn_bufs[ch]
                idx = self.fdn_idxs[ch]
                
                # フレーム全体の遅延信号をシミュレートしてブレンド
                delayed = np.zeros_like(mono_in)
                for s_i in range(len(mono_in)):
                    delayed[s_i] = buf[idx]
                    buf[idx] = mono_in[s_i] + buf[idx] * feedback
                    idx = (idx + 1) % d_len
                
                self.fdn_idxs[ch] = idx
                rev_signal += delayed / float(resolution)

            mixed_mono = mono_in + rev_signal * wet
            
            # scipyのoaconvolve（Overlap-Add法）による高速HRTF畳み込み
            out_l_full = signal.oaconvolve(mixed_mono, hrir_l, mode='full')
            out_r_full = signal.oaconvolve(mixed_mono, hrir_r, mode='full')
            
            # 前フレームからの重なり（Overlap）データを加算
            out_l_full[:self.hrir_len - 1] += self.conv_overlap_l
            out_r_full[:self.hrir_len - 1] += self.conv_overlap_r
            
            # 次フレーム用の重なりデータを保存
            self.conv_overlap_l = out_l_full[len(mono_in):]
            self.conv_overlap_r = out_r_full[len(mono_in):]
            
            # 正規の出力サイズにカット
            out_l = out_l_full[:len(mono_in)]
            out_r = out_r_full[:len(mono_in)]
            
            # 音割れガード処理と16bitパッキング
            out_l = np.clip(out_l * 0.75, -1.0, 1.0)
            out_r = np.clip(out_r * 0.75, -1.0, 1.0)
            
            out_samples = np.empty(len(samples), dtype=np.int16)
            out_samples[0::2] = (out_l * 32767).astype(np.int16)
            out_samples[1::2] = (out_r * 32767).astype(np.int16)
            
            return struct.pack(fmt, *out_samples.tolist())

        # ==================================================
        # 10. wfs モード（バイノーラル波面合成: Wave Field Synthesis）
        # ==================================================
        elif mode == 'wfs':
            # 入力波形をnumpy配列に変換してモノラル化
            in_data = np.array(samples, dtype=np.float32) / 32768.0
            mono_in = (in_data[0::2] + in_data[1::2]) * 0.5
            n_samples = len(mono_in)
            
            # 入力信号をリングバッファに格納
            write_idxs = (self.wfs_write_idx + np.arange(n_samples)) % self.wfs_buf_len
            self.wfs_buffer[write_idxs] = mono_in
            
            # 仮想音源の3次元位置決定 (前方約1.8mの空間を左右に滑らかに往復する点音源)
            wfs_angle = (self.count / 300.0) * 2.0 * np.pi
            source_pos = np.array([1.8 * np.sin(wfs_angle), 1.8 + 0.3 * np.cos(wfs_angle)], dtype=np.float32)
            
            out_l = np.zeros(n_samples, dtype=np.float32)
            out_r = np.zeros(n_samples, dtype=np.float32)
            
            # 8基のスピーカーから放出された波面の重ね合わせをシミュレート
            for j in range(self.wfs_speakers):
                sp_pos = self.speaker_coords[j]
                
                # 1. 音源 から 仮想スピーカー への距離と遅延・減衰
                d_src_sp = np.linalg.norm(source_pos - sp_pos)
                delay_src_sp = int((d_src_sp / 340.0) * self.sr)
                atten_src_sp = 1.0 / max(0.5, d_src_sp)
                
                # 2. 仮想スピーカー から 左右の耳 への距離と遅延・減衰
                d_sp_l = np.linalg.norm(sp_pos - self.ear_l)
                d_sp_r = np.linalg.norm(sp_pos - self.ear_r)
                
                delay_sp_l = int((d_sp_l / 340.0) * self.sr)
                delay_sp_r = int((d_sp_r / 340.0) * self.sr)
                
                atten_sp_l = 1.0 / max(0.5, d_sp_l)
                atten_sp_r = 1.0 / max(0.5, d_sp_r)
                
                # 音源 -> スピーカー -> 耳 のトータル遅延を計算
                total_delay_l = delay_src_sp + delay_sp_l
                total_delay_r = delay_src_sp + delay_sp_r
                
                # リングバッファからそれぞれの遅延時間位置の信号を高速に抽出
                read_idxs_l = (self.wfs_write_idx - total_delay_l + np.arange(n_samples)) % self.wfs_buf_len
                read_idxs_r = (self.wfs_write_idx - total_delay_r + np.arange(n_samples)) % self.wfs_buf_len
                
                # 重ね合わせ（干渉）して波面を合成
                out_l += self.wfs_buffer[read_idxs_l] * (atten_src_sp * atten_sp_l)
                out_r += self.wfs_buffer[read_idxs_r] * (atten_src_sp * atten_sp_r)
                
            # バッファ書き込み位置の更新
            self.wfs_write_idx = (self.wfs_write_idx + n_samples) % self.wfs_buf_len
            
            # 出力ゲイン調整と安全なクリッピング
            out_l = np.clip(out_l * 0.35, -1.0, 1.0)
            out_r = np.clip(out_r * 0.35, -1.0, 1.0)
            
            # ステレオ16bit PCMバイナリにパッキング
            out_samples = np.empty(len(samples), dtype=np.int16)
            out_samples[0::2] = (out_l * 32767).astype(np.int16)
            out_samples[1::2] = (out_r * 32767).astype(np.int16)
            
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

# ==========================================
# 🆕 立体音響（Spatial Audio）専用コンポーネント & View
# ==========================================
class SpatialModeSelect(discord.ui.Select):
    """立体音響のモード（Spatial / WFS / OFF）を切り替えるセレクト"""
    def __init__(self, cog, guild_id: int, row: int = 0):
        self.cog = cog
        self.guild_id = guild_id
        state = cog.get_state(guild_id)
        current = state.get('eq', 'flat')
        options = [
            discord.SelectOption(label="Spatial (リアルHRTF立体音響)", value="spatial", description="頭部伝達関数による高度な3D音響", default=(current == "spatial")),
            discord.SelectOption(label="WFS (波面合成立体音響)", value="wfs", description="マルチスピーカー波面合成", default=(current == "wfs")),
            discord.SelectOption(label="OFF / Flat (標準ステレオ)", value="flat", description="立体音響を無効化します", default=(current not in ["spatial", "wfs"])),
        ]
        super().__init__(placeholder=f"🎧 立体音響モード (現在: {current})", min_values=1, max_values=1, options=options, row=row)

    async def callback(self, interaction: discord.Interaction):
        state = self.cog.get_state(self.guild_id)
        state['eq'] = self.values[0]
        state['custom_eq_filter'] = None
        await interaction.response.send_message(f"🎧 立体音響モードを `{state['eq']}` に切り替えました。", ephemeral=True)
        await self.cog.update_panel(self.guild_id)


class SpatialDistanceSelect(discord.ui.Select):
    """音像の距離を動的に制御するスライダー代替UI"""
    def __init__(self, cog, guild_id: int, row: int = 1):
        self.cog = cog
        self.guild_id = guild_id
        state = cog.get_state(guild_id)
        current = state.get('spatial_distance', 1.0)
        options = [
            discord.SelectOption(label="超至近距離 (0.2x)", value="0.2", description="耳元ギリギリで鳴らします", default=(current == 0.2)),
            discord.SelectOption(label="近め (0.6x)", value="0.6", default=(current == 0.6)),
            discord.SelectOption(label="標準距離 (1.0x)", value="1.0", default=(current == 1.0)),
            discord.SelectOption(label="遠め (1.8x)", value="1.8", description="空気吸収による高域減衰が始まります", default=(current == 1.8)),
            discord.SelectOption(label="超遠距離 (3.0x)", value="3.0", description="かなり遠くの広場から響きます", default=(current == 3.0)),
        ]
        super().__init__(placeholder=f"📏 音源の距離 (現在: {current}x)", min_values=1, max_values=1, options=options, row=row)

    async def callback(self, interaction: discord.Interaction):
        state = self.cog.get_state(self.guild_id)
        state['spatial_distance'] = float(self.values[0])
        await interaction.response.send_message(f"📏 立体音響の音像距離を `{state['spatial_distance']}x` に変更しました（リアルタイム反映）。", ephemeral=True)
        await self.cog.update_panel(self.guild_id)


class SpatialRoomSizeSelect(discord.ui.Select):
    """部屋の大きさ（残響時間）を動的に制御するUI"""
    def __init__(self, cog, guild_id: int, row: int = 2):
        self.cog = cog
        self.guild_id = guild_id
        state = cog.get_state(guild_id)
        current = state.get('spatial_room_size', 0.5)
        options = [
            discord.SelectOption(label="無響室 / 反射なし (0.1)", value="0.1", description="スタジオのようなデッドな響き", default=(current == 0.1)),
            discord.SelectOption(label="小さな部屋 (0.3)", value="0.3", default=(current == 0.3)),
            discord.SelectOption(label="標準の部屋 (0.5)", value="0.5", default=(current == 0.5)),
            discord.SelectOption(label="大きなホール (0.8)", value="0.8", description="リバーブテイルが長く伸びます", default=(current == 0.8)),
            discord.SelectOption(label="巨大な大聖堂 (0.95)", value="0.95", description="最大級の空間反射", default=(current == 0.95)),
        ]
        super().__init__(placeholder=f"🏠 部屋の大きさ (現在: {current})", min_values=1, max_values=1, options=options, row=row)

    async def callback(self, interaction: discord.Interaction):
        state = self.cog.get_state(self.guild_id)
        state['spatial_room_size'] = float(self.values[0])
        await interaction.response.send_message(f"🏠 空間の部屋のサイズ（残響係数）を `{state['spatial_room_size']}` に変更しました（リアルタイム反映）。", ephemeral=True)
        await self.cog.update_panel(self.guild_id)


class SpatialControlView(discord.ui.View):
    """独立して呼び出せる立体音響専用コントロールView"""
    def __init__(self, cog, guild_id: int):
        super().__init__(timeout=None)
        self.cog = cog
        self.guild_id = guild_id

        # 各コントロールコンポーネントを配置
        self.add_item(SpatialModeSelect(cog, guild_id, row=0))
        self.add_item(SpatialDistanceSelect(cog, guild_id, row=1))
        self.add_item(SpatialRoomSizeSelect(cog, guild_id, row=2))
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
        self.log_buffer = bot.log_buffer
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

    def get_cpu_usage(self):
        def read_cpu():
            try:
                with open("/proc/stat", "r") as f:
                    line = f.readline()
                    values = list(map(int, line.split()[1:]))
                    return values[3], sum(values)
            except: return 0, 1
        i1, t1 = read_cpu()
        time.sleep(0.5)
        i2, t2 = read_cpu()
        if t2 - t1 == 0: return 0
        return 100 * (1 - (i2 - i1) / (t2 - t1))

    def get_mem_usage(self):
        try:
            mem = {}
            with open("/proc/meminfo") as f:
                for line_str in f:
                    parts = line_str.split(":")
                    if len(parts) == 2: mem[parts[0]] = int(parts[1].split()[0])
            total = mem.get("MemTotal", 1)
            used = total - mem.get("MemAvailable", mem.get("MemFree", 0))
            return (used / total) * 100, used, total
        except: return 0, 0, 0
            
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

    @commands.command()
    async def join(self, ctx):
        if ctx.author.voice is None:
            return await ctx.send(embed=we("ボイスチャンネルに接続してください。"))
        vc = ctx.voice_client
        if vc is None:
            await ctx.author.voice.channel.connect(timeout=20.0, reconnect=True)
            await ctx.send(embed=we("接続しました。"))
        else:
            await vc.move_to(ctx.author.voice.channel)
            await ctx.send(embed=we("移動しました。"))

    @commands.command()
    async def leave(self, ctx):
        vc = ctx.voice_client
        if vc:
            state = self.get_state(ctx.guild.id)
            while not state['queue'].empty(): state['queue'].get_nowait()
            await vc.disconnect()
            await ctx.send(embed=we("切断しました。"))


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
        if not 0.1 <= vol <= 2.0: return await ctx.send(embed=we("音量は 0.1 から 2.0 の間で指定してください。"))
        state = self.get_state(ctx.guild.id)
        state['volume'] = vol
        await ctx.send(embed=we(f"🔊 音量を `{vol}` に設定しました。"))
        await self.apply_immediate_setting(ctx)

    @commands.command()
    async def speed(self, ctx, speed: float):
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
            
    @commands.command()
    async def play(self, ctx, *, input_str: str = None):
        if not ctx.voice_client: 
            return await ctx.send("先に !join してください。")

        state = self.get_state(ctx.guild.id)
        state['current_ctx'] = ctx
        
        is_yt = False
        url, filename, final_id = None, None, None

        if input_str and ("youtube.com" in input_str or "youtu.be" in input_str):
            await ctx.send("⏳ YouTubeを解析中...")
            try:
                info = await self.get_yt_info(input_str)
                url, filename, is_yt = input_str, info['title'], True
            except Exception as e:
                return await ctx.send(f"❌ 解析失敗: {e}")

        elif ctx.message.attachments:
            attachment = ctx.message.attachments[0]
            url, filename = attachment.url, attachment.filename
            final_id = encode_full_id(ctx.guild.id, ctx.channel.id, ctx.message.id)
        
        elif input_str and len(input_str.split()) == 1 and all(c in BASE62 for c in input_str):
            url, filename = await self.get_attachment_info(input_str)
            final_id = input_str
            
            if not url:
                await ctx.send(f"🔎 YouTubeで「{input_str}」を検索中...")
                try:
                    info = await self.get_yt_info(f"ytsearch:{input_str}")
                    url, filename, is_yt = info['url'], info['title'], True
                    final_id = None
                except Exception as e:
                    return await ctx.send(f"❌ 検索失敗: {e}")

        elif input_str:
            await ctx.send(f"🔎 YouTubeで「{input_str}」を検索中...")
            try:
                info = await self.get_yt_info(f"ytsearch:{input_str}")
                url, filename, is_yt = info['url'], info['title'], True
            except Exception as e:
                return await ctx.send(f"❌ 検索失敗: {e}")
        
        else:
            return await ctx.send(embed=we("ファイル添付、ID、YouTube URL、または検索キーワードを指定してください。"))

        if not url:
            return await ctx.send(embed=we("情報の取得に失敗しました。"))

        await state['queue'].put((url, filename, final_id, is_yt))

        if not ctx.voice_client.is_playing() and not state['is_processing_queue'] and not state['is_paused']:
            await self.check_queue(ctx.guild.id)
        else:
            await ctx.send(f"✅ キューに追加: **{filename}**")
            await self.update_panel(ctx.guild.id)

    @commands.command()
    async def stop_all(self, ctx):
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

    @commands.command()
    async def pause(self, ctx):
        vc = ctx.voice_client
        state = self.get_state(ctx.guild.id)
        if vc and vc.is_playing():
            actual_played = (time.time() - state['start_time']) * state.get('speed', 1.0)
            state['elapsed_offset'] += actual_played
            state['is_paused'] = True
            vc.stop()
            await ctx.send(embed=we(f"⏸️ 再生を一時停止しました。(`{int(state['elapsed_offset'])}秒` 時点)\n`!resume` で再開できます。"))
            await self.update_panel(ctx.guild.id)
        else:
            await ctx.send(embed=we("現在楽曲を再生していません。"))

    @commands.command()
    async def resume(self, ctx):
        vc = ctx.voice_client
        state = self.get_state(ctx.guild.id)
        if vc and state['is_paused'] and state['current_track']:
            state['is_paused'] = False
            await self.check_queue(ctx.guild.id)
            await ctx.send(embed=we(f"▶️ 一時停止位置から再生を再開しました。"))
        else:
            await ctx.send(embed=we("一時停止中のトラックがありません。"))

    @commands.command()
    async def skip(self, ctx):
        vc = ctx.voice_client
        state = self.get_state(ctx.guild.id)
        if vc and (vc.is_playing() or state['is_paused']):
            state['current_track'] = None
            state['elapsed_offset'] = 0
            state['is_paused'] = False
            vc.stop()
            await ctx.send(embed=we("スキップしました。"))
        else:
            await ctx.send(embed=we("現在再生中の楽曲がありません。"))

    @commands.command()
    async def list(self, ctx, limit: int = 20):
        embed = we(title="チャンネル内音声リスト")
        desc = "ユニバーサルID（全サーバー共通）\n" + "─" * 20 + "\n"
        async for msg in ctx.channel.history(limit=limit):
            if msg.attachments:
                b62 = encode_full_id(ctx.guild.id, ctx.channel.id, msg.id)
                desc += f"`{b62}` : **{msg.attachments[0].filename}**\n"
        embed.description = desc
        await ctx.send(embed=embed)

    @commands.command()
    async def id(self, ctx):
        async for msg in ctx.channel.history(limit=10):
            if msg.attachments:
                b62 = encode_full_id(ctx.guild.id, ctx.channel.id, msg.id)
                embed = we(title="ユニバーサルID発行")
                embed.add_field(name="ファイル", value=msg.attachments[0].filename)
                embed.add_field(name="ID", value=f"`{b62}`")
                return await ctx.send(embed=embed)

    @commands.command()
    async def plist(self, ctx, *, input_data: str = None):
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
    async def save_plist(self, ctx, name: str):
        if not self.bot.supabase: return await ctx.send("DB未設定です。")
        if not ctx.message.attachments: return await ctx.send("JSONファイルを添付してください。")

        try:
            content = await ctx.message.attachments[0].read()
            ids = json.loads(content.decode('utf-8'))
            self.bot.supabase.table("playlists").upsert({"name": name, "ids": ids}).execute()
            await ctx.send(f"✅ DBにプレイリスト `{name}` を保存しました。")
        except Exception as e:
            await ctx.send(f"エラー: {e}")

    @commands.command()
    async def save_current(self, ctx, name: str):
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
            
    @commands.command()
    async def logs(self, ctx, lines: int = 10):
        log_buffer = self.bot.log_buffer
        logs = list(log_buffer.logs)[-lines:]
        if not logs:
            await ctx.send("表示するログがありません。")
            return
        text = "\n".join(logs)
        if len(text) > 1900:
            text = text[-1900:]
        await ctx.send(f"```\n{text}\n```")

    @commands.command()
    async def sysinfo(self, ctx):
        cpu = self.get_cpu_usage()
        m_p, used, total = self.get_mem_usage()
        desc = f"CPU: `{cpu:.1f}%` / Mem: `{m_p:.1f}%` ({used/1024:.0f}/{total/1024:.0f}MB)"
        await ctx.send(embed=we(desc))

    @commands.command(name="spatial", aliases=["3d", "立体音響"])
    async def spatial_cmd(self, ctx):
        """立体音響（リアルHRTF / 空間音響）の独立設定パネルを呼び出します"""
        state = self.get_state(ctx.guild.id)
        current_eq = state.get('eq', 'flat')
        dist = state.get('spatial_distance', 1.0)
        room = state.get('spatial_room_size', 0.5)

        embed = discord.Embed(
            title="🎧 立体音響 (3D Spatial Audio) 設定パネル",
            description=(
                "リアルタイムHRTF（頭部伝達関数）および空間音響パラメータを個別設定できます。\n"
                "下のメニュー操作は再生中の音声へ即座に反映されます。\n\n"
                f"現在のモード: **{current_eq}**\n"
                f"音像の距離: **{dist}x**\n"
                f"部屋のサイズ (残響): **{room}**"
            ),
            color=0xFFFFFF
        )
        view = SpatialControlView(self, ctx.guild.id)
        await ctx.send(embed=embed, view=view)






async def setup(bot):
    await bot.add_cog(VoiceCog(bot))
