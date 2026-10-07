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
        description="MeinaMix V11 を使用してパラメータを指定し画像を生成します。",
    )
    @app_commands.describe(
        prompt="生成プロンプト (英文)",
        negative_prompt="ネガティブプロンプト (英文)",
        width="画像の幅 (デフォルト: 128)",
        height="画像の高さ (デフォルト: 128)",
        steps="ステップ数 (デフォルト: 4)",
        cfg_scale="CFG Scale (デフォルト: 1.0)",
        threads="使用スレッド数 1-4 (デフォルト: 4)",
        use_lora="LCM-LoRAの適用有無 (デフォルト: True)",
        seed="シード値 (-1でランダム)",
    )
    @app_commands.choices(
        width=[
            app_commands.Choice(name="128", value=128),
            app_commands.Choice(name="256", value=256),
            app_commands.Choice(name="384", value=384),
            app_commands.Choice(name="512", value=512),
        ],
        height=[
            app_commands.Choice(name="128", value=128),
            app_commands.Choice(name="256", value=256),
            app_commands.Choice(name="384", value=384),
            app_commands.Choice(name="512", value=512),
        ],
    )
    async def generate(
        self,
        interaction: discord.Interaction,
        prompt: str,
        negative_prompt: str = "",
        width: int = 128,
        height: int = 128,
        steps: int = 4,
        cfg_scale: float = 1.0,
        threads: int = 4,
        use_lora: bool = True,
        seed: int = -1,
    ):
        if self.lock.locked():
            await interaction.response.send_message(
                "現在、他のユーザーが画像を生成中です。完了までしばらくお待ちください。",
                ephemeral=True,
            )
            return

        await interaction.response.defer(thinking=True)

        async with self.lock:
            output_path = f"/tmp/sd_output_{interaction.id}.png"

            # 基本コマンド構築
            cmd = [
                SD_BIN_PATH,
                "-m",
                MODEL_PATH,
                "-p",
                prompt,
                "-o",
                output_path,
                "--steps",
                str(steps),
                "--cfg-scale",
                str(cfg_scale),
                "-H",
                str(height),
                "-W",
                str(width),
                "-t",
                str(threads),
            ]

            # オプション引数の追加
            if negative_prompt:
                cmd.extend(["-n", negative_prompt])

            if use_lora and os.path.exists(LORA_PATH):
                cmd.extend(["--lora-model-dir", LORA_PATH])

            if seed != -1:
                cmd.extend(["-s", str(seed)])

            try:
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
                    info_msg = (
                        f"生成が完了しました (所要時間: {time_str})\n"
                        f"**プロンプト**: `{prompt}`\n"
                    )
                    if negative_prompt:
                        info_msg += f"**ネガティブプロンプト**: `{negative_prompt}`\n"
                    info_msg += (
                        f"**設定**: {width}x{height} | steps: {steps} | cfg: {cfg_scale} | "
                        f"threads: {threads} | LoRA: {use_lora} | seed: {seed}"
                    )

                    await interaction.followup.send(
                        content=info_msg,
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
