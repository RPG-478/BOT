import discord
from discord.ext import commands
from discord import app_commands
import asyncio
import logging
import config
import traceback

logger = logging.getLogger(__name__)

COIN_SETTER_USER_ID = 1320705325686587408
NEW_USER_BALANCE = 10  # まだ行がないユーザーに最初に渡す残高（/wallet と同じ）
# 残高を書き換えるときに、ほかの処理と同時に更新されて食い違った場合の再試行回数
BALANCE_UPDATE_ATTEMPTS = 5
INSUFFICIENT = object()  # 残高不足を表す目印

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
        if receiver.id == interaction.user.id:
            await interaction.response.send_message("自分自身に送金することはできません。", ephemeral=True)
            return
        if receiver.bot:
            await interaction.response.send_message("Bot には送金できません。", ephemeral=True)
            return

        # 途中の案内は本人にだけ見せる。送金できたときの完了通知だけを全体に出す。
        await interaction.response.defer(ephemeral=True, thinking=True)

        sender_id = str(interaction.user.id)
        receiver_id = str(receiver.id)

        # 1. 送り手の残高を減らす（残高を読み直して、変わっていなければ書き込む。変わっていたらやり直す）
        try:
            debit = await self._change_balance(sender_id, -amount, require_funds=True)
        except Exception:
            logger.exception("pay: 送り手の残高更新に失敗 sender=%s receiver=%s amount=%s", sender_id, receiver_id, amount)
            debit = None
        if debit is INSUFFICIENT:
            await interaction.followup.send("残高が不足しているため、送金できません。", ephemeral=True)
            return
        if debit is None:
            await interaction.followup.send(
                "送金処理中にエラーが発生しました。残高は変わっていません。時間を置いて再度お試しください。", ephemeral=True)
            return

        # 2. 受け手の残高を増やす。失敗したら送り手に返金する。
        try:
            credit = await self._change_balance(receiver_id, amount, create_with=NEW_USER_BALANCE)
        except Exception:
            logger.exception("pay: 受け手の残高更新に失敗 sender=%s receiver=%s amount=%s", sender_id, receiver_id, amount)
            credit = None
        if credit is None:
            try:
                refund = await self._change_balance(sender_id, amount)
            except Exception:
                logger.exception("pay: 返金処理で例外 sender=%s amount=%s", sender_id, amount)
                refund = None
            if refund is None:
                logger.critical(
                    "pay: 返金に失敗しました。手動で戻してください: sender=%s receiver=%s amount=%s "
                    "（送り手から %s AGO を引いたまま、受け手には入っていません）",
                    sender_id, receiver_id, amount, amount)
                await interaction.followup.send(
                    f"送金に失敗し、{amount} AGO の返金もできませんでした。"
                    "お手数ですが管理者に連絡してください（記録は残してあります）。",
                    ephemeral=True,
                )
                return
            await interaction.followup.send(
                "送金処理中にエラーが発生したため、送金を取り消しました。残高は元に戻っています。", ephemeral=True)
            return

        try:
            await asyncio.to_thread(lambda: config.supabase.table("transaction_history").insert({
                "sender_id": sender_id,
                "receiver_id": receiver_id,
                "amount": amount,
                "reason": "送金"
            }).execute())
        except Exception:
            # 送金自体は終わっているので、履歴だけ残せなかったことを記録する。
            logger.exception("pay: 送金履歴の記録に失敗 sender=%s receiver=%s amount=%s", sender_id, receiver_id, amount)

        await interaction.followup.send(f"送金しました。残高は {debit:,} AGO です。", ephemeral=True)
        embed = discord.Embed(
            title="送金完了",
            description=f"{interaction.user.mention} さんが {receiver.mention} に {amount} AGO コインを送金しました。",
            color=0xffffff
        )
        await interaction.followup.send(embed=embed)

    async def _change_balance(self, user_id: str, delta: int, *, require_funds: bool = False,
                              create_with: int | None = None):
        """残高に delta を足す。読んだ残高から変わっていないときだけ書き込み、変わっていたら読み直す。

        成功したら新しい残高、残高不足なら INSUFFICIENT、やり直しても書き込めなければ None を返す。
        create_with を指定すると、行がないユーザーをその残高で作ってから delta を足す。
        """
        for _ in range(BALANCE_UPDATE_ATTEMPTS):
            current = await asyncio.to_thread(
                lambda: config.supabase.table("users").select("balance").eq("user_id", user_id).execute())
            if not current.data:
                if require_funds:
                    return INSUFFICIENT
                if create_with is None:
                    return None
                new_balance = create_with + delta
                try:
                    inserted = await asyncio.to_thread(lambda: config.supabase.table("users").insert(
                        {"user_id": user_id, "balance": new_balance, "debt": 0}).execute())
                except Exception:
                    # 同時に別の処理が行を作った場合など。読み直してやり直す。
                    logger.warning("pay: ユーザー行の作成に失敗、読み直します user=%s", user_id, exc_info=True)
                    continue
                if inserted.data:
                    return new_balance
                continue
            old_balance = int(current.data[0].get("balance") or 0)
            new_balance = old_balance + delta
            if require_funds and new_balance < 0:
                return INSUFFICIENT
            updated = await asyncio.to_thread(
                lambda: config.supabase.table("users").update({"balance": new_balance})
                .eq("user_id", user_id).eq("balance", old_balance).execute())
            if updated.data:
                return new_balance
        return None

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
