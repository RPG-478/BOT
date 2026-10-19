"""通常メッセージで使える 1d ダイス機能。"""
from __future__ import annotations

import random
import re

import discord
from discord.ext import commands


# Pythonの任意精度整数を利用しつつ、メッセージ長・計算量の暴走を防ぐ。
MAX_SIDES_DIGITS = 1000
MAX_SIDES = 10**MAX_SIDES_DIGITS
_DICE_PATTERN = re.compile(r"^1d(?:(any)|([0-9]+))$")


def parse_dice_message(content: str) -> tuple[str, int | None] | None:
    """``1d100`` または ``1dany`` を解釈する。完全一致・前後空白は許可。"""
    match = _DICE_PATTERN.fullmatch((content or "").strip())
    if not match:
        return None
    if match.group(1):
        return "any", None
    sides = int(match.group(2))
    if sides < 1 or len(match.group(2)) > MAX_SIDES_DIGITS:
        return "invalid", sides
    return "explicit", sides


def roll_dice(sides: int, rng: random.Random | random.SystemRandom = random) -> int:
    """1以上 sides 以下の値を返す。"""
    return rng.randint(1, sides)


class DiceCog(commands.Cog):
    """コマンド登録を行わず、通常メッセージだけを監視するCog。"""

    def __init__(self, bot: commands.Bot, rng=None):
        self.bot = bot
        self.rng = rng or random.SystemRandom()

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return

        parsed = parse_dice_message(message.content)
        if parsed is None:
            return

        kind, sides = parsed
        if kind == "invalid":
            await message.reply(
                f"🎲 面数は1以上、{MAX_SIDES_DIGITS}桁以内で指定してください。",
                mention_author=False,
            )
            return

        if kind == "any":
            sides = self.rng.randint(1, MAX_SIDES)
            notation = f"1d{sides}"
        else:
            notation = f"1d{sides}"

        result = roll_dice(sides, self.rng)
        await message.reply(f"🎲 `{notation}` → **{result}**", mention_author=False)


async def setup(bot: commands.Bot):
    await bot.add_cog(DiceCog(bot))
