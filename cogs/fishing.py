import discord
from discord.ext import commands
from discord import app_commands
import random
import asyncio
import time
import math

# --- 定数設定 ---
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
    "aji": {"name": "アジ", "rarity": 1, "max_hp": 50, "base_escape": 0.02, "weight_base": 0.5, "price": 10},
    "maguro": {"name": "マグロ", "rarity": 5, "max_hp": 300, "base_escape": 0.12, "weight_base": 100.0, "price": 500},
    "suzuki": {"name": "スズキ", "rarity": 3, "max_hp": 120, "base_escape": 0.05, "weight_base": 5.0, "price": 100},
    "ayu": {"name": "アユ", "rarity": 1, "max_hp": 40, "base_escape": 0.015, "weight_base": 0.3, "price": 15},
    "sake": {"name": "サケ", "rarity": 3, "max_hp": 150, "base_escape": 0.06, "weight_base": 4.0, "price": 120},
    "iwana": {"name": "イワナ", "rarity": 2, "max_hp": 60, "base_escape": 0.03, "weight_base": 0.8, "price": 50},
    "medaka": {"name": "メダカ", "rarity": 1, "max_hp": 10, "base_escape": 0.005, "weight_base": 0.01, "price": 5},
    "koi": {"name": "コイ", "rarity": 2, "max_hp": 80, "base_escape": 0.04, "weight_base": 3.0, "price": 80},
    "funagi": {"name": "フナ", "rarity": 1, "max_hp": 30, "base_escape": 0.02, "weight_base": 0.4, "price": 20}
}

class FishingCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.active_sessions = {} # {user_id: session_data}
        self.user_data = {} # {user_id: {"coins": int, "inventory": [], "items": []}}

    def get_user_profile(self, user_id):
        if user_id not in self.user_data:
            self.user_data[user_id] = {"coins": 0, "inventory": [], "items": [], "level": 1}
        return self.user_data[user_id]

    def get_rod_power(self, user_id):
        profile = self.get_user_profile(user_id)
        base_power = 20 + (profile["level"] * 10) # 基礎2倍強化 (10 -> 20)
        
        # ショップアイテム「攻撃力2倍」の適用
        if "power_boost" in profile["items"]:
            return base_power * 2
        return base_power

    @app_commands.command(name="fish", description="釣りメニューを表示します")
    async def fish_menu(self, interaction: discord.Interaction):
        user_id = str(interaction.user.id)
        if user_id in self.active_sessions:
            await interaction.response.send_message("現在釣りの最中です。", ephemeral=True)
            return

        await self._show_main_menu(interaction)

    async def _show_main_menu(self, interaction: discord.Interaction):
        user_id = str(interaction.user.id)
        profile = self.get_user_profile(user_id)
        
        embed = discord.Embed(title="釣りステータス", color=0x7289da)
        embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.display_avatar.url)
        embed.add_field(name="所持金", value=f"🪙 {profile['coins']}", inline=True)
        embed.add_field(name="竿レベル", value=f"Lv.{profile['level']}", inline=True)
        
        inv_count = len(profile["inventory"])
        embed.add_field(name="所持魚数", value=f"{inv_count} 匹", inline=True)
        
        if profile["items"]:
            embed.add_field(name="バフアイテム", value=", ".join(profile["items"]), inline=False)

        view = MainMenuView(user_id, self)
        if interaction.response.is_done():
            await interaction.edit_original_response(embed=embed, view=view)
        else:
            await interaction.response.send_message(embed=embed, view=view)

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
        
        view = WaitingView(user_id, self)
        await interaction.edit_original_response(embed=embed, view=view)

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
            content=f"{interaction.user.mention} ❗ アタリです！10秒以内に反応してください！",
            view=view
        )
        
        await asyncio.sleep(10) # 猶予を10秒に延長
        
        if user_id in self.active_sessions and self.active_sessions[user_id]["status"] == "hit_pending":
            self.active_sessions.pop(user_id, None)
            try: await hit_msg.delete()
            except: pass
            
            embed = discord.Embed(title="逃げられた", description="反応が遅すぎました...", color=discord.Color.red())
            await interaction.edit_original_response(embed=embed, view=None)

    async def start_battle(self, user_id, hit_msg):
        if user_id not in self.active_sessions: return
        session = self.active_sessions[user_id]
        session["status"] = "battling"
        interaction = session["main_interaction"]
        
        try: await hit_msg.delete()
        except: pass

        fish_key = random.choice(BIOMES[session["biome_id"]]["fish_pool"])
        fish_base = FISH_DATA[fish_key]
        hp_mod = random.uniform(0.8, 1.2)
        max_hp = int(fish_base["max_hp"] * hp_mod)
        weight = round(fish_base["weight_base"] * hp_mod * random.uniform(0.95, 1.05), 2)
        
        battle_data = {
            "user_id": user_id,
            "fish_key": fish_key,
            "fish_name": fish_base["name"],
            "rarity": fish_base["rarity"],
            "max_hp": max_hp,
            "hp": max_hp,
            "weight": weight,
            "base_escape": fish_base["base_escape"],
            "picks": 0,
            "power": self.get_rod_power(user_id),
            "biome_id": session["biome_id"]
        }

        # バフ消費
        profile = self.get_user_profile(user_id)
        if "power_boost" in profile["items"]:
            profile["items"].remove("power_boost")

        embed = discord.Embed(title="格闘中", description=f"**{fish_base['name']}** がヒット！連打しましょう！", color=0xe67e22)
        embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.display_avatar.url)
        embed.add_field(name="推定重量", value=f"{weight}kg", inline=True)
        embed.add_field(name="体力", value=f"{max_hp} / {max_hp}", inline=True)
        
        view = FishingBattleView(battle_data, self)
        await interaction.edit_original_response(embed=embed, view=view)

