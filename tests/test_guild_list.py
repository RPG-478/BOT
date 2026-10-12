"""!guild（導入サーバー一覧）のテスト。"""

import sys
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cogs.terminal import guild_list_messages  # noqa: E402


def g(i, name, n):
    return types.SimpleNamespace(id=i, name=name, member_count=n)


class GuildListTest(unittest.TestCase):
    def test_sorted_by_members(self):
        out = guild_list_messages([g(1, "小", 3), g(2, "大", 50)])
        self.assertEqual(len(out), 1)
        self.assertIn("2 件", out[0])
        self.assertLess(out[0].index("大"), out[0].index("小"))

    def test_split_under_limit(self):
        out = guild_list_messages([g(i, "サーバー" * 20, 1) for i in range(100)])
        self.assertGreater(len(out), 1)
        self.assertTrue(all(len(c) <= 1900 for c in out))
        self.assertEqual(sum(c.count("ID ") for c in out), 100)


if __name__ == "__main__":
    unittest.main()
