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
    self.lock = asyncio.Lock()

  @app_commands.command(name="ai", description="LFM2.5-2.6B に質問します")
  @app_commands.describe(prompt="AIへの質問・プロンプトを入力してください")
  async def ai_command(self, interaction: discord.Interaction, prompt: str):
    if self.lock.locked():
      await interaction.response.send_message(
          "現在、他のリクエストを処理中です。しばらく時間をおいて再度お試しください。",
          ephemeral=True,
      )
      return

    async with self.lock:
      await interaction.response.defer()

      payload = {
          "model": self.model_name,
          "prompt": prompt,
          "stream": False,
          "keep_alive": "5m",  # 5分間アクセスがなければ自動でRAMからオフロード
          "options": {
              "num_thread": 4,  # ラズパイ4Bの4コアに最適化
              "num_ctx": 2048,  # コンテキストサイズを抑えて軽量化
              "num_predict": 512,  # 生成する最大トークン数を制限して高速化
          },
      }

      try:
        # 初回ロード（コールドスタート）に耐えられるよう5分(300s)に延長
        timeout = aiohttp.ClientTimeout(total=300)
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
            "処理がタイムアウトしました。初回ロードまたは応答生成に時間がかかりすぎています。"
        )
      except Exception as e:
        response_text = f"通信エラーが発生しました: {e}"

      if len(response_text) <= 2000:
        await interaction.followup.send(response_text)
      else:
        for i in range(0, len(response_text), 2000):
          await interaction.followup.send(response_text[i : i + 2000])


async def setup(bot: commands.Bot):
  await bot.add_cog(AICog(bot))
