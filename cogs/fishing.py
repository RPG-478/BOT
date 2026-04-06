import discord
from discord.ext import commands
from discord import app_commands
import random
import asyncio
import time
import math
from typing import Dict, Any, Optional

# --- Constants ---
BIOMES = {
    "sea": {
        "name": "Sea",
        "color": 0x3498db,
        "wait_range": (30, 120),
        "fish_pool": ["mackerel", "tuna", "seabass"]
    },
    "river": {
        "name": "River",
        "color": 0x1abc9c,
        "wait_range": (15, 60),
        "fish_pool": ["sweetfish", "salmon", "char"]
    },
    "pond": {
        "name": "Pond",
        "color": 0x2ecc71,
        "wait_range": (5, 30),
        "fish_pool": ["medaka", "koi", "crucian"]
    }
}

FISH_DATA = {
    "mackerel": {"name": "Mackerel", "rarity": 1, "max_hp": 50, "base_escape": 0.02, "weight_base": 0.5, "price": 10},
    "tuna": {"name": "Tuna", "rarity": 5, "max_hp": 350, "base_escape": 0.08, "weight_base": 100.0, "price": 500},
    "seabass": {"name": "Seabass", "rarity": 3, "max_hp": 150, "base_escape": 0.04, "weight_base": 5.0, "price": 100},
    "sweetfish": {"name": "Sweetfish", "rarity": 1, "max_hp": 40, "base_escape": 0.015, "weight_base": 0.3, "price": 15},
    "salmon": {"name": "Salmon", "rarity": 3, "max_hp": 180, "base_escape": 0.05, "weight_base": 4.0, "price": 120},
    "char": {"name": "Char", "rarity": 2, "max_hp": 70, "base_escape": 0.03, "weight_base": 0.8, "price": 50},
    "medaka": {"name": "Killifish", "rarity": 1, "max_hp": 15, "base_escape": 0.005, "weight_base": 0.01, "price": 5},
    "koi": {"name": "Koi Carp", "rarity": 2, "max_hp": 100, "base_escape": 0.03, "weight_base": 3.0, "price": 80},
    "crucian": {"name": "Crucian Carp", "rarity": 1, "max_hp": 40, "base_escape": 0.02, "weight_base": 0.4, "price": 20}
}

SHOP_ITEMS = {
    "power_boost": {
        "name": "Power Boost",
        "description": "Increases damage by 2.5x for the next catch.",
        "price": 150,
        "type": "buff"
    },
    "rod_upgrade": {
        "name": "Rod Reinforcement",
        "description": "Permanently increases base power by 15.",
        "price": 500,
        "type": "upgrade"
    }
}

class FishingCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.active_sessions: Dict[int, Dict[str, Any]] = {}
        self.user_data = {}

    # --- Data Persistence Layer ---
    async def load_user_data(self, user_id: int):
        if user_id not in self.user_data:
            self.user_data[user_id] = {
                "coins": 100,
                "inventory": [],
                "items": [],
                "level": 1,
                "stats_power": 20
            }
        return self.user_data[user_id]

    async def save_user_data(self, user_id: int, data: dict):
        self.user_data[user_id] = data

    def get_rod_power(self, profile):
        power = profile.get("stats_power", 20) + (profile["level"] * 5)
        if "power_boost" in profile["items"]:
            return int(power * 2.5)
        return power

    # --- Session Cleanup ---
    async def cleanup_session(self, user_id: int):
        if user_id in self.active_sessions:
            session = self.active_sessions[user_id]
            if "task" in session and not session["task"].done():
                session["task"].cancel()
            if "hit_event" in session:
                session["hit_event"].set()
            self.active_sessions.pop(user_id, None)

    @app_commands.command(name="fish", description="Open the fishing menu")
    async def fish(self, interaction: discord.Interaction):
        user_id = interaction.user.id
        if user_id in self.active_sessions:
            await interaction.response.send_message("You are already fishing or battling!", ephemeral=True)
            return
        await self._show_main_menu(interaction)

    async def _show_main_menu(self, interaction: discord.Interaction):
        user_id = interaction.user.id
        profile = await self.load_user_data(user_id)
        
        embed = discord.Embed(title="FISHING STATUS", color=0x7289da)
        embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.display_avatar.url)
        embed.add_field(name="Coins", value=f"{profile['coins']}", inline=True)
        embed.add_field(name="Rod Power", value=f"{self.get_rod_power(profile)} (Lv.{profile['level']})", inline=True)
        embed.add_field(name="Bag", value=f"{len(profile['inventory'])} / 20", inline=True)
        
        buffs = [SHOP_ITEMS[i]["name"] for i in profile["items"] if i in SHOP_ITEMS]
        if buffs:
            embed.add_field(name="Active Buffs", value=", ".join(buffs), inline=False)

        view = MainMenuView(user_id, self)
        if interaction.response.is_done():
            await interaction.edit_original_response(content=None, embed=embed, view=view)
        else:
            await interaction.response.send_message(embed=embed, view=view)

    # --- Waiting Logic ---
    async def start_waiting(self, interaction: discord.Interaction, biome_id: str):
        user_id = interaction.user.id
        biome = BIOMES[biome_id]
        wait_seconds = random.randint(*biome["wait_range"])
        
        hit_event = asyncio.Event()
        self.active_sessions[user_id] = {
            "status": "waiting",
            "biome_id": biome_id,
            "hit_event": hit_event,
            "interaction": interaction
        }

        embed = discord.Embed(
            title="WAITING...",
            description=f"Area: {biome['name']}\nWaiting for a bite...",
            color=biome["color"]
        )
        
        view = WaitingView(user_id, self)
        await interaction.response.edit_message(content=None, embed=embed, view=view)

        task = asyncio.create_task(self._wait_loop(user_id, interaction, wait_seconds))
        self.active_sessions[user_id]["task"] = task

    async def _wait_loop(self, user_id, interaction, seconds):
        try:
            await asyncio.sleep(seconds)
            await self._trigger_hit(user_id, interaction)
        except asyncio.CancelledError:
            pass

    async def _trigger_hit(self, user_id, interaction: discord.Interaction):
        session = self.active_sessions.get(user_id)
        if not session: return
        
        session["status"] = "hit_pending"
        hit_event = session["hit_event"]

        try:
            view = HitConfirmView(user_id, self)
            hit_msg = await interaction.channel.send(
                content=f"HIT! {interaction.user.mention} A fish bit the bait! Press [Hook] within 10s!",
                view=view
            )
            
            try:
                await asyncio.wait_for(hit_event.wait(), timeout=10.0)
                await hit_msg.delete()
                await self.start_battle(user_id, interaction)
            except asyncio.TimeoutError:
                await self.cleanup_session(user_id)
                await hit_msg.edit(content=f"LOST: {interaction.user.mention} The fish got away...", view=None)
        except Exception as e:
            print(f"Error in hit trigger: {e}")

    # --- Battle Logic ---
    async def start_battle(self, user_id, interaction: discord.Interaction):
        session = self.active_sessions.get(user_id)
        if not session: return
        
        fish_key = random.choice(BIOMES[session["biome_id"]]["fish_pool"])
        fish_base = FISH_DATA[fish_key]
        mod = random.uniform(0.8, 1.3)
        max_hp = int(fish_base["max_hp"] * mod)
        weight = round(fish_base["weight_base"] * mod * random.uniform(0.9, 1.1), 2)
        
        profile = await self.load_user_data(user_id)
        power = self.get_rod_power(profile)
        
        if "power_boost" in profile["items"]:
            profile["items"].remove("power_boost")
            await self.save_user_data(user_id, profile)

        session["battle"] = {
            "fish_name": fish_base["name"],
            "max_hp": max_hp,
            "hp": max_hp,
            "weight": weight,
            "rarity": fish_base["rarity"],
            "base_escape": fish_base["base_escape"],
            "picks": 0,
            "power": power,
            "biome_id": session["biome_id"]
        }
        session["status"] = "battling"

        await self._update_battle_ui(user_id, interaction)

    async def _update_battle_ui(self, user_id, interaction: discord.Interaction):
        session = self.active_sessions.get(user_id)
        if not session or "battle" not in session: return
        
        s = session["battle"]
        hp_ratio = max(0, s["hp"]) / s["max_hp"]
        tension_val = (s["base_escape"] * (s["picks"]**1.4) * (hp_ratio + 0.2)) * 100
        
        gauge_len = 15
        filled = round(gauge_len * hp_ratio)
        hp_bar = "[" + "#" * filled + "-" * (gauge_len - filled) + "]"
        
        tension_bar_len = 5
        t_filled = min(tension_bar_len, math.ceil(tension_val / 5))
        tension_bar = "!" * t_filled + "." * (tension_bar_len - t_filled)
        
        embed = discord.Embed(title="BATTLE", color=0xe67e22)
        embed.add_field(name="Target", value=f"**{s['fish_name']}** ({s['weight']}kg)", inline=False)
        embed.add_field(name="Fish HP", value=f"`{hp_bar}` {s['hp']}/{s['max_hp']}", inline=True)
        embed.add_field(name="Tension", value=f"`{tension_bar}`", inline=True)
        
        view = BattleView(user_id, self)
        
        # Fixed interaction handling to prevent "Unknown Interaction"
        try:
            if not interaction.response.is_done():
                await interaction.response.edit_message(embed=embed, view=view)
            else:
                await interaction.edit_original_response(embed=embed, view=view)
        except discord.HTTPException:
            pass

