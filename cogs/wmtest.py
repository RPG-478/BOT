import random
import discord
from discord import app_commands
from discord.ext import commands


class MemoryGameView(discord.ui.View):
    def __init__(self, original_numbers):
        super().__init__(timeout=120)
        # 現在利用可能な数字のプール（ラベル付き）
        self.pool = [
            {"value": num, "label": f"{i+1}番目の数字"}
            for i, num in enumerate(original_numbers)
        ]
        self.score = 0
        self.next_question()

    def next_question(self):
        # ランダムに2つ選出
        self.item1, self.item2 = random.sample(self.pool, 2)
        self.operator = random.choice(["+", "-", "*"])
        
        if self.operator == "+":
            self.correct_answer = self.item1["value"] + self.item2["value"]
        elif self.operator == "-":
            self.correct_answer = self.item1["value"] - self.item2["value"]
        else:
            self.correct_answer = self.item1["value"] * self.item2["value"]

    def get_pool_display(self):
        # 現在のプールにある数字をEmbedで見せるための文字列生成
        return "\n".join([f"{item['label']}: {item['value']}" for item in self.pool])

    @discord.ui.button(label="回答する", style=discord.ButtonStyle.primary)
    async def answer_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(MemoryGameModal(self))


class MemoryGameModal(discord.ui.Modal):
    def __init__(self, game_view: MemoryGameView):
        super().__init__(title="計算問題")
        self.game_view = game_view
        self.answer_input = discord.ui.TextInput(
            label=f"{self.game_view.item1['label']} {self.game_view.operator} {self.game_view.item2['label']}",
            placeholder="結果を入力してください",
        )
        self.add_item(self.answer_input)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            user_ans = int(self.answer_input.value)
        except ValueError:
            await interaction.response.send_message("数値を入力してください。", ephemeral=True)
            return

        if user_ans == self.game_view.correct_answer:
            self.game_view.score += 1
            new_label = f"{self.game_view.score}問目の回答"
            self.game_view.pool.append({"value": user_ans, "label": new_label})
            
            # 褒め言葉のロジック
            praise = "ナイス！"
            if self.game_view.score >= 5: praise = "素晴らしい集中力！天才的だ！"
            elif self.game_view.score >= 3: praise = "いい調子！ワーキングメモリが冴えている！"

            self.game_view.next_question()
            
            embed = discord.Embed(title="正解！", description=f"**{praise}**", color=discord.Color.green())
            embed.add_field(name="現在のスコア", value=str(self.game_view.score), inline=True)
            embed.add_field(name="記憶すべき数字リスト", value=self.game_view.get_pool_display(), inline=False)
            
            await interaction.response.edit_message(embed=embed, view=self.game_view)
        else:
            embed = discord.Embed(
                title="ゲームオーバー...",
                description=f"残念！正解は **{self.game_view.correct_answer}** でした。\n最終スコア: **{self.game_view.score}**",
                color=discord.Color.red()
            )
            for child in self.game_view.children:
                child.disabled = True
            await interaction.response.edit_message(embed=embed, view=self.game_view)


class MemoryGameCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="memory_game", description="ワーキングメモリ強化ゲームを開始")
    async def memory_game(self, interaction: discord.Interaction):
        # 1-9から5つ選ぶ
        original_numbers = random.sample(range(1, 10), 5)
        view = MemoryGameView(original_numbers)
        
        embed = discord.Embed(
            title="ワーキングメモリ強化ゲーム",
            description="表示されている数字を記憶してください！計算するたびに正解がリストに追加されます。",
            color=discord.Color.blue()
        )
        embed.add_field(name="現在の記憶リスト", value=view.get_pool_display(), inline=False)
        
        # ephemeral=False にして全員に見えるようにする
        await interaction.response.send_message(embed=embed, view=view)


async def setup(bot):
    await bot.add_cog(MemoryGameCog(bot))
