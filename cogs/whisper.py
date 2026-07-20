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
        await interaction.response.defer(ephemeral=True)
        embed = discord.Embed(
            description=self.content.value,
            color=discord.Color.blue()
        )
        await interaction.channel.send(embed=embed)


class WhisperView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="つぶやき", style=discord.ButtonStyle.primary, custom_id="whisper_button_panel")
    async def whisper_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(WhisperModal())


class DisabledWhisperView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="つぶやき", style=discord.ButtonStyle.secondary, custom_id="whisper_button_panel_disabled", disabled=True)
    async def whisper_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        pass


class WhisperCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.active_panels = {}

    async def cog_load(self):
        self.bot.add_view(WhisperView())

    @app_commands.command(name="whisper", description="匿名つぶやきパネルを設置・リセットします")
    @app_commands.default_permissions(manage_channels=True)
    @app_commands.checks.has_permissions(manage_channels=True)
    async def whisper(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild_id = interaction.guild_id

        if guild_id in self.active_panels:
            old_channel_id, old_message_id = self.active_panels[guild_id]
            try:
                old_channel = self.bot.get_channel(old_channel_id) or await self.bot.fetch_channel(old_channel_id)
                old_message = await old_channel.fetch_message(old_message_id)
                await old_message.edit(view=DisabledWhisperView())
            except Exception:
                pass

        embed = discord.Embed(
            title="匿名のつぶやき",
            description="下のボタンを押してつぶやくことができます。",
            color=discord.Color.blue()
        )
        
        message = await interaction.channel.send(embed=embed, view=WhisperView())
        self.active_panels[guild_id] = (interaction.channel_id, message.id)

    @whisper.error
    async def whisper_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.defer(ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(WhisperCog(bot))
