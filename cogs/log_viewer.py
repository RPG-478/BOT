# cogs/log_viewer.py

import io
from datetime import datetime

import discord
from discord.ext import commands


# ここにコマンドを使えるユーザーIDを指定する
# 例: 自分と管理者だけ許可するなど
ALLOWED_USER_IDS = {
    1320705325686587408,  # ← ここを実際のユーザーIDに置き換える
    1000302102473613373,
}


async def is_log_allowed(ctx: commands.Context) -> bool:
    """
    ALLOWED_USER_IDS に含まれているユーザーのみ許可するチェック
    """
    return ctx.author.id in ALLOWED_USER_IDS


class LogViewer(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.command(name="logs", usage="[行数]")
    @commands.check(is_log_allowed)
    async def logs(self, ctx: commands.Context, line_count: int = 30):
        """
        !logs 50
        のように使って、最新から指定行数分のログを表示する。
        同時に、現在保持している全ログをファイルで添付する。
        """

        # main.py で設定している bot.log_buffer を取得
        buffer = getattr(self.bot, "log_buffer", None)

        if buffer is None:
            await ctx.send(
                "❌ `bot.log_buffer` が見つかりません。\n"
                "`main.py` で `bot.log_buffer = log_buffer` が実行されているか確認してください。"
            )
            return

        # deque からリスト化
        all_lines = list(buffer.logs)

        if not all_lines:
            await ctx.send("📭 現在、取得できるログはありません。")
            return

        if line_count <= 0:
            await ctx.send("❌ 行数は 1 以上で指定してください。")
            return

        # 最新側から指定行数分取得
        requested_lines = all_lines[-line_count:]
        requested_text = "\n".join(requested_lines)

        # 全ログ
        all_text = "\n".join(all_lines)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        # 全ログファイル
        all_file = discord.File(
            io.BytesIO(all_text.encode("utf-8")),
            filename=f"all_logs_{timestamp}.txt"
        )

        # コードブロックを壊しにくいように一応エスケープ
        safe_requested_text = requested_text.replace("```", "｀｀｀")

        content = (
            f"📜 ログ（最新 {len(requested_lines)} 件 / 保持 {len(all_lines)} 件）\n"
            f"```log\n"
            f"{safe_requested_text}\n"
            f"```"
        )

        # Discord のメッセージ上限 2000 文字以内なら本文として送る
        if len(content) <= 2000:
            await ctx.send(content, file=all_file)
        else:
            # 長すぎて本文に入りきらない場合はファイルで送る
            if requested_text == all_text:
                await ctx.send(
                    f"📜 ログが長いため、全ログファイルを添付します。（保持 {len(all_lines)} 件）",
                    file=all_file
                )
            else:
                requested_file = discord.File(
                    io.BytesIO(requested_text.encode("utf-8")),
                    filename=f"requested_logs_{timestamp}.txt"
                )

                await ctx.send(
                    f"📜 ログが長いため、指定分と全ログをファイルで添付します。\n"
                    f"（指定 {len(requested_lines)} 件 / 保持 {len(all_lines)} 件）",
                    files=[all_file, requested_file]
                )

    @logs.error
    async def logs_error(self, ctx: commands.Context, error: commands.CommandError):
        """
        logs コマンド専用エラーハンドラ
        """

        # 許可されていないユーザーが使用した場合
        if isinstance(error, commands.CheckFailure):
            try:
                await ctx.send("❌ このコマンドは許可されたユーザーのみ使用できます。")
            except Exception:
                pass
            return

        # 引数の数字が不正な場合
        if isinstance(error, commands.BadArgument):
            try:
                await ctx.send("❌ 行数は数字で指定してください。例: `!logs 50`")
            except Exception:
                pass
            return

        # その他のエラー
        try:
            await ctx.send("❌ ログ取得中にエラーが発生しました。")
        except Exception:
            pass

        print(f"[LogViewer] logs command error: {error}")


async def setup(bot: commands.Bot):
    await bot.add_cog(LogViewer(bot))
