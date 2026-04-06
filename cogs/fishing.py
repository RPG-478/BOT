import discord
from discord.ext import commands
from discord import app_commands
import random
import asyncio
import time

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
        # インベントリ管理 {user_id: [{"name": str, "weight": float, "rarity": int}]}
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
            title="釣り待機中",
            description=f"【{biome['name']}】に糸を垂らしました。アタリを待っています...",
            color=biome["color"]
        )
        embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.display_avatar.url)
        
        m, s = divmod(wait_seconds, 60)
        time_text = f"{m}分{s}秒" if m > 0 else f"{s}秒"
        embed.set_footer(text=f"推定アタリ時間: 約{time_text}")

        # 待機中はタイムアウトなし（None）を設定
        view = WaitingView(interaction.user.id, self)
        
        if interaction.response.is_done():
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

        # 通知メッセージ送信（5秒タイムアウト）
        view = HitConfirmView(user_id, self)
        hit_msg = await interaction.channel.send(
            content=f"{interaction.user.mention} ❗ アタリです！5秒以内に『あわせる』を押してください！",
            view=view
        )
        
        await asyncio.sleep(5)
        
        # タイムアウト判定
        if user_id in self.active_sessions and self.active_sessions[user_id]["status"] == "hit_pending":
            self.active_sessions.pop(user_id, None)
            try:
                await hit_msg.delete()
            except:
                pass
            
            embed = discord.Embed(title="逃げられた", description="反応が遅く、魚は逃げてしまいました。", color=discord.Color.red())
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
        
        # 個体差: HP 80%〜120%
        hp_mod = random.uniform(0.8, 1.2)
        current_max_hp = int(fish_base["max_hp"] * hp_mod)
        weight = round(fish_base["weight_base"] * hp_mod * random.uniform(0.95, 1.05), 2)
        
        battle_data = {
            "user_id": user_id,
            "fish_key": fish_key,
            "fish_name": fish_base["name"],
            "rarity": fish_base["rarity"],
            "max_hp": current_max_hp,
            "hp": current_max_hp,
            "weight": weight,
            "base_escape": fish_base["base_escape"],
            "picks": 0,
            "rod_power": self.get_rod_power(1),
            "biome_id": biome_id
        }

        embed = discord.Embed(
            title="格闘中",
            description=f"**{fish_base['name']}** がヒットしました！連打して釣り上げましょう！",
            color=0xe67e22
        )
        embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.display_avatar.url)
        embed.add_field(name="推定重量", value=f"{weight}kg", inline=True)
        embed.add_field(name="体力", value=f"{current_max_hp} / {current_max_hp}", inline=True)
        
        # 格闘フェーズは2分でタイムアウト設定
        view = FishingBattleView(battle_data, self)
        await interaction.edit_original_response(embed=embed, view=view)

# --- View: 待機用 (タイムアウトなし) ---
class WaitingView(discord.ui.View):
    def __init__(self, user_id, cog):
        super().__init__(timeout=None)
        self.user_id = str(user_id)
        self.cog = cog

    @discord.ui.button(label="竿を揺らす", style=discord.ButtonStyle.secondary)
    async def shake(self, interaction: discord.Interaction, button: discord.ui.Button):
        if str(interaction.user.id) != self.user_id:
            await interaction.response.send_message("他人の竿は操作できません。", ephemeral=True)
            return

        if self.user_id in self.cog.active_sessions:
            self.cog.active_sessions[self.user_id]["end_time"] -= random.randint(3, 10)
            await interaction.response.defer()

    @discord.ui.button(label="釣りをやめる", style=discord.ButtonStyle.danger)
    async def stop(self, interaction: discord.Interaction, button: discord.ui.Button):
        if str(interaction.user.id) != self.user_id:
            await interaction.response.send_message("本人以外は中断できません。", ephemeral=True)
            return
        self.cog.active_sessions.pop(self.user_id, None)
        await interaction.response.edit_message(content="釣りを中断しました。", embed=None, view=None)

