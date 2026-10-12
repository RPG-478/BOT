"""/nation の初回ガイドのテスト。Discord・Supabase には接続しない。"""

import asyncio
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import discord  # noqa: E402
from discord.ext import commands  # noqa: E402

from cogs import nation_onboarding as onboarding  # noqa: E402
from core import command_meta  # noqa: E402
from core.storage import KVStore  # noqa: E402


def run(coro):
    return asyncio.run(coro)


class FakeResponse:
    def __init__(self, done=True):
        self.done, self.sent, self.edits = done, [], []

    def is_done(self):
        return self.done

    async def send_message(self, **kwargs):
        self.sent.append(kwargs)

    async def edit_message(self, **kwargs):
        self.edits.append(kwargs)


def fake_interaction(user_id=42, done=True):
    sent = []

    async def followup_send(**kwargs):
        sent.append(kwargs)
    return types.SimpleNamespace(user=types.SimpleNamespace(id=user_id), response=FakeResponse(done),
                                 followup=types.SimpleNamespace(send=followup_send), sent=sent)


def command(name):
    return types.SimpleNamespace(qualified_name=name)


class NationOnboardingTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = os.path.join(tmp.name, "bot_kv.json")
        self.bot = commands.Bot(command_prefix="!", intents=discord.Intents.none())

    def cog(self):
        return onboarding.NationOnboardingCog(self.bot, store=KVStore("nation_onboarding", client=None, path=self.path))

    def test_first_nation_command_shows_private_guide_once(self):
        cog = self.cog()
        first = fake_interaction()
        run(cog.on_app_command_completion(first, command("nation status")))
        self.assertEqual(len(first.sent), 1)
        self.assertTrue(first.sent[0]["ephemeral"])
        self.assertIn(command_meta.NATION_TUTORIAL[0]["title"], first.sent[0]["embed"].title)
        again = fake_interaction()
        run(cog.on_app_command_completion(again, command("nation join")))
        self.assertEqual(again.sent, [])

    def test_seen_is_remembered_across_restart(self):
        run(self.cog().on_app_command_completion(fake_interaction(), command("nation found")))
        later = fake_interaction()
        run(self.cog().on_app_command_completion(later, command("nation status")))
        self.assertEqual(later.sent, [])
        other = fake_interaction(user_id=7)
        run(self.cog().on_app_command_completion(other, command("nation status")))
        self.assertEqual(len(other.sent), 1)

    def test_other_commands_are_ignored(self):
        cog = self.cog()
        for name in ("wallet", "nationx", "help"):
            i = fake_interaction()
            run(cog.on_app_command_completion(i, command(name)))
            self.assertEqual(i.sent, [])
        self.assertEqual(cog.store.load_local(), {})

    def test_uses_response_when_not_done(self):
        i = fake_interaction(done=False)
        run(self.cog().on_app_command_completion(i, command("nation join")))
        self.assertEqual(len(i.response.sent), 1)

    def test_view_steps_through_three_pages(self):
        async def go():
            view = onboarding.TutorialView(42)
            self.assertTrue(view.back.disabled)
            for step in (1, 2):
                i = fake_interaction()
                await view.next.callback(i)
                self.assertEqual(view.step, step)
                self.assertIn(command_meta.NATION_TUTORIAL[step]["title"], i.response.edits[0]["embed"].title)
            self.assertEqual(view.next.label, "とじる")
            i = fake_interaction()
            await view.back.callback(i)
            self.assertEqual(view.step, 1)
            await view.next.callback(fake_interaction())
            close = fake_interaction()
            await view.next.callback(close)
            self.assertIsNone(close.response.edits[0]["view"])
            self.assertFalse(await view.interaction_check(fake_interaction(user_id=1)))
        run(go())

    def test_guide_text_is_shared_with_help(self):
        self.assertEqual(len(command_meta.NATION_TUTORIAL), 3)
        for key in ("/nation join", "/nation found", "/nation status"):
            self.assertEqual(command_meta.resolve_guide(command_meta.COMMAND_META[key]), command_meta.NATION_GUIDE)
        for step in range(3):
            embed = onboarding.tutorial_embed(step)
            self.assertLessEqual(len(embed.title), 256)
            self.assertLessEqual(len(embed.description), 4096)


if __name__ == "__main__":
    unittest.main()