# --- Views ---

class MainMenuView(discord.ui.View):
    def __init__(self, user_id, cog):
        super().__init__(timeout=120)
        self.user_id = user_id
        self.cog = cog

    @discord.ui.button(label="Go Fishing", style=discord.ButtonStyle.primary)
    async def go(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id: return
        view = BiomeSelectView(self.user_id, self.cog)
        await interaction.response.edit_message(content="Select a fishing spot:", embed=None, view=view)

    @discord.ui.button(label="Exchange", style=discord.ButtonStyle.success)
    async def exchange(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id: return
        profile = await self.cog.load_user_data(self.user_id)
        if not profile["inventory"]:
            await interaction.response.send_message("No fish in bag.", ephemeral=True)
            return
        
        total_reward = 0
        summary = {}
        for fish in profile["inventory"]:
            # Basic reward logic
            reward = int(10 * (1 + fish["rarity"] * 0.5) * math.sqrt(fish["weight"] + 0.5))
            total_reward += reward
            summary[fish["name"]] = summary.get(fish["name"], 0) + 1
        
        profile["coins"] += total_reward
        profile["inventory"] = []
        await self.cog.save_user_data(self.user_id, profile)
        
        log = "\n".join([f"- {n} x{c}" for n, c in summary.items()])
        embed = discord.Embed(title="EXCHANGE", description=f"Sold fish:\n{log}\n\n**Total: {total_reward} Coins**", color=0xf1c40f)
        await interaction.response.send_message(embed=embed, ephemeral=True)
        await self.cog._show_main_menu(interaction)

    @discord.ui.button(label="Shop", style=discord.ButtonStyle.secondary)
    async def shop(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id: return
        view = ShopView(self.user_id, self.cog)
        await interaction.response.edit_message(content="Welcome to the Shop:", embed=None, view=view)

class BiomeSelectView(discord.ui.View):
    def __init__(self, user_id, cog):
        super().__init__(timeout=60)
        self.user_id = user_id
        self.cog = cog

    @discord.ui.select(placeholder="Where to go?", options=[
        discord.SelectOption(label=v["name"], value=k) for k, v in BIOMES.items()
    ])
    async def select(self, interaction: discord.Interaction, select: discord.ui.Select):
        if interaction.user.id != self.user_id: return
        await self.cog.start_waiting(interaction, select.values[0])

class ShopView(discord.ui.View):
    def __init__(self, user_id, cog):
        super().__init__(timeout=60)
        self.user_id = user_id
        self.cog = cog

    @discord.ui.select(placeholder="Buy items...", options=[
        discord.SelectOption(label=f"{v['name']} ({v['price']}c)", value=k, description=v['description']) for k, v in SHOP_ITEMS.items()
    ])
    async def buy(self, interaction: discord.Interaction, select: discord.ui.Select):
        if interaction.user.id != self.user_id: return
        item_id = select.values[0]
        item = SHOP_ITEMS[item_id]
        profile = await self.cog.load_user_data(self.user_id)
        
        if profile["coins"] < item["price"]:
            await interaction.response.send_message("Not enough coins!", ephemeral=True)
            return

        profile["coins"] -= item["price"]
        if item["type"] == "buff":
            profile["items"].append(item_id)
        elif item["type"] == "upgrade":
            profile["stats_power"] += 15
            profile["level"] += 1
        
        await self.cog.save_user_data(self.user_id, profile)
        await interaction.response.send_message(f"Purchased: {item['name']}", ephemeral=True)
        await self.cog._show_main_menu(interaction)

    @discord.ui.button(label="Back", style=discord.ButtonStyle.danger)
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id: return
        await self.cog._show_main_menu(interaction)

class WaitingView(discord.ui.View):
    def __init__(self, user_id, cog):
        super().__init__(timeout=None)
        self.user_id = user_id
        self.cog = cog

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.danger)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id: return
        await self.cog.cleanup_session(self.user_id)
        await self.cog._show_main_menu(interaction)

class HitConfirmView(discord.ui.View):
    def __init__(self, user_id, cog):
        super().__init__(timeout=10)
        self.user_id = user_id
        self.cog = cog

    @discord.ui.button(label="Hook!", style=discord.ButtonStyle.success)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id: return
        session = self.cog.active_sessions.get(self.user_id)
        if session and session["status"] == "hit_pending":
            session["hit_event"].set()
            if not interaction.response.is_done():
                await interaction.response.defer()

class BattleView(discord.ui.View):
    def __init__(self, user_id, cog):
        super().__init__(timeout=120)
        self.user_id = user_id
        self.cog = cog

    @discord.ui.button(label="PULL", style=discord.ButtonStyle.primary)
    async def pull(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id: return
        
        session = self.cog.active_sessions.get(self.user_id)
        if not session or "battle" not in session: return
        
        # Handle interaction immediately to prevent timeout errors during rapid clicks
        try:
            if not interaction.response.is_done():
                await interaction.response.defer()
        except:
            pass

        s = session["battle"]
        s["picks"] += 1
        damage = random.randint(int(s["power"] * 0.7), s["power"])
        s["hp"] -= damage
        
        hp_ratio = max(0, s["hp"]) / s["max_hp"]
        escape_chance = s["base_escape"] * (s["picks"]**1.4) * (hp_ratio + 0.2)
        
        if random.random() < escape_chance and s["hp"] > 0:
            await self.cog.cleanup_session(self.user_id)
            await interaction.edit_original_response(content="LOST: The line snapped! The fish got away...", embed=None, view=None)
            return

        if s["hp"] <= 0:
            profile = await self.cog.load_user_data(self.user_id)
            profile["inventory"].append({
                "name": s["fish_name"], 
                "weight": s["weight"], 
                "rarity": s["rarity"]
            })
            await self.cog.save_user_data(self.user_id, profile)
            
            embed = discord.Embed(title="SUCCESS", description=f"You caught a **{s['fish_name']}**!", color=0x2ecc71)
            embed.add_field(name="Weight", value=f"{s['weight']} kg")
            embed.add_field(name="Rarity", value="*" * s["rarity"])
            embed.set_footer(text="Next cast in 5 seconds...")
            
            # Clear view to prevent further clicks
            await interaction.edit_original_response(embed=embed, view=None)
            
            await asyncio.sleep(5)
            if self.user_id in self.cog.active_sessions:
                # Start new waiting phase
                await self.cog.start_waiting(interaction, s["biome_id"])
        else:
            await self.cog._update_battle_ui(self.user_id, interaction)

async def setup(bot):
    await bot.add_cog(FishingCog(bot))