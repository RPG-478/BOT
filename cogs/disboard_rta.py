"""Default-on Disboard bump / Dis速 up reminders and RTA leaderboard."""
import asyncio
import logging
from datetime import timedelta

import discord
from discord import app_commands
from discord.ext import commands, tasks
from core.supabase_client import key_role, select_key

logger = logging.getLogger(__name__)
DISBOARD_BOT_ID = 302050872383242240
DISOKU_BOT_ID = 761562078095867916
LEADERBOARD_SCOPE_CHOICES = [
    app_commands.Choice(name="自分のベスト", value="me"),
    app_commands.Choice(name="このサーバー", value="local"),
    app_commands.Choice(name="全サーバー", value="global"),
]


def command_event(message):
    """Identify a bump/up command interaction by the responding bot application.

    This deliberately does not inspect message content or embeds. Discord.py provides
    MessageInteractionMetadata even when Message Content Intent fields are unavailable.
    """
    author_id = getattr(getattr(message, "author", None), "id", None)
    application_id = getattr(message, "application_id", None)
    if author_id == DISBOARD_BOT_ID:
        kind, expected_application_id = "bump", DISBOARD_BOT_ID
    elif author_id == DISOKU_BOT_ID:
        kind, expected_application_id = "up", DISOKU_BOT_ID
    else:
        return None
    metadata = getattr(message, "interaction_metadata", None)
    if metadata is None:
        return None
    if getattr(metadata, "type", None) != discord.InteractionType.application_command:
        return None
    # Bind the response to the expected official app and its bot user; reject mismatches.
    if application_id is None or int(application_id) != expected_application_id:
        return None
    user = getattr(metadata, "user", None)
    user_id = getattr(user, "id", None)
    event_at = getattr(metadata, "created_at", None) or getattr(message, "created_at", None)
    if user_id is None or event_at is None:
        return None
    return kind, int(user_id), event_at


