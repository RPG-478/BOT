import random
import types
import unittest
from unittest.mock import AsyncMock

from cogs.dice import DiceCog, MAX_SIDES, MAX_SIDES_DIGITS, parse_dice_message, roll_dice


class DiceParsingTest(unittest.TestCase):
    def test_parses_explicit_sides(self):
        self.assertEqual(parse_dice_message("1d100"), ("explicit", 100))
        self.assertEqual(parse_dice_message(" 1d6 "), ("explicit", 6))

    def test_parses_any(self):
        self.assertEqual(parse_dice_message("1dany"), ("any", None))

    def test_non_matching_messages_are_ignored(self):
        for content in ("d100", "2d6", "1D100", "1dany please", "hello1d6", "1d"):
            self.assertIsNone(parse_dice_message(content))

    def test_zero_and_too_many_digits_are_invalid(self):
        self.assertEqual(parse_dice_message("1d0"), ("invalid", 0))
        self.assertEqual(parse_dice_message("1d" + "9" * (MAX_SIDES_DIGITS + 1))[0], "invalid")

    def test_roll_is_inclusive(self):
        rng = random.Random(4)
        for _ in range(100):
            result = roll_dice(6, rng)
            self.assertTrue(1 <= result <= 6)


class DiceCogTest(unittest.IsolatedAsyncioTestCase):
    def message(self, content):
        return types.SimpleNamespace(
            content=content,
            author=types.SimpleNamespace(bot=False),
            reply=AsyncMock(),
        )

    async def test_explicit_dice_replies_with_result(self):
        cog = DiceCog(None, rng=random.Random(1))
        message = self.message("1d6")
        await cog.on_message(message)
        text = message.reply.await_args.args[0]
        self.assertIn("1d6", text)
        value = int(text.split("**")[1])
        self.assertTrue(1 <= value <= 6)
        self.assertEqual(message.reply.await_args.kwargs["mention_author"], False)

    async def test_any_selects_sides_and_rolls_within_limit(self):
        cog = DiceCog(None, rng=random.Random(2))
        message = self.message("1dany")
        await cog.on_message(message)
        text = message.reply.await_args.args[0]
        sides = int(text.split("1d")[1].split("`")[0])
        value = int(text.split("**")[1])
        self.assertTrue(1 <= sides <= MAX_SIDES)
        self.assertTrue(1 <= value <= sides)

    async def test_bot_messages_are_ignored(self):
        cog = DiceCog(None, rng=random.Random(1))
        message = self.message("1d6")
        message.author.bot = True
        await cog.on_message(message)
        message.reply.assert_not_awaited()

    async def test_invalid_sides_get_feedback(self):
        cog = DiceCog(None, rng=random.Random(1))
        message = self.message("1d0")
        await cog.on_message(message)
        self.assertIn("1以上", message.reply.await_args.args[0])


if __name__ == "__main__":
    unittest.main()
