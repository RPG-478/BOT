import unittest

from cogs.chess import ChessMoveView
from cogs.othello import OthelloMoveView, WHITE, legal_moves, new_board
from cogs.shogi import ShogiMoveView


class SelectMenuTest(unittest.TestCase):
    def test_chess_uses_numbered_select(self):
        view = ChessMoveView(None, object(), [("1", (0, 0)), ("2", (0, 1))], "source")
        self.assertEqual([option.label for option in view.children[0].options], ["1番", "2番"])

    def test_othello_uses_numbered_select(self):
        view = OthelloMoveView(None, object(), legal_moves(new_board(), WHITE))
        self.assertTrue(all(option.label.endswith("番") for option in view.children[0].options))

    def test_shogi_uses_numbered_select(self):
        view = ShogiMoveView(None, object(), [("1", (0, 0))])
        self.assertEqual(view.children[0].options[0].label, "1番")


if __name__ == "__main__":
    unittest.main()
