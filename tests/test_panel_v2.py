import types
import unittest
from unittest.mock import AsyncMock

from cogs.game import GameDetailView
from cogs.sio_voice import VoicePanelView
from core.panel_v2 import as_panel_v2


class PanelV2StateTest(unittest.IsolatedAsyncioTestCase):
    async def test_game_selection_writes_through_to_wrapped_panel(self):
        panel = GameDetailView(None, "othello")
        wrapped = as_panel_v2(panel)

        self.assertEqual(panel.chess_mode, "human")
        wrapped.chess_mode = "cpu"
        self.assertEqual(panel.chess_mode, "cpu")

    async def test_voice_genre_dropdown_keeps_v2_wrapper(self):
        panel = VoicePanelView(None)
        wrapped = as_panel_v2(panel)
        select = wrapped.children[0].children[1].children[0]
        select._values = ["connection"]
        interaction = types.SimpleNamespace(
            response=types.SimpleNamespace(edit_message=AsyncMock())
        )

        await select.callback(interaction)

        self.assertEqual(panel.genre, "connection")
        self.assertIs(interaction.response.edit_message.call_args.kwargs["view"], wrapped)
        self.assertNotIn("embed", interaction.response.edit_message.call_args.kwargs)


if __name__ == "__main__":
    unittest.main()
