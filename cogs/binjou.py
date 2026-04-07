import discord
from discord.ext import commands

class Thinking(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # 反応する絵文字をリスト化しておくと後で増やしやすいです
        self.target_emojis = ['🤔', '🧐', '👈']

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        """
        リアクションが追加された際に実行されるリスナー
        """
        
        # ボット自身のリアクションには反応しない（無限ループ防止）
        if payload.user_id == self.bot.user.id:
            return

        # 追加された絵文字が対象リストに含まれているか確認
        emoji_str = str(payload.emoji)
        if emoji_str in self.target_emojis:
            try:
                # チャンネルオブジェクトの取得
                channel = self.bot.get_channel(payload.channel_id)
                if not channel:
                    channel = await self.bot.fetch_channel(payload.channel_id)

                # メッセージオブジェクトの取得
                message = await channel.fetch_message(payload.message_id)

                # すでにボットがリアクション済みかチェック（二重反応防止）
                # 必要なければこのifブロックは削ってもOKです
                existing_reaction = discord.utils.get(message.reactions, emoji=emoji_str)
                if existing_reaction and existing_reaction.me:
                    return

                # ボットも同じ絵文字でリアクション
                await message.add_reaction(emoji_str)

            except discord.Forbidden:
                # ボットにリアクション権限がない場合
                pass
            except discord.NotFound:
                # メッセージが既に削除されていた場合
                pass
            except Exception as e:
                print(f"Error in Thinking Cog: {e}")

async def setup(bot):
    await bot.add_cog(Thinking(bot))