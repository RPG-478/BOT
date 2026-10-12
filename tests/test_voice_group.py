"""/voice グループ（PR-C）のテスト。Discord には接続しない。

- 10 個のサブコマンドが、旧コマンド（/join・!rec・!stt など）と同じ実装関数を同じ引数で呼ぶこと
- /voice status が、VC を使っている機能と開始した人を表示すること
- 音声認識モデルが無いとき、文字起こし・カラオケは VC に入らずに断ること
- !rec pitch（/voice record action:音程解析）が NameError にならず音階を返すこと
- 録音を始めると、テキストチャンネルに全員に見えるお知らせが出ること
"""

import inspect
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

for _name, _value in {'SUPABASE_URL': 'https://example.supabase.co', 'SUPABASE_KEY': 'dummy-key'}.items():
    os.environ.setdefault(_name, _value)

import discord  # noqa: E402
import numpy as np  # noqa: E402

from core import legacy as legacy_module  # noqa: E402
from core import vosk_model  # noqa: E402
from core.legacy import Responder  # noqa: E402
from cogs import (  # noqa: E402
    sio_globalVC, sio_karaoke, sio_music, sio_rec, sio_saito, sio_transcription, sio_voice, sio_voicechanger,
)
from tests.test_all_commands import FakeSupabase  # noqa: E402
from tests.test_music_group import FakeCtx, FakeInteraction, choice  # noqa: E402
from tests.test_voice_session import make_bot, make_world  # noqa: E402


