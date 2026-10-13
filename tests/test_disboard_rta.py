import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from cogs.disboard_rta import (
    BumpRta,
    DISBOARD_BOT_ID,
    DISOKU_BOT_ID,
    event_kind,
    interaction_user_id,
    message_text,
)


class BumpRtaParserTest(unittest.TestCase):
    def test_configured_bot_ids(self):
        self.assertEqual(DISBOARD_BOT_ID, 302050872383242240)
        self.assertEqual(DISOKU_BOT_ID, 761562078095867916)

    def test_successful_bump_variants(self):
        for text in ('Bump done!', 'Bump successful!', 'バンプ成功しました'):
            self.assertEqual(event_kind(text), 'bump', text)

    def test_successful_up_variants(self):
        for text in ('Up successful!', 'サーバーをupしました', '掲載完了'):
            self.assertEqual(event_kind(text), 'up', text)

    def test_disboard_success_embed_with_bot_id(self):
        # DISBOARD's embed can omit the literal word "bump"; the verified bot ID
        # disambiguates its Japanese success copy from a Dis速 up event.
        self.assertEqual(event_kind('表示順をアップしたよ 👍', DISBOARD_BOT_ID), 'bump')
        self.assertEqual(event_kind('Lunachan.com をアップしたよ! 🙏', DISOKU_BOT_ID), 'up')

    def test_unrelated_messages_are_ignored(self):
        for text in ('bump again in 2 hours', 'up in 15 minutes', 'hello'):
            self.assertIsNone(event_kind(text), text)

    def test_embed_text_is_parsed(self):
        msg = SimpleNamespace(content='', embeds=[SimpleNamespace(title='Bump done!', description='Thanks', fields=[])])
        self.assertEqual(event_kind(message_text(msg)), 'bump')

    def test_interaction_metadata_user_is_attributed(self):
        msg = SimpleNamespace(
            interaction_metadata=SimpleNamespace(user=SimpleNamespace(id=987654321)),
            interaction=None,
        )
        self.assertEqual(interaction_user_id(msg), 987654321)

    def test_legacy_interaction_user_is_supported(self):
        msg = SimpleNamespace(
            interaction_metadata=None,
            interaction=SimpleNamespace(user=SimpleNamespace(id=123456789)),
        )
        self.assertEqual(interaction_user_id(msg), 123456789)


class DefaultNotificationsTest(unittest.IsolatedAsyncioTestCase):
    async def test_notifications_are_on_without_any_configuration(self):
        cog = BumpRta(SimpleNamespace(supabase=None))
        self.assertTrue(await cog._is_enabled(123))

    async def test_disabled_setting_is_respected_from_cache(self):
        cog = BumpRta(SimpleNamespace(supabase=None))
        cog._enabled_cache['123'] = False
        self.assertFalse(await cog._is_enabled(123))

    async def test_disboard_bot_comment_triggers_bump_and_attributes_interaction_user(self):
        cog = BumpRta(SimpleNamespace(supabase=object()))
        cog._is_enabled = AsyncMock(return_value=True)
        cog._schedule_reminder = AsyncMock()
        cog._record_rta_event = AsyncMock()
        message = SimpleNamespace(
            id=111, guild=SimpleNamespace(id=222),
            author=SimpleNamespace(id=DISBOARD_BOT_ID, bot=True),
            content='', embeds=[SimpleNamespace(title='', description='表示順をアップしたよ 👍', fields=[])],
            interaction_metadata=SimpleNamespace(user=SimpleNamespace(id=333)),
            interaction=None,
        )
        await cog.on_message(message)
        cog._schedule_reminder.assert_awaited_once_with(message, 333, 'bump')
        cog._record_rta_event.assert_awaited_once_with(message, 'bump', 333)

    async def test_disoku_bot_comment_triggers_up(self):
        cog = BumpRta(SimpleNamespace(supabase=object()))
        cog._is_enabled = AsyncMock(return_value=True)
        cog._schedule_reminder = AsyncMock()
        cog._record_rta_event = AsyncMock()
        message = SimpleNamespace(
            id=444, guild=SimpleNamespace(id=222),
            author=SimpleNamespace(id=DISOKU_BOT_ID, bot=True),
            content='', embeds=[SimpleNamespace(title='', description='Lunachan.com をアップしたよ! 🙏', fields=[])],
            interaction_metadata=SimpleNamespace(user=SimpleNamespace(id=333)),
            interaction=None,
        )
        await cog.on_message(message)
        cog._schedule_reminder.assert_awaited_once_with(message, 333, 'up')
        cog._record_rta_event.assert_awaited_once_with(message, 'up', 333)


if __name__ == '__main__':
    unittest.main()
