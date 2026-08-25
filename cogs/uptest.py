import discord
from discord.ext import commands


class TestUpload(commands.Cog):

  def __init__(self, bot):
    self.bot = bot

  @discord.app_commands.command(
      name="test_upload", description="ファイルをそのまま送信してアップロード制限を検証します"
  )
  @discord.app_commands.describe(file="テストするファイル")
  async def test_upload(
      self, interaction: discord.Interaction, file: discord.Attachment
  ):
    await interaction.response.defer(thinking=True)

    try:
      # 受け取ったファイルをそのままDiscordへ送り返す
      file_bytes = await file.to_file()
      await interaction.followup.send(
          content=f"送信成功: {file.filename} ({file.size / 1024 / 1024:.2f} MB)",
          file=file_bytes,
      )
    except Exception as e:
      # 制限に引っかかった場合のエラー内容を確認
      await interaction.followup.send(
          f"送信失敗 (エラー発生): \n```python\n{e}\n```"
      )


async def setup(bot):
  await bot.add_cog(TestUpload(bot))
