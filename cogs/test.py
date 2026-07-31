import asyncio
import math
import os
import tempfile
import discord
from discord.ext import commands
import yt_dlp


class VideoConvertCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="clip")
    async def clip_youtube(
        self, ctx: commands.Context, url: str, total_duration: int = 180
    ):
        status_msg = await ctx.send("動画の処理を開始します...")

        chunk_size = 60
        num_chunks = math.ceil(total_duration / chunk_size)

        for i in range(num_chunks):
            start_time = i * chunk_size
            end_time = min((i + 1) * chunk_size, total_duration)

            await status_msg.edit(
                content=f"処理中... パート {i + 1}/{num_chunks} ({start_time}秒〜{end_time}秒)"
            )

            with tempfile.TemporaryDirectory() as tmpdir:
                input_video = os.path.join(tmpdir, f"input_{i}.mp4")
                output_webp = os.path.join(tmpdir, f"output_{i}.webp")

                ydl_opts_video = {
                    "format": "bestvideo[height<=480][ext=mp4]/best[height<=480][ext=mp4]/best",
                    "outtmpl": input_video,
                    "download_ranges": yt_dlp.utils.download_range_func(
                        None, [(start_time, end_time)]
                    ),
                    "force_keyframes_at_cuts": True,
                    "quiet": True,
                }

                loop = asyncio.get_running_loop()
                try:
                    await loop.run_in_executor(
                        None,
                        lambda: yt_dlp.YoutubeDL(ydl_opts_video).download(
                            [url]
                        ),
                    )
                except Exception as e:
                    await ctx.send(
                        f"パート {i + 1} のダウンロードに失敗しました: {e}"
                    )
                    continue

                ffmpeg_cmd = [
                    "ffmpeg",
                    "-y",
                    "-i",
                    input_video,
                    "-vf",
                    "fps=12,scale=320:-1",
                    "-vcodec",
                    "libwebp",
                    "-lossless",
                    "0",
                    "-compression_level",
                    "0",
                    "-q:v",
                    "30",
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
                    await ctx.send(
                        f"パート {i + 1} のWebP変換に失敗しました: {stderr_ffmpeg.decode()[:100]}"
                    )
                    continue

                file_size = os.path.getsize(output_webp) / (1024 * 1024)
                if file_size > 10:
                    await ctx.send(
                        f"パート {i + 1} のファイルサイズが10MBを超えたためスキップします ({file_size:.2f}MB)。"
                    )
                    continue

                file = discord.File(output_webp, filename=f"preview_{i}.webp")
                embed = discord.Embed(
                    title=f"YouTube プレビュー ({start_time}秒〜{end_time}秒)",
                    description=url,
                )
                embed.set_image(url=f"attachment://preview_{i}.webp")

                await ctx.send(embed=embed, file=file)

        await status_msg.delete()


async def setup(bot):
    await bot.add_cog(VideoConvertCog(bot))
