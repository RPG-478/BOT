import discord
from discord.ext import commands
from discord import app_commands
import random
import asyncio
import time
import math
from typing import Dict, Any, Optional, List

# --- 定数設定 (将来のDB移行を考慮) ---
BIOMES = {
    "sea": {
        "name": "Sea",
        "display_name": "海",
        "color": 0x3498db,
        "wait_range": (30, 120),
        "fish_pool": ["aji", "maguro", "suzuki"]
    },
    "river": {
        "name": "River",
        "display_name": "川",
        "color": 0x1abc9c,
        "wait_range": (15, 60),
        "fish_pool": ["ayu", "sake", "iwana"]
    },
    "pond": {
        "name": "Pond",
        "display_name": "池",
        "color": 0x2ecc71,
        "wait_range": (5, 30),
        "fish_pool": ["medaka", "koi", "funagi"]
    }
}

FISH_DATA = {
    "aji": {"name": "アジ", "rarity": 1, "max_hp": 50, "base_escape": 0.02, "weight_base": 0.5, "price": 10},
    "maguro": {"name": "マグロ", "rarity": 5, "max_hp": 350, "base_escape": 0.08, "weight_base": 100.0, "price": 500},
    "suzuki": {"name": "スズキ", "rarity": 3, "max_hp": 150, "base_escape": 0.04, "weight_base": 5.0, "price": 100},
    "ayu": {"name": "アユ", "rarity": 1, "max_hp": 40, "base_escape": 0.015, "weight_base": 0.3, "price": 15},
    "sake": {"name": "サケ", "rarity": 3, "max_hp": 180, "base_escape": 0.05, "weight_base": 4.0, "price": 120},
    "iwana": {"name": "イワナ", "rarity": 2, "max_hp": 70, "base_escape": 0.03, "weight_base": 0.8, "price": 50},
    "medaka": {"name": "メダカ", "rarity": 1, "max_hp": 15, "base_escape": 0.005, "weight_base": 0.01, "price": 5},
    "koi": {"name": "コイ", "rarity": 2, "max_hp": 100, "base_escape": 0.03, "weight_base": 3.0, "price": 80},
    "funagi": {"name": "フナ", "rarity": 1, "max_hp": 40, "base_escape": 0.02, "weight_base": 0.4, "price": 20}
}

SHOP_ITEMS = {
    "power_boost": {
        "name": "パワーブースト",
        "description": "次回のみ格闘ダメージが2.5倍になります",
        "price": 150,
        "type": "buff"
    },
    "rod_upgrade": {
        "name": "竿の補強",
        "description": "恒久的に基礎攻撃力が +15 されます",
        "price": 500,
        "type": "upgrade"
    }
}

class FishingCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.active_sessions: Dict[int, Dict[str, Any]] = {}
        self.user_data_cache: Dict[int, Dict[str, Any]] = {}

    # --- データ永続化レイヤー (DB移行の準備) ---
    async def load_user_data(self, user_id: int) -> Dict[str, Any]:
        if user_id not in self.user_data_cache:
            # デフォルトデータ
            self.user_data_cache[user_id] = {
                "coins": 100,
                "inventory": [],
                "active_buffs": [],
                "rod_level": 1,
                "base_power": 20
            }
        return self.user_data_cache[user_id]

    async def save_user_data(self, user_id: int, data: Dict[str, Any]):
        self.user_data_cache[user_id] = data
        # ここに外部DB(Supabase等)への非同期保存処理を将来的に追加可能

    def get_total_power(self, data: Dict[str, Any]) -> int:
        power = data["base_power"] + (data["rod_level"] * 5)
        if "power_boost" in data["active_buffs"]:
            return int(power * 2.5)
        return power

    # --- セッション管理 ---
    async def cancel_user_session(self, user_id: int):
        if user_id in self.active_sessions:
            session = self.active_sessions[user_id]
            if "wait_task" in session and not session["wait_task"].done():
                session["wait_task"].cancel()
            if "hit_event" in session:
                session["hit_event"].set()
            self.active_sessions.pop(user_id, None)

    @app_commands.command(name="fish", description="釣りメニューを開きます。")
    async def fish(self, interaction: discord.Interaction):
        user_id = interaction.user.id
        if user_id in self.active_sessions:
            await interaction.response.send_message("既に釣りを行っています。", ephemeral=True)
            return
        await self._send_main_menu(interaction)

    async def _send_main_menu(self, interaction: discord.Interaction):
        user_id = interaction.user.id
        data = await self.load_user_data(user_id)
        
        embed = discord.Embed(title="FISHING MENU", color=0x7289da)
        embed.add_field(name="User", value=interaction.user.display_name, inline=True)
        embed.add_field(name="Coins", value=f"{data['coins']}", inline=True)
        embed.add_field(name="Rod Power", value=f"{self.get_total_power(data)} (Lv.{data['rod_level']})", inline=True)
        embed.add_field(name="Inventory", value=f"{len(data['inventory'])} items", inline=True)
        
        if data["active_buffs"]:
            buff_names = [SHOP_ITEMS[b]["name"] for b in data["active_buffs"] if b in SHOP_ITEMS]
            embed.add_field(name="Active Buffs", value=", ".join(buff_names), inline=False)

        view = MainMenuView(user_id, self)
        if interaction.response.is_done():
            await interaction.edit_original_response(content=None, embed=embed, view=view)
        else:
            await interaction.response.send_message(embed=embed, view=view)

    # --- 釣りフロー ---
    async def start_waiting(self, interaction: discord.Interaction, biome_id: str):
        user_id = interaction.user.id
        biome = BIOMES[biome_id]
        wait_time = random.randint(*biome["wait_range"])
        hit_event = asyncio.Event()

        self.active_sessions[user_id] = {
            "status": "waiting",
            "biome_id": biome_id,
            "hit_event": hit_event,
            "interaction": interaction
        }

        embed = discord.Embed(
            title="WAITING...",
            description=f"Location: {biome['display_name']}\nアタリを待っています...",
            color=biome["color"]
        )
        
        view = GenericCancelView(user_id, self)
        await interaction.response.edit_message(content=None, embed=embed, view=view)

        # 待機タスクの開始
        task = asyncio.create_task(self._wait_for_hit(user_id, wait_time))
        self.active_sessions[user_id]["wait_task"] = task

    async def _wait_for_hit(self, user_id: int, wait_time: int):
        try:
            await asyncio.sleep(wait_time)
            session = self.active_sessions.get(user_id)
            if not session: return
            
            interaction = session["interaction"]
            session["status"] = "hit"
            hit_event = session["hit_event"]

            # アタリ発生の通知
            view = HitConfirmView(user_id, self)
            msg = await interaction.channel.send(
                content=f"HIT: {interaction.user.mention} アタリです！10秒以内に[あわせる]を押してください！",
                view=view
            )

            try:
                # Eventの待機 (ボタンが押されたら解除される)
                await asyncio.wait_for(hit_event.wait(), timeout=10.0)
                await msg.delete()
                # バトル開始
                await self.start_battle(user_id, interaction)
            except asyncio.TimeoutError:
                await msg.edit(content=f"MISS: {interaction.user.mention} 逃げられてしまいました。", view=None)
                await self.cancel_user_session(user_id)
        except asyncio.CancelledError:
            pass

    async def start_battle(self, user_id: int, interaction: discord.Interaction):
        session = self.active_sessions.get(user_id)
        if not session: return
        
        data = await self.load_user_data(user_id)
        biome = BIOMES[session["biome_id"]]
        fish_id = random.choice(biome["fish_pool"])
        fish_base = FISH_DATA[fish_id]
        
        # 個体差
        mod = random.uniform(0.9, 1.2)
        max_hp = int(fish_base["max_hp"] * mod)
        weight = round(fish_base["weight_base"] * mod, 2)
        
        power = self.get_total_power(data)
        # 消費型バフの削除
        if "power_boost" in data["active_buffs"]:
            data["active_buffs"].remove("power_boost")
            await self.save_user_data(user_id, data)

        session["battle"] = {
            "fish_name": fish_base["name"],
            "fish_id": fish_id,
            "max_hp": max_hp,
            "hp": max_hp,
            "weight": weight,
            "rarity": fish_base["rarity"],
            "base_escape": fish_base["base_escape"],
            "picks": 0,
            "power": power
        }
        session["status"] = "battle"

        await self._update_battle_ui(user_id, interaction)

    async def _update_battle_ui(self, user_id: int, interaction: discord.Interaction):
        session = self.active_sessions.get(user_id)
        if not session: return
        battle = session["battle"]

        hp_ratio = max(0, battle["hp"]) / battle["max_hp"]
        gauge_len = 15
        filled = round(gauge_len * hp_ratio)
        gauge = "[" + "■" * filled + "□" * (gauge_len - filled) + "]"
        
        # テンション計算 (逃走率の可視化)
        tension_val = (battle["base_escape"] * (battle["picks"]**1.5) * (hp_ratio + 0.1)) * 100
        tension_bar_len = 5
        t_filled = min(tension_bar_len, math.ceil(tension_val / 5))
        tension_bar = "!" * t_filled + "." * (tension_bar_len - t_filled)

        embed = discord.Embed(title="BATTLE", color=0xe67e22)
        embed.add_field(name="Target", value=f"{battle['fish_name']} ({battle['weight']}kg)", inline=False)
        embed.add_field(name="HP", value=f"`{gauge}` {battle['hp']}/{battle['max_hp']}", inline=True)
        embed.add_field(name="Tension", value=f"`{tension_bar}`", inline=True)
        
        view = BattleView(user_id, self)
        
        try:
            # 既にレスポンス済みの場合はedit、そうでなければresponse.edit_message
            await interaction.edit_original_response(embed=embed, view=view)
        except discord.HTTPException:
            pass # レート制限等の場合はスキップ

