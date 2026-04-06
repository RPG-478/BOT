import discord
from discord.ext import commands
from discord import app_commands
import random
import asyncio
import time
import math

# --- プログラム内定数 ---
BIOMES = {
    "sea": {
        "name": "海",
        "color": 0x3498db,
        "wait_range": (600, 3600), # 10分〜60分
        "fish_pool": ["aji", "maguro", "suzuki"]
    },
    "river": {
        "name": "川",
        "color": 0x1abc9c,
        "wait_range": (30, 300),   # 30秒〜5分
        "fish_pool": ["ayu", "sake", "iwana"]
    },
    "pond": {
        "name": "池",
        "color": 0x2ecc71,
        "wait_range": (10, 120),   # 10秒〜2分
        "fish_pool": ["medaka", "koi", "funagi"]
    }
}

FISH_DATA = {
    "aji": {"name": "アジ", "rarity": 1, "max_hp": 50, "base_escape": 0.02, "weight_base": 0.5},
    "maguro": {"name": "マグロ", "rarity": 5, "max_hp": 300, "base_escape": 0.12, "weight_base": 100.0},
    "suzuki": {"name": "スズキ", "rarity": 3, "max_hp": 120, "base_escape": 0.05, "weight_base": 5.0},
    "ayu": {"name": "アユ", "rarity": 1, "max_hp": 40, "base_escape": 0.015, "weight_base": 0.3},
    "sake": {"name": "サケ", "rarity": 3, "max_hp": 150, "base_escape": 0.06, "weight_base": 4.0},
    "iwana": {"name": "イワナ", "rarity": 2, "max_hp": 60, "base_escape": 0.03, "weight_base": 0.8},
    "medaka": {"name": "メダカ", "rarity": 1, "max_hp": 10, "base_escape": 0.005, "weight_base": 0.01},
    "koi": {"name": "コイ", "rarity": 2, "max_hp": 80, "base_escape": 0.04, "weight_base": 3.0},
    "funagi": {"name": "フナ", "rarity": 1, "max_hp": 30, "base_escape": 0.02, "weight_base": 0.4}
}

class FishingCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # セッション管理 {user_id: {"end_time": float, "status": str, "main_interaction": Interaction}}
        self.active_sessions = {}
        # 簡易インベントリ管理 (本来はDB) {user_id: [fish_name, ...]}
        self.user_inventories = {}

    def get_rod_power(self, level):
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

        embed = discord.Embed(
            title="🎣 釣り開始",
            description=f"【{biome['name']}】で糸を垂らしました...\nアタリを待っています。",
            color=biome["color"]
        )
        embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.display_avatar.url)
        
        # 待機時間が長い場合のアドバイス
        m, s = divmod(wait_seconds, 60)
        time_hint = f"最大約{m}分{s}秒" if m > 0 else f"最大約{s}秒"
        embed.set_footer(text=f"推定待機時間: {time_hint}")

        view = WaitingView(interaction.user.id, self)
        
        if interaction.response.is_done():
            # 再試行（Retry）時は元のメッセージが削除されているためfollowup
            await interaction.followup.send(embed=embed, view=view)
        else:
            await interaction.response.send_message(embed=embed, view=view)

        # 待機ループ
        while True:
            if user_id not in self.active_sessions or self.active_sessions[user_id]["status"] != "waiting":
                return
            
            if time.time() >= self.active_sessions[user_id]["end_time"]:
                break
            
            await asyncio.sleep(1)

        await self._trigger_hit(user_id)

    async def _trigger_hit(self, user_id):
        if user_id not in self.active_sessions:
            return

        session = self.active_sessions[user_id]
        session["status"] = "hit_pending"
        interaction = session["main_interaction"]

        view = HitConfirmView(user_id, self)
        hit_msg = await interaction.channel.send(
            content=f"{interaction.user.mention} ❗ **アタリです！**\n（5秒以内に『あわせる』を押してください）",
            view=view
        )
        
        await asyncio.sleep(5)
        
        if user_id in self.active_sessions and self.active_sessions[user_id]["status"] == "hit_pending":
            self.active_sessions.pop(user_id, None)
            try:
                await hit_msg.delete()
            except:
                pass
            
            embed = discord.Embed(title="❌ 逃げられた", description="反応が遅すぎ、魚は深くに消えていきました...", color=discord.Color.red())
            embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.display_avatar.url)
            
            retry_view = RetryView(user_id, session["biome_id"], self)
            await interaction.edit_original_response(embed=embed, view=retry_view)

    async def start_battle(self, user_id, hit_msg):
        if user_id not in self.active_sessions:
            return

        session = self.active_sessions[user_id]
        session["status"] = "battling"
        interaction = session["main_interaction"]
        biome_id = session["biome_id"]

        try:
            await hit_msg.delete()
        except:
            pass

        fish_key = random.choice(BIOMES[biome_id]["fish_pool"])
        fish_base = FISH_DATA[fish_key]
        
        # 個体差の実装: HP 80%〜120%
        hp_mod = random.uniform(0.8, 1.2)
        current_max_hp = int(fish_base["max_hp"] * hp_mod)
        
        # 重量の算出 (ベース重量 * HP補正 * ランダム微動)
        weight = fish_base["weight_base"] * hp_mod * random.uniform(0.95, 1.05)
        
        battle_data = {
            "user_id": user_id,
            "fish_key": fish_key,
            "fish_name": fish_base["name"],
            "rarity": fish_base["rarity"],
            "max_hp": current_max_hp,
            "hp": current_max_hp,
            "weight": round(weight, 2),
            "base_escape": fish_base["base_escape"],
            "picks": 0,
            "rod_power": self.get_rod_power(1),
            "biome_id": biome_id
        }

        embed = discord.Embed(
            title="⚔️ 格闘開始！",
            description=f"大物か！？ **{fish_base['name']}** が掛かった！\n`Pick!`を連打して体力を削れ！",
            color=0xe67e22
        )
        embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.display_avatar.url)
        embed.add_field(name="予測重量", value=f"{round(weight, 2)}kg", inline=True)
        embed.add_field(name="体力", value=f"{current_max_hp} / {current_max_hp}", inline=True)
        
        view = FishingBattleView(battle_data, self)
        await interaction.edit_original_response(embed=embed, view=view)

# --- View: 待機用 ---
class WaitingView(discord.ui.View):
    def __init__(self, user_id, cog):
        super().__init__(timeout=None)
        self.user_id = str(user_id)
        self.cog = cog

    @discord.ui.button(label="竿を揺らす", style=discord.ButtonStyle.secondary)
    async def shake(self, interaction: discord.Interaction, button: discord.ui.Button):
        if str(interaction.user.id) != self.user_id:
            await interaction.response.send_message("他人の竿に触れてはいけません。", ephemeral=True)
            return

        if self.user_id in self.cog.active_sessions:
            # 内部的に数秒短縮
            self.cog.active_sessions[self.user_id]["end_time"] -= random.randint(3, 8)
            await interaction.response.defer()

    @discord.ui.button(label="中止", style=discord.ButtonStyle.danger)
    async def stop(self, interaction: discord.Interaction, button: discord.ui.Button):
        if str(interaction.user.id) != self.user_id:
            await interaction.response.send_message("自分以外のセッションは中止できません。", ephemeral=True)
            return
        self.cog.active_sessions.pop(self.user_id, None)
        await interaction.response.edit_message(content="釣りを中止しました。", embed=None, view=None)

# --- View: ヒット確認用 ---
class HitConfirmView(discord.ui.View):
    def __init__(self, user_id, cog):
        super().__init__(timeout=5)
        self.user_id = str(user_id)
        self.cog = cog

    @discord.ui.button(label="あわせる！", style=discord.ButtonStyle.success, emoji="🎣")
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if str(interaction.user.id) != self.user_id:
            await interaction.response.send_message("自分宛のアタリではありません。", ephemeral=True)
            return
        
        await interaction.response.defer()
        await self.cog.start_battle(self.user_id, interaction.message)

