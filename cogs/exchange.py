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
        # 実際の実装では、ここで fishing.py の Cog を取得するか、
        # 共通のデータベース（Supabase等）を介してデータをやり取りします。
        # ここではモックとして、fishing.py 内のインベントリ構造を想定します。

    def calculate_coin(self, rarity, weight, base_value):
        """
        換金額の算出ロジック
        コイン = 基礎値 * レア度補正 * 重量補正
        """
        # レア度補正: レア度が高いほど倍率アップ
        rarity_multiplier = 1 + (rarity * 0.5)
        
        # 重量補正: 1kgあたりを基準に、重いほど価値が高まる
        # (ただし、メダカのような小さな魚でも価値が出るよう log または sqrt を検討)
        weight_multiplier = math.sqrt(weight + 0.5)
        
        total = base_value * rarity_multiplier * weight_multiplier
        return int(total)

    @app_commands.command(name="fishexchange", description="所持している魚をコインに換金します")
    async def fishexchange(self, interaction: discord.Interaction):
        user_id = str(interaction.user.id)
        
        # fishing.py の Cog を取得してインベントリを確認する例
        fishing_cog = self.bot.get_cog("FishingCog")
        if not fishing_cog or user_id not in fishing_cog.user_inventories:
            await interaction.response.send_message("換金できる魚を持っていません。", ephemeral=True)
            return

        inventory = fishing_cog.user_inventories[user_id]
        if not inventory:
            await interaction.response.send_message("インベントリが空です。", ephemeral=True)
            return

        total_coins = 0
        exchanged_count = 0
        
        # 換金処理
        # 注意: fishing.py 側でインベントリに「オブジェクト（名前、重さ、レア度）」を
        # 保存するように変更されている必要があります。
        # 現状の fishing.py は名前のみなので、ここでは「名前」からデータを逆引きする簡易版です。
        
        # ※ fishing.py 側のインベントリが [ {"name": "マグロ", "weight": 105.2, "key": "maguro"}, ... ] 
        # という形式で保存されていると仮定したロジックにします。
        
        # (以下、現在の fishing.py の簡易インベントリをベースにした擬似処理)
        for item in inventory:
            # 本来は item["key"] などで引く
            fish_key = None
            for key, data in FISH_DATA.items():
                if data["name"] == item: # 名前一致で検索
                    fish_key = key
                    break
            
            if fish_key:
                data = FISH_DATA[fish_key]
                # 重量は fishing.py 側で保存されていない場合、平均値を使用（本来は個体値を保存すべき）
                # ここでは「換金」という概念を示すため、固定の計算を行います
                rarity = data["rarity"]
                base_val = data["base_value"]
                
                # 簡易的に 1.0kg と仮定。
                # 本来は `self.s['weight']` をインベントリに保存しておく必要があります。
                weight = 1.0 
                
                coin = self.calculate_coin(rarity, weight, base_val)
                total_coins += coin
                exchanged_count += 1

        # インベントリをクリア
        fishing_cog.user_inventories[user_id] = []

        embed = discord.Embed(
            title="💰 換金完了",
            description=f"釣り上げた魚をコインに換えました！",
            color=discord.Color.gold()
        )
        embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.display_avatar.url)
        embed.add_field(name="換金した数", value=f"{exchanged_count} 匹", inline=True)
        embed.add_field(name="獲得コイン", value=f"🪙 {total_coins} Coins", inline=True)
        embed.set_footer(text="もっと大物を釣って高額換金を狙いましょう！")

        await interaction.response.send_message(embed=embed)

async def setup(bot):
    await bot.add_cog(ExchangeCog(bot))