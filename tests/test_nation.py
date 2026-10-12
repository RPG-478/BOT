"""/nation（参加・建国・状態表示）のテスト。Discord・Supabase には接続しない。"""

import asyncio
import sys
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tests.test_all_commands import USER_ID, FakeSupabase, fake_interaction  # noqa: E402

import discord  # noqa: E402
from discord.ext import commands  # noqa: E402

from cogs import nation as nation_module  # noqa: E402


class NationFakeSupabase(FakeSupabase):
    """呼ばれた rpc を記録する。nation_found の再現は tests/test_all_commands.py の FakeSupabase にある。"""

    def __init__(self):
        super().__init__()
        self.rpc_calls = []

    def rpc(self, name, params=None, **kwargs):
        self.rpc_calls.append((name, params))
        return super().rpc(name, params, **kwargs)


def run(coro):
    return asyncio.run(coro)


class NationTest(unittest.TestCase):
    def setUp(self):
        self.db = NationFakeSupabase()
        self.bot = commands.Bot(command_prefix='!', intents=discord.Intents.none())
        self.bot.supabase = self.db
        self.cog = nation_module.NationCog(self.bot)

    def call(self, name, admin=True, owner=False, user_id=USER_ID):
        interaction, _, _ = fake_interaction(self.bot)
        sent = []

        async def send(*args, **kwargs):
            sent.append(kwargs)
        interaction.response.send_message = send
        interaction.followup.send = send
        interaction.user.id = user_id
        interaction.user.guild_permissions = discord.Permissions.all() if admin else discord.Permissions.none()
        interaction.guild.owner_id = user_id if owner else 1
        run(getattr(self.cog, name).callback(self.cog, interaction))
        return sent

    def rows(self, table):
        return self.db.tables.get(table, [])

    def test_spiral_starts_at_origin_and_is_unique(self):
        coords = list(nation_module.spiral_coords(3))
        self.assertEqual(coords[0], (0, 0))
        self.assertEqual(len(coords), len(set(coords)))
        self.assertEqual(len(coords), 49)

    def test_found_creates_nation_capital_and_king(self):
        sent = self.call('found')
        self.assertEqual(sent[0]['embed'].title, '建国しました')
        self.assertEqual(self.rows('nation_guilds')[0]['guild_id'], '55')
        tile = self.rows('nation_tiles')[0]
        self.assertEqual((tile['x'], tile['y'], tile['tile_type'], tile['owner_guild_id']), (0, 0, 'capital', '55'))
        player = self.rows('nation_players')[0]
        self.assertEqual((player['user_id'], player['role'], player['hunger']), (str(USER_ID), 'king', 100))

    def test_found_skips_taken_tile(self):
        self.db.table('nation_tiles').insert({'x': 0, 'y': 0, 'owner_guild_id': '1'}).execute()
        self.call('found')
        g = self.rows('nation_guilds')[0]
        self.assertNotEqual((g['capital_x'], g['capital_y']), (0, 0))
        self.assertLessEqual(max(abs(g['capital_x']), abs(g['capital_y'])), 1)

    def test_found_uses_single_rpc(self):
        self.call('found')
        self.assertEqual(self.db.rpc_calls, [('nation_found', {'p_guild_id': '55', 'p_user_id': str(USER_ID)})])

    def test_found_maps_rpc_errors_to_japanese(self):
        for code, title in (('ALREADY_IN_NATION', '建国できません'), ('NO_FREE_TILE', '建国できません'),
                            ('NATION_EXISTS', '建国済み')):
            class Failing(NationFakeSupabase):
                def rpc(self, name, params=None, **kwargs):
                    def execute(code=code):
                        raise RuntimeError(f"{{'message': '{code}: x', 'code': 'P0001'}}")
                    return types.SimpleNamespace(execute=execute)
            self.cog.supabase = Failing()
            sent = self.call('found')
            self.assertEqual(sent[0]['embed'].title, title, code)
            self.assertTrue(sent[0]['ephemeral'])

    def test_found_refuses_member_of_other_nation(self):
        self.db.table('nation_players').insert({'user_id': str(USER_ID), 'guild_id': '999', 'role': 'citizen', 'hunger': 50}).execute()
        sent = self.call('found')
        self.assertIn('別の国', sent[0]['embed'].description)
        self.assertEqual(self.rows('nation_guilds'), [])

    def test_found_unknown_error_propagates(self):
        class Down(NationFakeSupabase):
            def rpc(self, name, params=None, **kwargs):
                def execute():
                    raise RuntimeError('connection reset')
                return types.SimpleNamespace(execute=execute)
        self.cog.supabase = Down()
        with self.assertRaises(RuntimeError):
            self.call('found')

    def test_sql_file_defines_function_and_grant(self):
        sql = (ROOT / 'docs' / 'sql' / 'nation_found.sql').read_text(encoding='utf-8')
        for needle in ('function public.nation_found(', 'pg_advisory_xact_lock', 'unique_violation',
                       'NATION_EXISTS', 'ALREADY_IN_NATION', 'NO_FREE_TILE',
                       'grant execute on function public.nation_found(text, text) to anon, authenticated'):
            self.assertIn(needle, sql)

    def test_found_requires_admin_or_owner(self):
        sent = self.call('found', admin=False)
        self.assertTrue(sent[0]['ephemeral'])
        self.assertEqual(self.rows('nation_guilds'), [])
        self.call('found', admin=False, owner=True)
        self.assertEqual(len(self.rows('nation_guilds')), 1)

    def test_found_only_once_per_guild(self):
        self.call('found')
        sent = self.call('found', user_id=USER_ID + 1)
        self.assertEqual(sent[0]['embed'].title, '建国済み')
        self.assertEqual(len(self.rows('nation_guilds')), 1)
        self.assertEqual(len(self.rows('nation_tiles')), 1)

    def test_join_needs_nation(self):
        sent = self.call('join')
        self.assertEqual(sent[0]['embed'].title, '国がありません')
        self.assertEqual(self.rows('nation_players'), [])

    def test_join_creates_citizen_once(self):
        self.call('found', user_id=1)
        sent = self.call('join')
        self.assertEqual(sent[0]['embed'].title, '参加しました')
        me = [p for p in self.rows('nation_players') if p['user_id'] == str(USER_ID)]
        self.assertEqual((me[0]['role'], me[0]['hunger'], me[0]['guild_id']), ('citizen', 100, '55'))
        sent = self.call('join')
        self.assertEqual(sent[0]['embed'].title, '参加できません')
        self.assertEqual(len(me), 1)

    def test_join_refuses_member_of_other_nation(self):
        self.call('found', user_id=1)
        self.db.table('nation_players').insert({'user_id': str(USER_ID), 'guild_id': '999', 'role': 'citizen', 'hunger': 50}).execute()
        sent = self.call('join')
        self.assertIn('別の国', sent[0]['embed'].description)

    def test_status_shows_balance_and_hunger(self):
        self.call('found')
        self.db.table('users').insert({'user_id': str(USER_ID), 'balance': 1234}).execute()
        sent = self.call('status')
        fields = {f.name: f.value for f in sent[0]['embed'].fields}
        self.assertEqual(fields['役職'], '国王')
        self.assertIn('1,234', fields['所持金'])
        self.assertIn('100/100', fields['空腹度'])

    def test_status_not_joined(self):
        sent = self.call('status')
        self.assertEqual(sent[0]['embed'].title, '未参加')

    def test_db_error_gives_private_reply(self):
        class Broken(FakeSupabase):
            def table(self, name):
                raise RuntimeError('down')
        self.cog.supabase = Broken()
        interaction, _, _ = fake_interaction(self.bot)
        sent = []

        async def send(*args, **kwargs):
            sent.append(kwargs)
        interaction.response.send_message = send
        run(self.cog.cog_app_command_error(interaction, discord.app_commands.AppCommandError('x')))
        self.assertTrue(sent[0]['ephemeral'])


if __name__ == '__main__':
    unittest.main()