# --- View: バトル用 ---
class FishingBattleView(discord.ui.View):
    def __init__(self, session, cog):
        super().__init__(timeout=120)
        self.s = session
        self.cog = cog

    @discord.ui.button(label="Pick!", style=discord.ButtonStyle.primary)
    async def pick(self, interaction: discord.Interaction, button: discord.ui.Button):
        if str(interaction.user.id) != self.s["user_id"]:
            await interaction.response.send_message("勝手に竿を奪ってはいけません。", ephemeral=True)
            return

        self.s["picks"] += 1
        damage = random.randint(1, self.s["rod_power"])
        self.s["hp"] -= damage

        hp_ratio = max(0, self.s["hp"]) / self.s["max_hp"]
        escape_prob = (self.s["base_escape"] * (self.s["picks"] ** 1.6)) * hp_ratio

        if random.random() < escape_prob and self.s["hp"] > 0:
            await self._finish(interaction, f"不覚！ **{self.s['fish_name']}** は糸を切って逃げてしまった...", success=False)
            return

        if self.s["hp"] <= 0:
            # インベントリに追加
            user_id = self.s["user_id"]
            if user_id not in self.cog.user_inventories:
                self.cog.user_inventories[user_id] = []
            self.cog.user_inventories[user_id].append(self.s["fish_name"])
            
            await self._finish(interaction, f"見事！ **{self.s['fish_name']}** ({self.s['weight']}kg) を釣り上げた！", success=True)
        else:
            gauge = "■" * round(10 * hp_ratio) + "□" * (10 - round(10 * hp_ratio))
            embed = interaction.message.embeds[0]
            embed.set_field_at(1, name="体力", value=f"`{gauge}` ({max(0, self.s['hp'])}/{self.s['max_hp']})")
            
            await interaction.response.edit_message(embed=embed)

    async def _finish(self, interaction, text, success):
        self.cog.active_sessions.pop(self.s["user_id"], None)
        self.cog.user_inventories[user_id].append({"name": name, "weight": weight, "rarity": rarity})
        color = discord.Color.gold() if success else discord.Color.dark_gray()
        
        embed = discord.Embed(title="釣りリザルト", description=text, color=color)
        embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.display_avatar.url)
        
        if success:
            embed.add_field(name="サイズ", value=f"{self.s['weight']}kg", inline=True)
            embed.add_field(name="レア度", value="⭐" * self.s["rarity"], inline=True)

        # 所持魚リストを表示
        inv = self.cog.user_inventories.get(self.s["user_id"], [])
        if inv:
            # 重複をカウントして表示
            summary = {}
            for f in inv:
                summary[f] = summary.get(f, 0) + 1
            inv_text = " / ".join([f"{k}x{v}" for k, v in summary.items()])
            embed.add_field(name="現在の所持魚", value=f"```{inv_text}```", inline=False)
        else:
            embed.add_field(name="現在の所持魚", value="なし", inline=False)
        
        view = RetryView(self.s["user_id"], self.s["biome_id"], self.cog)
        await interaction.response.edit_message(embed=embed, view=view)

# --- View: リトライ用 ---
class RetryView(discord.ui.View):
    def __init__(self, user_id, biome_id, cog):
        super().__init__(timeout=60)
        self.user_id = user_id
        self.biome_id = biome_id
        self.cog = cog

    @discord.ui.button(label="もう一度釣る", style=discord.ButtonStyle.success)
    async def retry(self, interaction: discord.Interaction, button: discord.ui.Button):
        if str(interaction.user.id) != str(self.user_id):
            await interaction.response.send_message("本人のみが再試行できます。", ephemeral=True)
            return
        
        # 古いメッセージを削除
        try:
            await interaction.message.delete()
        except:
            pass

        await self.cog._start_waiting_phase(interaction, self.biome_id)

async def setup(bot):
    await bot.add_cog(FishingCog(bot))