# --- View: ヒット確認用 (5秒) ---
class HitConfirmView(discord.ui.View):
    def __init__(self, user_id, cog):
        super().__init__(timeout=5)
        self.user_id = str(user_id)
        self.cog = cog

    @discord.ui.button(label="あわせる", style=discord.ButtonStyle.success)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if str(interaction.user.id) != self.user_id:
            await interaction.response.send_message("自分宛のアタリではありません。", ephemeral=True)
            return
        
        await interaction.response.defer()
        await self.cog.start_battle(self.user_id, interaction.message)

# --- View: バトル用 (2分) ---
class FishingBattleView(discord.ui.View):
    def __init__(self, session, cog):
        super().__init__(timeout=120)
        self.s = session
        self.cog = cog

    @discord.ui.button(label="Pick!", style=discord.ButtonStyle.primary)
    async def pick(self, interaction: discord.Interaction, button: discord.ui.Button):
        if str(interaction.user.id) != self.s["user_id"]:
            await interaction.response.send_message("他人の獲物を横取りはできません。", ephemeral=True)
            return

        self.s["picks"] += 1
        damage = random.randint(1, self.s["rod_power"])
        self.s["hp"] -= damage

        hp_ratio = max(0, self.s["hp"]) / self.s["max_hp"]
        escape_prob = (self.s["base_escape"] * (self.s["picks"] ** 1.6)) * hp_ratio

        if random.random() < escape_prob and self.s["hp"] > 0:
            await self._finish(interaction, f"**{self.s['fish_name']}** に逃げられてしまいました...", success=False)
            return

        if self.s["hp"] <= 0:
            user_id = self.s["user_id"]
            if user_id not in self.cog.user_inventories:
                self.cog.user_inventories[user_id] = []
            
            fish_info = {
                "name": self.s["fish_name"],
                "weight": self.s["weight"],
                "rarity": self.s["rarity"]
            }
            self.cog.user_inventories[user_id].append(fish_info)
            
            await self._finish(interaction, f"おめでとうございます！ **{self.s['fish_name']}** ({self.s['weight']}kg) を釣り上げました！", success=True)
        else:
            gauge = "■" * round(10 * hp_ratio) + "□" * (10 - round(10 * hp_ratio))
            embed = interaction.message.embeds[0]
            embed.set_field_at(1, name="体力", value=f"`{gauge}` ({max(0, self.s['hp'])}/{self.s['max_hp']})")
            await interaction.response.edit_message(embed=embed)

    async def _finish(self, interaction, text, success):
        self.cog.active_sessions.pop(self.s["user_id"], None)
        color = discord.Color.gold() if success else discord.Color.dark_gray()
        
        embed = discord.Embed(title="釣りリザルト", description=text, color=color)
        embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.display_avatar.url)
        
        if success:
            embed.add_field(name="サイズ", value=f"{self.s['weight']}kg", inline=True)
            embed.add_field(name="レア度", value="★" * self.s["rarity"], inline=True)

        inv = self.cog.user_inventories.get(self.s["user_id"], [])
        if inv:
            summary = {}
            for f in inv:
                name = f["name"]
                summary[name] = summary.get(name, 0) + 1
            inv_text = " / ".join([f"{k}x{v}" for k, v in summary.items()])
            embed.add_field(name="現在の所持魚", value=f"```{inv_text}```", inline=False)
        else:
            embed.add_field(name="現在の所持魚", value="なし", inline=False)
        
        view = RetryView(self.s["user_id"], self.s["biome_id"], self.cog)
        await interaction.response.edit_message(embed=embed, view=view)

# --- View: リトライ用 (60秒) ---
class RetryView(discord.ui.View):
    def __init__(self, user_id, biome_id, cog):
        super().__init__(timeout=60)
        self.user_id = user_id
        self.biome_id = biome_id
        self.cog = cog

    @discord.ui.button(label="もう一度釣る", style=discord.ButtonStyle.success)
    async def retry(self, interaction: discord.Interaction, button: discord.ui.Button):
        if str(interaction.user.id) != str(self.user_id):
            await interaction.response.send_message("本人のみ再試行できます。", ephemeral=True)
            return
        
        try:
            await interaction.message.delete()
        except:
            pass

        await self.cog._start_waiting_phase(interaction, self.biome_id)

async def setup(bot):
    await bot.add_cog(FishingCog(bot))