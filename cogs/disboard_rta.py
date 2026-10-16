"""Default-on Disboard bump / Dis速 up reminders and separate RTA leaderboards."""
import asyncio
import logging
from datetime import datetime, timedelta, timezone

import discord
from discord import app_commands
from discord.ext import commands, tasks
from core.supabase_client import key_role, select_key

logger = logging.getLogger(__name__)
DISBOARD_BOT_ID = 302050872383242240
DISOKU_BOT_ID = 761562078095867916
ACTION_CHOICES = [
    app_commands.Choice(name="状態", value="status"),
    app_commands.Choice(name="通知オン", value="on"),
    app_commands.Choice(name="通知オフ", value="off"),
    app_commands.Choice(name="ランキング", value="leaderboard"),
]
EVENT_TYPE_CHOICES = [
    app_commands.Choice(name="bump", value="bump"),
    app_commands.Choice(name="up", value="up"),
]
LEADERBOARD_SCOPE_CHOICES = [
    app_commands.Choice(name="自分のベスト", value="me"),
    app_commands.Choice(name="このサーバー", value="local"),
    app_commands.Choice(name="全サーバー", value="global"),
]
ALLOWED_CHANNEL_TYPES = {
    discord.ChannelType.text,
    discord.ChannelType.news,
    discord.ChannelType.public_thread,
    discord.ChannelType.private_thread,
    discord.ChannelType.news_thread,
}


def _collect_embed_text(message):
    """Collect text from message content and all relevant Discord embed properties."""
    parts = [getattr(message, "content", "") or ""]
    for embed in getattr(message, "embeds", ()) or ():
        # Include properties that are easy to overlook when an app uses rich embeds.
        for attr in ("title", "description", "url", "type"):
            value = getattr(embed, attr, None)
            if value:
                parts.append(str(value))
        for section_name in ("author", "footer", "provider", "image", "thumbnail", "video"):
            section = getattr(embed, section_name, None)
            if section:
                for attr in ("name", "text", "url", "proxy_url"):
                    value = getattr(section, attr, None)
                    if value:
                        parts.append(str(value))
        for field in getattr(embed, "fields", ()) or ():
            parts.extend((getattr(field, "name", "") or "", getattr(field, "value", "") or ""))
    return " ".join(str(part) for part in parts if part)


def _snowflake_datetime(snowflake_id):
    """Decode a Discord Snowflake ID into its UTC creation timestamp."""
    timestamp_ms = (int(snowflake_id) >> 22) + 1420070400000
    return datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc)


