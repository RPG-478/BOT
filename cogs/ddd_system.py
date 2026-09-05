import os
import discord
from discord import app_commands
from discord.ext import commands
from supabase import create_client, Client

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

EXPAND_COST = 1000  # 5枠拡張コスト

class SystemCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="box", description="所持しているモンスターボックスを確認します")
    async def show_box(self, interaction: discord.Interaction):
        user_id = str(interaction.user.id)
        await interaction.response.defer()

        user_res = supabase.table("users").select("max_box_slots").eq("user_id", user_id).execute()
        max_slots = user_res.data[0]["max_box_slots"] if user_res.data else 20

        monsters_res = supabase.table("monsters").select("*").eq("user_id", user_id).order("created_at", desc=True).execute()
        monsters = monsters_res.data

        embed = discord.Embed(
            title=f"📦 モンスターボックス ({len(monsters)}/{max_slots}匹)",
            color=discord.Color.blue()
        )

        if not monsters:
            embed.description = "モンスターを所持していません。`/appraise` で鑑定しましょう！"
        else:
            for idx, m in enumerate(monsters[:10]):  # 先頭10匹表示
                embed.add_field(
                    name=f"{idx+1}. 【{m['element_type']}】{m['name']} (Lv.{m['current_level']})",
                    value=f"才能合計: {m['dice_talent']} | 特性: {m['characteristic']}",
                    inline=False
                )

        await interaction.followup.send(embed=embed)

    @app_commands.command(name="expand_box", description="1000 ago コインを消費してボックス上限を5枠拡張します")
    async def expand_box(self, interaction: discord.Interaction):
        user_id = str(interaction.user.id)
        await interaction.response.defer()

        # コイン消費
        user_res = supabase.table("users").select("balance, max_box_slots").eq("user_id", user_id).execute()
        if not user_res.data or user_res.data[0]["balance"] < EXPAND_COST:
            await interaction.followup.send(f"❌ コインが不足しています。（必要: {EXPAND_COST} ago）")
            return

        current_balance = user_res.data[0]["balance"]
        current_slots = user_res.data[0]["max_box_slots"]

        # トランザクション処理
        supabase.table("users").update({
            "balance": current_balance - EXPAND_COST,
            "max_box_slots": current_slots + 5
        }).eq("user_id", user_id).execute()

        supabase.table("transaction_history").insert({
            "sender_id": user_id,
            "receiver_id": "SYSTEM_EXPAND",
            "amount": EXPAND_COST,
            "reason": "box_expansion"
        }).execute()

        await interaction.followup.send(f"🎉 ボックス枠を拡張しました！（上限: {current_slots} → **{current_slots + 5}** 枠）")

async def setup(bot):
    await bot.add_cog(SystemCog(bot))
