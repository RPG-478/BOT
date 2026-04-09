import discord
from discord.ext import commands
from discord import app_commands
import math

# fishing.py と共通のデータ（本来は共通の定数ファイルからインポートするのが理想）
FISH_DATA = {
    "aji": {"name": "アジ", "rarity": 1, "base_value": 10},
    "maguro": {"name": "マグロ", "rarity": 5, "base_value": 500},
    "suzuki": {"name": "スズキ", "rarity": 3, "base_value": 100},
    "ayu": {"name": "アユ", "rarity": 1, "base_value": 15},
    "sake": {"name": "サケ", "rarity": 3, "base_value": 120},
    "iwana": {"name": "イワナ", "rarity": 2, "base_value": 50},
    "medaka": {"name": "メダカ", "rarity": 1, "base_value": 5},
    "koi": {"name": "コイ", "rarity": 2, "base_value": 80},
    "funagi": {"name": "フナ", "rarity": 1, "base_value": 20}
}

class ExchangeCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def calculate_coin(self, rarity, weight, base_value):
        """
        換金額の算出ロジック
        コイン = 基礎値 * レア度補正 * 重量補正
        """
        rarity_multiplier = 1 + (rarity * 0.5)
        weight_multiplier = math.sqrt(weight + 0.5)
        total = base_value * rarity_multiplier * weight_multiplier
        return int(total)

    @app_commands.command(name="fishexchange", description="所持している魚をコインに換金します")
    async def fishexchange(self, interaction: discord.Interaction):
        user_id = str(interaction.user.id)
        
        fishing_cog = self.bot.get_cog("FishingCog")
        if not fishing_cog or user_id not in fishing_cog.user_inventories:
            embed = discord.Embed(description="換金できる魚を持っていません。", color=0xFFFFFF)
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        inventory = fishing_cog.user_inventories[user_id]
        if not inventory:
            embed = discord.Embed(description="インベントリが空です。", color=0xFFFFFF)
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        total_coins = 0
        exchanged_count = 0
        
        for item in inventory:
            fish_key = None
            for key, data in FISH_DATA.items():
                if data["name"] == item:
                    fish_key = key
                    break
            
            if fish_key:
                data = FISH_DATA[fish_key]
                rarity = data["rarity"]
                base_val = data["base_value"]
                weight = 1.0 
                coin = self.calculate_coin(rarity, weight, base_val)
                total_coins += coin
                exchanged_count += 1

        fishing_cog.user_inventories[user_id] = []

        embed = discord.Embed(
            title="換金完了",
            description="釣り上げた魚をコインに換えました！",
            color=0xFFFFFF
        )
        embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.display_avatar.url)
        embed.add_field(name="換金した数", value=f"{exchanged_count} 匹", inline=True)
        embed.add_field(name="獲得コイン", value=f"{total_coins} Coins", inline=True)
        embed.set_footer(text="もっと大物を釣って高額換金を狙いましょう！")

        await interaction.response.send_message(embed=embed)

async def setup(bot):
    await bot.add_cog(ExchangeCog(bot))