def detect_event(message):
    """Return (kind, user_id, event_at) for an official successful service embed.

    Use the message Snowflake timestamp as the event time. This avoids relying on
    interaction metadata timestamps, which may differ from the actual message time.
    """
    if not getattr(message, "guild", None):
        return None
    channel_type = getattr(getattr(message, "channel", None), "type", None)
    if channel_type not in ALLOWED_CHANNEL_TYPES:
        return None
    author_id = getattr(getattr(message, "author", None), "id", None)
    application_id = getattr(message, "application_id", None)

    text = _collect_embed_text(message)
    folded = text.casefold()
    # Some application-generated messages may expose an application/integration
    # author differently across discord.py/API versions. Recognize the visible
    # Disoku success embed as well as its known bot ID, while requiring both the
    # service branding and an explicit successful /up result for this fallback.
    is_disoku = (
        author_id == DISOKU_BOT_ID
        or ("ディス速" in text and ("アップしたよ" in text or "をアップ" in text)
            and ("command:/up" in folded or "/up" in folded))
    )
    is_disboard = author_id == DISBOARD_BOT_ID
    if not (is_disboard or is_disoku):
        return None

    if is_disoku:
        metadata = getattr(message, "interaction_metadata", None)
        logger.info(
            "Disoku message seen: author_id=%s app_id=%s meta_type=%s content=%r embed_count=%s text=%s",
            author_id,
            application_id,
            getattr(metadata, "type", None),
            getattr(message, "content", "") or "",
            len(getattr(message, "embeds", ()) or ()),
            text[:1000],
        )

    if is_disboard:
        if "表示順をアップしたよ" not in text and "bump done" not in folded:
            return None
        kind = "bump"
    else:
        if "アップ" not in text and "up" not in folded:
            logger.info("Disoku message ignored (no up keyword): %s", text[:1000])
            return None
        # Require an explicit success phrase to avoid matching unrelated chat.
        if not any(phrase in text for phrase in ("アップしたよ", "をアップ", "アップしました")):
            logger.info("Disoku message ignored (no success phrase): %s", text[:1000])
            return None
        kind = "up"

    metadata = getattr(message, "interaction_metadata", None)
    if metadata is not None and getattr(metadata, "type", None) not in (
        None, discord.InteractionType.application_command
    ):
        logger.info("Ignored non-application_command type: %s", getattr(metadata, "type", None))
        return None
    user = getattr(metadata, "user", None)
    user_id = getattr(user, "id", None)
    if user_id is None:
        legacy_interaction = getattr(message, "interaction", None)
        user_id = getattr(getattr(legacy_interaction, "user", None), "id", None)
    try:
        # Discord Snowflake stores the message creation time at millisecond precision.
        event_at = _snowflake_datetime(message.id)
    except (TypeError, ValueError, OverflowError):
        logger.exception("Could not decode message Snowflake timestamp: %s", getattr(message, "id", None))
        return None
    return kind, int(user_id) if user_id is not None else None, event_at


