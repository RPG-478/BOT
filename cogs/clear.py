import discord
from discord import app_commands
from discord.ext import commands
from typing import Optional

class ClearCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="clear", description="指定した個数のメッセージを削除します")
    @app_commands.describe(amount="削除するメッセージ数", member="対象のユーザー（省略可能）")
    async def clear(self, interaction: discord.Interaction, amount: int, member: Optional[discord.Member] = None):
        await interaction.response.defer(ephemeral=True)

        if not isinstance(interaction.channel, (discord.TextChannel, discord.VoiceChannel, discord.Thread)):
            await interaction.followup.send("このチャンネルでは実行できません。", ephemeral=True)
            return

        def check(message: discord.Message) -> bool:
            if member is None:
                return True
            return message.author.id == member.id

        deleted = await interaction.channel.purge(limit=amount, check=check)
        await interaction.followup.send(f"{len(deleted)}件のメッセージを削除しました。", ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(ClearCog(bot))
