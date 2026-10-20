import unittest

from cogs.game import GameDetailView
from core.panel_v2 import as_panel_v2


class PanelV2StateTest(unittest.TestCase):
    def test_game_selection_writes_through_to_wrapped_panel(self):
        panel = GameDetailView(None, "othello")
        wrapped = as_panel_v2(panel)

        self.assertEqual(panel.chess_mode, "human")
        wrapped.chess_mode = "cpu"
        self.assertEqual(panel.chess_mode, "cpu")


if __name__ == "__main__":
    unittest.main()
