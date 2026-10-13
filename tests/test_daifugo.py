"""大富豪の基本ルール回帰テスト。"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import game_fakes  # noqa: F401
from cogs.daifugo import DaifugoGame


class DaifugoRulesTest(unittest.TestCase):
    def test_eight_cut_clears_table_and_passes_lead_to_next_player(self):
        game = DaifugoGame(10, 20, 1)
        game.players = {1: object(), 2: object(), 3: object()}
        game.hands = {1: ["S5"], 2: ["H8", "C3"], 3: ["D4"]}
        game.phase = "playing"
        game.turn = 2
        game.table = ("S5",)
        game.last_player = 1

        result = game.play(2, ("H8",))

        self.assertEqual(result, "ok")
        self.assertIsNone(game.table)
        self.assertEqual(game.turn, 3)
        self.assertTrue(game.cleared)
        self.assertTrue(game.eight_cut)


if __name__ == "__main__":
    unittest.main()