class BumpRta(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db = getattr(bot, "supabase", None)
        self._enabled_cache = {}
        self._locks = {}
        self._processed_messages = set()
        self._claimed_reminders = set()

    async def cog_load(self):
        if self.db is not None and not self.reminder_worker.is_running():
            self.reminder_worker.start()
        key, source = select_key()
        role = key_role(key) if key else "not-set"
        if self.db is not None and role not in {"anon", "service_role"}:
            logger.warning(
                "bump/up RTA RPC requires an anon/service_role key and matching SQL grant; source=%s role=%s",
                source or "not-set", role,
            )

    def cog_unload(self):
        self.reminder_worker.cancel()

    async def _call(self, fn):
        return await asyncio.to_thread(fn)

    async def _is_enabled(self, guild_id):
        gid = str(guild_id)
        if gid in self._enabled_cache:
            return self._enabled_cache[gid]
        if self.db is None:
            return True
        try:
            result = await self._call(lambda: self.db.table("bump_rta_settings").select(
                "notifications_enabled").eq("guild_id", gid).limit(1).execute())
            enabled = bool(result.data[0]["notifications_enabled"]) if result.data else True
            self._enabled_cache[gid] = enabled
            return enabled
        except Exception:
            logger.exception("bump_rta_settings read failed; using default enabled state: guild=%s", gid)
            return True

    @app_commands.command(name="bumprta", description="bump/up通知設定・状態・個別ランキング")
    @app_commands.choices(action=ACTION_CHOICES, event_type=EVENT_TYPE_CHOICES, scope=LEADERBOARD_SCOPE_CHOICES)
    @app_commands.describe(
        action="操作",
        event_type="ランキング対象（bumpとupは別集計）",
        scope="自己ベスト・サーバー内・全体",
    )
    async def bumprta_command(
        self,
        interaction: discord.Interaction,
        action: app_commands.Choice[str],
        event_type: app_commands.Choice[str] | None = None,
        scope: app_commands.Choice[str] | None = None,
    ):
        selected_action = action.value
        if selected_action == "status":
            enabled = await self._is_enabled(interaction.guild_id)
            return await interaction.response.send_message(
                f"bump/up通知とRTA計測: **{'オン' if enabled else 'オフ'}**（初期状態: オン）", ephemeral=True)
        if selected_action in {"on", "off"}:
            if not getattr(getattr(interaction.user, "guild_permissions", None), "manage_guild", False):
                return await interaction.response.send_message("この操作にはサーバー管理権限が必要です。", ephemeral=True)
            enabled = selected_action == "on"
            gid = str(interaction.guild_id)
            self._enabled_cache[gid] = enabled
            if self.db is not None:
                await self._call(lambda: self.db.table("bump_rta_settings").upsert(
                    {"guild_id": gid, "notifications_enabled": enabled}, on_conflict="guild_id").execute())
                if not enabled:
                    await self._call(lambda: self.db.table("bump_rta_reminders").update(
                        {"sent_at": discord.utils.utcnow().isoformat()}).eq("guild_id", gid).is_("sent_at", "null").execute())
                    await self._call(lambda: self.db.table("bump_rta_pending").delete().eq("guild_id", gid).execute())
            return await interaction.response.send_message(
                f"bump/up通知とRTA計測を **{'オン' if enabled else 'オフ'}** にしました。", ephemeral=True)
        if self.db is None:
            return await interaction.response.send_message("Supabase未接続のため順位を取得できません。", ephemeral=True)
        kind = event_type.value if event_type else "bump"
        selected_scope = scope.value if scope else "local"
        try:
            if selected_scope == "me":
                uid, gid = str(interaction.user.id), str(interaction.guild_id)
                local = await self._call(lambda: self.db.table("bump_rta_records").select(
                    "elapsed_ms,completed_at").eq("guild_id", gid).eq("user_id", uid).eq("event_type", kind).limit(1).execute())
                global_best = await self._call(lambda: self.db.table("bump_rta_events").select(
                    "elapsed_ms,completed_at").eq("user_id", uid).eq("event_type", kind).order("elapsed_ms").limit(1).execute())
                local_text = f"{local.data[0]['elapsed_ms'] / 1000:.2f}秒" if local.data else "記録なし"
                global_text = f"{global_best.data[0]['elapsed_ms'] / 1000:.2f}秒" if global_best.data else "記録なし"
                return await interaction.response.send_message(
                    f"🏁 <@{uid}> の**{kind}自己ベスト**\nこのサーバー: **{local_text}**\n全サーバー: **{global_text}**")
            if selected_scope == "global":
                rows = await self._call(lambda: self.db.rpc("get_bump_rta_global_ranking", {
                    "p_event_type": kind, "p_limit": 10}).execute())
                data = rows.data or []
                lines = [f"**{i}.** <@{r['user_id']}> — **{r['elapsed_ms'] / 1000:.2f}秒**（{r['attempts']}回）" for i, r in enumerate(data, 1)]
                title = f"全サーバー {kind} RTAランキング"
            else:
                rows = await self._call(lambda: self.db.table("bump_rta_records").select(
                    "user_id,elapsed_ms,completed_at").eq("guild_id", str(interaction.guild_id)).eq(
                    "event_type", kind).order("elapsed_ms").limit(10).execute())
                data = rows.data or []
                lines = [f"**{i}.** <@{r['user_id']}> — **{r['elapsed_ms'] / 1000:.2f}秒**" for i, r in enumerate(data, 1)]
                title = f"このサーバー {kind} RTAランキング"
            return await interaction.response.send_message(
                f"🏁 **{title}**\n" + ("\n".join(lines) if lines else "まだ記録がありません。"))
        except Exception as e:
            logger.exception("bump/up leaderboard query failed: scope=%s kind=%s", selected_scope, kind)
            return await interaction.response.send_message(
                f"❌ ランキングの取得に失敗しました。\n（{type(e).__name__}: {e}）", ephemeral=True)

    async def _schedule_reminder(self, message, user_id, kind, event_at):
        due_at = (event_at + timedelta(hours=2)).isoformat()
        reminder = {
            "message_id": str(message.id), "guild_id": str(message.guild.id),
            "channel_id": str(message.channel.id), "user_id": str(user_id) if user_id else None,
            "event_type": kind, "due_at": due_at,
        }
        await self._call(lambda: self.db.table("bump_rta_reminders").upsert(
            reminder, on_conflict="message_id", ignore_duplicates=True).execute())

    async def _start_rta_timer(self, row, due_at_iso):
        kind = row["event_type"]
        pending = {
            "guild_id": str(row["guild_id"]), "event_type": kind,
            "user_id": str(row["user_id"]) if row.get("user_id") else None,
            "bump_message_id": str(row["message_id"]), "bump_at": due_at_iso,
        }
        await self._call(lambda: self.db.table("bump_rta_pending").upsert(
            pending, on_conflict="guild_id,event_type").execute())

    async def _claim_reminder(self, message_id):
        """Claim a reminder. Local set is the primary guard; DB is secondary."""
        if message_id in self._claimed_reminders:
            return False
        self._claimed_reminders.add(message_id)
        if len(self._claimed_reminders) > 2000:
            self._claimed_reminders.clear()
            self._claimed_reminders.add(message_id)
        if self.db is None:
            return True
        try:
            result = await self._call(lambda: self.db.table("bump_rta_reminders").update(
                {"sent_at": discord.utils.utcnow().isoformat()}
            ).eq("message_id", message_id).is_("sent_at", "null").execute())
            logger.debug("Claimed reminder %s, data=%s", message_id, bool(result.data))
            return True
        except Exception:
            logger.exception("DB claim failed for reminder %s (local claim still active)", message_id)
            return True

    @tasks.loop(seconds=10)
    async def reminder_worker(self):
        if self.db is None:
            return
        try:
            now_iso = discord.utils.utcnow().isoformat()
            due = await self._call(lambda: self.db.table("bump_rta_reminders").select(
                "message_id,guild_id,channel_id,user_id,event_type,due_at"
            ).is_("sent_at", "null").lte("due_at", now_iso).order("due_at").limit(50).execute())
            for row in due.data or []:
                mid = row["message_id"]
                if mid in self._claimed_reminders:
                    continue
                if not await self._is_enabled(row["guild_id"]):
                    await self._call(lambda row=row: self.db.table("bump_rta_reminders").update(
                        {"sent_at": discord.utils.utcnow().isoformat()}).eq("message_id", mid).execute())
                    self._claimed_reminders.add(mid)
                    continue
                if not await self._claim_reminder(mid):
                    continue
                channel = self.bot.get_channel(int(row["channel_id"]))
                if channel is None:
                    try:
                        channel = await self.bot.fetch_channel(int(row["channel_id"]))
                    except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                        logger.warning("Could not fetch channel %s for reminder", row["channel_id"])
                        self._claimed_reminders.discard(mid)
                        continue
                try:
                    original = await channel.fetch_message(int(mid))
                except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                    original = None
                noun = "bump" if row["event_type"] == "bump" else "up"
                embed = discord.Embed(
                    title=f"{noun.upper()} RTA記録開始",
                    description=f"{noun}の再実行可能時刻になりました。ここからRTA計測を開始します！",
                    color=discord.Color.blurple(),
                    timestamp=discord.utils.utcnow(),
                )
                embed.set_footer(text="RTA計測を開始しました")
                try:
                    await channel.send(
                        embed=embed,
                        reference=original,
                        mention_author=False,
                        allowed_mentions=discord.AllowedMentions.none(),
                    )
                except discord.HTTPException as e:
                    logger.warning("Failed to send %s reminder in %s: %s", noun, row["channel_id"], e)
                    self._claimed_reminders.discard(mid)
                    await self._call(lambda mid=mid: self.db.table("bump_rta_reminders").update(
                        {"sent_at": None}).eq("message_id", mid).execute())
                    continue
                await self._start_rta_timer(row, row["due_at"])
        except Exception:
            logger.exception("bump/up reminder worker failed")

    @reminder_worker.before_loop
    async def before_reminder_worker(self):
        await self.bot.wait_until_ready()

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        # Diagnostic logging for Disoku's application embed. The screenshot shows
        # the success phrase inside the embed description, not message.content.
        if (getattr(getattr(message, "author", None), "id", None) == DISOKU_BOT_ID
                or "ディス速" in _collect_embed_text(message)):
            try:
                metadata = getattr(message, "interaction_metadata", None)
                logger.info(
                    "Disoku debug: message_id=%s author_id=%s application_id=%s "
                    "channel_type=%s content=%r metadata_type=%s metadata_user=%s",
                    message.id,
                    getattr(getattr(message, "author", None), "id", None),
                    getattr(message, "application_id", None),
                    getattr(getattr(message, "channel", None), "type", None),
                    getattr(message, "content", "") or "",
                    getattr(metadata, "type", None),
                    getattr(getattr(metadata, "user", None), "id", None),
                )
                for index, embed in enumerate(getattr(message, "embeds", ()) or ()):
                    logger.info("Disoku embed[%s] raw=%s", index, embed.to_dict())
            except Exception:
                logger.exception("Failed to log Disoku embed details")

        if message.id in self._processed_messages:
            return
        event = detect_event(message)
        if event is None:
            return
        kind, user_id, event_at = event
        guild_id = message.guild.id
        if not await self._is_enabled(guild_id):
            return
        self._processed_messages.add(message.id)
        if len(self._processed_messages) > 5000:
            self._processed_messages.clear()
        lock = self._locks.setdefault((guild_id, kind), asyncio.Lock())
        async with lock:
            # Do not send a separate notification at detection time. The bump/up
            # notification is sent when the two-hour RTA timer actually starts.
            if self.db is None:
                return
            try:
                await self._record_rta_event(message, kind, user_id, event_at)
            except Exception:
                logger.exception("Failed to record %s RTA event: guild=%s message=%s", kind, guild_id, message.id)
            try:
                await self._schedule_reminder(message, user_id, kind, event_at)
            except Exception:
                logger.exception("Failed to save %s reminder: guild=%s message=%s", kind, guild_id, message.id)

    async def _record_rta_event(self, message, kind, user_id, event_at):
        gid = str(message.guild.id)
        pending = await self._call(lambda: self.db.table("bump_rta_pending").select(
            "user_id,bump_message_id,bump_at").eq("guild_id", gid).eq("event_type", kind).limit(1).execute())
        if not pending.data:
            return
        start = pending.data[0]
        record_user_id = str(user_id or "")
        if not record_user_id:
            logger.warning("Cannot attribute %s RTA completion: guild=%s", kind, gid)
            return
        existing = await self._call(lambda: self.db.table("bump_rta_events").select(
            "elapsed_ms,completed_at").eq("bump_message_id", start["bump_message_id"]).eq(
            "event_type", kind).limit(1).execute())
        if existing.data:
            elapsed = int(existing.data[0]["elapsed_ms"])
            completed_at = existing.data[0]["completed_at"]
        else:
            try:
                start_time = discord.utils.parse_time(start["bump_at"])
                elapsed = max(1, int((event_at - start_time).total_seconds() * 1000))
            except (TypeError, ValueError):
                elapsed = 1
            completed_at = event_at.isoformat()
            await self._call(lambda: self.db.table("bump_rta_events").insert({
                "guild_id": gid, "user_id": record_user_id, "event_type": kind,
                "elapsed_ms": elapsed, "bump_message_id": start["bump_message_id"],
                "completed_at": completed_at,
            }).execute())
        await self._call(lambda: self.db.rpc("record_bump_rta_best", {
            "p_guild_id": gid, "p_user_id": record_user_id, "p_event_type": kind,
            "p_elapsed_ms": elapsed, "p_completed_at": completed_at,
        }).execute())
        await self._call(lambda: self.db.table("bump_rta_pending").delete().eq("guild_id", gid).eq(
            "event_type", kind).execute())
        embed = discord.Embed(
            title="RTA記録",
            description=f"🏁 {kind} **{elapsed / 1000:.2f}秒**",
            color=discord.Color.gold(),
        )
        try:
            await message.channel.send(
                embed=embed,
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except discord.HTTPException as e:
            logger.warning("Failed to send RTA result embed: %s", e)


async def setup(bot):
    await bot.add_cog(BumpRta(bot))
