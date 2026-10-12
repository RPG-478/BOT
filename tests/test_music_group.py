"""/music グループ（PR-B）のテスト。Discord・Supabase には接続しない。

- 新しいサブコマンドと旧コマンドが、同じ実装関数（_xxx_impl）を同じ引数で呼ぶこと
- 旧コマンドの「移りました」案内が、同じ人・同じコマンドには 1 日 1 回だけ出ること
- プレイリストの scope（自分 / サーバー）が別々の保存先を使うこと
- /music play が VC に自動で参加し、別の機能が使用中なら断ること
"""

import datetime
import inspect
import json
import os
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

for _name, _value in {'SUPABASE_URL': 'https://example.supabase.co', 'SUPABASE_KEY': 'dummy-key'}.items():
    os.environ.setdefault(_name, _value)

from discord import app_commands  # noqa: E402

from core import legacy as legacy_module  # noqa: E402
from cogs import sio_music  # noqa: E402
from tests.test_all_commands import FakeSupabase  # noqa: E402
from tests.test_voice_session import make_bot, make_world  # noqa: E402


class FakeResponse:
    def __init__(self, interaction):
        self.interaction = interaction
        self.done = False

    def is_done(self):
        return self.done

    async def defer(self, **kwargs):
        self.done = True

    async def send_message(self, content=None, **kwargs):
        self.done = True
        self.interaction.sent.append((content, kwargs))


class FakeInteraction:
    def __init__(self, world, user):
        self.guild, self.guild_id, self.user = world.guild, world.guild.id, user
        self.channel, self.channel_id, self.id = world.text, world.text.id, 4242
        self.sent = []
        self.response = FakeResponse(self)
        self.followup = types.SimpleNamespace(send=self._followup)

    async def _followup(self, content=None, **kwargs):
        self.sent.append((content, kwargs))
        return types.SimpleNamespace(edit=AsyncMock())

    async def original_response(self):
        return types.SimpleNamespace(edit=AsyncMock())

    def texts(self):
        out = []
        for content, kwargs in self.sent:
            embed = kwargs.get('embed')
            out.append(str(content if content is not None else (embed.description if embed else '')))
        return '\n'.join(out)


class FakeCtx:
    def __init__(self, world, user, attachments=()):
        self.guild, self.author, self.channel, self.prefix = world.guild, user, world.text, '!'
        self.message = types.SimpleNamespace(attachments=list(attachments))
        self.sent = []

    @property
    def voice_client(self):
        return self.guild.voice_client

    async def send(self, content=None, **kwargs):
        self.sent.append((content, kwargs))
        return types.SimpleNamespace(edit=AsyncMock())

    def texts(self):
        out = []
        for content, kwargs in self.sent:
            embed = kwargs.get('embed')
            out.append(str(content if content is not None else (embed.description if embed else '')))
        return '\n'.join(out)


def choice(value):
    return app_commands.Choice(name=str(value), value=value)


