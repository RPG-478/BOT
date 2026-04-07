import discord
from discord import app_commands
from discord.ext import commands
import datetime
from datetime import timedelta

# config.py から必要な要素をインポート
from config import supabase, JST

class React(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.success_emoji = "<:success:1490985168100659322>"

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        """リアルタイムのリアクションをDBに保存"""
        if supabase is None or payload.user_id == self.bot.user.id:
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
        except Exception:
            pass

    @app_commands.command(name="rank", description="リアクション受領数ランキングを表示します")
    @app_commands.choices(
        scope=[
            app_commands.Choice(name="サーバー別", value="guild"),
            app_commands.Choice(name="チャンネル別", value="channel"),
        ],
        period=[
            app_commands.Choice(name="1日", value="1"),
            app_commands.Choice(name="1週間", value="7"),
            app_commands.Choice(name="1ヶ月", value="30"),
        ]
    )
    async def rank(self, interaction: discord.Interaction, scope: str, period: str):
        """ランキング表示（DBにない場合は直接取得）"""
        await interaction.response.defer()

        days = int(period)
        # 比較用（UTC）
        after_date = datetime.datetime.now(datetime.timezone.utc) - timedelta(days=days)
        
        stats = {}
        scope_label = "サーバー別" if scope == "guild" else "チャンネル別"

        # 1. まずはDBからデータを取得してみる
        if supabase:
            query = supabase.table("reaction_logs").select("author_id")
            if scope == "guild":
                query = query.eq("guild_id", interaction.guild_id)
            else:
                query = query.eq("channel_id", interaction.channel_id)
            
            query = query.gte("created_at", after_date.isoformat())
            res = query.execute()
            
            if res.data:
                for log in res.data:
                    aid = log.get('author_id')
                    stats[aid] = stats.get(aid, 0) + 1

        # 2. DBにデータが少ない、または過去分を補完する場合（直接取得）
        # ※DBのデータが0件の場合のみ実行する安全策
        if not stats:
            target_channels = []
            if scope == "guild":
                target_channels = [c for c in interaction.guild.text_channels 
                                   if c.permissions_for(interaction.guild.me).read_message_history]
            else:
                target_channels = [interaction.channel]

            for ch in target_channels:
                try:
                    async for msg in ch.history(after=after_date, limit=2000): # 負荷軽減のため上限設定
                        if msg.reactions:
                            total_reactions = sum(r.count for r in msg.reactions)
                            stats[msg.author.id] = stats.get(msg.author.id, 0) + total_reactions
                except:
                    continue

        if not stats:
            await interaction.followup.send("期間内にリアクションデータが見つかりませんでした。")
            return

        # ソート
        sorted_stats = sorted(stats.items(), key=lambda x: x[1], reverse=True)[:10]

        # 表示作成
        rank_desc = ""
        for i, (u_id, count) in enumerate(sorted_stats, 1):
            rank_desc += f"**{i}位** | <@{u_id}> - `{count}` pts\n"

        embed = discord.Embed(
            title=f"リアクションランキング ({scope_label})",
            description=f"統計期間: 過去{period}日間\n\n{rank_desc}",
            color=0xFFFFFF,
            timestamp=datetime.datetime.now(JST)
        )

        success_text = f"{self.success_emoji}{interaction.user.display_name}が{scope_label}ランキングを表示しました"
        await interaction.followup.send(content=success_text, embed=embed)

async def setup(bot: commands.Bot):
    await bot.add_cog(React(bot))