# --- Views ---

class MainMenuView(discord.ui.View):
    def __init__(self, user_id, cog):
        super().__init__(timeout=60)
        self.user_id = user_id
        self.cog = cog

    @discord.ui.button(label="釣りに行く", style=discord.ButtonStyle.primary)
    async def go_fishing(self, interaction: discord.Interaction, button: discord.ui.Button):
        if str(interaction.user.id) != self.user_id: return
        view = BiomeSelectView(self.user_id, self.cog)
        await interaction.response.edit_message(content="釣り場を選択してください：", embed=None, view=view)

    @discord.ui.button(label="換金する", style=discord.ButtonStyle.success)
    async def exchange(self, interaction: discord.Interaction, button: discord.ui.Button):
        if str(interaction.user.id) != self.user_id: return
        profile = self.cog.get_user_profile(self.user_id)
        if not profile["inventory"]:
            await interaction.response.send_message("魚を持っていません。", ephemeral=True)
            return
        
        total_coins = 0
        for fish in profile["inventory"]:
            # 価格算出: 基礎価格 * レア度 * √重量
            val = FISH_DATA[next(k for k, v in FISH_DATA.items() if v["name"] == fish["name"])]["price"]
            reward = int(val * (1 + fish["rarity"] * 0.5) * math.sqrt(fish["weight"] + 0.5))
            total_coins += reward
        
        profile["coins"] += total_coins
        profile["inventory"] = []
        await interaction.response.send_message(f"すべての魚を換金し、🪙 {total_coins} を獲得しました！", ephemeral=True)
        await self.cog._show_main_menu(interaction)

    @discord.ui.button(label="ショップ", style=discord.ButtonStyle.secondary)
    async def shop(self, interaction: discord.Interaction, button: discord.ui.Button):
        if str(interaction.user.id) != self.user_id: return
        view = ShopView(self.user_id, self.cog)
        await interaction.response.edit_message(content="購入するアイテムを選んでください：", embed=None, view=view)

class BiomeSelectView(discord.ui.View):
    def __init__(self, user_id, cog):
        super().__init__(timeout=60)
        self.user_id = user_id
        self.cog = cog

    @discord.ui.select(placeholder="行き先を選択...", options=[
        discord.SelectOption(label=v["name"], value=k) for k, v in BIOMES.items()
    ])
    async def select_biome(self, interaction: discord.Interaction, select: discord.ui.Select):
        if str(interaction.user.id) != self.user_id: return
        await interaction.response.defer()
        await self.cog._start_waiting_phase(interaction, select.values[0])

