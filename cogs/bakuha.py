import random
import discord
from discord.ext import commands

class GameView(discord.ui.View):
    def __init__(self, cog):
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(label="ボタンを押す", style=discord.ButtonStyle.primary, custom_id="game_1_100_btn")
    async def press_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        rand = random.randint(1, 100)
        
        if rand == 1:
            final_score = self.cog.current_count
            self.cog.current_count = 0
            button.disabled = True
            await interaction.response.edit_message(view=self)
            
            gif_url = "https://example.com/explosion.gif"
            await interaction.channel.send(
                content=f"{interaction.user.mention} ゲームオーバー！爆発しました。\n全体の記録: {final_score}回連続成功\n{https://images-ext-1.discordapp.net/external/kELQIr5tksGFpxAG8ZSHfwICC62WtJ9faF-jGolqXAI/https/static.klipy.com/ii/4493325008d34b7bf8cd6813cd5c1619/fe/75/MxbliZ98VarH0Rc84u.mp4}"
            )
            return

        self.cog.current_count += 1
        
        if rand <= 3:
            await interaction.response.edit_message(content=f"セーフ！現在 {self.cog.current_count} 回連続成功中。")
            
            events = [
                "何もないぞ良かったな。",
                "語尾ににゃんをつける。",
                "2分浮上禁止。",
                "ユーザーネームを3文字以下にする。"
            ]
            selected_event = random.choice(events)
            await interaction.channel.send(
                content=f"{interaction.user.mention} イベント発生！\n{selected_event}"
            )
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
        await ctx.send("全員で共有する爆発ボタンを設置しました。", view=GameView(self))

async def setup(bot):
    await bot.add_cog(ExplosionGame(bot))