class Base(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        legacy_module.NOTICES.clear()
        self.bot, self.manager = make_bot()
        self.bot.supabase = FakeSupabase()
        self.bot.get_guild = lambda gid: self.w.guild if gid == self.w.guild.id else None
        self.w = make_world()
        self.cog = sio_music.VoiceCog(self.bot)

    async def asyncTearDown(self):
        await self.manager.close()
        legacy_module.NOTICES.clear()

    def interaction(self, user=None):
        return FakeInteraction(self.w, user or self.w.alice)

    def ctx(self, user=None, attachments=()):
        return FakeCtx(self.w, user or self.w.alice, attachments)

    async def slash(self, command, interaction, **kwargs):
        return await command.callback(self.cog, interaction, **kwargs)

    async def prefix(self, command, ctx, *args, **kwargs):
        return await command.callback(self.cog, ctx, *args, **kwargs)


class SameImplementationTest(Base):
    """新旧のコマンドが同じ実装関数を呼ぶ。"""

    def group_command(self, name):
        return self.cog.music_group.get_command(name)

    @staticmethod
    def bound(impl, call):
        """実装関数に渡った引数を、既定値を補ったうえで（呼び出し元 = 第1引数を除いて）返す。"""
        signature = inspect.signature(getattr(sio_music.VoiceCog, impl))
        arguments = signature.bind(None, *call.args, **call.kwargs)
        arguments.apply_defaults()
        values = dict(arguments.arguments)
        values.pop('self')
        values.pop(next(iter(values)))  # interaction / Responder
        return values

    async def check(self, impl, new_call, old_calls):
        mock = AsyncMock()
        with patch.object(self.cog, impl, mock):
            await new_call()
            self.assertEqual(mock.await_count, 1, impl)
            expected = self.bound(impl, mock.await_args)
            for index, old in enumerate(old_calls):
                mock.reset_mock()
                await old()
                with self.subTest(impl=impl, old=index):
                    self.assertEqual(mock.await_count, 1)
                    self.assertEqual(self.bound(impl, mock.await_args), expected)
        return expected

    async def test_sixteen_subcommands(self):
        names = sorted(c.name for c in self.cog.music_group.commands)
        self.assertEqual(names, sorted([
            'play', 'pause', 'skip', 'stop', 'seek', 'queue', 'loop', 'shuffle', 'volume', 'speed',
            'eq', 'spatial', 'panel', 'search', 'playlist', 'files']))

    async def test_interaction_based_pairs(self):
        g, c = self.group_command, self.cog
        await self.check('_play_impl',
                         lambda: self.slash(g('play'), self.interaction(), query='song'),
                         [lambda: self.slash(c.play, self.interaction(), query='song')])
        for impl, new, old in [('_pause_impl', 'pause', c.pause), ('_skip_impl', 'skip', c.skip),
                               ('_queue_impl', 'queue', c.queue_cmd), ('_shuffle_impl', 'shuffle', c.shuffle_cmd)]:
            await self.check(impl, lambda new=new: self.slash(g(new), self.interaction()),
                             [lambda old=old: self.slash(old, self.interaction())])
        await self.check('_seek_impl', lambda: self.slash(g('seek'), self.interaction(), seconds=12.0),
                         [lambda: self.slash(c.seek_cmd, self.interaction(), seconds=12.0)])
        await self.check('_loop_impl', lambda: self.slash(g('loop'), self.interaction(), mode=choice('track')),
                         [lambda: self.slash(c.loop_cmd, self.interaction(), mode=choice('track'))])
        await self.check('_eq_impl', lambda: self.slash(g('eq'), self.interaction(), mode='bass'),
                         [lambda: self.slash(c.eq, self.interaction(), mode='bass')])

    async def test_responder_based_pairs(self):
        g, c = self.group_command, self.cog
        await self.check('_stop_impl', lambda: self.slash(g('stop'), self.interaction()),
                         [lambda: self.prefix(c.stop_all, self.ctx())])
        await self.check('_volume_impl', lambda: self.slash(g('volume'), self.interaction(), value=0.5),
                         [lambda: self.prefix(c.volume, self.ctx(), 0.5)])
        await self.check('_speed_impl', lambda: self.slash(g('speed'), self.interaction(), value=1.5),
                         [lambda: self.prefix(c.speed, self.ctx(), 1.5)])
        await self.check('_panel_impl', lambda: self.slash(g('panel'), self.interaction()),
                         [lambda: self.prefix(c.panel, self.ctx())])
        await self.check('_search_impl', lambda: self.slash(g('search'), self.interaction(), keyword='abc'),
                         [lambda: self.prefix(c.search, self.ctx(), keyword='abc')])
        await self.check('_files_impl', lambda: self.slash(g('files'), self.interaction(), limit=20),
                         [lambda: self.prefix(c.list, self.ctx(), 20)])

    async def test_spatial_pairs(self):
        g, c = self.group_command, self.cog
        await self.check('_spatial_impl', lambda: self.slash(g('spatial'), self.interaction()),
                         [lambda: self.slash(c.spatial_cmd, self.interaction())])
        await self.check('_spatial_impl',
                         lambda: self.slash(g('spatial'), self.interaction(), feedback=0.4, wet=0.5),
                         [lambda: self.prefix(c.rval, self.ctx(), 0.4, 0.5)])
        await self.check('_spatial_impl', lambda: self.slash(g('spatial'), self.interaction(), resolution=8),
                         [lambda: self.prefix(c.rres, self.ctx(), 8)])

    async def test_playlist_pairs(self):
        g, c = self.group_command, self.cog
        play = g('playlist')

        def new(action, name=None, scope=None):
            return lambda: self.slash(play, self.interaction(), action=choice(action), name=name,
                                      scope=choice(scope) if scope else None)
        await self.check('_playlist_impl', new('save', 'mix'), [
            lambda: self.slash(c.playlist_cmd, self.interaction(), action=choice('save'), name='mix'),
            lambda: self.prefix(c.personal_playlist_save, self.ctx(), name='mix')])
        await self.check('_playlist_impl', new('list'), [
            lambda: self.slash(c.playlist_cmd, self.interaction(), action=choice('list')),
            lambda: self.prefix(c.personal_playlist_list, self.ctx())])
        await self.check('_playlist_impl', new('play', 'mix'), [
            lambda: self.slash(c.playlist_cmd, self.interaction(), action=choice('play'), name='mix'),
            lambda: self.prefix(c.personal_playlist_play, self.ctx(), name='mix')])
        await self.check('_playlist_impl', new('save', 'mix', 'server'), [
            lambda: self.prefix(c.save_current, self.ctx(), 'mix')])
        await self.check('_playlist_impl', new('play', 'mix', 'server'), [
            lambda: self.prefix(c.plist, self.ctx(), input_data='mix')])

    async def test_legacy_signatures_unchanged(self):
        self.assertIn('vol', self.cog.volume.clean_params)
        self.assertIn('keyword', self.cog.search.clean_params)
        self.assertEqual([p.name for p in self.cog.play.parameters], ['query', 'file', 'start_at'])
        self.assertEqual([p.name for p in self.cog.loop_cmd.parameters], ['mode'])


class LegacyNoticeTest(Base):
    async def test_notice_once_per_user_per_day(self):
        with patch.object(self.cog, '_volume_impl', AsyncMock()):
            first, second = self.ctx(), self.ctx()
            await self.prefix(self.cog.volume, first, 0.5)
            await self.prefix(self.cog.volume, second, 0.5)
            other = self.ctx(self.w.bob)
            await self.prefix(self.cog.volume, other, 0.5)
        self.assertIn('/music volume', first.texts())
        self.assertIn('に移りました', first.texts())
        self.assertEqual(second.sent, [])
        self.assertIn('/music volume', other.texts())

    async def test_notice_again_next_day(self):
        with patch.object(self.cog, '_skip_impl', AsyncMock()):
            await self.slash(self.cog.skip, self.interaction())
            tomorrow = legacy_module.LegacyNotices.today() + datetime.timedelta(days=1)
            with patch.object(legacy_module.LegacyNotices, 'today', staticmethod(lambda: tomorrow)):
                again = self.interaction()
                await self.slash(self.cog.skip, again)
        self.assertIn('/music skip', again.texts())

    async def test_slash_notice_is_ephemeral_followup(self):
        interaction = self.interaction()
        await self.slash(self.cog.shuffle_cmd, interaction)  # 本来の返信のあとに案内
        self.assertEqual(len(interaction.sent), 2)
        content, kwargs = interaction.sent[-1]
        self.assertIn('/music shuffle', content)
        self.assertTrue(kwargs.get('ephemeral'))

    async def test_new_commands_have_no_notice(self):
        interaction = self.interaction()
        await self.slash(self.cog.music_group.get_command('shuffle'), interaction)
        self.assertEqual(len(interaction.sent), 1)
        self.assertNotIn('移りました', interaction.texts())


class PlaylistScopeTest(Base):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        state = self.cog.get_state(self.w.guild.id)
        state['current_track'] = ('https://cdn/x.mp3', 'upload.mp3', 10, 'ID1', False)
        await state['queue'].put(('https://youtube.com/watch?v=a', 'yt song', None, True))
        await state['queue'].put(('https://cdn/y.mp3', 'upload2.mp3', 'ID2', False))
        self.playlist = self.cog.music_group.get_command('playlist')

    async def run_playlist(self, action, name=None, scope=None, user=None, file=None):
        interaction = self.interaction(user)
        await self.slash(self.playlist, interaction, action=choice(action), name=name,
                         scope=choice(scope) if scope else None, file=file)
        return interaction

    async def test_save_scopes_use_separate_tables(self):
        await self.run_playlist('save', 'mine', 'me')
        await self.run_playlist('save', 'shared', 'server')
        tables = self.bot.supabase.tables
        personal = tables['user_music_playlists']
        self.assertEqual([(r['owner_user_id'], r['name'], len(r['tracks'])) for r in personal],
                         [(self.w.alice.id, 'mine', 3)])
        self.assertEqual(tables['playlists'], [{'id': 1, 'name': f'{self.w.guild.id}:shared', 'ids': ['ID1', 'ID2']}])

    async def test_list_scopes(self):
        await self.run_playlist('save', 'mine', 'me')
        await self.run_playlist('save', 'shared', 'server')
        self.bot.supabase.tables['playlists'].append({'name': '999:other-guild', 'ids': ['X']})
        mine = await self.run_playlist('list', scope='me')
        server = await self.run_playlist('list', scope='server')
        bob = await self.run_playlist('list', scope='me', user=self.w.bob)
        self.assertIn('mine', mine.texts())
        self.assertNotIn('shared', mine.texts())
        self.assertIn('shared', server.texts())
        self.assertNotIn('other-guild', server.texts())
        self.assertIn('登録されていません', bob.texts())

    async def test_default_scope_is_personal(self):
        await self.run_playlist('save', 'mine')
        self.assertIn('user_music_playlists', self.bot.supabase.tables)
        self.assertNotIn('playlists', self.bot.supabase.tables)

    async def test_play_server_playlist_by_name_ids_and_json(self):
        await self.run_playlist('save', 'shared', 'server')
        loaded = AsyncMock()
        connect = AsyncMock(return_value=None)
        with patch.object(self.cog, 'start_playlist_load', loaded), \
                patch.object(self.cog, '_ensure_music_connection', connect):
            await self.run_playlist('play', 'shared', 'server')
            await self.run_playlist('play', 'AAA, BBB', 'server')
            attachment = types.SimpleNamespace(read=AsyncMock(return_value=json.dumps(['J1', 'J2']).encode()))
            await self.run_playlist('play', None, 'server', file=attachment)
        inputs = [[t['input'] for t in call.args[1]] for call in loaded.await_args_list]
        self.assertEqual(inputs, [['ID1', 'ID2'], ['AAA', 'BBB'], ['J1', 'J2']])

    async def test_play_personal_playlist(self):
        await self.run_playlist('save', 'mine', 'me')
        loaded = AsyncMock()
        with patch.object(self.cog, 'start_playlist_load', loaded), \
                patch.object(self.cog, '_ensure_music_connection', AsyncMock(return_value=None)):
            await self.run_playlist('play', 'mine', 'me')
            missing = await self.run_playlist('play', 'nothing', 'me')
        self.assertEqual(len(loaded.await_args.args[1]), 3)
        self.assertIn('見つかりません', missing.texts())

    async def test_legacy_prefix_reads_same_stores(self):
        await self.prefix(self.cog.save_current, self.ctx(), 'legacy')
        await self.prefix(self.cog.personal_playlist_save, self.ctx(), name='legacy-me')
        server = await self.run_playlist('list', scope='server')
        mine = await self.run_playlist('list', scope='me')
        self.assertIn('legacy', server.texts())
        self.assertIn('legacy-me', mine.texts())


class PlayAutoJoinTest(Base):
    async def test_play_auto_joins(self):
        info = {'webpage_url': 'https://youtube.com/watch?v=x', 'title': 'テスト曲'}
        with patch.object(self.cog, 'get_yt_info', AsyncMock(return_value=info)), \
                patch.object(self.cog, 'check_queue', AsyncMock()) as check_queue:
            interaction = self.interaction()
            await self.slash(self.cog.music_group.get_command('play'), interaction, query='テスト')
        self.assertEqual(self.w.voice.connect_calls, 1)
        self.assertEqual(self.manager.owner(self.w.guild.id), 'music')
        self.assertEqual(self.manager.get(self.w.guild.id).user_id, self.w.alice.id)
        self.assertEqual(self.cog.get_state(self.w.guild.id)['queue'].qsize(), 1)
        check_queue.assert_awaited()
        self.assertIn('再生を開始します', interaction.texts())

    async def test_play_refused_while_other_feature_holds_vc(self):
        await self.manager.acquire(self.w.guild, self.w.voice, 'record', self.w.alice)
        vc = self.w.guild.voice_client
        with patch.object(self.cog, 'get_yt_info', AsyncMock()) as yt:
            interaction = self.interaction(self.w.bob)
            await self.slash(self.cog.music_group.get_command('play'), interaction, query='テスト')
        self.assertIn('録音', interaction.texts())
        yt.assert_not_awaited()
        self.assertTrue(vc.is_connected())
        self.assertEqual(self.manager.owner(self.w.guild.id), 'record')
        self.assertEqual(self.cog.get_state(self.w.guild.id)['queue'].qsize(), 0)

    async def test_play_needs_user_in_voice(self):
        self.w.alice.voice = None
        interaction = self.interaction()
        await self.slash(self.cog.music_group.get_command('play'), interaction, query='テスト')
        self.assertIn('ボイスチャンネルに参加', interaction.texts())
        self.assertEqual(self.w.voice.connect_calls, 0)

    async def test_panel_auto_joins(self):
        interaction = self.interaction()
        await self.slash(self.cog.music_group.get_command('panel'), interaction)
        self.assertEqual(self.manager.owner(self.w.guild.id), 'music')
        self.assertIsNotNone(self.cog.get_state(self.w.guild.id)['panel_message'])

    async def test_spatial_options_set_values(self):
        interaction = self.interaction()
        await self.slash(self.cog.music_group.get_command('spatial'), interaction, feedback=0.4, wet=0.2, resolution=8)
        state = self.cog.get_state(self.w.guild.id)
        self.assertEqual((state['fdn_feedback'], state['fdn_wet'], state['fdn_resolution']), (0.4, 0.2, 8))
        ctx = self.ctx()
        await self.prefix(self.cog.rres, ctx, 5)
        self.assertIn('4', ctx.texts())
        self.assertEqual(state['fdn_resolution'], 8)

    async def test_stop_clears_queue(self):
        await self.manager.acquire(self.w.guild, self.w.voice, 'music', self.w.alice)
        state = self.cog.get_state(self.w.guild.id)
        await state['queue'].put(('u', 't', None, True))
        interaction = self.interaction()
        await self.slash(self.cog.music_group.get_command('stop'), interaction)
        self.assertEqual(state['queue'].qsize(), 0)
        self.assertTrue(self.w.guild.voice_client.is_connected())


if __name__ == '__main__':
    unittest.main()
