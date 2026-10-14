import unittest

from cogs.othello import BLACK, WHITE, choose_ai_move as choose_othello_move, legal_moves as othello_moves, new_board
from cogs.shogi import choose_ai_move as choose_shogi_move
from core.shogi_engine import Color, ShogiGame


class BoardAiTest(unittest.TestCase):
    def test_othello_difficulties_return_legal_moves(self):
        board = new_board()
        for difficulty in range(1, 11):
            with self.subTest(difficulty=difficulty):
                move = choose_othello_move(board, WHITE, difficulty)
                self.assertIn(move, othello_moves(board, WHITE))
        self.assertEqual(len(othello_moves(board, BLACK)), 4)

    def test_shogi_difficulties_return_executable_moves(self):
        for difficulty in range(1, 11):
            with self.subTest(difficulty=difficulty):
                game = ShogiGame()
                move = choose_shogi_move(game, difficulty)
                self.assertIsNotNone(move)
                source, dest, promote, drop_type = move
                self.assertEqual(game.turn, Color.SENTE)
                self.assertTrue(game.make_move(source, dest, promote=promote, drop_type=drop_type))


if __name__ == "__main__":
    unittest.main()
