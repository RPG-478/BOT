import asyncio
import unittest

from cogs.chess import Chess
from cogs.othello import Othello
from cogs.shogi import Shogi


class FakeMessage:
    def __init__(self):
        self.added = []

    async def add_reaction(self, emoji):
        self.added.append(emoji)


class ReactionParallelTest(unittest.TestCase):
    def test_chess_adds_all_reactions(self):
        message = FakeMessage()
        asyncio.run(Chess(None)._add_reactions(message, ["1️⃣", "🇦", "🇧"]))
        self.assertEqual(message.added, ["1️⃣", "🇦", "🇧"])

    def test_othello_adds_all_reactions(self):
        message = FakeMessage()
        asyncio.run(Othello(None)._add_reactions(message, ["1️⃣", "➡️", "⬅️"]))
        self.assertEqual(message.added, ["1️⃣", "➡️", "⬅️"])

    def test_shogi_adds_all_reactions(self):
        message = FakeMessage()
        asyncio.run(Shogi(None)._add_reactions(message, ["1️⃣", "🇦", "↩️"]))
        self.assertEqual(message.added, ["1️⃣", "🇦", "↩️"])


if __name__ == "__main__":
    unittest.main()
