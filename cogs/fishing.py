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
    "aji": {"name": "アジ", "rarity": 1, "max_hp": 50, "base_escape": 0.02},
    "maguro": {"name": "マグロ", "rarity": 5, "max_hp": 300, "base_escape": 0.12},
    "suzuki": {"name": "スズキ", "rarity": 3, "max_hp": 120, "base_escape": 0.05},
    "ayu": {"name": "アユ", "rarity": 1, "max_hp": 40, "base_escape": 0.015},
    "sake": {"name": "サケ", "rarity": 3, "max_hp": 150, "base_escape": 0.06},
    "medaka": {"name": "メダカ", "rarity": 1, "max_hp": 10, "base_escape": 0.005},
    "koi": {"name": "コイ", "rarity": 2, "max_hp": 80, "base_escape": 0.04}
}

class FishingCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # セッション管理 {user_id: {"end_time": float, "status": str, "main_interaction": Interaction}}
        self.active_sessions = {}

    def get_rod_power(self, level):
        """竿のレベルからダメージ期待値を算出"""
        return 10 + (level * 5)

    @app_commands.command(name="fish", description="釣り場を選択して釣りを開始します")
    @app_commands.describe(biome="釣り場を選択してください")
    @app_commands.choices(biome=[
        app_commands.Choice(name=v["name"], value=k) for k, v in BIOMES.items()
    ])
    async def fish(self, interaction: discord.Interaction, biome: str):
        user_id = str(interaction.user.id)

        if user_id in self.active_sessions:
            await interaction.response.send_message("既に釣りを行っています。", ephemeral=True)
            return

        await self._start_waiting_phase(interaction, biome)

    async def _start_waiting_phase(self, interaction, biome_id):
        user_id = str(interaction.user.id)
        biome = BIOMES[biome_id]
        wait_seconds = random.randint(*biome["wait_range"])
        
        self.active_sessions[user_id] = {
            "end_time": time.time() + wait_seconds,
            "status": "waiting",
            "main_interaction": interaction,
            "biome_id": biome_id
        }

        view = WaitingView(interaction.user.id, self)
        await interaction.response.send_message(
            f"【{biome['name']}】で糸を垂らしました... アタリを待っています。",
            view=view
        )

        # 待機ループ
        while True:
            if user_id not in self.active_sessions or self.active_sessions[user_id]["status"] != "waiting":
                return
            
            if time.time() >= self.active_sessions[user_id]["end_time"]:
                break
            
            await asyncio.sleep(1)

        await self._trigger_hit(user_id)

    async def _trigger_hit(self, user_id):
        """アタリ発生通知（別メッセージ送信）"""
        if user_id not in self.active_sessions:
            return

        session = self.active_sessions[user_id]
        session["status"] = "hit_pending"
        interaction = session["main_interaction"]

        # 通知用の新規メッセージを別枠で送信
        view = HitConfirmView(user_id, self)
        hit_msg = await interaction.channel.send(
            content=f"{interaction.user.mention} ❗ **アタリです！竿が強く引かれています！**\n（5秒以内に『あわせる』を押してください）",
            view=view
        )
        
        # 5秒待機
        await asyncio.sleep(5)
        
        # 5秒後、まだhit_pending状態ならタイムアウト処理
        if user_id in self.active_sessions and self.active_sessions[user_id]["status"] == "hit_pending":
            self.active_sessions.pop(user_id, None)
            
            # アタリメッセージを削除
            try:
                await hit_msg.delete()
            except:
                pass
            
            # メインメッセージを逃走表示に更新
            retry_view = RetryView(user_id, session["biome_id"], self)
            await interaction.edit_original_response(
                content=f"魚に逃げられてしまいました...（反応がありませんでした）",
                view=retry_view
            )

    async def start_battle(self, user_id, hit_msg):
        """あわせる成功時。アタリメッセージを削除し、メインメッセージでバトル開始"""
        if user_id not in self.active_sessions:
            return

        session = self.active_sessions[user_id]
        session["status"] = "battling"
        interaction = session["main_interaction"]
        biome_id = session["biome_id"]

        # アタリメッセージを即座に削除
        try:
            await hit_msg.delete()
        except:
            pass

        # 魚の選出とバトルデータ準備
        fish_key = random.choice(BIOMES[biome_id]["fish_pool"])
        fish = FISH_DATA[fish_key]
        rod_level = 1 # 仮
        
        battle_data = {
            "user_id": user_id,
            "fish_key": fish_key,
            "fish_name": fish["name"],
            "rarity": fish["rarity"],
            "max_hp": fish["max_hp"],
            "hp": fish["max_hp"],
            "base_escape": fish["base_escape"],
            "picks": 0,
            "rod_power": self.get_rod_power(rod_level),
            "biome_id": biome_id
        }

        view = FishingBattleView(battle_data, self)
        await interaction.edit_original_response(
            content=f"🎣 **格闘開始！** \n出現: **{fish['name']}** (⭐{fish['rarity']})",
            view=view
        )

