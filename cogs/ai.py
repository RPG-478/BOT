"""!ai で Logfare のチャットモデルを呼び出す機能。"""
from __future__ import annotations

import logging

import discord
from discord.ext import commands

from core import ai_preferences, logfare

logger = logging.getLogger(__name__)


class AICog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.command(name="ai", help="LogfareのAIに質問します。例: !ai 今日の天気を教えて")
    @commands.cooldown(1, 5.0, commands.BucketType.user)
    async def ai(self, ctx: commands.Context, *, prompt: str = ""):
        prompt = prompt.strip()
        if not prompt:
            return await ctx.reply("使い方: `!ai 質問内容`", mention_author=False)
        if not logfare.api_key():
            return await ctx.reply("Logfareが未設定です。`.env` に `LOGFARE_API_KEY` を設定してください。", mention_author=False)

        preferred = ai_preferences.get_model(ctx.author.id) or logfare.configured_default_model()
        try:
            model, exact = await logfare.resolve_model(preferred)
            async with ctx.typing():
                answer = await logfare.chat(
                    model,
                    [
                        {
                            "role": "system",
                            "content": "あなたはDiscord上の親切なアシスタントです。日本語で簡潔かつ正確に回答してください。",
                        },
                        {"role": "user", "content": prompt},
                    ],
                )
        except Exception:
            logger.exception("!ai request failed: user=%s model=%s", ctx.author.id, preferred)
            return await ctx.reply("AIへの問い合わせに失敗しました。しばらくしてから再試行してください。", mention_author=False)

        if not answer:
            return await ctx.reply("AIから空の回答が返りました。", mention_author=False)
        notice = "" if exact else f"（指定モデルがfree一覧にないため `{model}` を使用）"
        text = f"**AI（{model}）**{notice}\n{answer}"
        await ctx.reply(text[:2000], mention_author=False)

    @ai.error
    async def ai_error(self, ctx: commands.Context, error: commands.CommandError):
        if isinstance(error, commands.CommandOnCooldown):
            return await ctx.reply(f"少し待ってから再試行してください（{error.retry_after:.1f}秒）。", mention_author=False)
        logger.exception("!ai command error", exc_info=error)


async def setup(bot: commands.Bot):
    await bot.add_cog(AICog(bot))
