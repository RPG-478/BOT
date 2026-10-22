"""@BOTメンションをBlockRun 6lunaへ接続するCog。"""
from __future__ import annotations

import logging
import os
import re

import discord
from discord.ext import commands

from core import blockrun_agent, blockrun_preferences

logger = logging.getLogger(__name__)


def _enabled_globally() -> bool:
    return os.getenv("BLOCKRUN_MENTION_ENABLED", "false").lower() in {"1", "true", "yes", "on"}


class BlockRunCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        await blockrun_preferences.ensure_loaded()

    def _clean_mention(self, content: str) -> str:
        if not self.bot.user:
            return content.strip()
        return re.sub(rf"<@!?{self.bot.user.id}>", "", content).strip()

    @commands.command(name="blockrun", help="BlockRunメンションエージェントの設定を表示・変更します")
    async def blockrun(self, ctx: commands.Context, action: str = "", *, value: str = ""):
        config = blockrun_preferences.get_config(ctx.author.id)
        action = action.lower().strip()
        if not action or action == "status":
            embed = discord.Embed(title="BlockRun設定", color=0x5865F2)
            embed.description = (
                f"有効: `{config['enabled']}`\n"
                f"許可ツール: `{', '.join(config['tools']) or 'なし'}`\n"
                f"追加方針: `{config['instruction'] or 'なし'}`\n\n"
                "判定モデル: `gpt-6-luna`（BlockRun Decisions API）\n"
                "設定例: `!blockrun on` / `!blockrun off`\n"
                "`!blockrun tools web_search`\n"
                "`!blockrun prompt 最新情報は必ずWeb検索してURLを示す`"
            )
            return await ctx.reply(embed=embed, mention_author=False)
        if action in {"on", "enable", "有効"}:
            await blockrun_preferences.update(ctx.author.id, enabled=True)
            return await ctx.reply("BlockRunメンション応答を有効にしました。", mention_author=False)
        if action in {"off", "disable", "無効"}:
            await blockrun_preferences.update(ctx.author.id, enabled=False)
            return await ctx.reply("BlockRunメンション応答を無効にしました。", mention_author=False)
        if action == "tools":
            requested = [item.strip() for item in value.split(",") if item.strip()]
            invalid = [item for item in requested if item not in blockrun_preferences.ALLOWED_TOOLS]
            if invalid:
                return await ctx.reply(
                    f"未対応ツールです: `{', '.join(invalid)}`。現在は `web_search` のみ設定できます。",
                    mention_author=False,
                )
            await blockrun_preferences.update(ctx.author.id, tools=requested)
            return await ctx.reply(
                f"BlockRunの許可ツールを `{', '.join(requested) or 'なし'}` に設定しました。",
                mention_author=False,
            )
        if action in {"prompt", "instruction", "方針"}:
            instruction = value.strip()
            if len(instruction) > 1000:
                return await ctx.reply("追加方針は1000文字以内で指定してください。", mention_author=False)
            await blockrun_preferences.update(ctx.author.id, instruction=instruction)
            return await ctx.reply("BlockRunの追加方針を更新しました。", mention_author=False)
        if action == "reset":
            await blockrun_preferences.set_config(ctx.author.id, blockrun_preferences.DEFAULT_CONFIG)
            return await ctx.reply("BlockRun設定を初期化しました。", mention_author=False)
        return await ctx.reply("使い方: `!blockrun status|on|off|tools web_search|prompt 方針|reset`", mention_author=False)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild or not _enabled_globally():
            return
        if not self.bot.user or self.bot.user not in message.mentions:
            return
        config = blockrun_preferences.get_config(message.author.id)
        if not config["enabled"]:
            return
        prompt = self._clean_mention(message.content)
        if not prompt:
            return await message.reply("メンションの後に質問を入力してください。", mention_author=False)
        async with message.channel.typing():
            try:
                answer, sources, decision = await blockrun_agent.answer(prompt, config)
            except Exception:
                logger.exception("BlockRun mention request failed: user=%s", message.author.id)
                return await message.reply(
                    "BlockRun Decisions APIへの問い合わせに失敗しました。APIキーと時間あたりの利用上限を確認してください。",
                    mention_author=False,
                )
        if not answer:
            return await message.reply("BlockRunから空の回答が返りました。", mention_author=False)
        embed = discord.Embed(title="BlockRun回答", description=answer[:4096], color=0x5865F2)
        embed.set_footer(
            text=f"判定: {decision.get('tool', 'none')} / 確率 {decision.get('probability', 0):.2f}"
        )
        unique = {source.get("url"): source for source in sources if source.get("url")}
        if unique:
            embed.add_field(
                name="参照ソース",
                value="\n".join(f"[{source.get('title', '参照')[:80]}]({url})" for url, source in list(unique.items())[:5])[:1024],
                inline=False,
            )
        await message.reply(embed=embed, mention_author=False)


async def setup(bot: commands.Bot):
    await bot.add_cog(BlockRunCog(bot))