class Base(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        legacy_module.NOTICES.clear()
        self.bot, self.manager = make_bot()
        self.bot.supabase = FakeSupabase()
        self.w = make_world()
        self.opus = patch.object(sio_rec.discord.opus, 'is_loaded', return_value=True)
        self.opus.start()
        self.addCleanup(self.opus.stop)
        self.music = sio_music.VoiceCog(self.bot)
        self.rec = sio_rec.RecordingCog(self.bot)
        self.stt = sio_transcription.TranscriptionCog(self.bot)
        self.karaoke = sio_karaoke.KaraokeCog(self.bot)
        self.changer = sio_voicechanger.VoiceChangerCog(self.bot)
        self.saito = sio_saito.SaitoRelay(self.bot)
        self.gvc = sio_globalVC.GlobalVCCog(self.bot)
        cogs = {type(c).__name__: c for c in (self.music, self.rec, self.stt, self.karaoke, self.changer,
                                              self.saito, self.gvc)}
        self.bot.get_cog = cogs.get
        self.hub = sio_voice.VoiceHub(self.bot)

    async def asyncTearDown(self):
        await self.manager.close()
        legacy_module.NOTICES.clear()

    def interaction(self, user=None):
        return FakeInteraction(self.w, user or self.w.alice)

    def ctx(self, user=None):
        return FakeCtx(self.w, user or self.w.alice)

    async def voice(self, name, interaction=None, **kwargs):
        command = self.hub.voice_group.get_command(name)
        interaction = interaction or self.interaction()
        await command.callback(self.hub, interaction, **kwargs)
        return interaction


class SameImplementationTest(Base):
    """/voice のサブコマンドと旧コマンドが、同じ実装関数を同じ引数で呼ぶ。"""

    @staticmethod
    def bound(signature, call):
        arguments = signature.bind(None, *call.args, **call.kwargs)
        arguments.apply_defaults()
        values = dict(arguments.arguments)
        values.pop('self')
        responder = values.pop(next(iter(values)))
        return responder, values

    async def check(self, cog, impl, new_name, new_kwargs, old_command, *old_args, **old_kwargs):
        cls = type(cog)
        signature = inspect.signature(getattr(cls, impl))
        with patch.object(cls, impl, AsyncMock()) as mock:
            interaction = await self.voice(new_name, **new_kwargs)
            self.assertEqual(mock.await_count, 1, f'/voice {new_name}')
            new_responder, new_values = self.bound(signature, mock.await_args)

            mock.reset_mock()
            source = self.interaction() if old_command.__class__.__module__.startswith('discord.app_commands') else self.ctx()
            await old_command.callback(cog, source, *old_args, **old_kwargs)
            self.assertEqual(mock.await_count, 1, old_command.qualified_name)
            old_responder, old_values = self.bound(signature, mock.await_args)

        self.assertIsInstance(new_responder, Responder)
        self.assertIs(new_responder.source, interaction)
        self.assertIsInstance(old_responder, Responder)
        self.assertIs(old_responder.source, source)
        self.assertEqual(new_values, old_values, f'/voice {new_name} と {old_command.qualified_name}')
        return new_values

    async def test_join_leave(self):
        await self.check(self.music, '_join_impl', 'join', {}, self.music.join_cmd)
        await self.check(self.music, '_leave_impl', 'leave', {}, self.music.leave_cmd)

    async def test_record(self):
        for value, old in (('start', self.rec.rec_start), ('stop', self.rec.rec_stop),
                           ('status', self.rec.rec_status), ('status', self.rec.rec_group),
                           ('pitch', self.rec.rec_pitch)):
            values = await self.check(self.rec, '_record_impl', 'record', {'action': choice(value)}, old)
            self.assertEqual(values, {'action': value})

    async def test_echo(self):
        await self.check(self.rec, '_echo_impl', 'echo', {'action': choice('start'), 'delay': 3.0}, self.rec.echo_start, 3.0)
        values = await self.check(self.rec, '_echo_impl', 'echo', {'action': choice('start')}, self.rec.echo_start)
        self.assertEqual(values, {'action': 'start', 'delay': None})
        await self.check(self.rec, '_echo_impl', 'echo', {'action': choice('delay'), 'delay': 1.5}, self.rec.echo_delay, 1.5)
        await self.check(self.rec, '_echo_impl', 'echo', {'action': choice('stop')}, self.rec.echo_stop)

    async def test_transcribe(self):
        target = self.w.text
        values = await self.check(self.stt, '_transcribe_impl', 'transcribe', {'action': choice('start'), 'channel': target},
                                  self.stt.stt_start, target)
        self.assertIs(values['target_channel'], target)
        await self.check(self.stt, '_transcribe_impl', 'transcribe', {'action': choice('start')}, self.stt.stt_start)
        await self.check(self.stt, '_transcribe_impl', 'transcribe', {'action': choice('stop')}, self.stt.stt_stop)

    async def test_karaoke(self):
        values = await self.check(self.karaoke, '_karaoke_impl', 'karaoke', {'action': choice('start'), 'lyrics': 'かえるのうた'},
                                  self.karaoke.karaoke_start, target_lyrics='かえるのうた')
        self.assertEqual(values, {'action': 'start', 'target_lyrics': 'かえるのうた'})
        await self.check(self.karaoke, '_karaoke_impl', 'karaoke', {'action': choice('score')}, self.karaoke.karaoke_score)
        await self.check(self.karaoke, '_karaoke_impl', 'karaoke', {'action': choice('stop')}, self.karaoke.karaoke_stop)

    async def test_changer(self):
        c = self.changer
        await self.check(c, '_changer_impl', 'changer', {'action': choice('start'), 'pitch': 3.0}, c.vc_start, 3.0)
        await self.check(c, '_changer_impl', 'changer', {'action': choice('start')}, c.vc_start)
        await self.check(c, '_changer_impl', 'changer', {'action': choice('status')}, c.vc_group)
        await self.check(c, '_changer_impl', 'changer', {'action': choice('status'), 'pitch': -2.0}, c.vc_pitch, -2.0)
        values = await self.check(c, '_changer_impl', 'changer', {'action': choice('status'), 'buffer_ms': 40.0, 'max_ms': 80.0},
                                  c.vc_buffer, 40.0, 80.0)
        self.assertEqual(values, {'action': 'status', 'pitch': None, 'buffer_ms': 40.0, 'max_ms': 80.0})
        await self.check(c, '_changer_impl', 'changer', {'action': choice('stop')}, c.vc_stop)

    async def test_match(self):
        await self.check(self.saito, '_match_impl', 'match', {'action': choice('start')}, self.saito.saito)
        await self.check(self.saito, '_match_impl', 'match', {'action': choice('stop')}, self.saito.saito_stop)

    async def test_global(self):
        values = await self.check(self.gvc, '_global_impl', 'global', {'action': choice('join'), 'room': 'lobby', 'password': 'pw'},
                                  self.gvc.gvc_join, 'lobby', 'pw')
        self.assertEqual(values, {'action': 'join', 'room_name': 'lobby', 'password': 'pw'})
        await self.check(self.gvc, '_global_impl', 'global', {'action': choice('leave')}, self.gvc.gvc_leave)

    def test_ten_subcommands(self):
        names = sorted(c.name for c in self.hub.voice_group.commands)
        self.assertEqual(names, sorted(['join', 'leave', 'status', 'record', 'echo', 'transcribe', 'karaoke',
                                        'changer', 'match', 'global']))

    async def test_legacy_notice_once_per_day(self):
        with patch.object(sio_rec.RecordingCog, '_record_impl', AsyncMock()):
            ctx = self.ctx()
            await self.rec.rec_status.callback(self.rec, ctx)
            await self.rec.rec_status.callback(self.rec, ctx)
        notices = [c for c, _ in ctx.sent if c and '/voice record action:状態' in c]
        self.assertEqual(len(notices), 1)


class StatusTest(Base):
    async def test_nobody(self):
        interaction = await self.voice('status')
        content, kwargs = interaction.sent[-1]
        self.assertTrue(kwargs['ephemeral'])
        self.assertIn('どの機能も使っていません', kwargs['embed'].description)

    async def test_shows_feature_user_and_stop_hint(self):
        await self.rec._record_impl(Responder(self.ctx(self.w.alice)), 'start')
        interaction = await self.voice('status', self.interaction(self.w.bob))
        embed = interaction.sent[-1][1]['embed']
        fields = {f.name: f.value for f in embed.fields}
        self.assertEqual(fields['機能'], '録音')
        self.assertEqual(fields['開始した人'], 'alice')
        self.assertIn('/voice record action:停止', fields['終了するには'])
        self.assertIn('秒', fields['経過時間'])

    async def test_busy_message_points_to_voice_commands(self):
        await self.rec._record_impl(Responder(self.ctx(self.w.alice)), 'start')
        interaction = await self.voice('join', self.interaction(self.w.bob))
        self.assertIn('/voice record action:停止', interaction.texts())
        self.assertEqual(self.manager.owner(self.w.guild.id), 'record')


class ModelMissingTest(Base):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.missing = os.path.join(tempfile.gettempdir(), 'no-such-vosk-model-dir')
        self.assertFalse(os.path.exists(self.missing))

    def assert_not_touched(self):
        self.assertIsNone(self.manager.get(self.w.guild.id))
        self.assertIsNone(self.w.guild.voice_client)

    async def test_transcribe_refuses_without_model(self):
        with patch.object(sio_transcription, 'MODEL_PATH', self.missing):
            interaction = await self.voice('transcribe', action=choice('start'))
            ctx = self.ctx()
            await self.stt.stt_start.callback(self.stt, ctx)
        self.assertIn('音声認識モデルが入っていません', interaction.texts())
        self.assertTrue(interaction.sent[-1][1]['ephemeral'])
        self.assertIn('音声認識モデルが入っていません', ctx.texts())
        self.assert_not_touched()

    async def test_karaoke_refuses_without_model(self):
        with patch.object(sio_karaoke, 'MODEL_PATH', self.missing):
            interaction = await self.voice('karaoke', action=choice('start'), lyrics='かえるのうた')
        self.assertIn('音声認識モデルが入っていません', interaction.texts())
        self.assert_not_touched()

    async def test_model_loaded_lazily_when_folder_appears(self):
        with tempfile.TemporaryDirectory() as folder:
            holder = type('Holder', (), {'vosk_model': None})()
            loaded = []

            def fake_model(path):
                loaded.append(path)
                return 'MODEL'
            self.assertIsNone(await vosk_model.ensure_model(holder, fake_model, folder))
            self.assertEqual((holder.vosk_model, loaded), ('MODEL', [folder]))
            self.assertEqual(await vosk_model.ensure_model(holder, None, folder), None)  # 読み込み済みならそのまま
            holder.vosk_model = None
            self.assertEqual(await vosk_model.ensure_model(holder, None, folder), vosk_model.VOSK_MISSING_MESSAGE)


class RecordingTest(Base):
    async def test_start_posts_visible_notice(self):
        interaction = await self.voice('record', action=choice('start'))
        notices = [m for m in self.w.text.sent if isinstance(m, str) and '録音を開始しました' in m]
        self.assertEqual(len(notices), 1)
        self.assertIn('alice', notices[0])
        self.assertIn(self.w.voice.name, notices[0])
        # 返信（状態表示）は interaction に返り、お知らせは ephemeral ではなくチャンネルに出る
        self.assertIn('録音を開始しました', interaction.texts())
        self.assertEqual(self.manager.owner(self.w.guild.id), 'record')

    async def test_no_notice_when_refused(self):
        await self.voice('join', self.interaction(self.w.bob))
        before = list(self.w.text.sent)
        await self.voice('record', action=choice('start'))
        self.assertEqual([m for m in self.w.text.sent[len(before):] if '録音を開始しました' in str(m)], [])

    async def test_pitch_returns_notes(self):
        await self.rec._record_impl(Responder(self.ctx()), 'start')
        t = np.arange(24000) / 48000
        mono = (np.sin(2 * np.pi * 440 * t) * 12000).astype(np.int16)
        pcm = np.column_stack((mono, mono)).flatten().tobytes()
        sink = self.rec.sessions[self.w.guild.id]['sink']
        with patch.object(sink, 'snapshot', return_value={'alice': pcm}):
            ctx = self.ctx()
            await self.rec.rec_pitch.callback(self.rec, ctx)  # 以前は NameError（detected_notes）
        embed = next(kwargs['embed'] for _, kwargs in ctx.sent if kwargs.get('embed') is not None
                     and kwargs['embed'].title and '音階' in kwargs['embed'].title)
        self.assertEqual(embed.fields[0].name, '🎙️ alice')
        self.assertIn('A4', embed.fields[0].value)

    def test_format_notes(self):
        self.assertEqual(sio_rec.format_notes([('A4', 'A4', 69), ('C#4', 'Db4', 61)]), ['A4', 'C#4/Db4'])


class ChangerOptionsTest(Base):
    async def test_options_change_running_changer(self):
        sink = type('Sink', (), {})()
        sink.set_semitones = lambda value: setattr(sink, 'semitones', value)
        src = type('Src', (), {'target_buffer_ms': 60.0})()
        src.update_settings = lambda **kw: setattr(src, 'settings', kw)
        sink.audio_source = src
        self.changer.vc_sessions[self.w.guild.id] = {'sink': sink, 'vc': None}
        interaction = await self.voice('changer', action=choice('status'), pitch=4.0, buffer_ms=40.0)
        self.assertEqual(sink.semitones, 4.0)
        self.assertEqual(src.settings, {'target_buffer_ms': 40.0, 'max_buffer_ms': 80.0})
        self.assertIn('設定を変更しました', interaction.texts())

        interaction = await self.voice('changer', action=choice('status'), max_ms=10.0)
        self.assertIn('上限バッファは目標バッファ以上', interaction.texts())

    async def test_options_without_changer(self):
        interaction = await self.voice('changer', action=choice('status'), pitch=4.0)
        self.assertIn('開始されていません', interaction.texts())


if __name__ == '__main__':
    unittest.main()
