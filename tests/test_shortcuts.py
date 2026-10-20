import types
import unittest
from unittest.mock import AsyncMock

from cogs.general import (GENERAL_ACTIONS, GENERAL_GENRES, GeneralPanel,
                           ShortcutManagerView, ShortcutRootPanel)
from cogs.game import GameDetailView, GameHubView
from core import shortcuts
from core.panel_v2 import as_panel_v2


class MemoryStore:
    def __init__(self):
        self.data = {}

    def get(self, guild_id, section):
        return self.data.get((guild_id, section), {})

    async def update(self, guild_id, section, **values):
        self.data[(guild_id, section)] = values


class ShortcutTest(unittest.IsolatedAsyncioTestCase):
    async def test_custom_genre_and_two_step_builder(self):
        self.assertIn("custom", GENERAL_GENRES)
        self.assertEqual(GENERAL_ACTIONS["custom"], [("ショートカットを管理", "shortcut_manage")])
        view = ShortcutRootPanel()
        self.assertEqual(len(view.children[0].options), 5)
        self.assertEqual(view.children[0].options[0].value, "general")

    async def test_general_custom_genre_keeps_components_v2_wrapper(self):
        panel = GeneralPanel(None)
        wrapper = as_panel_v2(panel)
        select = wrapper.children[0].children[1].children[0]
        select._values = ["custom"]
        interaction = types.SimpleNamespace(
            response=types.SimpleNamespace(edit_message=AsyncMock())
        )

        await select.callback(interaction)

        self.assertEqual(panel.genre, "custom")
        self.assertIs(interaction.response.edit_message.call_args.kwargs["view"], wrapper)
        self.assertNotIn("embed", interaction.response.edit_message.call_args.kwargs)

    async def test_shortcut_manager_register_button_opens_v2_root_panel(self):
        manager = ShortcutManagerView(None, 1, 2)
        wrapper = as_panel_v2(manager)
        register = wrapper.children[0].children[1].children[0]
        interaction = types.SimpleNamespace(
            response=types.SimpleNamespace(edit_message=AsyncMock())
        )

        self.assertEqual(manager.embed().color.value, 0xFFFFFF)
        await register.callback(interaction)

        next_view = interaction.response.edit_message.call_args.kwargs["view"]
        self.assertIsInstance(next_view.panel, ShortcutRootPanel)

    async def test_game_selection_keeps_components_v2_wrapper(self):
        panel = GameHubView(None, shortcut_mode=True)
        wrapper = as_panel_v2(panel)
        genre_select = wrapper.children[0].children[1].children[0]
        genre_select._values = ["party"]
        genre_interaction = types.SimpleNamespace(
            response=types.SimpleNamespace(edit_message=AsyncMock())
        )

        await genre_select.callback(genre_interaction)

        self.assertEqual(panel.genre, "party")
        self.assertIs(genre_interaction.response.edit_message.call_args.kwargs["view"], wrapper)
        self.assertNotIn("embed", genre_interaction.response.edit_message.call_args.kwargs)
        game_select = wrapper.children[0].children[2].children[0]
        game_select._values = ["uno"]
        game_interaction = types.SimpleNamespace(
            response=types.SimpleNamespace(edit_message=AsyncMock())
        )
        await game_select.callback(game_interaction)

        next_view = game_interaction.response.edit_message.call_args.kwargs["view"]
        self.assertIsInstance(next_view.panel, GameDetailView)

    async def test_game_detail_back_keeps_components_v2_wrapper(self):
        panel = GameDetailView(None, "othello")
        wrapper = as_panel_v2(panel)
        back = next(
            item for row in wrapper.children[0].children
            for item in getattr(row, "children", [])
            if getattr(item, "label", None) == "戻る"
        )
        interaction = types.SimpleNamespace(
            response=types.SimpleNamespace(edit_message=AsyncMock())
        )

        await back.callback(interaction)

        next_view = interaction.response.edit_message.call_args.kwargs["view"]
        self.assertIsInstance(next_view.panel, GameHubView)

    async def test_limit_duplicate_and_remove(self):
        store = MemoryStore()
        for index in range(shortcuts.MAX_SHORTCUTS):
            await shortcuts.add(store, 1, 2, f"t{index}", {"root": "general", "value": "status"})
        with self.assertRaises(ValueError):
            await shortcuts.add(store, 1, 2, "overflow", {"root": "general", "value": "status"})
        with self.assertRaises(ValueError):
            await shortcuts.add(store, 1, 2, "t1", {"root": "general", "value": "status"})
        rows = shortcuts.for_user(store, 1, 2)
        self.assertTrue(await shortcuts.remove(store, 1, 2, rows[0]["id"]))
        self.assertEqual(len(shortcuts.for_user(store, 1, 2)), 9)


if __name__ == "__main__":
    unittest.main()
