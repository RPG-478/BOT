import unittest

from cogs.othello import BLACK, WHITE, choose_ai_move as choose_othello_move, legal_moves as othello_moves, new_board
from cogs.shogi import ShogiRenderer, choose_ai_move as choose_shogi_move
from core.shogi_engine import Color, Piece, PieceType, ShogiGame


class BoardAiTest(unittest.TestCase):
    def empty_shogi(self):
        game = ShogiGame()
        game.board = [[None for _ in range(9)] for _ in range(9)]
        return game

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

    def test_shogi_promoted_piece_does_not_reuse_unpromoted_image_cache(self):
        renderer = ShogiRenderer()
        plain = renderer._piece_img(Piece(PieceType.PAWN, Color.SENTE))
        promoted = renderer._piece_img(Piece(PieceType.PAWN, Color.SENTE, promoted=True))
        self.assertIsNot(plain, promoted)

    def test_shogi_promotion_and_hand_drop(self):
        game = ShogiGame()
        game.board = [[None for _ in range(9)] for _ in range(9)]
        game.board[3][3] = Piece(PieceType.PAWN, Color.SENTE)
        self.assertTrue(game.make_move((3, 3), (2, 3), promote=True))
        self.assertTrue(game.board[2][3].promoted)

        game.turn = Color.SENTE
        game.hands[Color.SENTE][PieceType.ROOK] = 1
        self.assertTrue(game.make_move(None, (4, 4), drop_type=PieceType.ROOK))
        self.assertEqual(game.board[4][4].type, PieceType.ROOK)
        self.assertEqual(game.hands[Color.SENTE][PieceType.ROOK], 0)

    def test_shogi_rejects_a_move_that_leaves_own_king_in_check(self):
        game = self.empty_shogi()
        game.board[8][4] = Piece(PieceType.KING, Color.SENTE)
        game.board[7][4] = Piece(PieceType.ROOK, Color.SENTE)
        game.board[0][4] = Piece(PieceType.ROOK, Color.GOTE)
        self.assertFalse(game.make_move((7, 4), (7, 3)))
        self.assertIsNotNone(game.board[7][4])

    def test_shogi_detects_checkmate(self):
        game = self.empty_shogi()
        game.board[8][8] = Piece(PieceType.KING, Color.SENTE)
        game.board[0][8] = Piece(PieceType.ROOK, Color.GOTE)
        game.board[8][0] = Piece(PieceType.ROOK, Color.GOTE)
        game.board[6][6] = Piece(PieceType.BISHOP, Color.GOTE)
        self.assertTrue(game.is_in_check(Color.SENTE))
        self.assertTrue(game.is_checkmate(Color.SENTE))


if __name__ == "__main__":
    unittest.main()
