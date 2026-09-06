import asyncio
import os
import random

import discord
from discord import app_commands
from discord.ext import commands
from supabase import Client, create_client

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

WIN_MULTIPLIER = 2.8
LOSS_MULTIPLIER = 1.5


def resolve_guess(bet: int, selected: int, answer: int) -> tuple[bool, int]:
    """勝敗と残高への増減を返す。勝ちは賭け額の2.8倍、負けは1.5倍。"""
    if bet <= 0:
        raise ValueError("bet must be positive")
    if selected not in (1, 2, 3) or answer not in (1, 2, 3):
        raise ValueError("choice must be between 1 and 3")
    return selected == answer, int(bet * (WIN_MULTIPLIER if selected == answer else -LOSS_MULTIPLIER))


class Guess(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="guess", description="1から3の数字を当ててagoを増減させます")
    @app_commands.describe(bet="賭け額（正の整数）", choice="1・2・3から選ぶ数字")
    @app_commands.choices(choice=[
        app_commands.Choice(name="1", value=1),
        app_commands.Choice(name="2", value=2),
        app_commands.Choice(name="3", value=3),
    ])
    async def guess(self, interaction: discord.Interaction, bet: int, choice: int):
        user_id = str(interaction.user.id)
        if bet <= 0:
            await interaction.response.send_message("賭け額は1以上で指定してください。", ephemeral=True)
            return

        try:
            profile = await self._get_profile(user_id)
            balance = int(profile.get("balance") or 0)
            answer = random.randint(1, 3)
            won, delta = resolve_guess(bet, choice, answer)
            if not won and balance < -delta:
                await interaction.response.send_message(
                    f"残高が不足しています。現在 {balance:,} ago、必要な損失上限は {-delta:,} ago です。",
                    ephemeral=True,
                )
                return
            new_balance = balance + delta
            updated = await self._update_balance(user_id, balance, new_balance, won)
            if not updated:
                await interaction.response.send_message("残高が更新されました。少し待ってから再度お試しください。", ephemeral=True)
                return
        except Exception:
            await interaction.response.send_message("ゲーム処理に失敗しました。時間を置いて再度お試しください。", ephemeral=True)
            return

        embed = discord.Embed(
            title="数字当て | 結果",
            description=(
                f"選択した数字: **{choice}**\n"
                f"正解の数字: **{answer}**\n\n"
                f"{'正解です。' if won else '不正解です。'}"
            ),
            color=0xFFFFFF,
        )
        embed.add_field(name="結果", value=f"{'勝ち' if won else '負け'} | 変動 **{delta:+,} ago**", inline=True)
        embed.add_field(name="残高", value=f"**{new_balance:,} ago**", inline=True)
        embed.set_footer(text=f"勝利時は賭け額の{WIN_MULTIPLIER}倍、敗北時は{LOSS_MULTIPLIER}倍を反映")
        await interaction.response.send_message(embed=embed)

    async def _get_profile(self, user_id: str) -> dict:
        result = await asyncio.to_thread(
            lambda: supabase.table("users").select("balance").eq("user_id", user_id).execute()
        )
        if result.data:
            return result.data[0]
        inserted = await asyncio.to_thread(
            lambda: supabase.table("users").insert({
                "user_id": user_id,
                "balance": 0,
                "max_box_slots": 20,
            }).execute()
        )
        return inserted.data[0]

    async def _update_balance(self, user_id: str, old_balance: int, new_balance: int, won: bool) -> bool:
        result = await asyncio.to_thread(
            lambda: supabase.table("users")
            .update({"balance": new_balance})
            .eq("user_id", user_id)
            .eq("balance", old_balance)
            .execute()
        )
        if not result.data:
            return False
        await asyncio.to_thread(
            lambda: supabase.table("transaction_history").insert({
                "sender_id": user_id if not won else "SYSTEM_GUESS",
                "receiver_id": "SYSTEM_GUESS" if not won else user_id,
                "amount": abs(new_balance - old_balance),
                "reason": "guess_win" if won else "guess_loss",
            }).execute()
        )
        return True


async def setup(bot: commands.Bot):
    await bot.add_cog(Guess(bot))
