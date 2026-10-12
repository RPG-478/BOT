"""グローバル人狼の合流パネル（GlobalJoinView）のテスト。Discord には接続しない。"""

import asyncio
import sys
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cogs import jinrou as J  # noqa: E402


class Chan:
    def __init__(self, cid):
        self.id, self.sent = cid, []

    async def send(self, *a, **k):
        self.sent.append(a[0] if a else k)


def interaction(uid, chan):
    replies = []

    async def send_message(*a, **k):
        replies.append(a[0] if a else k.get("content"))
    return types.SimpleNamespace(user=types.SimpleNamespace(id=uid, display_name=f"u{uid}"), channel=chan,
                                 response=types.SimpleNamespace(send_message=send_message)), replies


class GlobalJoinTest(unittest.TestCase):
    def setUp(self):
        self.origin, self.other = Chan(1), Chan(2)
        self.game = J.JinrouGame()
        self.game.is_global, self.game.is_running = True, True
        self.game.channels = [self.origin, self.other]
        self.cog = types.SimpleNamespace(games={"global": self.game})

    def press(self, uid, chan):
        it, replies = interaction(uid, chan)

        async def go():
            view = J.GlobalJoinView(self.cog, self.game)
            await view.join.callback(it)
        asyncio.run(go())
        return replies

    def test_join_during_recruit(self):
        replies = self.press(10, self.other)
        self.assertEqual([p.id for p in self.game.players], [10])
        self.assertIn("参加しました", replies[0])
        self.assertTrue(self.origin.sent)  # 元のサーバーにも知らせる

    def test_no_double_join(self):
        self.press(10, self.other)
        self.assertIn("既に", self.press(10, self.other)[0])
        self.assertEqual(len(self.game.players), 1)

    def test_refuse_after_start(self):
        self.game.started = True
        self.assertIn("進行中", self.press(10, self.other)[0])
        self.assertEqual(self.game.players, [])

    def test_refuse_when_recruit_over(self):
        self.game.is_running = False
        self.assertIn("終わりました", self.press(10, self.other)[0])


if __name__ == "__main__":
    unittest.main()
