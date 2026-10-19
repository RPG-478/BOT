import types
import unittest

from cogs.general import GENERAL_ACTIONS, GENERAL_GENRES, ShortcutRootPanel
from core import shortcuts


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
