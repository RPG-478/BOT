"""Disboard bump から Dis速 up までのRTA記録と、2時間後の返信リマインダー。"""
import asyncio
import re
import time
from datetime import timedelta

import discord
from discord import app_commands
from discord.ext import commands, tasks

RANKING_SCOPE_CHOICES = [
    app_commands.Choice(name="このサーバー", value="local"),
    app_commands.Choice(name="全サーバー", value="global"),
]


def message_text(message):
    parts = [getattr(message, "content", "") or ""]
    for embed in getattr(message, "embeds", ()):
        parts.extend((getattr(embed, "title", "") or "", getattr(embed, "description", "") or ""))
        parts.extend(f"{f.name} {f.value}" for f in getattr(embed, "fields", ()))
    return " ".join(parts)


def event_kind(text):
    value = text.casefold()
    success = any(token in value for token in ("success", "done", "完了", "成功", "しました", "ました", "bumped"))
    bump = "bump" in value or "バンプ" in value
    up = bool(re.search(r"(?<![a-z])up(?![a-z])", value)) or any(token in value for token in ("上げ", "アップ", "掲載", "更新"))
    if bump and success:
        return "bump"
    if up and success:
        return "up"
    return None


class BumpRta(commands.Cog):
    bumprta = app_commands.Group(name="bumprta", description="DisboardからDis速 upまでのRTA", guild_only=True)

    def __init__(self, bot):
        self.bot = bot
        self.db = getattr(bot, "supabase", None)
        self._pending = {}
        self._locks = {}

    async def cog_load(self):
        if self.db is not None and not self.reminder_worker.is_running():
            self.reminder_worker.start()

    def cog_unload(self):
        self.reminder_worker.cancel()

    async def _call(self, fn):
        return await asyncio.to_thread(fn)

    @bumprta.command(name="setup", description="計測するDisboard/Dis速 Botとチャンネルを設定します")
    @app_commands.default_permissions(manage_guild=True)
    async def setup_rta(self, interaction: discord.Interaction, disboard_bot: discord.User | None = None,
                        disoku_bot: discord.User | None = None, channel: discord.TextChannel | None = None):
        if not disboard_bot or not disoku_bot or channel is None:
            return await interaction.response.send_message("Disboard Bot・Dis速 Bot・計測チャンネルをすべて指定してください。", ephemeral=True)
        if not disboard_bot.bot or not disoku_bot.bot or disboard_bot.id == disoku_bot.id:
            return await interaction.response.send_message("異なる2つのBotユーザーを指定してください。", ephemeral=True)
        row = {"guild_id": str(interaction.guild_id), "channel_id": str(channel.id),
               "disboard_bot_id": str(disboard_bot.id), "disoku_bot_id": str(disoku_bot.id)}
        await interaction.response.defer(ephemeral=True)
        await self._call(lambda: self.db.table("bump_rta_settings").upsert(row, on_conflict="guild_id").execute())
        await interaction.followup.send(f"設定しました: {channel.mention} / Disboard {disboard_bot.mention} / Dis速 {disoku_bot.mention}", ephemeral=True)

    @bumprta.command(name="status", description="このサーバーの計測設定と現在の記録を表示します")
    async def status(self, interaction: discord.Interaction):
        if self.db is None:
            return await interaction.response.send_message("Supabase未接続のため設定を確認できません。", ephemeral=True)
        rows = await self._call(lambda: self.db.table("bump_rta_settings").select("channel_id,disboard_bot_id,disoku_bot_id").eq("guild_id", str(interaction.guild_id)).limit(1).execute())
        if not rows.data:
            return await interaction.response.send_message("未設定です。管理者が `/bumprta setup` を実行してください。", ephemeral=True)
        cfg = rows.data[0]
        current = self._pending.get(interaction.guild_id)
        text = f"計測チャンネル: <#{cfg['channel_id']}>\nDisboard Bot: <@{cfg['disboard_bot_id']}>\nDis速 Bot: <@{cfg['disoku_bot_id']}>"
        if current:
            text += f"\n計測中: <@{current['user_id']}> / {time.monotonic() - current['started']:.2f}秒"
        await interaction.response.send_message(text, ephemeral=True)

    @bumprta.command(name="best", description="自分のこのサーバー/全体の自己ベストを表示します")
    async def best(self, interaction: discord.Interaction):
        if self.db is None:
            return await interaction.response.send_message("Supabase未接続のため記録を取得できません。", ephemeral=True)
        uid, gid = str(interaction.user.id), str(interaction.guild_id)
        local = await self._call(lambda: self.db.table("bump_rta_records").select("elapsed_ms,completed_at").eq("guild_id", gid).eq("user_id", uid).limit(1).execute())
        global_best = await self._call(lambda: self.db.table("bump_rta_events").select("elapsed_ms,completed_at").eq("user_id", uid).order("elapsed_ms").limit(1).execute())
        local_text = f"{local.data[0]['elapsed_ms'] / 1000:.2f}秒" if local.data else "記録なし"
        global_text = f"{global_best.data[0]['elapsed_ms'] / 1000:.2f}秒" if global_best.data else "記録なし"
        await interaction.response.send_message(f"🏁 <@{uid}> の自己ベスト\nこのサーバー: **{local_text}**\n全サーバー: **{global_text}**")

    @bumprta.command(name="ranking", description="最速記録をサーバー内/全体で表示します")
    @app_commands.choices(scope=RANKING_SCOPE_CHOICES)
    @app_commands.describe(scope="このサーバー内、または全サーバー")
    async def ranking(self, interaction: discord.Interaction, scope: app_commands.Choice[str] | None = None):
        if self.db is None:
            return await interaction.response.send_message("Supabase未接続のため順位を取得できません。", ephemeral=True)
        selected = scope.value if scope else "local"
        if selected == "global":
            rows = await self._call(lambda: self.db.rpc("get_bump_rta_global_ranking", {"p_limit": 10}).execute())
            data = rows.data or []
            lines = [f"**{i}.** <@{r['user_id']}> — **{r['elapsed_ms'] / 1000:.2f}秒**（{r['attempts']}回）" for i, r in enumerate(data, 1)]
            title = "全サーバー RTAランキング"
        else:
            rows = await self._call(lambda: self.db.table("bump_rta_records").select("user_id,elapsed_ms,completed_at").eq("guild_id", str(interaction.guild_id)).order("elapsed_ms").limit(10).execute())
            data = rows.data or []
            lines = [f"**{i}.** <@{r['user_id']}> — **{r['elapsed_ms'] / 1000:.2f}秒**" for i, r in enumerate(data, 1)]
            title = "このサーバーのRTAランキング"
        await interaction.response.send_message(f"🏁 **{title}**\n" + ("\n".join(lines) if lines else "まだ記録がありません。"))

    async def _schedule_reminder(self, message, user_id, kind):
        due_at = (message.created_at + timedelta(hours=2)).isoformat()
        reminder = {"message_id": str(message.id), "guild_id": str(message.guild.id),
                    "channel_id": str(message.channel.id), "user_id": str(user_id) if user_id else None,
                    "event_type": kind, "due_at": due_at}
        await self._call(lambda: self.db.table("bump_rta_reminders").upsert(
            reminder, on_conflict="message_id", ignore_duplicates=True).execute())

    @tasks.loop(minutes=1)
    async def reminder_worker(self):
        """期限到来した通知を、元メッセージへの返信として送る。"""
        try:
            due = await self._call(lambda: self.db.table("bump_rta_reminders").select(
                "message_id,guild_id,channel_id,user_id,event_type,due_at"
            ).is_("sent_at", "null").lte("due_at", discord.utils.utcnow().isoformat()).order("due_at").limit(50).execute())
            for row in due.data or []:
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
                user = f"<@{row['user_id']}> " if row.get("user_id") else ""
                text = f"⏰ {user}{'bump' if row['event_type'] == 'bump' else 'up'}から2時間です。次のbump / upが可能か確認してください。"
                await channel.send(text, reference=original, mention_author=False,
                                   allowed_mentions=discord.AllowedMentions(users=bool(row.get("user_id"))))
                await self._call(lambda row=row: self.db.table("bump_rta_reminders").update(
                    {"sent_at": discord.utils.utcnow().isoformat()}).eq("message_id", row["message_id"]).execute())
        except Exception:
            # A temporary database/Discord failure should not stop the periodic loop.
            return

    @reminder_worker.before_loop
    async def before_reminder_worker(self):
        await self.bot.wait_until_ready()

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if not message.guild or not getattr(message.author, "bot", False) or self.db is None:
            return
        gid = message.guild.id
        lock = self._locks.setdefault(gid, asyncio.Lock())
        async with lock:
            try:
                result = await self._call(lambda: self.db.table("bump_rta_settings").select(
                    "channel_id,disboard_bot_id,disoku_bot_id").eq("guild_id", str(gid)).limit(1).execute())
                if not result.data:
                    return
                cfg = result.data[0]
                if str(message.channel.id) != cfg["channel_id"]:
                    return
                kind = event_kind(message_text(message))
                bot_id = str(message.author.id)
                if kind == "bump" and bot_id == cfg["disboard_bot_id"]:
                    user_id = getattr(getattr(message, "interaction_metadata", None), "user_id", None)
                    if user_id is None:
                        interaction_user = getattr(getattr(message, "interaction", None), "user", None)
                        user_id = getattr(interaction_user, "id", None) or getattr(
                            getattr(message, "interaction", None), "user_id", None)
                    if user_id is not None:
                        self._pending[gid] = {"started": time.monotonic(), "user_id": int(user_id),
                                              "bump_message_id": str(message.id)}
                    await self._schedule_reminder(message, user_id, kind)
                elif kind == "up" and bot_id == cfg["disoku_bot_id"]:
                    started = self._pending.pop(gid, None)
                    if started:
                        elapsed = max(1, int((time.monotonic() - started["started"]) * 1000))
                        await self._call(lambda: self.db.table("bump_rta_events").insert({
                            "guild_id": str(gid), "user_id": str(started["user_id"]), "elapsed_ms": elapsed,
                            "bump_message_id": started["bump_message_id"], "completed_at": message.created_at.isoformat()
                        }).execute())
                        await self._call(lambda: self.db.rpc("record_bump_rta_best", {
                            "p_guild_id": str(gid), "p_user_id": str(started["user_id"]),
                            "p_elapsed_ms": elapsed, "p_completed_at": message.created_at.isoformat()
                        }).execute())
                        await message.channel.send(f"🏁 <@{started['user_id']}> のRTA記録: **{elapsed / 1000:.2f}秒**",
                                                   allowed_mentions=discord.AllowedMentions(users=True))
                    await self._schedule_reminder(message, started["user_id"] if started else None, kind)
            except Exception:
                # Tracking failures must not interrupt normal message processing.
                return


async def setup(bot):
    await bot.add_cog(BumpRta(bot))
