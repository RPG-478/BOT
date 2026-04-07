import discord
from discord import app_commands
from discord.ext import commands
from supabase import create_client, Client
import datetime
from datetime import timedelta

# Supabaseの設定
SUPABASE_URL = "SUPABASE_URL"
SUPABASE_KEY = "SUPABASE_KEY"
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

class React(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.success_emoji = "<:success:1490985168100659322>"

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        """全てのリアクションを検知してDBに保存（便乗なし）"""
        if payload.user_id == self.bot.user.id:
            return

        try:
            channel = self.bot.get_channel(payload.channel_id) or await self.bot.fetch_channel(payload.channel_id)
            message = await channel.fetch_message(payload.message_id)

            data = {
                "guild_id": payload.guild_id,
                "channel_id": payload.channel_id,
                "message_id": payload.message_id,
                "user_id": payload.user_id,
                "author_id": message.author.id,
                "emoji": str(payload.emoji)
            }
            supabase.table("reaction_logs").insert(data).execute()
        except Exception as e:
            print(f"Error saving reaction: {e}")

    @app_commands.command(name="ranking", description="リアクション受領数ランキングを表示します")
    @app_commands.choices(
        type=[
            app_commands.Choice(name="サーバー別", value="guild"),
            app_commands.Choice(name="チャンネル別", value="channel"),
            app_commands.Choice(name="総合", value="all"),
        ],
        period=[
            app_commands.Choice(name="過去24時間", value="day"),
            app_commands.Choice(name="過去1週間", value="week"),
            app_commands.Choice(name="過去1ヶ月", value="month"),
            app_commands.Choice(name="全期間", value="forever"),
        ]
    )
    async def ranking(self, interaction: discord.Interaction, type: str, period: str):
        """ランキング表示コマンド (期間指定対応)"""
        await interaction.response.defer()

        # 基本クエリ
        query = supabase.table("reaction_logs").select("author_id")

        # 範囲フィルタリング (type)
        type_label = ""
        if type == "guild":
            query = query.eq("guild_id", interaction.guild_id)
            type_label = "サーバー別"
        elif type == "channel":
            query = query.eq("channel_id", interaction.channel_id)
            type_label = "チャンネル別"
        else:
            type_label = "総合"

        # 期間フィルタリング (period)
        period_label = ""
        now = datetime.datetime.now(datetime.timezone.utc)
        
        if period == "day":
            target_date = now - timedelta(days=1)
            query = query.gte("created_at", target_date.isoformat())
            period_label = "【過去24時間】"
        elif period == "week":
            target_date = now - timedelta(weeks=1)
            query = query.gte("created_at", target_date.isoformat())
            period_label = "【過去1週間】"
        elif period == "month":
            target_date = now - timedelta(days=30)
            query = query.gte("created_at", target_date.isoformat())
            period_label = "【過去1ヶ月】"
        else:
            period_label = "【全期間】"

        response = query.execute()
        logs = response.data

        if not logs:
            await interaction.followup.send(f"指定された期間（{period_label}）のデータが見つかりませんでした。")
            return

        # 集計
        stats = {}
        for log in logs:
            aid = log['author_id']
            stats[aid] = stats.get(aid, 0) + 1

        # ソート（降順、上位10件）
        sorted_stats = sorted(stats.items(), key=lambda x: x[1], reverse=True)[:10]

        description = ""
        for i, (user_id, count) in enumerate(sorted_stats, 1):
            description += f"**{i}位** | <@{user_id}> - `{count}` pts\n"

        embed = discord.Embed(
            title=f"リアクションランキング {type_label}",
            description=f"{period_label}\n\n{description}",
            color=0xFFFFFF,
            timestamp=datetime.datetime.now()
        )

        await interaction.followup.send(
            content=f"{self.success_emoji} {interaction.user.display_name}が{type_label}ランキングを表示しました",
            embed=embed
        )

async def setup(bot: commands.Bot):
    await bot.add_cog(React(bot))