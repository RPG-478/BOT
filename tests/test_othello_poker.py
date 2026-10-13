"""オセロ・ポーカーの基本ルールテスト。"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import game_fakes  # noqa: F401
from cogs.othello import BLACK, WHITE, legal_moves, new_board, play_move
from cogs.poker import evaluate


class OthelloTest(unittest.TestCase):
    def test_initial_moves_and_flip(self):
        board = new_board()
        moves = legal_moves(board, BLACK)
        self.assertEqual(len(moves), 4)
        self.assertTrue(play_move(board, BLACK, 2, 3))
        self.assertEqual(board[3][3], BLACK)
        self.assertEqual(board[2][3], BLACK)
        self.assertEqual(len(legal_moves(board, WHITE)), 3)

    def test_reject_illegal_move(self):
        self.assertFalse(play_move(new_board(), BLACK, 0, 0))


class PokerTest(unittest.TestCase):
    def test_hand_rank_order(self):
        hands = [
            ["2♠", "3♥", "4♦", "5♣", "6♠"],
            ["A♠", "A♥", "A♦", "A♣", "2♠"],
            ["2♠", "2♥", "2♦", "3♣", "3♠"],
        ]
        ranked = [evaluate(hand)[0] for hand in hands]
        self.assertGreater(ranked[1], ranked[2])
        self.assertGreater(ranked[2], ranked[0])

    def test_wheel_straight_flush(self):
        score, name = evaluate(["A♠", "2♠", "3♠", "4♠", "5♠"])
        self.assertEqual(name, "ストレートフラッシュ")
        self.assertEqual(score, (8, 5))


if __name__ == "__main__":
    unittest.main()
