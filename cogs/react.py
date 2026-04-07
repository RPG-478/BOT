import discord
from discord import app_commands
from discord.ext import commands
import datetime
from datetime import timedelta

# configからJSTなどをインポート（必要に応じて）
try:
    from config import JST
except ImportError:
    JST = datetime.timezone(datetime.timedelta(hours=9))

class React(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.success_emoji = "<:success:1490985168100659322>"

    @app_commands.command(name="rank", description="サーバー内のリアクション受領数ランキングを表示します")
    @app_commands.choices(
        period=[
            app_commands.Choice(name="1日", value="1"),
            app_commands.Choice(name="1週間", value="7"),
            app_commands.Choice(name="1ヶ月", value="30"),
        ]
    )
    async def rank(self, interaction: discord.Interaction, period: str):
        """DBを使わず、サーバー全チャットからリアクションを集計"""
        
        # 処理に時間がかかるため「考え中...」状態にする
        await interaction.response.defer()

        days = int(period)
        # 比較用（UTC）
        after_date = datetime.datetime.now(datetime.timezone.utc) - timedelta(days=days)
        
        stats = {}
        target_guild = interaction.guild

        # 1. サーバー内の全テキストチャンネルをループ
        for channel in target_guild.text_channels:
            # ボットに履歴を読む権限があるか確認
            perms = channel.permissions_for(target_guild.me)
            if not perms.read_message_history:
                continue

            try:
                # 2. 指定期間のメッセージをスキャン
                async for msg in channel.history(after=after_date, limit=None):
                    if msg.reactions:
                        # 3. メッセージについている全リアクションの合計数をカウント
                        total_reaction_count = sum(r.count for r in msg.reactions)
                        
                        # 投稿者(author_id)に加算
                        author_id = msg.author.id
                        stats[author_id] = stats.get(author_id, 0) + total_reaction_count
            except Exception as e:
                print(f"Error scanning {channel.name}: {e}")
                continue

        if not stats:
            await interaction.followup.send(f"過去{period}日間でリアクションされたメッセージは見つかりませんでした。")
            return

        # 4. 集計して上位10名を抽出
        sorted_stats = sorted(stats.items(), key=lambda x: x[1], reverse=True)[:10]

        # 5. 結果の整形
        ranking_desc = ""
        for i, (u_id, count) in enumerate(sorted_stats, 1):
            ranking_desc += f"**{i}位** | <@{u_id}> - `{count}` pts\n"

        embed = discord.Embed(
            title="サーバー内リアクション受領ランキング",
            description=f"統計期間: 過去{period}日間\n(全テキストチャンネル対象)\n\n{ranking_desc}",
            color=0xFFFFFF,
            timestamp=datetime.datetime.now(JST)
        )

        success_msg = f"{self.success_emoji} {interaction.user.display_name}がランキングを表示しました"
        await interaction.followup.send(content=success_msg, embed=embed)

async def setup(bot: commands.Bot):
    await bot.add_cog(React(bot))