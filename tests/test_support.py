import types
import unittest
from unittest.mock import AsyncMock

from cogs.support import RoleBulkView, SupportCog, SUPPORT_ACTIONS


class FakeRole:
    def __init__(self, role_id=10):
        self.id = role_id
        self.mention = f"<@&{role_id}>"

    def __eq__(self, other):
        return isinstance(other, FakeRole) and self.id == other.id


class FakeMember:
    def __init__(self, member_id, roles=()):
        self.id = member_id
        self.roles = list(roles)
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

    def test_support_has_role_bulk_action_and_panel(self):
        self.assertIn("role_bulk", [choice.value for choice in SUPPORT_ACTIONS])
        view = RoleBulkView(SupportCog(None), types.SimpleNamespace(), FakeRole())
        self.assertEqual(len(view.children), 3)


if __name__ == "__main__":
    unittest.main()
