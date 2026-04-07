import discord
from discord import app_commands
from discord.ext import commands
from supabase import create_client, Client
import datetime

# Supabaseの設定
SUPABASE_URL = "YOUR_SUPABASE_URL"
SUPABASE_KEY = "YOUR_SUPABASE_ANON_KEY"
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

class React(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # 便乗リアクションをしたい特定の絵文字だけここに残す（任意）
        self.thinking_emojis = ['🤔', '🧐']
        self.success_emoji = "<:success:1490985168100659322>"

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        """全てのリアクションを検知してDBに保存"""
        # ボット自身のリアクションはカウントしない
        if payload.user_id == self.bot.user.id:
            return

        emoji_str = str(payload.emoji)
        
        try:
            # メッセージ情報を取得
            channel = self.bot.get_channel(payload.channel_id) or await self.bot.fetch_channel(payload.channel_id)
            message = await channel.fetch_message(payload.message_id)

            # Supabaseに保存（全ての絵文字を対象）
            data = {
                "guild_id": payload.guild_id,
                "channel_id": payload.channel_id,
                "message_id": payload.message_id,
                "user_id": payload.user_id,    # 押した人
                "author_id": message.author.id, # もらった人
                "emoji": emoji_str
            }
            supabase.table("reaction_logs").insert(data).execute()
            
            # 特定の絵文字（Thinkingなど）にはボットも便乗する
            if emoji_str in self.thinking_emojis:
                await message.add_reaction(emoji_str)

        except Exception as e:
            print(f"Error saving reaction: {e}")

    @app_commands.command(name="ranking", description="リアクション受領数ランキングを表示します")
    @app_commands.choices(type=[
        app_commands.Choice(name="サーバー別", value="guild"),
        app_commands.Choice(name="チャンネル別", value="channel"),
        app_commands.Choice(name="総合", value="all"),
    ])
    async def ranking(self, interaction: discord.Interaction, type: str):
        """ランキング表示コマンド"""
        await interaction.response.defer()

        # 全てのリアクションログを取得
        query = supabase.table("reaction_logs").select("author_id")

        if type == "guild":
            query = query.eq("guild_id", interaction.guild_id)
            type_label = "サーバー別"
        elif type == "channel":
            query = query.eq("channel_id", interaction.channel_id)
            type_label = "チャンネル別"
        else:
            type_label = "総合"

        response = query.execute()
        logs = response.data

        if not logs:
            await interaction.followup.send("データが見つかりませんでした。")
            return

        # 集計
        stats = {}
        for log in logs:
            aid = log['author_id']
            stats[aid] = stats.get(aid, 0) + 1

        # ソート（上位10名）
        sorted_stats = sorted(stats.items(), key=lambda x: x[1], reverse=True)[:10]

        description = ""
        for i, (user_id, count) in enumerate(sorted_stats, 1):
            description += f"{i}位: <@{user_id}> - **{count}** pts\n"

        embed = discord.Embed(
            title=f"リアクション受領ランキング（{type_label}）",
            description=description,
            color=0xFFFFFF,
            timestamp=datetime.datetime.now()
        )

        await interaction.followup.send(
            content=f"{self.success_emoji} {interaction.user.display_name}が{type_label}ランキングを表示しました",
            embed=embed
        )

async def setup(bot: commands.Bot):
    await bot.add_cog(React(bot))
