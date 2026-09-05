import os
import random
import discord
from discord import app_commands
from discord.ext import commands
from supabase import create_client, Client

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# 属性相性表 (攻撃側 -> 防御側)
TYPE_CHART = {
    "虚": {"実": 2.0, "虚": 0.5},
    "実": {"虚": 2.0, "実": 0.5},
    "正": {"負": 2.0, "正": 0.5},
    "負": {"正": 2.0, "負": 0.5},
    "無": {}
}

def calc_stat(max_stat: int, level: int) -> int:
    """Lv.30での最高個体値から現在Lvのステータスを計算"""
    return max(1, int(max_stat * (0.2 + 0.8 * (level / 30.0))))

def get_type_multiplier(atk_type: str, def_type: str) -> float:
    return TYPE_CHART.get(atk_type, {}).get(def_type, 1.0)

class BattleView(discord.ui.View):
    def __init__(self, battle_id: str, current_turn_user_id: str, active_monster: dict, party: list):
        super().__init__(timeout=180)
        self.battle_id = battle_id
        self.current_turn_user_id = current_turn_user_id
        
        # 技ボタン生成
        for idx, move in enumerate(active_monster["moves"]):
            btn = discord.ui.Button(
                label=f"{move['name']} ({move['type']}/威:{move.get('power',0)})",
                style=discord.ButtonStyle.primary,
                custom_id=f"move_{idx}",
                row=0 if idx < 2 else 1
            )
            btn.callback = self.create_move_callback(idx)
            self.add_item(btn)

    def create_move_callback(self, move_idx: int):
        async def callback(interaction: discord.Interaction):
            if str(interaction.user.id) != self.current_turn_user_id:
                await interaction.response.send_message("あなたのターンではありません。", ephemeral=True)
                return
            await interaction.response.defer()
            self.process_turn(interaction, move_idx)
        return callback

    def process_turn(self, interaction: discord.Interaction, move_idx: int):
        # バトルログおよびダメージ処理をアトミックにDB更新
        pass  # ターン同期ロジック

class BattleCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="battle", description="他のプレイヤーと3v3のシングルマッチを行います")
    async def battle(self, interaction: discord.Interaction, opponent: discord.User):
        await interaction.response.defer()
        
        # 両者の最新3匹を取得
        p1_res = supabase.table("monsters").select("*").eq("user_id", str(interaction.user.id)).order("created_at", desc=True).limit(3).execute()
        p2_res = supabase.table("monsters").select("*").eq("user_id", str(opponent.id)).order("created_at", desc=True).limit(3).execute()

        if len(p1_res.data) < 3 or len(p2_res.data) < 3:
            await interaction.followup.send("対戦を行うには両プレイヤーが手持ちモンスターを【3匹以上】所有している必要があります。")
            return

        p1_party = p1_res.data
        p2_party = p2_res.data

        # 先攻後攻の判定（素早さ参照）
        p1_spd = calc_stat(p1_party[0]["max_speed"], p1_party[0]["current_level"])
        p2_spd = calc_stat(p2_party[0]["max_speed"], p2_party[0]["current_level"])
        
        first_user_id = str(interaction.user.id) if p1_spd >= p2_spd else str(opponent.id)

        embed = discord.Embed(
            title="⚔️ DDD 3v3 シングルマッチ開始",
            description=f"<@{interaction.user.id}> VS <@{opponent.id}>\n\n先発: **{p1_party[0]['name']}** VS **{p2_party[0]['name']}**"
        )
        await interaction.followup.send(content=f"<@{first_user_id}> のターンです。", embed=embed)

async def setup(bot):
    await bot.add_cog(BattleCog(bot))
