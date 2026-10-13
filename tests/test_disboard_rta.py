import unittest
from types import SimpleNamespace

from cogs.disboard_rta import (
    BumpRta,
    DISBOARD_BOT_ID,
    DISOKU_BOT_ID,
    event_kind,
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

    def test_unrelated_messages_are_ignored(self):
        for text in ('bump again in 2 hours', 'up in 15 minutes', 'hello'):
            self.assertIsNone(event_kind(text), text)

    def test_embed_text_is_parsed(self):
        msg = SimpleNamespace(content='', embeds=[SimpleNamespace(title='Bump done!', description='Thanks', fields=[])])
        self.assertEqual(event_kind(message_text(msg)), 'bump')


class DefaultNotificationsTest(unittest.IsolatedAsyncioTestCase):
    async def test_notifications_are_on_without_any_configuration(self):
        cog = BumpRta(SimpleNamespace(supabase=None))
        self.assertTrue(await cog._is_enabled(123))

    async def test_disabled_setting_is_respected_from_cache(self):
        cog = BumpRta(SimpleNamespace(supabase=None))
        cog._enabled_cache['123'] = False
        self.assertFalse(await cog._is_enabled(123))


if __name__ == '__main__':
    unittest.main()
