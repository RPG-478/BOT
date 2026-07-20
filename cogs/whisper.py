import discord
from discord.ext import commands
from discord import app_commands


class WhisperModal(discord.ui.Modal, title="匿名のつぶやき"):
    content = discord.ui.TextInput(
        label="内容",
        style=discord.TextStyle.paragraph,
        placeholder="つぶやきたい内容を入力してください",
        required=True,
        max_length=1000,
    )

    async def on_submit(self, interaction: discord.Interaction):
        embed = discord.Embed(
            description=self.content.value,
            color=discord.Color.blue()
        )
        await interaction.response.send_message("送信しました。", ephemeral=True)
        await interaction.channel.send(embed=embed)


class WhisperView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="つぶやき", style=discord.ButtonStyle.primary, custom_id="whisper_button_panel")
    async def whisper_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(WhisperModal())


class WhisperCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.active_panels = {}

    async def cog_load(self):
        self.bot.add_view(WhisperView())

    @app_commands.command(name="whisper", description="匿名つぶやきパネルを設置します")
    async def whisper(self, interaction: discord.Interaction):
        guild_id = interaction.guild_id

        if guild_id in self.active_panels:
            await interaction.response.send_message(
                "このサーバーには既にパネルが設置されています。1サーバーにつき1個までです。",
                ephemeral=True
            )
            return

        embed = discord.Embed(
            title="匿名のつぶやき",
            description="下のボタンを押してつぶやくことができます。",
            color=discord.Color.blue()
        )
        
        await interaction.response.send_message("パネルを設置しました。", ephemeral=True)
        message = await interaction.channel.send(embed=embed, view=WhisperView())
        
        self.active_panels[guild_id] = message.id


async def setup(bot: commands.Bot):
    await bot.add_cog(WhisperCog(bot))
