```python
import discord
from discord.ext import commands
from discord import app_commands
import asyncio
from typing import Dict, List

class NumberInputModal(discord.ui.Modal, title='数字の選択'):
    """
    ユーザーが数字を入力するためのモーダル画面
    """
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
            
            # 参加情報を保存
            self.game_cog.add_entry(self.game_id, interaction.user, val)
            await interaction.response.send_message(f"数字「{val}」でエントリーしました。", ephemeral=True)
        except ValueError:
            await interaction.response.send_message("数字のみを入力してください。", ephemeral=True)

class GameView(discord.ui.View):
    """
    ゲーム開始時に表示されるボタンパネル
    """
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
    """
    ファーストゲームのメインロジックを管理するCog
    """
    def __init__(self, bot):
        self.bot = bot
        self.games: Dict[int, Dict[discord.Member, int]] = {}
        self.active_games: List[int] = []
        self._game_counter = 0

    def add_entry(self, game_id: int, user: discord.Member, number: int):
        if game_id in self.games:
            self.games[game_id][user] = number

    def is_game_active(self, game_id: int) -> bool:
        return game_id in self.active_games

    @commands.command(name="firstgame")
    async def start_game(self, ctx):
        """
        ファーストゲームを開始するコマンド
        """
        self._game_counter += 1
        game_id = self._game_counter
        self.games[game_id] = {}
        self.active_games.append(game_id)

        embed = discord.Embed(
            title="ファーストゲーム開始",
            description="誰とも被らない最小の数字を選んだ人が勝ちです。\n下のボタンを押して1〜100の数字を入力してください。\n制限時間は1分間です。",
            color=discord.Color.blue()
        )
        
        view = GameView(self, game_id)
        message = await ctx.send(embed=embed, view=view)

        # 1分待機
        await asyncio.sleep(60)
        
        # 受付終了
        self.active_games.remove(game_id)
        await self.show_results(ctx, game_id)

    async def show_results(self, ctx, game_id: int):
        """
        結果を集計して表示
        """
        entries = self.games.get(game_id, {})
        if not entries:
            await ctx.send("参加者がいなかったため、ゲームを終了します。")
            return

        # 数字ごとのカウント
        counts = {}
        for num in entries.values():
            counts[num] = counts.get(num, 0) + 1

        # 被っていない数字（カウントが1）を抽出
        unique_numbers = [num for num, count in counts.items() if count == 1]
        
        result_embed = discord.Embed(title="ファーストゲーム 結果発表", color=discord.Color.gold())
        
        if not unique_numbers:
            result_embed.description = "全員の数字が重複しました。勝者なしです。"
        else:
            # 被っていない中で最小の数字を特定
            winner_number = min(unique_numbers)
            # その数字を選んだユーザーを特定
            winner = None
            for user, num in entries.items():
                if num == winner_number:
                    winner = user
                    break
            
            result_embed.description = f"勝者は **{winner.display_name}** さんです！"
            result_embed.add_field(name="勝利した数字", value=str(winner_number))

        # 参加状況のサマリー
        summary = "\n".join([f"{u.display_name}: {n}" for u, n in entries.items()])
        result_embed.add_field(name="全参加者の選択", value=summary if len(summary) < 1024 else "データが多すぎるため省略します", inline=False)

        await ctx.send(embed=result_embed)
        # データのクリーンアップ
        del self.games[game_id]

async def setup(bot):
    await bot.add_cog(FirstGame(bot))

```
