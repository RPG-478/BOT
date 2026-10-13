"""Default-on Disboard bump / Dis速 up reminders and separate RTA leaderboards."""
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


def detect_event(message):
    """Return (kind, user_id, event_at) for an official successful service embed."""
    if not getattr(message, "guild", None):
        return None
    if getattr(getattr(message, "channel", None), "type", None) != discord.ChannelType.text:
        return None
    author_id = getattr(getattr(message, "author", None), "id", None)
    application_id = getattr(message, "application_id", None)
    if author_id not in (DISBOARD_BOT_ID, DISOKU_BOT_ID) or application_id != author_id:
        return None
    embeds = getattr(message, "embeds", ()) or ()
    description = (getattr(embeds[0], "description", "") or "") if embeds else ""
    folded = description.casefold()
    if author_id == DISBOARD_BOT_ID:
        if "表示順をアップしたよ" not in description and "bump done" not in folded:
            return None
        kind = "bump"
    else:
        if "アップしたよ" not in description and "up successful" not in folded:
            return None
        kind = "up"
    metadata = getattr(message, "interaction_metadata", None)
    if metadata is not None and getattr(metadata, "type", None) != discord.InteractionType.application_command:
        return None
    user = getattr(metadata, "user", None)
    user_id = getattr(user, "id", None)
    if user_id is None:
        legacy_interaction = getattr(message, "interaction", None)
        user_id = getattr(getattr(legacy_interaction, "user", None), "id", None)
    event_at = getattr(metadata, "created_at", None) or getattr(message, "created_at", None)
    if event_at is None:
        return None
    return kind, int(user_id) if user_id is not None else None, event_at


class BumpRta(commands.Cog):
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

    async def _schedule_reminder(self, message, user_id, kind, event_at):
        reminder = {
            "message_id": str(message.id), "guild_id": str(message.guild.id),
            "channel_id": str(message.channel.id), "user_id": str(user_id) if user_id else None,
            "event_type": kind, "due_at": (event_at + timedelta(hours=2)).isoformat(),
        }
        await self._call(lambda: self.db.table("bump_rta_reminders").upsert(
            reminder, on_conflict="message_id", ignore_duplicates=True).execute())

    async def _start_rta_timer(self, row, sent_message):
        kind = row["event_type"]
        sent_at = getattr(sent_message, "created_at", None) or discord.utils.utcnow()
        pending = {
            "guild_id": str(row["guild_id"]), "event_type": kind,
            "user_id": str(row["user_id"]) if row.get("user_id") else None,
            "bump_message_id": str(row["message_id"]), "bump_at": sent_at.isoformat(),
        }
        await self._call(lambda: self.db.table("bump_rta_pending").upsert(
            pending, on_conflict="guild_id,event_type").execute())

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
                embed = discord.Embed(description=f"{noun}できるようになりました", color=discord.Color.blurple())
                sent = await channel.send(
                    embed=embed, reference=original, mention_author=False,
                    allowed_mentions=discord.AllowedMentions.none(),
                )
                await self._start_rta_timer(row, sent)
                await self._call(lambda row=row: self.db.table("bump_rta_reminders").update(
                    {"sent_at": discord.utils.utcnow().isoformat()}).eq("message_id", row["message_id"]).execute())
        except Exception:
            logger.exception("bump/up reminder worker failed")

    @reminder_worker.before_loop
    async def before_reminder_worker(self):
        await self.bot.wait_until_ready()

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        event = detect_event(message)
        if event is None:
            return
        kind, user_id, event_at = event
        guild_id = message.guild.id
        if not await self._is_enabled(guild_id):
            return
        lock = self._locks.setdefault((guild_id, kind), asyncio.Lock())
        async with lock:
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
            elapsed = max(1, int((event_at - discord.utils.parse_time(start["bump_at"])).total_seconds() * 1000))
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
        await message.channel.send(
            embed=discord.Embed(description=f"🏁 {kind} RTA記録: **{elapsed / 1000:.2f}秒**", color=discord.Color.green()),
            allowed_mentions=discord.AllowedMentions.none(),
        )


async def setup(bot):
    await bot.add_cog(BumpRta(bot))
