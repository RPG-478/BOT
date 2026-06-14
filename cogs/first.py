import discord
from discord.ext import commands
from discord import app_commands
import asyncio
from typing import Dict, List
from supabase import create_client
from config import SUPABASE_URL, SUPABASE_KEY

class NumberInputModal(discord.ui.Modal, title='数字の選択'):
    number_input = discord.ui.TextInput(
        label='1から100までの数字を入力してください',
        placeholder='例: 1',
        min_length=1,
        max_length=3,
        required=True
    )

    def __init__(self, game_cog, game_id: int):
        super().__init__()
        self.game_cog = game_cog
        self.game_id = game_id

    async def on_submit(self, interaction: discord.Interaction):
        try:
            val = int(self.number_input.value)
            if not (1 <= val <= 100):
                await interaction.response.send_message("1から100の間で入力してください。", ephemeral=True)
                return
            
            self.game_cog.add_entry(self.game_id, interaction.user, val)
            await interaction.response.send_message(f"数字「{val}」でエントリーしました。", ephemeral=True)
        except ValueError:
            await interaction.response.send_message("数字のみを入力してください。", ephemeral=True)

class GameView(discord.ui.View):
    def __init__(self, game_cog, game_id: int):
        super().__init__(timeout=60)
        self.game_cog = game_cog
        self.game_id = game_id

    @discord.ui.button(label="ゲームに参加（数字を入力）", style=discord.ButtonStyle.primary)
    async def join_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.game_cog.is_game_active(self.game_id):
            await interaction.response.send_message("このゲームは既に終了しています。", ephemeral=True)
            return
        
        await interaction.response.send_modal(NumberInputModal(self.game_cog, self.game_id))

class FirstGame(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
        self.games: Dict[int, Dict[discord.Member, int]] = {}
        self.active_games: List[int] = []
        self._game_counter = 0

    def add_entry(self, game_id: int, user: discord.Member, number: int):
        if game_id in self.games:
            self.games[game_id][user] = number

    def is_game_active(self, game_id: int) -> bool:
        return game_id in self.active_games

    async def _update_user_balance_and_debt(self, user_id: str, balance_change: int) -> int:
        str_user_id = str(user_id)
        
        res = self.supabase.table("users").select("balance, debt").eq("user_id", str_user_id).execute()
        
        if not res.data:
            current_balance = 0
            current_debt = 0
            self.supabase.table("users").insert({"user_id": str_user_id, "balance": 0, "debt": 0}).execute()
        else:
            current_balance = res.data[0]["balance"]
            current_debt = res.data[0]["debt"]

        new_balance = current_balance + balance_change
        new_debt = current_debt

        if new_balance < 0:
            shortfall = abs(new_balance)
            new_debt += shortfall
            new_balance = 0

        self.supabase.table("users").update({
            "balance": new_balance,
            "debt": new_debt
        }).eq("user_id", str_user_id).execute()

        return balance_change

    async def _record_transaction(self, sender_id: str, receiver_id: str, amount: int, reason: str):
        self.supabase.table("transaction_history").insert({
            "sender_id": str(sender_id),
            "receiver_id": str(receiver_id),
            "amount": amount,
            "reason": reason
        }).execute()

    @app_commands.command(name="firstgame", description="ファーストゲームを開始します")
    async def start_game(self, interaction: discord.Interaction):
        self._game_counter += 1
        game_id = self._game_counter
        self.games[game_id] = {}
        self.active_games.append(game_id)

        embed = discord.Embed(
            title="ファーストゲーム開始",
            description="誰とも被らない最小の数字を選んだ人が勝ちです。\n下のボタンを押して1〜100の数字を入力してください。\n制限時間は1分間です。\n\n**【報酬ルール】**\n勝者は「勝利数字×10」のコインを他の参加者全員からそれぞれ徴収します。\n※残高が足りない敗者は自動的に**借金**を背負うことになります。",
            color=discord.Color.blue()
        )
        
        view = GameView(self, game_id)
        await interaction.response.send_message(embed=embed, view=view)

        await asyncio.sleep(60)
        
        self.active_games.remove(game_id)
        await self.show_results(interaction, game_id)

    async def show_results(self, interaction: discord.Interaction, game_id: int):
        entries = self.games.get(game_id, {})
        if not entries:
            await interaction.channel.send("参加者がいなかったため、ゲームを終了します。")
            return

        counts = {}
        for num in entries.values():
            counts[num] = counts.get(num, 0) + 1

        unique_numbers = [num for num, count in counts.items() if count == 1]
        
        result_embed = discord.Embed(title="ファーストゲーム 結果発表", color=discord.Color.gold())
        
        if not unique_numbers:
            result_embed.description = "全員の数字が重複しました。勝者なしです。コインの移動はありません。"
        else:
            winner_number = min(unique_numbers)
            winner = None
            for user, num in entries.items():
                if num == winner_number:
                    winner = user
                    break
            
            per_person_fee = winner_number * 10
            losers = [user for user in entries.keys() if user != winner]
            
            total_won_coin = 0
            
            if losers:
                for loser in losers:
                    await self._update_user_balance_and_debt(loser.id, -per_person_fee)
                    await self._record_transaction(loser.id, winner.id, per_person_fee, f"FirstGame 敗北 (GameID: {game_id})")
                    total_won_coin += per_person_fee
                
                await self._update_user_balance_and_debt(winner.id, total_won_coin)

            result_embed.description = f"勝者は **{winner.display_name}** さんです！"
            result_embed.add_field(name="勝利した数字", value=f"{winner_number}（1人あたりから {per_person_fee} コイン徴収）", inline=False)
            result_embed.add_field(name="総獲得コイン", value=f"{total_won_coin} コイン", inline=False)

        summary = "\n".join([f"{u.display_name}: {n}" for u, n in entries.items()])
        result_embed.add_field(name="全参加者の選択", value=summary if len(summary) < 1024 else "データが多すぎるため省略します", inline=False)

        await interaction.channel.send(embed=result_embed)
        del self.games[game_id]

async def setup(bot):
    await bot.add_cog(FirstGame(bot))
