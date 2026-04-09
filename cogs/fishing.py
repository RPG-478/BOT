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
        "color": 0xFFFFFF,
        "wait_range": (45, 120),
        "fish_pool": ["mackerel", "tuna", "seabass"]
    },
    "river": {
        "name": "River",
        "color": 0xFFFFFF,
        "wait_range": (15, 60),
        "fish_pool": ["sweetfish", "salmon", "char"]
    },
    "pond": {
        "name": "Pond",
        "color": 0xFFFFFF,
        "wait_range": (1, 15),
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

def we(description: str = None, title: str = None) -> discord.Embed:
    """白色embedを生成するヘルパー"""
    return discord.Embed(title=title, description=description, color=0xFFFFFF)

class FishingCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.active_sessions: Dict[int, Dict[str, Any]] = {}
        self.user_data = {}

    async def load_user_data(self, user_id: int):
        if user_id not in self.user_data:
            self.user_data[user_id] = {
                "coins": 150,
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

    async def delete_last_message(self, user_id: int):
        session = self.active_sessions.get(user_id)
        if session and "last_msg" in session:
            try:
                await session["last_msg"].delete()
            except:
                pass
            session.pop("last_msg", None)

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
            await self.delete_last_message(user_id)
            await self.cleanup_session(user_id)
        
        await self._show_main_menu(interaction)

    async def _show_main_menu(self, interaction: discord.Interaction):
        user_id = interaction.user.id
        profile = await self.load_user_data(user_id)
        embed = discord.Embed(title="FISHING STATUS", color=0xFFFFFF)
        embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.display_avatar.url)
        embed.add_field(name="Coins", value=f"{profile['coins']}", inline=True)
        embed.add_field(name="Rod Power", value=f"{self.get_rod_power(profile)} (Lv.{profile['level']})", inline=True)
        embed.add_field(name="Bag", value=f"{len(profile['inventory'])} / 20", inline=True)
        
        view = MainMenuView(user_id, self)
        
        if interaction.response.is_done():
            msg = await interaction.followup.send(embed=embed, view=view)
        else:
            await interaction.response.send_message(embed=embed, view=view)
            msg = await interaction.original_response()
        
        if user_id not in self.active_sessions:
            self.active_sessions[user_id] = {}
        self.active_sessions[user_id]["last_msg"] = msg

    async def start_waiting(self, interaction: discord.Interaction, biome_id: str):
        user_id = interaction.user.id
        biome = BIOMES[biome_id]
        wait_seconds = random.randint(*biome["wait_range"])
        hit_event = asyncio.Event()

        await self.delete_last_message(user_id)
        
        if user_id in self.active_sessions:
            if "task" in self.active_sessions[user_id] and not self.active_sessions[user_id]["task"].done():
                self.active_sessions[user_id]["task"].cancel()
        else:
            self.active_sessions[user_id] = {}

        self.active_sessions[user_id].update({
            "status": "waiting",
            "biome_id": biome_id,
            "hit_event": hit_event,
            "interaction": interaction
        })

        embed = discord.Embed(
            title="WAITING...",
            description=f"Area: {biome['name']}\nWaiting for a bite...",
            color=0xFFFFFF
        )
        view = WaitingView(user_id, self)
        
        if interaction.response.is_done():
            msg = await interaction.followup.send(embed=embed, view=view)
        else:
            await interaction.response.send_message(embed=embed, view=view)
            msg = await interaction.original_response()

        self.active_sessions[user_id]["last_msg"] = msg
        task = asyncio.create_task(self._wait_loop(user_id, msg, wait_seconds))
        self.active_sessions[user_id]["task"] = task

    async def _wait_loop(self, user_id, message, seconds):
        try:
            await asyncio.sleep(seconds)
            session = self.active_sessions.get(user_id)
            if session:
                await self._trigger_hit(user_id, session["interaction"])
        except asyncio.CancelledError:
            pass

    async def _trigger_hit(self, user_id, interaction: discord.Interaction):
        session = self.active_sessions.get(user_id)
        if not session: return
        
        await self.delete_last_message(user_id)
        
        session["status"] = "hit_pending"
        hit_event = session["hit_event"]

        try:
            view = HitConfirmView(user_id, self)
            hit_embed = discord.Embed(
                title="HIT!",
                description=f"{interaction.user.mention} A fish bit the bait! Press [Hook] within 10s!",
                color=0xFFFFFF
            )
            hit_msg = await interaction.channel.send(embed=hit_embed, view=view)
            session["last_msg"] = hit_msg
            
            try:
                await asyncio.wait_for(hit_event.wait(), timeout=10.0)
                await self.start_battle(user_id, interaction)
            except asyncio.TimeoutError:
                await self.cleanup_session(user_id)
                lost_embed = discord.Embed(
                    description=f"LOST: {interaction.user.mention} The fish got away...",
                    color=0xFFFFFF
                )
                await hit_msg.edit(content=None, embed=lost_embed, view=None)
        except Exception as e:
            print(f"Error in hit: {e}")

    async def start_battle(self, user_id, interaction: discord.Interaction):
        session = self.active_sessions.get(user_id)
        if not session: return
        
        await self.delete_last_message(user_id)
        
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
            "fish_name": fish_base["name"], "max_hp": max_hp, "hp": max_hp,
            "weight": weight, "rarity": fish_base["rarity"], "base_escape": fish_base["base_escape"],
            "picks": 0, "power": power, "biome_id": session["biome_id"]
        }
        session["status"] = "battling"
        
        embed = discord.Embed(title="BATTLE", description="Preparing battle...", color=0xFFFFFF)
        msg = await interaction.channel.send(embed=embed)
        session["last_msg"] = msg
        
        await self._update_battle_ui(user_id, interaction)

    async def _update_battle_ui(self, user_id, interaction: discord.Interaction):
        session = self.active_sessions.get(user_id)
        if not session or "battle" not in session or "last_msg" not in session: return
        s = session["battle"]
        hp_ratio = max(0, s["hp"]) / s["max_hp"]
        tension_val = (s["base_escape"] * (s["picks"]**1.4) * (hp_ratio + 0.2)) * 100
        hp_bar = "[" + "#" * round(15 * hp_ratio) + "-" * (15 - round(15 * hp_ratio)) + "]"
        t_bar = "!" * min(5, math.ceil(tension_val / 5)) + "." * (5 - min(5, math.ceil(tension_val / 5)))
        
        embed = discord.Embed(title="BATTLE", color=0xFFFFFF)
        embed.add_field(name="Target", value=f"**{s['fish_name']}** ({s['weight']}kg)", inline=False)
        embed.add_field(name="Fish HP", value=f"`{hp_bar}` {s['hp']}/{s['max_hp']}", inline=True)
        embed.add_field(name="Tension", value=f"`{t_bar}`", inline=True)
        
        view = BattleView(user_id, self)
        await session["last_msg"].edit(embed=embed, view=view)

    async def do_pull(self, user_id, interaction: discord.Interaction):
        session = self.active_sessions.get(user_id)
        if not session or session["status"] != "battling": return
        s = session["battle"]
        s["picks"] += 1
        dmg = int(s["power"] * random.uniform(0.8, 1.2))
        s["hp"] -= dmg
        
        hp_ratio = max(0, s["hp"]) / s["max_hp"]
        tension_val = (s["base_escape"] * (s["picks"]**1.4) * (hp_ratio + 0.2)) * 100
        
        if s["hp"] <= 0:
            await self._finish_catch(user_id, interaction)
        elif random.random() < (tension_val / 100):
            await self._lose_fish(user_id, interaction)
        else:
            await self._update_battle_ui(user_id, interaction)

    async def _finish_catch(self, user_id, interaction: discord.Interaction):
        session = self.active_sessions.get(user_id)
        s = session["battle"]
        profile = await self.load_user_data(user_id)
        
        fish_obj = {"name": s["fish_name"], "weight": s["weight"], "rarity": s["rarity"]}
        profile["inventory"].append(fish_obj)
        await self.save_user_data(user_id, profile)
        
        embed = discord.Embed(
            title="CAUGHT!",
            description=f"Success! {interaction.user.mention} caught a **{s['fish_name']}** ({s['weight']}kg)!",
            color=0xFFFFFF
        )
        await session["last_msg"].edit(embed=embed, view=None)
        await self.cleanup_session(user_id)

    async def _lose_fish(self, user_id, interaction: discord.Interaction):
        session = self.active_sessions.get(user_id)
        embed = discord.Embed(
            title="SNAP!",
            description=f"Oh no! The line snapped and the fish got away...",
            color=0xFFFFFF
        )
        await session["last_msg"].edit(embed=embed, view=None)
        await self.cleanup_session(user_id)

