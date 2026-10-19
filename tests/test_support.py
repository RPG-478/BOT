import types
import unittest
from unittest.mock import AsyncMock, patch

from cogs.support import (
    RoleBulkView, RoleTargetSelect, SupportCog, SUPPORT_ACTIONS, THINKING_EMOJI, THINKING_SECTION,
)


class FakeRole:
    def __init__(self, role_id=10):
        self.id = role_id
        self.mention = f"<@&{role_id}>"

    def __eq__(self, other):
        return isinstance(other, FakeRole) and self.id == other.id


class FakeMember:
    def __init__(self, member_id, roles=(), *, bot=False):
        self.id = member_id
        self.roles = list(roles)
        self.bot = bot
        self.add_roles = AsyncMock(side_effect=self._add)
        self.remove_roles = AsyncMock(side_effect=self._remove)

    async def _add(self, role, **kwargs):
        if role not in self.roles:
            self.roles.append(role)

    async def _remove(self, role, **kwargs):
        if role in self.roles:
            self.roles.remove(role)


class SupportRoleBulkTest(unittest.IsolatedAsyncioTestCase):
    async def test_adds_only_members_without_role(self):
        cog = SupportCog(None)
        role = FakeRole()
        members = [FakeMember(1), FakeMember(2, [role]), FakeMember(3)]
        guild = types.SimpleNamespace(members=members)
        affected, skipped, failed = await cog.bulk_role_update(guild, role, True)
        self.assertEqual((affected, skipped, failed), (2, 1, 0))
        self.assertIn(role, members[0].roles)
        self.assertIn(role, members[2].roles)
        members[1].add_roles.assert_not_awaited()

    async def test_removes_only_members_with_role(self):
        cog = SupportCog(None)
        role = FakeRole()
        members = [FakeMember(1, [role]), FakeMember(2), FakeMember(3, [role])]
        guild = types.SimpleNamespace(members=members)
        affected, skipped, failed = await cog.bulk_role_update(guild, role, False)
        self.assertEqual((affected, skipped, failed), (2, 1, 0))
        self.assertNotIn(role, members[0].roles)
        self.assertNotIn(role, members[2].roles)
        members[1].remove_roles.assert_not_awaited()

    async def test_bots_are_excluded_by_default(self):
        cog = SupportCog(None)
        role = FakeRole()
        human = FakeMember(1)
        bot = FakeMember(2, bot=True)
        guild = types.SimpleNamespace(members=[human, bot])
        affected, skipped, failed = await cog.bulk_role_update(guild, role, True)
        self.assertEqual((affected, skipped, failed), (1, 1, 0))
        human.add_roles.assert_awaited_once()
        bot.add_roles.assert_not_awaited()

    async def test_bots_can_be_included_with_all_mode(self):
        cog = SupportCog(None)
        role = FakeRole()
        bot = FakeMember(2, bot=True)
        guild = types.SimpleNamespace(members=[bot])
        affected, skipped, failed = await cog.bulk_role_update(guild, role, True, target_mode="all")
        self.assertEqual((affected, skipped, failed), (1, 0, 0))
        bot.add_roles.assert_awaited_once()

    async def test_bots_only_mode_excludes_human_members(self):
        cog = SupportCog(None)
        role = FakeRole()
        human = FakeMember(1)
        bot = FakeMember(2, bot=True)
        guild = types.SimpleNamespace(members=[human, bot])
        affected, skipped, failed = await cog.bulk_role_update(guild, role, True, target_mode="bots")
        self.assertEqual((affected, skipped, failed), (1, 1, 0))
        human.add_roles.assert_not_awaited()
        bot.add_roles.assert_awaited_once()

    def test_support_has_role_bulk_action_and_panel(self):
        self.assertIn("role_bulk", [choice.value for choice in SUPPORT_ACTIONS])
        view = RoleBulkView(SupportCog(None), types.SimpleNamespace(), FakeRole())
        self.assertEqual(len(view.children), 4)
        self.assertEqual(view.target_mode, "humans")
        self.assertIn("人間のみ", view.description())
        target_select = next(item for item in view.children if isinstance(item, RoleTargetSelect))
        self.assertIn("bots", [option.value for option in target_select.options])


class SupportThinkingReactionTest(unittest.IsolatedAsyncioTestCase):
    def make_cog(self, enabled):
        message = types.SimpleNamespace(reactions=[], add_reaction=AsyncMock())
        channel = types.SimpleNamespace(fetch_message=AsyncMock(return_value=message))
        bot = types.SimpleNamespace(
            user=types.SimpleNamespace(id=999),
            get_channel=lambda channel_id: channel,
        )
        cog = SupportCog(bot)
        store = types.SimpleNamespace(
            ensure_loaded=AsyncMock(),
            get=lambda guild_id, section: ({"enabled": enabled} if section == THINKING_SECTION else {}),
        )
        return cog, store, channel, message

    async def test_adds_custom_reaction_when_enabled(self):
        cog, store, channel, message = self.make_cog(True)
        payload = types.SimpleNamespace(
            guild_id=1, user_id=2, emoji="🤔", member=types.SimpleNamespace(bot=False),
            channel_id=3, message_id=4,
        )
        with patch("cogs.support.guild_settings.get_store", return_value=store):
            await cog.on_raw_reaction_add(payload)
        message.add_reaction.assert_awaited_once_with(THINKING_EMOJI)
        channel.fetch_message.assert_awaited_once_with(4)

    async def test_setting_defaults_to_enabled_for_unconfigured_guild(self):
        cog, store, channel, message = self.make_cog(None)
        store.get = lambda guild_id, section: {}
        payload = types.SimpleNamespace(
            guild_id=1, user_id=2, emoji="🤔", member=types.SimpleNamespace(bot=False),
            channel_id=3, message_id=4,
        )
        with patch("cogs.support.guild_settings.get_store", return_value=store):
            await cog.on_raw_reaction_add(payload)
        message.add_reaction.assert_awaited_once_with(THINKING_EMOJI)

    async def test_explicitly_disabled_setting_does_not_mirror(self):
        cog, store, channel, message = self.make_cog(False)
        payload = types.SimpleNamespace(
            guild_id=1, user_id=2, emoji="🤔", member=types.SimpleNamespace(bot=False),
            channel_id=3, message_id=4,
        )
        with patch("cogs.support.guild_settings.get_store", return_value=store):
            await cog.on_raw_reaction_add(payload)
        channel.fetch_message.assert_not_awaited()
        message.add_reaction.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
