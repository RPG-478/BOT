import asyncio
import aiohttp
import discord
from discord import app_commands
from discord.ext import commands


class AICog(commands.Cog):

  def __init__(self, bot: commands.Bot):
    self.bot = bot
    self.ollama_url = "http://localhost:11434/api/generate"
    self.model_name = "lfm-custom:latest"
    self.lock = asyncio.Lock()  # 1件限定実行用の排他ロック

  @app_commands.command(name="ai", description="LFM2.5-2.6B に質問します")
  @app_commands.describe(prompt="AIへの質問・プロンプトを入力してください")
  async def ai_command(self, interaction: discord.Interaction, prompt: str):
    # 他のリクエストが処理中の場合は即時拒否（Ephemeralメッセージ）
    if self.lock.locked():
      await interaction.response.send_message(
          "現在、他のリクエストを処理中です。しばらく時間をおいて再度お試しください。",
          ephemeral=True,
      )
      return

    # ロックを取得して処理を開始
    async with self.lock:
      # Discordの3秒タイムアウト回避のため準備中（考え中...）にする
      await interaction.response.defer()

      payload = {
          "model": self.model_name,
          "prompt": prompt,
          "stream": False,
          "keep_alive": 0,  # 応答完了後に即時RAMからアンロード（オフロード）
      }

      try:
        # ラズパイでの推論時間を考慮しタイムアウトを120秒に設定
        timeout = aiohttp.ClientTimeout(total=120)
        async with aiohttp.ClientSession(timeout=timeout) as session:
          async with session.post(self.ollama_url, json=payload) as resp:
            if resp.status == 200:
              data = await resp.json()
              response_text = data.get(
                  "response", "応答を生成できませんでした。"
              )
            else:
              response_text = f"エラーが発生しました (Status: {resp.status})"
      except asyncio.TimeoutError:
        response_text = (
            "処理がタイムアウトしました。質問内容を短くして再度お試しください。"
        )
      except Exception as e:
        response_text = f"通信エラーが発生しました: {e}"

      # Discordの2000文字制限の分割送信対応
      if len(response_text) <= 2000:
        await interaction.followup.send(response_text)
      else:
        for i in range(0, len(response_text), 2000):
          await interaction.followup.send(response_text[i : i + 2000])


async def setup(bot: commands.Bot):
  await bot.add_cog(AICog(bot))
