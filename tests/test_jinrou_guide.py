"""人狼の初心者ガイド（core/jinrou_guide.py）と役職 ID のテスト。通信はしない。"""
import re
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "tests"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import game_fakes  # noqa: E402,F401  （環境変数などの準備）
from cogs import jinrou  # noqa: E402
from core import jinrou_guide as guide  # noqa: E402

SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def interaction(uid):
    return types.SimpleNamespace(user=types.SimpleNamespace(id=uid),
                                 guild=types.SimpleNamespace(get_member=lambda _: None),
                                 response=types.SimpleNamespace(send_message=AsyncMock()))


class RoleIdTest(unittest.TestCase):
    def test_every_role_has_unique_url_safe_slug(self):
        names = [r[0] for r in jinrou.HELP_ROLES]
        slugs = [r[4] for r in jinrou.HELP_ROLES]
        self.assertTrue(all(len(r) == 5 for r in jinrou.HELP_ROLES))
        self.assertEqual(len(set(names)), len(names))
        self.assertEqual(len(set(slugs)), len(slugs), "役職 ID が重複しています")
        for slug in slugs:
            self.assertRegex(slug, SLUG)
            self.assertTrue(slug.isascii())

    def test_url_uses_slug_and_single_base(self):
        self.assertEqual(guide.role_url("ハゲ"), f"{guide.ROLE_GUIDE_BASE_URL}/hage")
        self.assertEqual(guide.role_url("人狼"), "https://bot-deshihito.vercel.app/jinrou/roles/werewolf")
        self.assertEqual(guide.role_url(None), guide.ROLE_GUIDE_BASE_URL)
        self.assertTrue(guide.role_url("未知の役職").startswith(guide.ROLE_GUIDE_BASE_URL + "/%E6"))


class GuideTextTest(unittest.TestCase):
    def test_every_role_has_full_guide(self):
        for name, team, desc, *_ in jinrou.HELP_ROLES:
            fields = dict(guide.guide_fields(name))
            self.assertEqual(fields["陣営"], team)
            self.assertEqual(fields["能力"], desc)
            self.assertTrue(fields["勝利条件"])
            self.assertTrue(fields["今夜やること"])

    def test_fallback_for_new_role(self):
        fields = dict(guide.guide_fields("新しい役職"))
        self.assertEqual(fields["陣営"], "不明")
        self.assertEqual(fields["今夜やること"], guide.PASSIVE_TODO)
        guide.register_roles([("新しい役職", "人狼陣営", "テスト", "X.PNG", "new-role")])
        try:
            self.assertEqual(dict(guide.guide_fields("新しい役職"))["能力"], "テスト")
            self.assertTrue(guide.role_url("新しい役職").endswith("/new-role"))
        finally:
            guide._roles.pop("新しい役職", None)
            guide.ROLE_IDS.pop("新しい役職", None)

    def test_win_conditions(self):
        self.assertIn("人狼陣営の勝ち", guide.win_condition("狂人"))
        self.assertIn("村人陣営の勝ち", guide.win_condition("占い師"))
        self.assertIn("追放されたら", guide.win_condition("ハゲ"))
        self.assertIn("襲う", guide.night_todo("人狼"))


class RoleNoticeTest(unittest.IsolatedAsyncioTestCase):
    def game(self, roles):
        game = jinrou.JinrouGame()
        game.roles = dict(roles)
        game.display_roles = dict(roles)
        return game

    async def test_role_notice_includes_guide_in_same_message(self):
        game = self.game({1: "占い師"})
        cog = MagicMock()
        cog.get_wolves_names.return_value = "なし"
        it = interaction(1)
        view = jinrou.RoleCheckView(game, cog)
        await view.check.callback(it)
        it.response.send_message.assert_awaited_once()
        kwargs = it.response.send_message.await_args.kwargs
        self.assertTrue(kwargs["ephemeral"])
        names = [f.name for f in kwargs["embed"].fields]
        self.assertIn("🔰 今夜やること", names)
        self.assertIn(guide.role_url("占い師"), [f.value for f in kwargs["embed"].fields])

    async def test_hidden_role_is_not_leaked(self):
        game = self.game({1: "入狼"})
        cog = MagicMock()
        cog.get_wolves_names.return_value = "なし"
        it = interaction(1)
        await jinrou.RoleCheckView(game, cog).check.callback(it)
        embed = it.response.send_message.await_args.kwargs["embed"]
        text = (embed.description or "") + "".join(f.value for f in embed.fields)
        self.assertNotIn("入狼", text)
        self.assertNotIn("nyurou", text)
        self.assertIn("villager", text)


class PhaseButtonTest(unittest.IsolatedAsyncioTestCase):
    async def test_button_sends_ephemeral_phase_help(self):
        game = jinrou.JinrouGame()
        game.roles = {1: "騎士"}
        for phase in ("night", "day", "vote"):
            button = guide.PhaseHelpButton(phase, jinrou._guide_role_lookup(game))
            self.assertEqual(button.label, "？")
            it = interaction(1)
            await button.callback(it)
            kwargs = it.response.send_message.await_args.kwargs
            self.assertTrue(kwargs["ephemeral"])
            self.assertEqual(kwargs["embed"].title, guide.PHASES[phase][0])
            self.assertIn(guide.role_url("騎士"), [f.value for f in kwargs["embed"].fields])
        it = interaction(99)  # 参加していない人
        await guide.PhaseHelpButton("vote", jinrou._guide_role_lookup(game)).callback(it)
        self.assertIn(guide.ROLE_GUIDE_BASE_URL, [f.value for f in it.response.send_message.await_args.kwargs["embed"].fields])

    async def test_phase_messages_have_help_button(self):
        game = jinrou.JinrouGame()
        sent = []
        game.game_channel = types.SimpleNamespace(send=AsyncMock(side_effect=lambda *a, **k: sent.append(k)))
        game.is_running = True
        cog = jinrou.JinrouCog.__new__(jinrou.JinrouCog)
        import asyncio
        real = asyncio.sleep
        jinrou.asyncio.sleep = AsyncMock()
        try:
            await cog.run_discussion(game, 2, "昼")
        finally:
            jinrou.asyncio.sleep = real
        labels = [getattr(i, "label", None) for k in sent if k.get("view") for i in k["view"].children]
        self.assertIn("？", labels)
        night = jinrou.NightActionView(game)
        night.add_item(guide.PhaseHelpButton("night", lambda _: None))
        self.assertEqual([getattr(i, "label", None) for i in night.children], ["夜のアクション", "？"])


if __name__ == "__main__":
    unittest.main()