class ShopView(discord.ui.View):
    def __init__(self, user_id, cog):
        super().__init__(timeout=60)
        self.user_id = user_id
        self.cog = cog

    @discord.ui.select(placeholder="商品を選択...", options=[
        discord.SelectOption(label="パワーブースト (100コイン)", description="次回のみ格闘パワーが2倍になります", value="power_boost")
    ])
    async def buy_item(self, interaction: discord.Interaction, select: discord.ui.Select):
        if str(interaction.user.id) != self.user_id: return
        profile = self.cog.get_user_profile(self.user_id)
        cost = 100
        if profile["coins"] < cost:
            await interaction.response.send_message("コインが足りません。", ephemeral=True)
            return
        
        if select.values[0] in profile["items"]:
            await interaction.response.send_message("既に所持しています。", ephemeral=True)
            return

        profile["coins"] -= cost
        profile["items"].append(select.values[0])
        await interaction.response.send_message(f"{select.values[0]} を購入しました！", ephemeral=True)
        await self.cog._show_main_menu(interaction)

    @discord.ui.button(label="キャンセル", style=discord.ButtonStyle.danger)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if str(interaction.user.id) != self.user_id: return
        await self.cog._show_main_menu(interaction)

class WaitingView(discord.ui.View):
    def __init__(self, user_id, cog):
        super().__init__(timeout=None)
        self.user_id = str(user_id)
        self.cog = cog

    @discord.ui.button(label="竿を揺らす", style=discord.ButtonStyle.secondary)
    async def shake(self, interaction: discord.Interaction, button: discord.ui.Button):
        if str(interaction.user.id) != self.user_id: return
        if self.user_id in self.cog.active_sessions:
            self.cog.active_sessions[self.user_id]["end_time"] -= random.randint(5, 15)
            await interaction.response.defer()

    @discord.ui.button(label="中断", style=discord.ButtonStyle.danger)
    async def stop(self, interaction: discord.Interaction, button: discord.ui.Button):
        if str(interaction.user.id) != self.user_id: return
        self.cog.active_sessions.pop(self.user_id, None)
        await self.cog._show_main_menu(interaction)

class HitConfirmView(discord.ui.View):
    def __init__(self, user_id, cog):
        super().__init__(timeout=10)
        self.user_id = str(user_id)
        self.cog = cog

    @discord.ui.button(label="あわせる", style=discord.ButtonStyle.success)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if str(interaction.user.id) != self.user_id: return
        await interaction.response.defer()
        await self.cog.start_battle(self.user_id, interaction.message)

class FishingBattleView(discord.ui.View):
    def __init__(self, session, cog):
        super().__init__(timeout=120)
        self.s = session
        self.cog = cog

    @discord.ui.button(label="Pick!", style=discord.ButtonStyle.primary)
    async def pick(self, interaction: discord.Interaction, button: discord.ui.Button):
        if str(interaction.user.id) != self.s["user_id"]: return
        self.s["picks"] += 1
        damage = random.randint(1, self.s["power"])
        self.s["hp"] -= damage
        hp_ratio = max(0, self.s["hp"]) / self.s["max_hp"]
        
        if random.random() < (self.s["base_escape"] * (self.s["picks"]**1.6) * hp_ratio) and self.s["hp"] > 0:
            self.cog.active_sessions.pop(self.s["user_id"], None)
            await interaction.response.edit_message(content="逃げられました...", embed=None, view=None)
            return

        if self.s["hp"] <= 0:
            profile = self.cog.get_user_profile(self.s["user_id"])
            profile["inventory"].append({"name": self.s["fish_name"], "weight": self.s["weight"], "rarity": self.s["rarity"]})
            await self._finish(interaction)
        else:
            embed = interaction.message.embeds[0]
            gauge = "■" * round(10 * hp_ratio) + "□" * (10 - round(10 * hp_ratio))
            embed.set_field_at(1, name="体力", value=f"`{gauge}` ({max(0, self.s['hp'])}/{self.s['max_hp']})")
            await interaction.response.edit_message(embed=embed)

    async def _finish(self, interaction):
        user_id = self.s["user_id"]
        biome_id = self.s["biome_id"]
        embed = discord.Embed(title="成功！", description=f"**{self.s['fish_name']}** ({self.s['weight']}kg) を釣りました！", color=discord.Color.gold())
        embed.set_footer(text="10秒後に自動的に次を狙います...")
        await interaction.response.edit_message(embed=embed, view=None)
        
        # 10秒待機後に自動再開
        await asyncio.sleep(10)
        if user_id in self.cog.active_sessions: # まだセッションが生きていれば（中断されていなければ）
            await self.cog._start_waiting_phase(interaction, biome_id)

async def setup(bot):
    await bot.add_cog(FishingCog(bot))