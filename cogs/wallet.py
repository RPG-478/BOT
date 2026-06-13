import discord
from discord.ext import commands
from discord import app_commands
from supabase import create_client, Client
import os

SUPABASE_URL = os.getenv("SUPABASE_URL", "your_supabase_url")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "your_supabase_key")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

class WalletCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="wallet", description="自身のコイン残高を確認します。")
    async def wallet(self, interaction: discord.Interaction):
        await interaction.response.defer()
        user_id = str(interaction.user.id)

        try:
            response = supabase.table("users").select("balance").eq("user_id", user_id).execute()
            data = response.data

            if not data:
                # データが存在しない場合は初期登録を行い、10コインを付与する
                supabase.table("users").insert({"user_id": user_id, "balance": 10}).execute()
                balance = 10
            else:
                balance = data[0]["balance"]

            embed = discord.Embed(
                title="ウォレット残高確認",
                description=f"{interaction.user.mention} さんの現在の残高です。",
                color=discord.Color.gold()
            )
            embed.add_field(name="保有コイン", value=f"{balance} AGO", inline=False)
            
            await interaction.followup.send(embed=embed)

        except Exception as e:
            await interaction.followup.send("データの取得中にエラーが発生しました。", ephemeral=True)

    @app_commands.command(name="pay", description="他のユーザーにコインを送金します。")
    @app_commands.describe(receiver="送金先のユーザー", amount="送金するコインの数量")
    async def pay(self, interaction: discord.Interaction, receiver: discord.User, amount: int):
        if amount <= 0:
            await interaction.response.send_message("1コイン以上を指定してください。", ephemeral=True)
            return

        await interaction.response.defer()
        
        sender_id = str(interaction.user.id)
        receiver_id = str(receiver.id)

        if sender_id == receiver_id:
            await interaction.followup.send("自分自身に送金することはできません。", ephemeral=True)
            return

        try:
            sender_res = supabase.table("users").select("balance").eq("user_id", sender_id).execute()
            if not sender_res.data or sender_res.data[0]["balance"] < amount:
                await interaction.followup.send("残高が不足しているため、送金できません。", ephemeral=True)
                return

            # 送り手の残高を減算
            update_sender = supabase.table("users").update({
                "balance": sender_res.data[0]["balance"] - amount
            }).eq("user_id", sender_id).gte("balance", amount).execute()

            if not update_sender.data:
                raise Exception("送り手の残高更新に失敗しました。")

            # 受け手のデータを取得して存在確認
            receiver_res = supabase.table("users").select("balance").eq("user_id", receiver_id).execute()
            
            if not receiver_res.data:
                # 受け手が存在しない場合は新規作成（初期10コイン + 送金額）
                new_balance = 10 + amount
                supabase.table("users").insert({"user_id": receiver_id, "balance": new_balance}).execute()
            else:
                # 既に存在する場合は既存の残高に加算
                new_balance = receiver_res.data[0]["balance"] + amount
                supabase.table("users").update({"balance": new_balance}).eq("user_id", receiver_id).execute()
            
            # 取引履歴にデータを挿入
            supabase.table("transaction_history").insert({
                "sender_id": sender_id,
                "receiver_id": receiver_id,
                "amount": amount,
                "reason": "送金"
            }).execute()

            await interaction.followup.send(f"{receiver.mention} に {amount} AGO コインを送金しました。")

        except Exception as e:
            await interaction.followup.send(f"送金処理中にエラーが発生しました。処理は中断されました。", ephemeral=True)

    @app_commands.command(name="leaderboard", description="コイン保有数のランキングを表示します。")
    async def leaderboard(self, interaction: discord.Interaction):
        await interaction.response.defer()

        try:
            response = supabase.table("users").select("user_id", "balance").order("balance", descending=True).limit(10).execute()
            data = response.data

            if not data:
                await interaction.followup.send("ランキングデータが存在しません。")
                return

            embed = discord.Embed(title="コイン保有ランキング (TOP 10)", color=discord.Color.blue())
            
            for index, record in enumerate(data, start=1):
                user_id = record["user_id"]
                balance = record["balance"]
                
                user = self.bot.get_user(int(user_id))
                user_name = user.name if user else f"User({user_id})"
                
                embed.add_field(
                    name=f"{index}位: {user_name}",
                    value=f"{balance} AGO",
                    inline=False
                )

            await interaction.followup.send(embed=embed)

        except Exception as e:
            await interaction.followup.send("ランキングの取得中にエラーが発生しました。", ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(WalletCog(bot))
