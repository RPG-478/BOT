import unittest

import discord

from cogs.chess import START_BOARD, apply_move, choose_ai_move, legal_moves
from cogs.game import ChessDifficultySelect, ChessModeSelect, GameDetailView


class ChessAiTest(unittest.TestCase):
    def test_each_difficulty_returns_a_legal_move(self):
        for difficulty in range(1, 11):
            with self.subTest(difficulty=difficulty):
                board = [row[:] for row in START_BOARD]
                move = choose_ai_move(board, "black", difficulty)
                self.assertIn(move, legal_moves(board, "black"))
                self.assertEqual(board, START_BOARD)

    def test_apply_move_does_not_mutate_original(self):
        move = ((6, 4), (4, 4))
        board = apply_move(START_BOARD, move)
        self.assertEqual(START_BOARD[6][4], "P")
        self.assertEqual(board[4][4], "P")
        self.assertEqual(board[6][4], ".")

    def test_difficulty_selector_has_values_one_to_ten(self):
        selector = ChessDifficultySelect(5)
        self.assertEqual([int(option.value) for option in selector.options], list(range(1, 11)))
        self.assertTrue(selector.options[4].default)

    def test_chess_detail_view_exposes_mode_and_difficulty(self):
        view = GameDetailView(type("Cog", (), {})(), "chess")
        selects = [child for child in view.children if isinstance(child, discord.ui.Select)]
        self.assertTrue(any(isinstance(child, ChessModeSelect) for child in selects))
        self.assertTrue(any(isinstance(child, ChessDifficultySelect) for child in selects))


if __name__ == "__main__":
    unittest.main()
