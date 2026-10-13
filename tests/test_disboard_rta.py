import unittest
from types import SimpleNamespace
from cogs.disboard_rta import event_kind, message_text

class BumpRtaParserTest(unittest.TestCase):
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

if __name__ == '__main__':
    unittest.main()
