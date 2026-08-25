import os
import subprocess
import discord
from discord.ext import commands


class Uploader(commands.Cog):

  def __init__(self, bot):
    self.bot = bot

  @discord.app_commands.command(
      name="upload", description="大容量ファイルを最適化して送信します"
  )
  @discord.app_commands.describe(file="送信する動画・音声ファイル")
  async def upload(self, interaction: discord.Interaction, file: discord.Attachment):
    await interaction.response.defer(thinking=True)

    input_path = f"./temp_{file.filename}"
    output_path = f"./optimized_{file.filename}"

    await file.save(input_path)

    try:
      subprocess.run(
          [
              "ffmpeg",
              "-i",
              input_path,
              "-vcodec",
              "libx264",
              "-crf",
              "28",
              "-acodec",
              "aac",
              output_path,
          ],
          check=True,
      )

      if os.path.getsize(output_path) > 20 * 1024 * 1024:
        await interaction.followup.send(
            "圧縮後もファイルサイズが大きすぎます。"
        )
        return

      await interaction.followup.send(file=discord.File(output_path))

    except Exception as e:
      await interaction.followup.send(f"エラー: {e}")

    finally:
      if os.path.exists(input_path):
        os.remove(input_path)
      if os.path.exists(output_path):
        os.remove(output_path)


async def setup(bot):
  await bot.add_cog(Uploader(bot))