# --- Views ---

class MainMenuView(discord.ui.View):
    def __init__(self, user_id: int, cog: FishingCog):
        super().__init__(timeout=60)
        self.user_id = user_id
        self.cog = cog

    @discord.ui.button(label="Go Fishing", style=discord.ButtonStyle.primary)
    async def go(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id: return
        view = BiomeSelectView(self.user_id, self.cog)
        await interaction.response.edit_message(content="釣り場を選択してください:", embed=None, view=view)

    @discord.ui.button(label="Sell Fish", style=discord.ButtonStyle.success)
    async def sell(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id: return
        data = await self.cog.load_user_data(self.user_id)
        if not data["inventory"]:
            await interaction.response.send_message("魚を持っていません。", ephemeral=True)
            return
        
        total = 0
        lines = []
        summary = {}
        for fish in data["inventory"]:
            f_id = next((k for k, v in FISH_DATA.items() if v["name"] == fish["name"]), "aji")
            base = FISH_DATA[f_id]
            price = int(base["price"] * (1 + fish["rarity"] * 0.5) * (fish["weight"] / base["weight_base"]))
            total += price
            summary[fish["name"]] = summary.get(fish["name"], 0) + 1
            
        data["coins"] += total
        data["inventory"] = []
        await self.cog.save_user_data(self.user_id, data)

        for name, count in summary.items():
            lines.append(f"- {name}: x{count}")
        
        embed = discord.Embed(title="EXCHANGE RESULT", description="\n".join(lines), color=0xf1c40f)
        embed.add_field(name="Total Received", value=f"{total} Coins")
        await interaction.response.send_message(embed=embed, ephemeral=True)
        await self.cog._send_main_menu(interaction)

    @discord.ui.button(label="Shop", style=discord.ButtonStyle.secondary)
    async def shop(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id: return
        view = ShopView(self.user_id, self.cog)
        await interaction.response.edit_message(content="ショップ:", embed=None, view=view)

class BiomeSelectView(discord.ui.View):
    def __init__(self, user_id: int, cog: FishingCog):
        super().__init__(timeout=60)
        self.user_id = user_id
        self.cog = cog

    @discord.ui.select(placeholder="釣り場を選択...", options=[
        discord.SelectOption(label=v["display_name"], value=k) for k, v in BIOMES.items()
    ])
    async def select(self, interaction: discord.Interaction, select: discord.ui.Select):
        if interaction.user.id != self.user_id: return
        await self.cog.start_waiting(interaction, select.values[0])

class ShopView(discord.ui.View):
    def __init__(self, user_id: int, cog: FishingCog):
        super().__init__(timeout=60)
        self.user_id = user_id
        self.cog = cog

    @discord.ui.select(placeholder="商品を購入...", options=[
        discord.SelectOption(label=f"{v['name']} ({v['price']}c)", value=k, description=v['description']) for k, v in SHOP_ITEMS.items()
    ])
    async def buy(self, interaction: discord.Interaction, select: discord.ui.Select):
        if interaction.user.id != self.user_id: return
        item_id = select.values[0]
        item = SHOP_ITEMS[item_id]
        data = await self.cog.load_user_data(self.user_id)

        if data["coins"] < item["price"]:
            await interaction.response.send_message("コインが足りません。", ephemeral=True)
            return

        data["coins"] -= item["price"]
        if item["type"] == "buff":
            data["active_buffs"].append(item_id)
        elif item["type"] == "upgrade":
            if item_id == "rod_upgrade":
                data["rod_level"] += 1
                data["base_power"] += 15
        
        await self.cog.save_user_data(self.user_id, data)
        await interaction.response.send_message(f"{item['name']}を購入しました。", ephemeral=True)
        await self.cog._send_main_menu(interaction)

    @discord.ui.button(label="Back", style=discord.ButtonStyle.secondary)
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id: return
        await self.cog._send_main_menu(interaction)

class GenericCancelView(discord.ui.View):
    def __init__(self, user_id: int, cog: FishingCog):
        super().__init__(timeout=None)
        self.user_id = user_id
        self.cog = cog

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.danger)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id: return
        await self.cog.cancel_user_session(self.user_id)
        await self.cog._send_main_menu(interaction)

class HitConfirmView(discord.ui.View):
    def __init__(self, user_id: int, cog: FishingCog):
        super().__init__(timeout=10)
        self.user_id = user_id
        self.cog = cog

    @discord.ui.button(label="あわせる！", style=discord.ButtonStyle.success)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id: return
        session = self.cog.active_sessions.get(self.user_id)
        if session and session["status"] == "hit":
            session["hit_event"].set()
            await interaction.response.defer()

class BattleView(discord.ui.View):
    def __init__(self, user_id: int, cog: FishingCog):
        super().__init__(timeout=120)
        self.user_id = user_id
        self.cog = cog

    @discord.ui.button(label="PULL", style=discord.ButtonStyle.primary)
    async def pull(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id: return
        session = self.cog.active_sessions.get(self.user_id)
        if not session or "battle" not in session: return
        
        battle = session["battle"]
        battle["picks"] += 1
        damage = random.randint(int(battle["power"] * 0.7), battle["power"])
        battle["hp"] -= damage

        hp_ratio = max(0, battle["hp"]) / battle["max_hp"]
        escape_chance = battle["base_escape"] * (battle["picks"]**1.5) * (hp_ratio + 0.1)

        # 逃走判定
        if random.random() < escape_chance and battle["hp"] > 0:
            await self.cog.cancel_user_session(self.user_id)
            await interaction.response.edit_message(content="逃げられてしまいました...", embed=None, view=None)
            return

        if battle["hp"] <= 0:
            # 成功
            data = await self.cog.load_user_data(self.user_id)
            data["inventory"].append({
                "name": battle["fish_name"],
                "weight": battle["weight"],
                "rarity": battle["rarity"]
            })
            await self.cog.save_user_data(self.user_id, data)
            
            embed = discord.Embed(title="SUCCESS", description=f"{battle['fish_name']} を釣り上げました！", color=0x2ecc71)
            embed.add_field(name="Weight", value=f"{battle['weight']}kg")
            embed.add_field(name="Rarity", value="*" * battle["rarity"])
            embed.set_footer(text="5秒後に自動的に釣りを再開します...")
            await interaction.response.edit_message(embed=embed, view=None)
            
            # 自動再開
            await asyncio.sleep(5)
            if self.user_id in self.cog.active_sessions:
                await self.cog.start_waiting(interaction, session["biome_id"])
        else:
            # レート制限を考慮したUI更新
            try:
                await self.cog._update_battle_ui(self.user_id, interaction)
                if not interaction.response.is_done():
                    await interaction.response.defer()
            except discord.HTTPException:
                pass

async def setup(bot: commands.Bot):
    await bot.add_cog(FishingCog(bot))