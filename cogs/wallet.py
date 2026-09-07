import discord
from discord.ext import commands
from discord import app_commands
import config
import traceback

COIN_SETTER_USER_ID = 1320705325686587408

class WalletCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.command(name="coin")
    async def set_coin(self, ctx: commands.Context, amount: int):
        """指定された管理者だけが !coin <数値> で残高を直接設定できる。"""
        if ctx.author.id != COIN_SETTER_USER_ID:
            await ctx.send("このコマンドを実行する権限がありません。")
            return
        if amount < 0:
            await ctx.send("コインは0以上の数値で指定してください。")
            return
        user_id = str(ctx.author.id)
        try:
            current = config.supabase.table("users").select("balance").eq("user_id", user_id).execute()
            old_balance = int(current.data[0].get("balance") or 0) if current.data else 0
            if current.data:
                updated = (config.supabase.table("users").update({"balance": amount})
                           .eq("user_id", user_id).eq("balance", old_balance).execute())
            else:
                updated = config.supabase.table("users").insert({"user_id": user_id, "balance": amount, "debt": 0}).execute()
            if not updated.data:
                raise RuntimeError("残高を更新できませんでした。")
            delta = amount - old_balance
            config.supabase.table("transaction_history").insert({
                "sender_id": "SYSTEM_ADMIN",
                "receiver_id": user_id,
                "amount": abs(delta),
                "reason": f"admin_coin_set_to_{amount}",
            }).execute()
            await ctx.send(f"コインを **{amount:,} AGO** に設定しました（変更: {delta:+,} AGO）。")
        except Exception:
            traceback.print_exc()
            await ctx.send("コイン設定中にエラーが発生しました。")

    @app_commands.command(name="wallet", description="自身のコイン残高を確認します。")
    async def wallet(self, interaction: discord.Interaction):
        await interaction.response.defer()
        user_id = str(interaction.user.id)

        try:
            response = config.supabase.table("users").select("balance, debt").eq("user_id", user_id).execute()
            data = response.data

            if not data:
                config.supabase.table("users").insert({"user_id": user_id, "balance": 10, "debt": 0}).execute()
                balance = 10
                debt = 0
            else:
                balance = data[0]["balance"]
                debt = data[0].get("debt", 0)

            embed = discord.Embed(
                title="ウォレット残高確認",
                description=f"{interaction.user.mention} さんの現在のステータスです。",
                color=0xffffff
            )
            embed.add_field(name="保有コイン", value=f"{balance} AGO", inline=True)
            embed.add_field(name="借金額", value=f"{debt} AGO", inline=True)
            
            await interaction.followup.send(embed=embed)

        except Exception as e:
            print("\n=== [WALLET COMMAND ERROR START] ===")
            traceback.print_exc()
            print("=== [WALLET COMMAND ERROR END] ===\n")
            await interaction.followup.send(f"データの取得中にエラーが発生しました。\nエラー内容: `{type(e).__name__}`", ephemeral=True)

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
            sender_res = config.supabase.table("users").select("balance").eq("user_id", sender_id).execute()
            if not sender_res.data or sender_res.data[0]["balance"] < amount:
                await interaction.followup.send("残高が不足しているため、送金できません。", ephemeral=True)
                return

            update_sender = config.supabase.table("users").update({
                "balance": sender_res.data[0]["balance"] - amount
            }).eq("user_id", sender_id).gte("balance", amount).execute()

            if not update_sender.data:
                raise Exception("送り手の残高更新に失敗しました。")

            receiver_res = config.supabase.table("users").select("balance").eq("user_id", receiver_id).execute()
            
            if not receiver_res.data:
                new_balance = 10 + amount
                config.supabase.table("users").insert({"user_id": receiver_id, "balance": new_balance, "debt": 0}).execute()
            else:
                new_balance = receiver_res.data[0]["balance"] + amount
                config.supabase.table("users").update({"balance": new_balance}).eq("user_id", receiver_id).execute()
            
            config.supabase.table("transaction_history").insert({
                "sender_id": sender_id,
                "receiver_id": receiver_id,
                "amount": amount,
                "reason": "送金"
            }).execute()

            embed = discord.Embed(
                title="送金完了",
                description=f"{receiver.mention} に {amount} AGO コインを送金しました。",
                color=0xffffff
            )
            await interaction.followup.send(embed=embed)

        except Exception as e:
            print("\n=== [PAY COMMAND ERROR START] ===")
            traceback.print_exc()
            print("=== [PAY COMMAND ERROR END] ===\n")
            await interaction.followup.send(f"送金処理中にエラーが発生しました。処理は中断されました。", ephemeral=True)

    @app_commands.command(name="leaderboard", description="コイン保有数のランキングを表示します。")
    async def leaderboard(self, interaction: discord.Interaction):
        await interaction.response.defer()

        try:
            response = config.supabase.table("users").select("user_id", "balance").order("balance", descending=True).limit(10).execute()
            data = response.data

            if not data:
                await interaction.followup.send("ランキングデータが存在しません。")
                return

            embed = discord.Embed(title="コイン保有ランキング (TOP 10)", color=0xffffff)
            
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
            print("\n=== [LEADERBOARD ERROR START] ===")
            traceback.print_exc()
            print("=== [LEADERBOARD ERROR END] ===\n")
            await interaction.followup.send("ランキングの取得中にエラーが発生しました。", ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(WalletCog(bot))
