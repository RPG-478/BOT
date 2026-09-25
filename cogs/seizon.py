import os
from datetime import datetime, timezone, timedelta
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

    def cog_unload(self):
        self.check_panic_alerts.cancel()

    fujo_group = app_commands.Group(name="fujo", description="生存確認機能のコマンド一覧")
    panic_group = app_commands.Group(name="panic", description="失踪警報・遺言設定のコマンド一覧", parent=fujo_group)

    # --- ヘルパー関数 ---

    def is_registered(self, user_id: int) -> bool:
        response = self.supabase.table("fujo_users").select("user_id").eq("user_id", user_id).execute()
        return len(response.data) > 0

    def record_activity(self, user_id: int, signal_type: str, status: str):
        if not self.is_registered(user_id):
            return
        now_str = datetime.now(timezone.utc).isoformat()
        self.supabase.table("fujo_activities").insert({
            "user_id": user_id,
            "detected_at": now_str,
            "signal_type": signal_type,
            "status": status
        }).execute()

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
            # JST(UTC+9) 換算で深夜23時〜5時のアクティブ判定
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
            await interaction.response.send_message("生存確認の追跡登録を解除しました。", ephemeral=True)
        else:
            self.supabase.table("fujo_users").insert({"user_id": user_id}).execute()
            await interaction.response.send_message("生存確認の追跡を登録しました。", ephemeral=True)

    @fujo_group.command(name="status", description="指定ユーザーの生存ステータスを確認します")
    async def status(self, interaction: discord.Interaction, target: discord.User):
        if not self.is_registered(target.id):
            await interaction.response.send_message(f"{target.mention} は追跡登録されていません。", ephemeral=True)
            return

        res = self.supabase.table("fujo_activities") \
            .select("detected_at, signal_type, status") \
            .eq("user_id", target.id) \
            .order("detected_at", desc=True) \
            .limit(1) \
            .execute()

        if not res.data:
            await interaction.response.send_message(f"{target.mention} のアクティブ記録がまだ存在しません。", ephemeral=True)
            return

        latest = res.data[0]
        dt = datetime.fromisoformat(latest["detected_at"].replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        unix_ts = int(dt.timestamp())

        hours_passed = (now - dt).total_seconds() / 3600.0

        # 動的表示設定（カラーと状態判定）
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

        # ゾンビ化率・生存確率の計算（7日間放置でゾンビ化率100%に達する設定）
        zombie_rate = min(100, int((hours_passed / (7 * 24)) * 100))
        survival_rate = 100 - zombie_rate

        # プログレスバー作成
        bar_len = 10
        filled = int(bar_len * (survival_rate / 100.0))
        progress_bar = f"[{'█' * filled}{'░' * (bar_len - filled)}] {survival_rate}%"

        title_name = self.calculate_title(target.id)

        embed = discord.Embed(title=f"生存ステータス - {target.display_name}", color=color)
        embed.set_thumbnail(url=target.display_avatar.url)
        embed.add_field(name="判定レベル", value=status_label, inline=True)
        embed.add_field(name="称号", value=f"【{title_name}】", inline=True)
        embed.add_field(name="最終アクティブ", value=f"<t:{unix_ts}:R>\n(<t:{unix_ts}:F>)", inline=False)
        embed.add_field(name="生存確率ゲージ", value=f"`{progress_bar}`", inline=False)
        embed.add_field(name="ゾンビ化率", value=f"{zombie_rate}%", inline=True)
        embed.add_field(name="検知タイプ", value=latest["signal_type"], inline=True)

        await interaction.response.send_message(embed=embed)

    @fujo_group.command(name="hindo", description="指定ユーザーのアクティブ頻度を確認します")
    async def hindo(self, interaction: discord.Interaction, target: discord.User):
        if not self.is_registered(target.id):
            await interaction.response.send_message(f"{target.mention} は追跡登録されていません。", ephemeral=True)
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
            await interaction.response.send_message(f"{target.mention} の過去30日間の記録はありません。", ephemeral=True)
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
            await interaction.response.send_message("登録ユーザーが存在しません。", ephemeral=True)
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
            await interaction.response.send_message(embed=embed)

        else:  # mode == "fossil"
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
            await interaction.response.send_message(embed=embed)

    # --- パニック機能（遺言警報）サブコマンド ---

    @panic_group.command(name="set", description="生存反応が途絶えた際の自動警報・遺言を設定します")
    async def panic_set(self, interaction: discord.Interaction, days: int, message: str):
        if days < 1:
            await interaction.response.send_message("警報日数は1日以上に設定してください。", ephemeral=True)
            return

        user_id = interaction.user.id
        if not self.is_registered(user_id):
            await interaction.response.send_message("先に /fujo register で追跡登録を行ってください。", ephemeral=True)
            return

        self.supabase.table("fujo_users").update({
            "panic_days": days,
            "panic_message": message,
            "panic_channel_id": interaction.channel_id,
            "last_panic_at": None
        }).eq("user_id", user_id).execute()

        await interaction.response.send_message(
            f"失踪警報を設定しました。\n{days} 日間アクティブが途絶えた場合、このチャンネルに遺言メッセージを発信します。",
            ephemeral=True
        )

    @panic_group.command(name="disable", description="失踪警報の設定を解除します")
    async def panic_disable(self, interaction: discord.Interaction):
        user_id = interaction.user.id
        self.supabase.table("fujo_users").update({
            "panic_days": None,
            "panic_message": None,
            "panic_channel_id": None,
            "last_panic_at": None
        }).eq("user_id", user_id).execute()

        await interaction.response.send_message("失踪警報の設定を解除しました。", ephemeral=True)

    # --- バックグラウンドタスク（遺言の自動検知・送信） ---

    @tasks.loop(minutes=30)
    async def check_panic_alerts(self):
        # 警報設定が有効なユーザーを取得
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

            # 途絶え時間が指定日数を超えているかチェック
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
                        alert_text = (
                            f"【生存警告】\n"
                            f"{user_mention} のアクティブ反応が {p_days} 日以上途絶えました。\n"
                            f"登録された遺言メッセージ:\n> {p_msg}"
                        )
                        await channel.send(alert_text)

                        self.supabase.table("fujo_users").update({
                            "last_panic_at": now.isoformat()
                        }).eq("user_id", uid).execute()


async def setup(bot: commands.Bot):
    await bot.add_cog(FujoSurvival(bot))