class BumpRta(commands.Cog):
    bumprta = app_commands.Group(name="bumprta", description="bump/up通知とRTAランキング", guild_only=True)

    def __init__(self, bot):
        self.bot = bot
        self.db = getattr(bot, "supabase", None)
        self._enabled_cache = {}
        self._locks = {}

    async def cog_load(self):
        if self.db is not None and not self.reminder_worker.is_running():
            self.reminder_worker.start()
        key, source = select_key()
        role = key_role(key) if key else "not-set"
        if self.db is not None and role not in {"anon", "service_role"}:
            logger.warning(
                "bump/up RTA RPC requires an anon/service_role key and the matching SQL grant; "
                "configured key source=%s role=%s. Key value is not logged.",
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
            # Keep the out-of-box default usable during a transient read failure.
            logger.exception("bump_rta_settings read failed; using default enabled state: guild=%s", gid)
            return True

    @bumprta.command(name="notifications", description="bump/up通知とRTA計測をオン/オフします（初期状態はオン）")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.describe(enabled="オフにすると2時間後通知とRTA計測の両方を停止")
    async def notifications(self, interaction: discord.Interaction, enabled: bool):
        gid = str(interaction.guild_id)
        self._enabled_cache[gid] = enabled
        if self.db is not None:
            await self._call(lambda: self.db.table("bump_rta_settings").upsert(
                {"guild_id": gid, "notifications_enabled": enabled}, on_conflict="guild_id").execute())
            if not enabled:
                await self._call(lambda: self.db.table("bump_rta_reminders").update(
                    {"sent_at": discord.utils.utcnow().isoformat()}).eq("guild_id", gid).is_("sent_at", "null").execute())
                await self._call(lambda: self.db.table("bump_rta_pending").delete().eq("guild_id", gid).execute())
        status = "オン" if enabled else "オフ"
        await interaction.response.send_message(f"bump/up通知とRTA計測を **{status}** にしました。", ephemeral=True)

    @bumprta.command(name="status", description="bump/up通知とRTAの有効状態を表示します")
    async def status(self, interaction: discord.Interaction):
        enabled = await self._is_enabled(interaction.guild_id)
        await interaction.response.send_message(
            f"bump/up通知とRTA計測: **{'オン' if enabled else 'オフ'}**（初期状態: オン）", ephemeral=True)

    @bumprta.command(name="leaderboard", description="自己ベストまたはサーバー内/全体ランキングを表示します")
    @app_commands.choices(scope=LEADERBOARD_SCOPE_CHOICES)
    @app_commands.describe(scope="自分のベスト、このサーバー、または全サーバー")
    async def leaderboard(self, interaction: discord.Interaction, scope: app_commands.Choice[str] | None = None):
        if self.db is None:
            return await interaction.response.send_message("Supabase未接続のため順位を取得できません。", ephemeral=True)
        selected = scope.value if scope else "local"
        if selected == "me":
            uid, gid = str(interaction.user.id), str(interaction.guild_id)
            local = await self._call(lambda: self.db.table("bump_rta_records").select(
                "elapsed_ms,completed_at").eq("guild_id", gid).eq("user_id", uid).limit(1).execute())
            global_best = await self._call(lambda: self.db.table("bump_rta_events").select(
                "elapsed_ms,completed_at").eq("user_id", uid).order("elapsed_ms").limit(1).execute())
            local_text = f"{local.data[0]['elapsed_ms'] / 1000:.2f}秒" if local.data else "記録なし"
            global_text = f"{global_best.data[0]['elapsed_ms'] / 1000:.2f}秒" if global_best.data else "記録なし"
            return await interaction.response.send_message(
                f"🏁 <@{uid}> の自己ベスト\nこのサーバー: **{local_text}**\n全サーバー: **{global_text}**")
        if selected == "global":
            rows = await self._call(lambda: self.db.rpc("get_bump_rta_global_ranking", {"p_limit": 10}).execute())
            data = rows.data or []
            lines = [f"**{i}.** <@{r['user_id']}> — **{r['elapsed_ms'] / 1000:.2f}秒**（{r['attempts']}回）" for i, r in enumerate(data, 1)]
            title = "全サーバー RTAランキング"
        else:
            rows = await self._call(lambda: self.db.table("bump_rta_records").select(
                "user_id,elapsed_ms,completed_at").eq("guild_id", str(interaction.guild_id)).order("elapsed_ms").limit(10).execute())
            data = rows.data or []
            lines = [f"**{i}.** <@{r['user_id']}> — **{r['elapsed_ms'] / 1000:.2f}秒**" for i, r in enumerate(data, 1)]
            title = "このサーバーのRTAランキング"
        await interaction.response.send_message(f"🏁 **{title}**\n" + ("\n".join(lines) if lines else "まだ記録がありません。"))

    async def _schedule_reminder(self, message, user_id, kind, event_at):
        reminder = {
            "message_id": str(message.id), "guild_id": str(message.guild.id),
            "channel_id": str(message.channel.id), "user_id": str(user_id) if user_id else None,
            "event_type": kind, "due_at": (event_at + timedelta(hours=2)).isoformat(),
        }
        await self._call(lambda: self.db.table("bump_rta_reminders").upsert(
            reminder, on_conflict="message_id", ignore_duplicates=True).execute())

    @tasks.loop(minutes=1)
    async def reminder_worker(self):
        if self.db is None:
            return
        try:
            due = await self._call(lambda: self.db.table("bump_rta_reminders").select(
                "message_id,guild_id,channel_id,user_id,event_type,due_at"
            ).is_("sent_at", "null").lte("due_at", discord.utils.utcnow().isoformat()).order("due_at").limit(50).execute())
            for row in due.data or []:
                if not await self._is_enabled(row["guild_id"]):
                    await self._call(lambda row=row: self.db.table("bump_rta_reminders").update(
                        {"sent_at": discord.utils.utcnow().isoformat()}).eq("message_id", row["message_id"]).execute())
                    continue
                channel = self.bot.get_channel(int(row["channel_id"]))
                if channel is None:
                    try:
                        channel = await self.bot.fetch_channel(int(row["channel_id"]))
                    except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                        continue
                try:
                    original = await channel.fetch_message(int(row["message_id"]))
                except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                    original = None
                noun = "bump" if row["event_type"] == "bump" else "up"
                user = f"<@{row['user_id']}> " if row.get("user_id") else ""
                text = f"⏰ {user}{noun}から2時間です。bumpしましょう！" if noun == "bump" else f"⏰ {user}upから2時間です。upしましょう！"
                await channel.send(text, reference=original, mention_author=False,
                                   allowed_mentions=discord.AllowedMentions(users=bool(row.get("user_id"))))
                await self._call(lambda row=row: self.db.table("bump_rta_reminders").update(
                    {"sent_at": discord.utils.utcnow().isoformat()}).eq("message_id", row["message_id"]).execute())
        except Exception:
            logger.exception("bump/up reminder worker failed")

    @reminder_worker.before_loop
    async def before_reminder_worker(self):
        await self.bot.wait_until_ready()

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if not message.guild or not getattr(message.author, "bot", False):
            return
        event = command_event(message)
        if event is None:
            return
        kind, user_id, event_at = event
        guild_id = message.guild.id
        if not await self._is_enabled(guild_id):
            return
        lock = self._locks.setdefault(guild_id, asyncio.Lock())
        async with lock:
            if self.db is not None:
                # A reminder DB failure should not prevent the RTA state machine from running.
                try:
                    await self._schedule_reminder(message, user_id, kind, event_at)
                except Exception:
                    logger.exception("Failed to save %s reminder: guild=%s message=%s", kind, guild_id, message.id)
                try:
                    await self._record_rta_event(message, kind, user_id, event_at)
                except Exception:
                    logger.exception("Failed to record %s RTA event: guild=%s message=%s", kind, guild_id, message.id)

    async def _record_rta_event(self, message, kind, user_id, event_at):
        gid = str(message.guild.id)
        if kind == "bump":
            if user_id is None:
                return
            await self._call(lambda: self.db.table("bump_rta_pending").upsert({
                "guild_id": gid, "user_id": str(user_id), "bump_message_id": str(message.id),
                "bump_at": event_at.isoformat(),
            }, on_conflict="guild_id").execute())
            return
        pending = await self._call(lambda: self.db.table("bump_rta_pending").select(
            "user_id,bump_message_id,bump_at").eq("guild_id", gid).limit(1).execute())
        if not pending.data:
            return
        start = pending.data[0]
        existing = await self._call(lambda: self.db.table("bump_rta_events").select(
            "elapsed_ms,completed_at").eq("bump_message_id", start["bump_message_id"]).limit(1).execute())
        if existing.data:
            # A prior attempt may have inserted the event but failed at the service_role-only RPC.
            elapsed = int(existing.data[0]["elapsed_ms"])
            completed_at = existing.data[0]["completed_at"]
        else:
            elapsed = max(1, int((event_at - discord.utils.parse_time(start["bump_at"])).total_seconds() * 1000))
            completed_at = event_at.isoformat()
            await self._call(lambda: self.db.table("bump_rta_events").insert({
                "guild_id": gid, "user_id": str(start["user_id"]), "elapsed_ms": elapsed,
                "bump_message_id": start["bump_message_id"], "completed_at": completed_at,
            }).execute())
        await self._call(lambda: self.db.rpc("record_bump_rta_best", {
            "p_guild_id": gid, "p_user_id": str(start["user_id"]), "p_elapsed_ms": elapsed,
            "p_completed_at": completed_at,
        }).execute())
        # Keep the timer until the best-record RPC has succeeded; retries are idempotent above.
        await self._call(lambda: self.db.table("bump_rta_pending").delete().eq("guild_id", gid).execute())
        await message.channel.send(f"🏁 <@{start['user_id']}> のRTA記録: **{elapsed / 1000:.2f}秒**",
                                   allowed_mentions=discord.AllowedMentions(users=True))


async def setup(bot):
    await bot.add_cog(BumpRta(bot))