class MainMenuView(discord.ui.View):
    def __init__(self, user_id, cog):
        super().__init__(timeout=60)
        self.user_id = user_id
        self.cog = cog

    @discord.ui.button(label="Go Fishing", style=discord.ButtonStyle.primary)
    async def go_fish(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id: return
        view = BiomeSelectView(self.user_id, self.cog)
        embed = discord.Embed(title="SELECT AREA", description="Choose where to fish:", color=0xFFFFFF)
        await interaction.response.edit_message(embed=embed, view=view)

    @discord.ui.button(label="Sell All Fish", style=discord.ButtonStyle.success)
    async def sell_all(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id: return
        profile = await self.cog.load_user_data(self.user_id)
        total_price = 0
        for fish in profile["inventory"]:
            # Find base price
            for k, v in FISH_DATA.items():
                if v["name"] == fish["name"]:
                    total_price += v["price"]
                    break
        
        profile["coins"] += total_price
        count = len(profile["inventory"])
        profile["inventory"] = []
        await self.cog.save_user_data(self.user_id, profile)
        
        embed = discord.Embed(description=f"Sold {count} fish for {total_price} coins!", color=0xFFFFFF)
        await interaction.response.edit_message(embed=embed, view=None)
        await asyncio.sleep(3)
        await self.cog._show_main_menu(interaction)

class BiomeSelectView(discord.ui.View):
    def __init__(self, user_id, cog):
        super().__init__(timeout=60)
        self.user_id = user_id
        self.cog = cog
        for bid, bdata in BIOMES.items():
            btn = discord.ui.Button(label=bdata["name"], custom_id=bid)
            btn.callback = self.make_callback(bid)
            self.add_item(btn)

    def make_callback(self, biome_id):
        async def callback(interaction: discord.Interaction):
            if interaction.user.id != self.user_id: return
            await self.cog.start_waiting(interaction, biome_id)
        return callback

class WaitingView(discord.ui.View):
    def __init__(self, user_id, cog):
        super().__init__(timeout=None)
        self.user_id = user_id
        self.cog = cog

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id: return
        await self.cog.cleanup_session(self.user_id)
        await self.cog._show_main_menu(interaction)

class HitConfirmView(discord.ui.View):
    def __init__(self, user_id, cog):
        super().__init__(timeout=10)
        self.user_id = user_id
        self.cog = cog

    @discord.ui.button(label="Hook!", style=discord.ButtonStyle.danger)
    async def hook(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id: return
        session = self.cog.active_sessions.get(self.user_id)
        if session and session["status"] == "hit_pending":
            session["hit_event"].set()
            await interaction.response.defer()

class BattleView(discord.ui.View):
    def __init__(self, user_id, cog):
        super().__init__(timeout=30)
        self.user_id = user_id
        self.cog = cog

    @discord.ui.button(label="Pull!", style=discord.ButtonStyle.primary)
    async def pull(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id: return
        await interaction.response.defer()
        await self.cog.do_pull(self.user_id, interaction)

async def setup(bot):
    await bot.add_cog(FishingCog(bot))
