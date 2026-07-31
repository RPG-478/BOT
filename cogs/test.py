import asyncio
import os
import tempfile
import discord
from discord.ext import commands


class VideoConvertCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="clip")
    async def clip_youtube(self, ctx: commands.Context, url: str):
        status_msg = await ctx.send("動画を処理中...")

        with tempfile.TemporaryDirectory() as tmpdir:
            input_video = os.path.join(tmpdir, "input.mp4")
            output_webp = os.path.join(tmpdir, "output.webp")

            ytdlp_cmd = [
                "yt-dlp",
                "-f",
                "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
                "--download-sections",
                "*00:00-01:00",
                "-o",
                input_video,
                url,
            ]

            process_ytdlp = await asyncio.create_subprocess_exec(
                *ytdlp_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr_ytdlp = await process_ytdlp.communicate()

            if process_ytdlp.returncode != 0:
                await status_msg.edit(
                    content=f"ダウンロードに失敗しました: {stderr_ytdlp.decode()[:100]}"
                )
                return

            ffmpeg_cmd = [
                "ffmpeg",
                "-y",
                "-i",
                input_video,
                "-vf",
                "fps=20,scale=480:-1",
                "-vcodec",
                "libwebp",
                "-lossless",
                "0",
                "-compression_level",
                "4",
                "-q:v",
                "60",
                "-loop",
                "0",
                output_webp,
            ]

            process_ffmpeg = await asyncio.create_subprocess_exec(
                *ffmpeg_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr_ffmpeg = await process_ffmpeg.communicate()

            if process_ffmpeg.returncode != 0:
                await status_msg.edit(
                    content=f"WebP変換に失敗しました: {stderr_ffmpeg.decode()[:100]}"
                )
                return

            file_size = os.path.getsize(output_webp) / (1024 * 1024)
            if file_size > 10:
                await status_msg.edit(
                    content=f"ファイルサイズが10MBを超えました ({file_size:.2f}MB)。画質や秒数を調整してください。"
                )
                return

            file = discord.File(output_webp, filename="preview.webp")
            embed = discord.Embed(
                title="YouTube プレビュー (冒頭1分)", description=url
            )
            embed.set_image(url="attachment://preview.webp")

            await status_msg.delete()
            await ctx.send(embed=embed, file=file)


async def setup(bot):
    await bot.add_cog(VideoConvertCog(bot))
