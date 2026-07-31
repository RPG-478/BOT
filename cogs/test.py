import asyncio
import os
import tempfile
import discord
from discord.ext import commands
import yt_dlp


class VideoConvertCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="clip")
    async def clip_youtube(self, ctx: commands.Context, url: str):
        status_msg = await ctx.send("動画・音声を処理中...")

        with tempfile.TemporaryDirectory() as tmpdir:
            input_video = os.path.join(tmpdir, "input.mp4")
            input_audio = os.path.join(tmpdir, "input.m4a")
            output_webp = os.path.join(tmpdir, "output.webp")

            ydl_opts_video = {
                "format": "bestvideo[height<=720][ext=mp4]/bestvideo[ext=mp4]/best[ext=mp4]",
                "outtmpl": input_video,
                "download_ranges": yt_dlp.utils.download_range_func(
                    None, [(0, 60)]
                ),
                "force_keyframes_at_cuts": True,
                "quiet": True,
            }

            ydl_opts_audio = {
                "format": "bestaudio[ext=m4a]/bestaudio/best",
                "outtmpl": input_audio,
                "download_ranges": yt_dlp.utils.download_range_func(
                    None, [(0, 60)]
                ),
                "force_keyframes_at_cuts": True,
                "quiet": True,
            }

            loop = asyncio.get_running_loop()
            try:
                await loop.run_in_executor(
                    None,
                    lambda: yt_dlp.YoutubeDL(ydl_opts_video).download([url]),
                )
                await loop.run_in_executor(
                    None,
                    lambda: yt_dlp.YoutubeDL(ydl_opts_audio).download([url]),
                )
            except Exception as e:
                await status_msg.edit(content=f"ダウンロードに失敗しました: {e}")
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

            if (
                ctx.voice_client
                and ctx.voice_client.is_connected()
                and os.path.exists(input_audio)
            ):
                if ctx.voice_client.is_playing():
                    ctx.voice_client.stop()

                audio_source = discord.FFmpegPCMAudio(input_audio)
                ctx.voice_client.play(audio_source)


async def setup(bot):
    await bot.add_cog(VideoConvertCog(bot))
