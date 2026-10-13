import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord
from cogs.disboard_rta import (
    BumpRta,
    DISBOARD_BOT_ID,
    DISOKU_BOT_ID,
    command_event,
)


class BumpRtaParserTest(unittest.TestCase):
    def test_configured_bot_ids(self):
        self.assertEqual(DISBOARD_BOT_ID, 302050872383242240)
        self.assertEqual(DISOKU_BOT_ID, 761562078095867916)

    def make_message(self, author_id=DISBOARD_BOT_ID, application_id=DISBOARD_BOT_ID,
                     interaction_type=discord.InteractionType.application_command,
                     content='', embeds=None):
        invoked_at = datetime(2026, 10, 13, 8, 0, 0, tzinfo=timezone.utc)
        metadata = SimpleNamespace(
            type=interaction_type,
            user=SimpleNamespace(id=987654321),
            created_at=invoked_at,
        )
        return SimpleNamespace(
            author=SimpleNamespace(id=author_id, bot=True),
            application_id=application_id,
            interaction_metadata=metadata,
            created_at=datetime(2026, 10, 13, 8, 0, 1, tzinfo=timezone.utc),
            content=content,
            embeds=embeds or [],
        )

    def test_official_disboard_application_flags_bump_without_content(self):
        msg = self.make_message(content='', embeds=[])
        event = command_event(msg)
        self.assertEqual(event[:2], ('bump', 987654321))
        self.assertEqual(event[2].isoformat(), '2026-10-13T08:00:00+00:00')

    def test_official_disoku_application_flags_up_without_content(self):
        msg = self.make_message(author_id=DISOKU_BOT_ID, application_id=DISOKU_BOT_ID)
        event = command_event(msg)
        self.assertEqual(event[:2], ('up', 987654321))

    def test_bot_and_application_must_match(self):
        self.assertIsNone(command_event(self.make_message(application_id=999)))
        self.assertIsNone(command_event(self.make_message(author_id=999, application_id=999)))

    def test_only_application_command_interactions_are_flagged(self):
        msg = self.make_message(interaction_type=discord.InteractionType.component)
        self.assertIsNone(command_event(msg))

    def test_message_content_and_embed_are_not_used(self):
        plain = self.make_message(content='', embeds=[])
        noisy = self.make_message(content='error, cooldown, arbitrary text', embeds=[SimpleNamespace(description='unrelated')])
        self.assertEqual(command_event(plain), command_event(noisy))


class DefaultNotificationsTest(unittest.IsolatedAsyncioTestCase):
    async def test_notifications_are_on_without_any_configuration(self):
        cog = BumpRta(SimpleNamespace(supabase=None))
        self.assertTrue(await cog._is_enabled(123))

    async def test_disabled_setting_is_respected_from_cache(self):
        cog = BumpRta(SimpleNamespace(supabase=None))
        cog._enabled_cache['123'] = False
        self.assertFalse(await cog._is_enabled(123))

    async def test_disboard_interaction_triggers_bump_and_attributes_interaction_user(self):
        cog = BumpRta(SimpleNamespace(supabase=object()))
        cog._is_enabled = AsyncMock(return_value=True)
        cog._schedule_reminder = AsyncMock()
        cog._record_rta_event = AsyncMock()
        message = SimpleNamespace(
            id=111, guild=SimpleNamespace(id=222),
            author=SimpleNamespace(id=DISBOARD_BOT_ID, bot=True),
            application_id=DISBOARD_BOT_ID,
            content='', embeds=[],
            interaction_metadata=SimpleNamespace(
                type=discord.InteractionType.application_command,
                user=SimpleNamespace(id=333),
                created_at=datetime(2026, 10, 13, 8, 0, 0, tzinfo=timezone.utc),
            ),
        )
        await cog.on_message(message)
        invoked_at = message.interaction_metadata.created_at
        cog._schedule_reminder.assert_awaited_once_with(message, 333, 'bump', invoked_at)
        cog._record_rta_event.assert_awaited_once_with(message, 'bump', 333, invoked_at)

    async def test_disoku_bot_comment_triggers_up(self):
        cog = BumpRta(SimpleNamespace(supabase=object()))
        cog._is_enabled = AsyncMock(return_value=True)
        cog._schedule_reminder = AsyncMock()
        cog._record_rta_event = AsyncMock()
        message = SimpleNamespace(
            id=444, guild=SimpleNamespace(id=222),
            author=SimpleNamespace(id=DISOKU_BOT_ID, bot=True),
            application_id=DISOKU_BOT_ID,
            content='', embeds=[],
            interaction_metadata=SimpleNamespace(
                type=discord.InteractionType.application_command,
                user=SimpleNamespace(id=333),
                created_at=datetime(2026, 10, 13, 8, 1, 0, tzinfo=timezone.utc),
            ),
        )
        await cog.on_message(message)
        invoked_at = message.interaction_metadata.created_at
        cog._schedule_reminder.assert_awaited_once_with(message, 333, 'up', invoked_at)
        cog._record_rta_event.assert_awaited_once_with(message, 'up', 333, invoked_at)


if __name__ == '__main__':
    unittest.main()
