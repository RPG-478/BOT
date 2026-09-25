import os
from datetime import datetime, timezone, timedelta, date
import discord
from discord import app_commands
from discord.ext import commands, tasks
from supabase import create_client, Client


class FujoSurvival(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        url: str = os.getenv("SUPABASE_URL", "")
        key: str = os.getenv("SUPABASE_KEY", "")
        self.supabase: Client = create_client(url, key)
        self.check_panic_alerts.start()
        self.check_duo_pester.start()

    def cog_unload(self):
        self.check_panic_alerts.cancel()
        self.check_duo_pester.cancel()

    fujo_group = app_commands.Group(name="fujo", description="生存確認機能のコマンド一覧")
    panic_group = app_commands.Group(name="panic", description="失踪警報・遺言設定のコマンド一覧", parent=fujo_group)

    # --- ヘルパー関数 (Embed生成・判定) ---

    def create_simple_embed(self, title: str, description: str, color: int = 0x2b2d31) -> discord.Embed:
        embed = discord.Embed(title=title, description=description, color=color)
        embed.set_footer(text="Survival Surveillance System")
        return embed

    def is_registered(self, user_id: int) -> bool:
        response = self.supabase.table("fujo_users").select("user_id").eq("user_id", user_id).execute()
        return len(response.data) > 0

    def record_activity(self, user_id: int, signal_type: str, status: str):
        if not self.is_registered(user_id):
            return

        now = datetime.now(timezone.utc)
        now_str = now.isoformat()
        today = now.date()

        # アクティブログ挿入
        self.supabase.table("fujo_activities").insert({
            "user_id": user_id,
            "detected_at": now_str,
            "signal_type": signal_type,
            "status": status
        }).execute()

        # ストリーク更新ロジック
        user_res = self.supabase.table("fujo_users").select("streak_count, last_streak_date, is_frozen").eq("user_id", user_id).execute()
        if user_res.data:
            u_data = user_res.data[0]
            last_date_str = u_data["last_streak_date"]
            streak = u_data["streak_count"]
            is_frozen = u_data["is_frozen"]

            last_date = datetime.strptime(last_date_str, "%Y-%m-%d").date() if last_date_str else None

            if last_date != today:
                if last_date == today - timedelta(days=1):
                    new_streak = streak + 1
                elif last_date is None:
                    new_streak = 1
                else:
                    if is_frozen:
                        new_streak = streak
                    else:
                        new_streak = 1

                self.supabase.table("fujo_users").update({
                    "streak_count": new_streak,
                    "last_streak_date": today.isoformat(),
                    "is_frozen": False,
                    "last_pester_level": 0
                }).eq("user_id", user_id).execute()

    def calculate_title(self, user_id: int) -> str:
        since_30d = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        res = self.supabase.table("fujo_activities") \
            .select("detected_at, signal_type") \
            .eq("user_id", user_id) \
            .gte("detected_at", since_30d) \
            .execute()

        records = res.data
        total = len(records)
        if total < 5:
            return "一般サバイバー"

        msg_count = 0
        voice_count = 0
        presence_count = 0
        night_count = 0

        for r in records:
            stype = r["signal_type"]
            if stype == "MESSAGE":
                msg_count += 1
            elif stype == "VOICE":
                voice_count += 1
            elif stype == "PRESENCE":
                presence_count += 1

            dt = datetime.fromisoformat(r["detected_at"].replace("Z", "+00:00"))
            jst_hour = (dt.hour + 9) % 24
            if jst_hour >= 23 or jst_hour < 5:
                night_count += 1

        if (night_count / total) >= 0.35:
            return "夜行性"
        if (msg_count + voice_count) / total <= 0.05:
            return "永遠のROMラー"
        if (voice_count / total) >= 0.40:
            return "出会い厨"
        if (msg_count / total) >= 0.40:
            return "おしゃべりマシン"

        return "一般サバイバー"

    # --- イベントリスナー ---

    @commands.Cog.listener()
    async def on_presence_update(self, before: discord.Member, after: discord.Member):
        if after.bot:
            return
        if after.status != discord.Status.offline:
            self.record_activity(after.id, "PRESENCE", str(after.status))

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        status = str(message.author.status) if isinstance(message.author, discord.Member) else "unknown"
        self.record_activity(message.author.id, "MESSAGE", status)

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        if member.bot:
            return
        self.record_activity(member.id, "VOICE", str(member.status))

    # --- コマンド一覧 ---

    @fujo_group.command(name="register", description="生存確認の追跡登録・解除を切り替えます")
    async def register(self, interaction: discord.Interaction):
        user_id = interaction.user.id
        if self.is_registered(user_id):
            self.supabase.table("fujo_users").delete().eq("user_id", user_id).execute()
            embed = self.create_simple_embed("追跡解除通知", "生存確認の追跡登録を解除しました。監視を終了します。", 0xe74c3c)
        else:
            self.supabase.table("fujo_users").insert({"user_id": user_id}).execute()
            embed = self.create_simple_embed("追跡開始通知", "生存確認の追跡を登録しました。24時間の監視を開始します。", 0x2ecc71)
        
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @fujo_group.command(name="status", description="指定ユーザーの生存ステータスを確認します")
    async def status(self, interaction: discord.Interaction, target: discord.User):
        if not self.is_registered(target.id):
            embed = self.create_simple_embed("エラー", f"{target.mention} は追跡登録されていません。", 0x95a5a6)
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        res = self.supabase.table("fujo_activities") \
            .select("detected_at, signal_type, status") \
            .eq("user_id", target.id) \
            .order("detected_at", desc=True) \
            .limit(1) \
            .execute()

        if not res.data:
            embed = self.create_simple_embed("データなし", f"{target.mention} のアクティブ記録がまだ存在しません。", 0x95a5a6)
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        user_db = self.supabase.table("fujo_users").select("streak_count, is_frozen").eq("user_id", target.id).execute()
        streak = user_db.data[0]["streak_count"] if user_db.data else 0
        is_frozen = user_db.data[0]["is_frozen"] if user_db.data else False

        latest = res.data[0]
        dt = datetime.fromisoformat(latest["detected_at"].replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        unix_ts = int(dt.timestamp())

        hours_passed = (now - dt).total_seconds() / 3600.0

        if hours_passed < 12:
            status_label = "[状態: 良好]"
            color = 0x2ecc71
        elif hours_passed < 48:
            status_label = "[状態: 注意]"
            color = 0xf1c40f
        elif hours_passed < 168:
            status_label = "[状態: 警戒]"
            color = 0xe67e22
        elif hours_passed < 720:
            status_label = "[状態: 霊体化]"
            color = 0x9b59b6
        else:
            status_label = "[状態: 化石化]"
            color = 0x34495e

        zombie_rate = min(100, int((hours_passed / (7 * 24)) * 100))
        survival_rate = 100 - zombie_rate

        bar_len = 10
        filled = int(bar_len * (survival_rate / 100.0))
        progress_bar = f"[{'█' * filled}{'░' * (bar_len - filled)}] {survival_rate}%"

        title_name = self.calculate_title(target.id)

        embed = discord.Embed(title=f"生存ステータス - {target.display_name}", color=color)
        embed.set_thumbnail(url=target.display_avatar.url)
        embed.add_field(name="判定レベル", value=status_label, inline=True)
        embed.add_field(name="称号", value=f"【{title_name}】", inline=True)
        embed.add_field(name="連続生存日数", value=f"{streak} 日連続 {'(フリーズ適用中)' if is_frozen else ''}", inline=True)
        embed.add_field(name="最終アクティブ", value=f"<t:{unix_ts}:R>\n(<t:{unix_ts}:F>)", inline=False)
        embed.add_field(name="生存確率ゲージ", value=f"`{progress_bar}`", inline=False)
        embed.add_field(name="ゾンビ化率", value=f"{zombie_rate}%", inline=True)
        embed.add_field(name="検知タイプ", value=latest["signal_type"], inline=True)
        embed.set_footer(text="Survival Surveillance System")

        await interaction.response.send_message(embed=embed)

    @fujo_group.command(name="hindo", description="指定ユーザーのアクティブ頻度を確認します")
    async def hindo(self, interaction: discord.Interaction, target: discord.User):
        if not self.is_registered(target.id):
            embed = self.create_simple_embed("エラー", f"{target.mention} は追跡登録されていません。", 0x95a5a6)
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        now = datetime.now(timezone.utc)
        since_30d = (now - timedelta(days=30)).isoformat()

        res = self.supabase.table("fujo_activities") \
            .select("detected_at") \
            .eq("user_id", target.id) \
            .gte("detected_at", since_30d) \
            .execute()

        records = res.data
        if not records:
            embed = self.create_simple_embed("データなし", f"{target.mention} の過去30日間の記録はありません。", 0x95a5a6)
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        count_24h = 0
        count_7d = 0
        count_30d = len(records)
        now_ts = now.timestamp()

        for r in records:
            dt = datetime.fromisoformat(r["detected_at"].replace("Z", "+00:00"))
            diff_hours = (now_ts - dt.timestamp()) / 3600
            if diff_hours <= 24:
                count_24h += 1
            if diff_hours <= 24 * 7:
                count_7d += 1

        avg_daily = round(count_30d / 30.0, 1)

        embed = discord.Embed(title=f"アクティブ頻度 - {target.display_name}", color=0x3498db)
        embed.set_thumbnail(url=target.display_avatar.url)
        embed.add_field(name="直近24時間", value=f"{count_24h} 回", inline=True)
        embed.add_field(name="直近7日間", value=f"{count_7d} 回", inline=True)
        embed.add_field(name="直近30日間", value=f"{count_30d} 回", inline=True)
        embed.add_field(name="1日平均 (30日換算)", value=f"約 {avg_daily} 回/日", inline=False)
        embed.set_footer(text="Survival Surveillance System")

        await interaction.response.send_message(embed=embed)

    @fujo_group.command(name="ranking", description="サーバー内の生存者・化石ランキングを表示します")
    @app_commands.choices(mode=[
        app_commands.Choice(name="アクティブ順 (過去30日の検出数)", value="active"),
        app_commands.Choice(name="化石順 (放置時間が長い順)", value="fossil")
    ])
    async def ranking(self, interaction: discord.Interaction, mode: str):
        users_res = self.supabase.table("fujo_users").select("user_id").execute()
        registered_ids = [r["user_id"] for r in users_res.data]

        if not registered_ids:
            embed = self.create_simple_embed("エラー", "登録ユーザーが存在しません。", 0x95a5a6)
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        now = datetime.now(timezone.utc)

        if mode == "active":
            since_30d = (now - timedelta(days=30)).isoformat()
            act_res = self.supabase.table("fujo_activities") \
                .select("user_id") \
                .gte("detected_at", since_30d) \
                .execute()

            counts = {}
            for row in act_res.data:
                uid = row["user_id"]
                counts[uid] = counts.get(uid, 0) + 1

            sorted_list = sorted(counts.items(), key=lambda x: x[1], reverse=True)[:5]

            embed = discord.Embed(title="アクティブ率 ランキング TOP5", color=0x2ecc71)
            description = ""
            for idx, (uid, count) in enumerate(sorted_list, 1):
                user = self.bot.get_user(uid)
                name = user.display_name if user else f"User({uid})"
                description += f"{idx}. **{name}**: {count} 回アクティブ\n"

            embed.description = description if description else "過去30日間のアクティブデータがありません。"

        else:
            latest_list = []
            for uid in registered_ids:
                res = self.supabase.table("fujo_activities") \
                    .select("detected_at") \
                    .eq("user_id", uid) \
                    .order("detected_at", desc=True) \
                    .limit(1) \
                    .execute()
                if res.data:
                    dt = datetime.fromisoformat(res.data[0]["detected_at"].replace("Z", "+00:00"))
                    latest_list.append((uid, dt))

            sorted_list = sorted(latest_list, key=lambda x: x[1])[:5]

            embed = discord.Embed(title="化石化 ランキング TOP5 (生存放置順)", color=0x34495e)
            description = ""
            for idx, (uid, dt) in enumerate(sorted_list, 1):
                user = self.bot.get_user(uid)
                name = user.display_name if user else f"User({uid})"
                ts = int(dt.timestamp())
                description += f"{idx}. **{name}**: 最終検知 <t:{ts}:R>\n"

            embed.description = description if description else "データが存在しません。"

        embed.set_footer(text="Survival Surveillance System")
        await interaction.response.send_message(embed=embed)

    @fujo_group.command(name="freeze", description="修羅場・旅行用に1日分のストリーク保護を申請します")
    async def freeze(self, interaction: discord.Interaction):
        user_id = interaction.user.id
        if not self.is_registered(user_id):
            embed = self.create_simple_embed("エラー", "先に /fujo register で追跡登録を行ってください。", 0x95a5a6)
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        self.supabase.table("fujo_users").update({"is_frozen": True}).eq("user_id", user_id).execute()
        embed = self.create_simple_embed(
            "ストリークフリーズ発動",
            "本日の失踪許可が適用されました。明日アクティブが途絶過しても連続生存記録はリセットされません。",
            0x3498db
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # --- パニック機能サブコマンド ---

    @panic_group.command(name="set", description="生存反応が途絶えた際の自動警報・遺言を設定します")
    async def panic_set(self, interaction: discord.Interaction, days: int, message: str):
        if days < 1:
            embed = self.create_simple_embed("エラー", "警報日数は1日以上に設定してください。", 0xe74c3c)
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        user_id = interaction.user.id
        if not self.is_registered(user_id):
            embed = self.create_simple_embed("エラー", "先に /fujo register で追跡登録を行ってください。", 0x95a5a6)
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        self.supabase.table("fujo_users").update({
            "panic_days": days,
            "panic_message": message,
            "panic_channel_id": interaction.channel_id,
            "last_panic_at": None
        }).eq("user_id", user_id).execute()

        embed = self.create_simple_embed(
            "失踪警報・遺言設定完了",
            f"{days} 日間アクティブが途絶えた場合、このチャンネルに遺言メッセージを自動発信します。\n\n**設定内容:**\n> {message}",
            0xf1c40f
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @panic_group.command(name="disable", description="失踪警報の設定を解除します")
    async def panic_disable(self, interaction: discord.Interaction):
        user_id = interaction.user.id
        self.supabase.table("fujo_users").update({
            "panic_days": None,
            "panic_message": None,
            "panic_channel_id": None,
            "last_panic_at": None
        }).eq("user_id", user_id).execute()

        embed = self.create_simple_embed("警報解除", "失踪警報の設定を解除しました。", 0x95a5a6)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # --- バックグラウンドタスク ---

    @tasks.loop(minutes=30)
    async def check_panic_alerts(self):
        users_res = self.supabase.table("fujo_users") \
            .select("user_id, panic_days, panic_message, panic_channel_id, last_panic_at") \
            .not_.is_("panic_days", "null") \
            .execute()

        now = datetime.now(timezone.utc)

        for u in users_res.data:
            uid = u["user_id"]
            p_days = u["panic_days"]
            p_msg = u["panic_message"]
            ch_id = u["panic_channel_id"]
            last_panic_at_str = u["last_panic_at"]

            act_res = self.supabase.table("fujo_activities") \
                .select("detected_at") \
                .eq("user_id", uid) \
                .order("detected_at", desc=True) \
                .limit(1) \
                .execute()

            if not act_res.data:
                continue

            last_act_dt = datetime.fromisoformat(act_res.data[0]["detected_at"].replace("Z", "+00:00"))
            hours_silent = (now - last_act_dt).total_seconds() / 3600.0

            if hours_silent >= (p_days * 24):
                should_alert = False
                if not last_panic_at_str:
                    should_alert = True
                else:
                    last_panic_dt = datetime.fromisoformat(last_panic_at_str.replace("Z", "+00:00"))
                    if last_panic_dt < last_act_dt:
                        should_alert = True

                if should_alert:
                    channel = self.bot.get_channel(ch_id)
                    if channel:
                        user = self.bot.get_user(uid)
                        user_mention = user.mention if user else f"ID:{uid}"

                        embed = discord.Embed(
                            title="生存警告: 自動失踪発報",
                            description=f"{user_mention} のアクティブ反応が {p_days} 日以上途絶えました。",
                            color=0xc0392b
                        )
                        embed.add_field(name="遺言メッセージ", value=f"> {p_msg}", inline=False)
                        embed.set_footer(text="Survival Surveillance System - Emergency Alert")

                        await channel.send(content=user_mention, embed=embed)

                        self.supabase.table("fujo_users").update({
                            "last_panic_at": now.isoformat()
                        }).eq("user_id", uid).execute()

    @tasks.loop(hours=1)
    async def check_duo_pester(self):
        users_res = self.supabase.table("fujo_users").select("user_id, last_pester_level, panic_channel_id").execute()
        now = datetime.now(timezone.utc)

        for u in users_res.data:
            uid = u["user_id"]
            last_lvl = u["last_pester_level"]
            ch_id = u["panic_channel_id"]

            act_res = self.supabase.table("fujo_activities") \
                .select("detected_at") \
                .eq("user_id", uid) \
                .order("detected_at", desc=True) \
                .limit(1) \
                .execute()

            if not act_res.data:
                continue

            last_act_dt = datetime.fromisoformat(act_res.data[0]["detected_at"].replace("Z", "+00:00"))
            hours = (now - last_act_dt).total_seconds() / 3600.0

            target_lvl = 0
            pester_msg = ""
            color = 0xf1c40f

            if hours >= 72:
                target_lvl = 3
                pester_msg = "あなたの存在がログから消えかけています。今すぐ何か発言してください。"
                color = 0x9b59b6
            elif hours >= 48:
                target_lvl = 2
                pester_msg = "連続生存記録が破棄されますよ。生存確認を行ってください。"
                color = 0xe67e22
            elif hours >= 24:
                target_lvl = 1
                pester_msg = "今日まだ生存が確認できていません。寂しいです。"
                color = 0xf1c40f

            if target_lvl > last_lvl:
                user = self.bot.get_user(uid)
                if user:
                    embed = discord.Embed(
                        title="生存督促通知",
                        description=f"{user.mention}\n{pester_msg}",
                        color=color
                    )
                    embed.set_footer(text="Surveillance System - Duo Protocol")

                    try:
                        await user.send(embed=embed)
                    except discord.Forbidden:
                        if ch_id:
                            channel = self.bot.get_channel(ch_id)
                            if channel:
                                await channel.send(content=user.mention, embed=embed)

                self.supabase.table("fujo_users").update({"last_pester_level": target_lvl}).eq("user_id", uid).execute()


async def setup(bot: commands.Bot):
    await bot.add_cog(FujoSurvival(bot))
