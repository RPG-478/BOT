import asyncio
import random
import discord
from discord import app_commands
from discord.ext import commands


class FlashMentalArithmetic(commands.Cog):

  def __init__(self, bot: commands.Bot):
    self.bot = bot

  @app_commands.command(
      name="flash", description="フラッシュ暗算を行います。"
  )
  @app_commands.describe(
      count="出題する数字の個数",
      interval="数字を表示する間隔（秒：最短1.0秒推奨）",
      digits="数字の桁数（1: 1-9, 2: 10-99など）",
  )
  async def flash(
      self, interaction: discord.Interaction, count: int, interval: float, digits: int
  ):
    # Discordのレートリミット（同一チャンネルのメッセージ編集/送信頻度）を考慮し、
    # 連続リクエストが過剰にならないよう最低間隔を1.0秒以上に制限（必要に応じて調整してください）
    if interval < 1.0:
      interval = 1.0

    if count < 1 or digits < 1 or count > 20:
      await interaction.response.send_message(
          "引数の値が不正です。countは1〜20、digitsは1以上を指定してください。",
          ephemeral=True,
      )
      return

    min_val = 10 ** (digits - 1)
    val_range = (10 ** digits) - min_val

    numbers = [random.randint(min_val, min_val + val_range - 1) for _ in range(count)]
    total_sum = sum(numbers)

    await interaction.response.send_message(
        f"フラッシュ暗算を開始します。\n数字の個数: {count}個 / 表示間隔: {interval}秒 / 桁数: {digits}桁\nまもなく開始します..."
    )

    await asyncio.sleep(2)

    for num in numbers:
      try:
        await interaction.edit_original_response(content=f"# {num}")
      except discord.HTTPException as e:
        if e.status == 429:
          # 万が一レートリミットに達した場合は、指定された秒数待機するか安全に離脱
          retry_after = getattr(e, "retry_after", 2.0)
          await asyncio.sleep(retry_after)
        else:
          raise e
      await asyncio.sleep(interval)

    await interaction.edit_original_response(content="終了！答えをチャットに送信してください。")

    def check(m: discord.Message):
      return (
          m.channel == interaction.channel
          and m.author == interaction.user
          and m.content.isdigit()
      )

    try:
      msg = await self.bot.wait_for("message", timeout=30.0, check=check)
    except asyncio.TimeoutError:
      await interaction.followup.send(
          f"時間切れです。正解は **{total_sum}** でした。"
      )
      return

    if int(msg.content) == total_sum:
      await interaction.followup.send(
          f"正解です！おめでとうございます！ (答え: {total_sum})"
      )
    else:
      await interaction.followup.send(
          f"不正解です...。正解は **{total_sum}** でした。"
      )


async def setup(bot: commands.Bot):
  await bot.add_cog(FlashMentalArithmetic(bot))
