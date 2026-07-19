import random
import discord
from discord.ext import commands

class GameView(discord.ui.View):
    def __init__(self, cog):
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(label="ボタンを押す", style=discord.ButtonStyle.primary, custom_id="game_1_100_btn")
    async def press_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if random.randint(1, 100) == 1:
            final_score = self.cog.current_count
            self.cog.current_count = 0
            gif_url = "https://example.com/explosion.gif"
            button.disabled = True
            await interaction.response.edit_message(
                content=f"ゲームオーバー！爆発しました。\n全体の記録: {final_score}回連続成功\n{https://images-ext-1.discordapp.net/external/kELQIr5tksGFpxAG8ZSHfwICC62WtJ9faF-jGolqXAI/https/static.klipy.com/ii/4493325008d34b7bf8cd6813cd5c1619/fe/75/MxbliZ98VarH0Rc84u.mp4}",
                view=self
            )
            return

        self.cog.current_count += 1
        
        if random.randint(1, 100) <= 5:
            bonus = 5
            self.cog.current_count += bonus
            await interaction.response.edit_message(content=f"イベント発生！ボーナスとしてカウントがさらに+{bonus}されました。\n現在 {self.cog.current_count} 回連続成功中。")
        else:
            await interaction.response.edit_message(content=f"セーフ！現在 {self.cog.current_count} 回連続成功中。")

class ExplosionGame(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.current_count = 0

    async def cog_load(self):
        self.bot.add_view(GameView(self))

    @commands.command(name="gameset")
    async def gameset(self, ctx):
        await ctx.send("全員で共有する1/100爆発ボタンを設置しました。", view=GameView(self))

async def setup(bot):
    await bot.add_cog(ExplosionGame(bot))