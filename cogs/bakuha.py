import random
import discord
from discord.ext import commands

class GameView(discord.ui.View):
    def __init__(self, cog):
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(label="ボタンを押す", style=discord.ButtonStyle.primary, custom_id="game_1_100_btn")
    async def press_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        user_id = interaction.user.id
        
        if user_id not in self.cog.scores:
            self.cog.scores[user_id] = 0
            
        if random.randint(1, 100) == 1:
            final_score = self.cog.scores[user_id]
            self.cog.scores[user_id] = 0
            gif_url = "https://images-ext-1.discordapp.net/external/kELQIr5tksGFpxAG8ZSHfwICC62WtJ9faF-jGolqXAI/https/static.klipy.com/ii/4493325008d34b7bf8cd6813cd5c1619/fe/75/MxbliZ98VarH0Rc84u.mp4"
            await interaction.response.edit_message(content=f"爆発しました。\n記録: {final_score}回連続成功\n{gif_url}")
        else:
            self.cog.scores[user_id] += 1
            current_score = self.cog.scores[user_id]
            await interaction.response.edit_message(content=f"押した回数{current_score} 回")

class ExplosionGame(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.scores = {}

    async def cog_load(self):
        self.bot.add_view(GameView(self))

    @commands.command(name="gameset")
    async def gameset(self, ctx):
        await ctx.send("1/100の確率で爆発するボタンを設置しました。", view=GameView(self))

async def setup(bot):
    await bot.add_cog(ExplosionGame(bot))
