import unittest

from cogs.othello import BLACK, WHITE, choose_ai_move as choose_othello_move, legal_moves as othello_moves, new_board
from cogs.shogi import ShogiRenderer, choose_ai_move as choose_shogi_move
from core.shogi_engine import Color, Piece, PieceType, ShogiGame


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

    def test_shogi_promoted_piece_images_are_not_transparent_placeholders(self):
        renderer = ShogiRenderer()
        for color in (Color.SENTE, Color.GOTE):
            for piece_type in (PieceType.PAWN, PieceType.LANCE, PieceType.KNIGHT,
                               PieceType.SILVER, PieceType.BISHOP, PieceType.ROOK):
                with self.subTest(color=color, piece_type=piece_type):
                    image = renderer._piece_img(Piece(piece_type, color, promoted=True))
                    self.assertIsNotNone(image.getchannel("A").getbbox())


if __name__ == "__main__":
    unittest.main()
