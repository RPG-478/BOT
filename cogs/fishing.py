import discord
from discord.ext import commands
from discord import app_commands
import random
import asyncio
import time
import math
from datetime import datetime

# --- プログラム内定数 (GitHub/Code管理) ---
BIOMES = {
    "sea": {
        "name": "海",
        "wait_range": (30, 120),
        "fish_pool": ["aji", "maguro", "suzuki"]
    },
    "river": {
        "name": "川",
        "wait_range": (20, 80),
        "fish_pool": ["ayu", "sake", "iwana"]
    },
    "pond": {
        "name": "池",
        "wait_range": (10, 60),
        "fish_pool": ["medaka", "koi", "funagi"]
    }
}

FISH_DATA = {
    "aji": {"name": "アジ", "rarity": 1, "max_hp": 50, "base_escape": 0.02, "price_range": (10, 20)},
    "maguro": {"name": "マグロ", "rarity": 5, "max_hp": 300, "base_escape": 0.12, "price_range": (500, 1200)},
    "suzuki": {"name": "スズキ", "rarity": 3, "max_hp": 120, "base_escape": 0.05, "price_range": (100, 250)},
    "ayu": {"name": "アユ", "rarity": 1, "max_hp": 40, "base_escape": 0.015, "price_range": (15, 30)},
    "sake": {"name": "サケ", "rarity": 3, "max_hp": 150, "base_escape": 0.06, "price_range": (120, 300)},
    "medaka": {"name": "メダカ", "rarity": 1, "max_hp": 10, "base_escape": 0.005, "price_range": (1, 5)},
    "koi": {"name": "コイ", "rarity": 2, "max_hp": 80, "base_escape": 0.04, "price_range": (50, 100)}
}

class FishingCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # セッション管理 {user_id: {"end_time": float, "is_active": bool}}
        self.waiting_sessions = {}
        # Supabaseクライアント（環境に合わせて初期化されている前提）
        # self.supabase = ... 

    def get_rod_power(self, level):
        """竿のレベルからダメージ期待値を算出"""
        return 10 + (level * 5)

    @app_commands.command(name="fish", description="釣り場を選択して釣りを開始します")
    @app_commands.describe(biome="釣りをする場所を選択してください")
    @app_commands.choices(biome=[
        app_commands.Choice(name=v["name"], value=k) for k, v in BIOMES.items()
    ])
    async def fish(self, interaction: discord.Interaction, biome: str):
        user_id = str(interaction.user.id)

        if user_id in self.waiting_sessions:
            await interaction.response.send_message("既に釣りの準備中、または格闘中です。", ephemeral=True)
            return

        await self._start_waiting_phase(interaction, biome)

    async def _start_waiting_phase(self, interaction, biome_id):
        user_id = str(interaction.user.id)
        biome = BIOMES[biome_id]
        wait_seconds = random.randint(*biome["wait_range"])
        
        # セッション情報の登録
        self.waiting_sessions[user_id] = {
            "end_time": time.time() + wait_seconds,
            "is_active": True
        }

        view = WaitingView(interaction.user.id, self)
        await interaction.response.send_message(
            f"【{biome['name']}】で糸を垂らしました... アタリを待っています。",
            view=view
        )

        # 待機ループ (揺らすボタンによる時間短縮をリアルタイム反映)
        while True:
            if user_id not in self.waiting_sessions:
                return # 中止された場合
            
            remaining = self.waiting_sessions[user_id]["end_time"] - time.time()
            if remaining <= 0:
                break
            
            await asyncio.sleep(1)

        # バトルフェーズへ移行
        await self._start_battle_phase(interaction, biome_id)

    async def _start_battle_phase(self, interaction, biome_id):
        user_id = str(interaction.user.id)
        if user_id not in self.waiting_sessions:
            return

        # 魚の抽選
        fish_key = random.choice(BIOMES[biome_id]["fish_pool"])
        fish_base = FISH_DATA[fish_key]
        
        # ユーザーデータの取得（モック: 本来はSupabaseから取得）
        # user_data = await self.supabase.table("user_fishing_stats").select("*").eq("user_id", user_id).single().execute()
        rod_level = 1 # デフォルト
        
        session_data = {
            "user_id": user_id,
            "fish_key": fish_key,
            "fish_name": fish_base["name"],
            "rarity": fish_base["rarity"],
            "max_hp": fish_base["max_hp"],
            "hp": fish_base["max_hp"],
            "base_escape": fish_base["base_escape"],
            "picks": 0,
            "rod_power": self.get_rod_power(rod_level),
            "biome_id": biome_id
        }

        view = FishingBattleView(session_data, self)
        await interaction.edit_original_response(
            content=f"❗ **アタリです！** \n出現: **{fish_base['name']}** (⭐{fish_base['rarity']})",
            view=view
        )

