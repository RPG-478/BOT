import os
import discord
from discord.ext import commands


class DirectSender(commands.Cog):

  def __init__(self, bot):
    self.bot = bot

  @discord.app_commands.command(
      name="send", description="ファイルをそのまま送信します"
  )
  @discord.app_commands.describe(file="送信するファイル")
  async def send(
      self, interaction: discord.Interaction, file: discord.Attachment
  ):
    await interaction.response.defer(thinking=True)

    input_path = f"./temp_{file.filename}"
    await file.save(input_path)

    try:
      with open(input_path, "rb") as f:
        discord_file = discord.File(f, filename=file.filename)
        await interaction.followup.send(
            content=f"{interaction.user.mention}からの送信", file=discord_file
        )

    except Exception as e:
      await interaction.followup.send(f"送信失敗: {e}")

    finally:
      if os.path.exists(input_path):
        os.remove(input_path)


async def setup(bot):
  await bot.add_cog(DirectSender(bot))
