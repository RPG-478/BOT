import asyncio
import re
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
    # 他のリクエストが処理中の場合は即時拒否
    if self.lock.locked():
      await interaction.response.send_message(
          "現在、他のリクエストを処理中です。しばらく時間をおいて再度お試しください。",
          ephemeral=True,
      )
      return

    async with self.lock:
      await interaction.response.defer()

      # システム指示（思考を10行以内に抑えさせる）
      system_instruction = (
          "思考プロセス（<think>タグ内）を出力する場合は、必ず10行以内の簡潔な内容に収めてください。"
          "思考後はユーザーの質問に日本語で回答してください。"
      )

      payload = {
          "model": self.model_name,
          "prompt": prompt,
          "system": system_instruction,
          "stream": False,
          "keep_alive": -1,  # RAMに完全常駐
          "options": {
              "num_thread": 4,  # ラズパイ4Bの4コアを活用
              "num_ctx": 4096,  # コンテキストサイズ
              "num_predict": 768,  # 生成の最大トークン数
          },
      }

      try:
        timeout = aiohttp.ClientTimeout(total=180)
        async with aiohttp.ClientSession(timeout=timeout) as session:
          async with session.post(self.ollama_url, json=payload) as resp:
            if resp.status == 200:
              data = await resp.json()
              response_text = data.get(
                  "response", "応答を生成できませんでした。"
              )

              # --- 思考ログ（<think>）を最大10行に制限する整形処理 ---
              response_text = self._limit_think_lines(
                  response_text, max_lines=10
              )

            else:
              response_text = f"エラーが発生しました (Status: {resp.status})"
      except asyncio.TimeoutError:
        response_text = "処理がタイムアウトしました。質問内容を短くして再度お試しください。"
      except Exception as e:
        response_text = f"通信エラーが発生しました: {e}"

      # 2000文字制限の分割送信対応
      if len(response_text) <= 2000:
        await interaction.followup.send(response_text)
      else:
        for i in range(0, len(response_text), 2000):
          await interaction.followup.send(response_text[i : i + 2000])

  def _limit_think_lines(self, text: str, max_lines: int = 10) -> str:
    """<think>タグ内のテキストを指定された行数(デフォルト10行)に切り詰めます"""

    def truncate_lines(content: str) -> str:
      lines = [line for line in content.strip().splitlines() if line.strip()]
      if len(lines) > max_lines:
        lines = lines[:max_lines] + ["...（思考制限のため省略）"]
      return "\n".join(lines)

    # 1. 閉じられた <think>...</think> の処理
    def replace_think(match):
      truncated = truncate_lines(match.group(1))
      return f"<think>\n{truncated}\n</think>"

    text = re.sub(r"<think>(.*?)</think>", replace_think, text, flags=re.DOTALL)

    # 2. 途中で途切れた未閉じ <think>... の処理
    if "<think>" in text and "</think>" not in text:
      parts = text.split("<think>", 1)
      truncated = truncate_lines(parts[1])
      text = f"{parts[0]}<think>\n{truncated}\n</think>"

    return text


async def setup(bot: commands.Bot):
  await bot.add_cog(AICog(bot))
