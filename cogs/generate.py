import asyncio
import os
import discord
from discord import app_commands
from discord.ext import commands

MODEL_PATH = "/home/luna/BOT/venv/MeinaMix_v11.safetensors"
LORA_PATH = "/home/luna/BOT/venv/lcm-lora-sdv1-5.safetensors"
SD_BIN_PATH = "/home/luna/stable-diffusion.cpp/build/bin/sd-cli"

if not os.path.exists(SD_BIN_PATH):
    SD_BIN_PATH = "/home/luna/stable-diffusion.cpp/build/bin/sd"


class GenerateCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.lock = asyncio.Lock()

    @app_commands.command(
        name="generate",
        description="MeinaMix V11 (LCM-LoRA) を使用して超高速画像生成（128x128 / 4steps）を行います。",
    )
    @app_commands.describe(prompt="生成画像の英文プロンプト")
    async def generate(self, interaction: discord.Interaction, prompt: str):
        if self.lock.locked():
            await interaction.response.send_message(
                "現在、他のユーザーが画像を生成中です。完了までしばらくお待ちください。",
                ephemeral=True,
            )
            return

        await interaction.response.defer(thinking=True)

        async with self.lock:
            output_path = f"/tmp/sd_output_{interaction.id}.png"
            cmd = [
                SD_BIN_PATH,
                "-m",
                MODEL_PATH,
                "--lora-model-dir",
                LORA_PATH,
                "-p",
                prompt,
                "-o",
                output_path,
                "--steps",
                "4",  # 高速サンプリング（4ステップ）
                "--cfg-scale",
                "1.0",  # LCM-LoRAに適した設定値
                "-H",
                "128",  # 極小解像度
                "-W",
                "128",  # 極小解像度
                "-t",
                "4",  # CPUの全4コアを使用
            ]

            try:
                # 処理時間を測定
                start_time = asyncio.get_event_loop().time()

                process = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                _, stderr = await process.communicate()

                end_time = asyncio.get_event_loop().time()
                elapsed_time = end_time - start_time
                minutes, seconds = divmod(int(elapsed_time), 60)
                time_str = (
                    f"{minutes}分{seconds}秒"
                    if minutes > 0
                    else f"{seconds}秒"
                )

                if process.returncode == 0 and os.path.exists(output_path):
                    file = discord.File(output_path, filename="generated.png")
                    await interaction.followup.send(
                        content=f"生成が完了しました！ (所要時間: {time_str})\n"
                        f"**プロンプト**: `{prompt}`\n"
                        f"**設定**: 128x128 | steps: 4 | threads: 4",
                        file=file,
                    )
                else:
                    err_text = stderr.decode("utf-8", errors="ignore")[-300:]
                    await interaction.followup.send(
                        f"画像生成に失敗しました。(コード: {process.returncode})\n```\n{err_text}\n```"
                    )

            except Exception as e:
                await interaction.followup.send(
                    f"エラーが発生しました: {str(e)}"
                )

            finally:
                if os.path.exists(output_path):
                    os.remove(output_path)


async def setup(bot: commands.Bot):
    await bot.add_cog(GenerateCog(bot))