# --- View: 予約フェーズ用 ---
class WaitingView(discord.ui.View):
    def __init__(self, user_id, cog):
        super().__init__(timeout=None)
        self.user_id = str(user_id)
        self.cog = cog

    @discord.ui.button(label="竿を揺らす", style=discord.ButtonStyle.secondary)
    async def shake(self, interaction: discord.Interaction, button: discord.ui.Button):
        if str(interaction.user.id) != self.user_id:
            await interaction.response.send_message("自分の竿ではありません。", ephemeral=True)
            return

        if self.user_id in self.cog.waiting_sessions:
            reduction = random.randint(1, 4)
            self.cog.waiting_sessions[self.user_id]["end_time"] -= reduction
            
            # 残り時間を計算して表示
            remaining = max(0, int(self.cog.waiting_sessions[self.user_id]["end_time"] - time.time()))
            await interaction.response.send_message(f"竿を揺らした！ 残り約{remaining}秒", ephemeral=True)

    @discord.ui.button(label="釣りをやめる", style=discord.ButtonStyle.danger)
    async def stop(self, interaction: discord.Interaction, button: discord.ui.Button):
        if str(interaction.user.id) != self.user_id:
            await interaction.response.send_message("操作権限がありません。", ephemeral=True)
            return

        self.cog.waiting_sessions.pop(self.user_id, None)
        await interaction.response.edit_message(content="釣りを中止しました。", view=None)

# --- View: バトルフェーズ用 ---
class FishingBattleView(discord.ui.View):
    def __init__(self, session, cog):
        super().__init__(timeout=60)
        self.s = session
        self.cog = cog

    @discord.ui.button(label="Pick!", style=discord.ButtonStyle.primary)
    async def pick(self, interaction: discord.Interaction, button: discord.ui.Button):
        if str(interaction.user.id) != self.s["user_id"]:
            await interaction.response.send_message("これはあなたの獲物ではありません。", ephemeral=True)
            return

        self.s["picks"] += 1
        damage = random.randint(1, self.s["rod_power"])
        self.s["hp"] -= damage

        # 逃走確率計算: P = (BaseRarity * (Picks^1.5)) * (CurrentHP / MaxHP)
        hp_ratio = max(0, self.s["hp"]) / self.s["max_hp"]
        escape_prob = (self.s["base_escape"] * (self.s["picks"] ** 1.5)) * hp_ratio

        if random.random() < escape_prob and self.s["hp"] > 0:
            await self._finish_battle(interaction, f"不覚！ **{self.s['fish_name']}** は逃げてしまった...", success=False)
            return

        if self.s["hp"] <= 0:
            # Supabase保存処理 (非同期)
            # await self.cog.supabase.table("user_inventories").insert({
            #     "user_id": self.s["user_id"],
            #     "fish_key": self.s["fish_key"],
            #     "rarity": self.s["rarity"]
            # }).execute()
            
            await self._finish_battle(interaction, f"成功！ **{self.s['fish_name']}** を釣り上げた！", success=True)
        else:
            # HP状況を可視化（簡易ゲージ）
            bar_len = 10
            filled = round(bar_len * hp_ratio)
            gauge = "■" * filled + "□" * (bar_len - filled)
            
            await interaction.response.edit_message(
                content=f"格闘中... (HP: {max(0, self.s['hp'])} / {self.s['max_hp']})\n`{gauge}`",
            )

    async def _finish_battle(self, interaction, text, success):
        self.cog.waiting_sessions.pop(self.s["user_id"], None)
        view = RetryView(self.s["user_id"], self.s["biome_id"], self.cog)
        await interaction.response.edit_message(content=text, view=view)

# --- View: リザルト用 (もう一度釣る) ---
class RetryView(discord.ui.View):
    def __init__(self, user_id, biome_id, cog):
        super().__init__(timeout=60)
        self.user_id = user_id
        self.biome_id = biome_id
        self.cog = cog

    @discord.ui.button(label="もう一度釣る", style=discord.ButtonStyle.success)
    async def retry(self, interaction: discord.Interaction, button: discord.ui.Button):
        if str(interaction.user.id) != str(self.user_id):
            await interaction.response.send_message("本人しか再開できません。", ephemeral=True)
            return
        
        # 既存メッセージを更新して再開
        await self.cog._start_waiting_phase(interaction, self.biome_id)

async def setup(bot):
    await bot.add_cog(FishingCog(bot))