# --- View: 待機用 (メインメッセージ) ---
class WaitingView(discord.ui.View):
    def __init__(self, user_id, cog):
        super().__init__(timeout=None)
        self.user_id = str(user_id)
        self.cog = cog

    @discord.ui.button(label="竿を揺らす", style=discord.ButtonStyle.secondary)
    async def shake(self, interaction: discord.Interaction, button: discord.ui.Button):
        if str(interaction.user.id) != self.user_id:
            await interaction.response.defer()
            return

        if self.user_id in self.cog.active_sessions:
            # 内部的に短縮
            self.cog.active_sessions[self.user_id]["end_time"] -= random.randint(1, 4)
            await interaction.response.defer()

    @discord.ui.button(label="中止", style=discord.ButtonStyle.danger)
    async def stop(self, interaction: discord.Interaction, button: discord.ui.Button):
        if str(interaction.user.id) != self.user_id:
            await interaction.response.defer()
            return
        self.cog.active_sessions.pop(self.user_id, None)
        await interaction.response.edit_message(content="釣りを中止しました。", view=None)

# --- View: ヒット確認用 (別枠メッセージ) ---
class HitConfirmView(discord.ui.View):
    def __init__(self, user_id, cog):
        super().__init__(timeout=5)
        self.user_id = str(user_id)
        self.cog = cog

    @discord.ui.button(label="あわせる！", style=discord.ButtonStyle.success, emoji="🎣")
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if str(interaction.user.id) != self.user_id:
            await interaction.response.defer()
            return
        
        # インタラクションを完了させ、Cog側のバトル開始処理を呼ぶ
        await interaction.response.defer()
        await self.cog.start_battle(self.user_id, interaction.message)

# --- View: バトル用 (メインメッセージ) ---
class FishingBattleView(discord.ui.View):
    def __init__(self, session, cog):
        super().__init__(timeout=60)
        self.s = session
        self.cog = cog

    @discord.ui.button(label="Pick!", style=discord.ButtonStyle.primary)
    async def pick(self, interaction: discord.Interaction, button: discord.ui.Button):
        if str(interaction.user.id) != self.s["user_id"]:
            await interaction.response.defer()
            return

        self.s["picks"] += 1
        damage = random.randint(1, self.s["rod_power"])
        self.s["hp"] -= damage

        hp_ratio = max(0, self.s["hp"]) / self.s["max_hp"]
        # P = (BaseRarity * (Picks^1.5)) * (CurrentHP / MaxHP)
        escape_prob = (self.s["base_escape"] * (self.s["picks"] ** 1.5)) * hp_ratio

        if random.random() < escape_prob and self.s["hp"] > 0:
            await self._finish(interaction, f"**{self.s['fish_name']}** は逃げてしまった...", success=False)
            return

        if self.s["hp"] <= 0:
            # 保存処理などをここに実装
            await self._finish(interaction, f"成功！ **{self.s['fish_name']}** を釣り上げた！", success=True)
        else:
            gauge = "■" * round(10 * hp_ratio) + "□" * (10 - round(10 * hp_ratio))
            await interaction.response.edit_message(
                content=f"格闘中... HP: {max(0, self.s['hp'])}/{self.s['max_hp']}\n`{gauge}`"
            )

    async def _finish(self, interaction, text, success):
        self.cog.active_sessions.pop(self.s["user_id"], None)
        view = RetryView(self.s["user_id"], self.s["biome_id"], self.cog)
        await interaction.response.edit_message(content=text, view=view)

# --- View: リトライ用 (メインメッセージ) ---
class RetryView(discord.ui.View):
    def __init__(self, user_id, biome_id, cog):
        super().__init__(timeout=60)
        self.user_id = user_id
        self.biome_id = biome_id
        self.cog = cog

    @discord.ui.button(label="もう一度釣る", style=discord.ButtonStyle.success)
    async def retry(self, interaction: discord.Interaction, button: discord.ui.Button):
        if str(interaction.user.id) != str(self.user_id):
            await interaction.response.defer()
            return
        await self.cog._start_waiting_phase(interaction, self.biome_id)

async def setup(bot):
    await bot.add_cog(FishingCog(bot))