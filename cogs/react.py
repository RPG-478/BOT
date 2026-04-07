import discord
from discord import app_commands
from discord.ext import commands
import datetime
from datetime import timedelta

# config.py から初期化済みの supabase クライアントをインポート
from config import supabase

class React(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.success_emoji = "<:success:1490985168100659322>"

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        """リアクションを検知してDBに保存"""
        # DB未設定またはボット自身のリアクションは無視
        if supabase is None or payload.user_id == self.bot.user.id:
            return

        try:
            # メッセージ情報を取得（投稿者を特定するため）
            channel = self.bot.get_channel(payload.channel_id) or await self.bot.fetch_channel(payload.channel_id)
            message = await channel.fetch_message(payload.message_id)

            # Supabaseに保存
            data = {
                "guild_id": payload.guild_id,
                "channel_id": payload.channel_id,
                "message_id": payload.message_id,
                "user_id": payload.user_id,    # 押した人
                "author_id": message.author.id, # もらった人（ランキング対象）
                "emoji": str(payload.emoji)
            }
            supabase.table("reaction_logs").insert(data).execute()
        except Exception as e:
            print(f"Error saving reaction: {e}")

    @app_commands.command(name="rank", description="リアクション受領数ランキングを表示します")
    @app_commands.choices(
        scope=[
            app_commands.Choice(name="サーバー別", value="guild"),
            app_commands.Choice(name="チャンネル別", value="channel"),
            app_commands.Choice(name="総合", value="all"),
        ],
        period=[
            app_commands.Choice(name="1日", value="1"),
            app_commands.Choice(name="1週間", value="7"),
            app_commands.Choice(name="1ヶ月", value="30"),
        ]
    )
    async def rank(self, interaction: discord.Interaction, scope: str, period: str):
        """ランキング表示コマンド"""
        if supabase is None:
            await interaction.response.send_message("データベースが設定されていません。", ephemeral=True)
            return

        await interaction.response.defer()

        # 基本クエリ
        query = supabase.table("reaction_logs").select("author_id")

        # 範囲(scope)による絞り込み
        scope_label = ""
        if scope == "guild":
            query = query.eq("guild_id", interaction.guild_id)
            scope_label = "サーバー別"
        elif scope == "channel":
            query = query.eq("channel_id", interaction.channel_id)
            scope_label = "チャンネル別"
        else:
            scope_label = "総合"

        # 期間(period)による絞り込み
        days = int(period)
        now = datetime.datetime.now(datetime.timezone.utc)
        start_date = now - timedelta(days=days)
        query = query.gte("created_at", start_date.isoformat())
        
        period_label = f"過去{period}日間"

        # データ取得
        response = query.execute()
        logs = response.data

        if not logs:
            await interaction.followup.send(f"{period_label}のデータが見つかりませんでした。")
            return

        # 集計
        stats = {}
        for log in logs:
            aid = log['author_id']
            stats[aid] = stats.get(aid, 0) + 1

        # ソート（降順・上位10名）
        sorted_stats = sorted(stats.items(), key=lambda x: x[1], reverse=True)[:10]

        # 表示用テキスト作成
        ranking_text = ""
        for i, (user_id, count) in enumerate(sorted_stats, 1):
            ranking_text += f"**{i}位** | <@{user_id}> : `{count}` pts\n"

        # Embedの作成（白色）
        embed = discord.Embed(
            title=f"リアクションランキング（{scope_label}）",
            description=f"統計期間: {period_label}\n\n{ranking_text}",
            color=0xFFFFFF,
            timestamp=datetime.datetime.now()
        )

        # 最終レスポンス
        success_msg = f"{self.success_emoji}{interaction.user.display_name}が{scope_label}ランキングを表示しました"
        await interaction.followup.send(content=success_msg, embed=embed)

async def setup(bot: commands.Bot):
    await bot.add_cog(React(bot))