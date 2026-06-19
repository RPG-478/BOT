import discord
from discord.ext import commands
import datetime
from groq import AsyncGroq
import os

class MentalAnalysis(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.client = AsyncGroq(api_key=os.environ.get("GROQ_API_KEY"))
        self.model = "llama3-70b-8192"

    @commands.command()
    async def mental(self, ctx, member: discord.Member = None):
        target = member or ctx.author
        await ctx.send("分析を開始します。メッセージ履歴の取得に時間がかかる場合があります。")

        two_weeks_ago = discord.utils.utcnow() - datetime.timedelta(days=14)
        messages_text = []

        async for message in ctx.channel.history(limit=1000, after=two_weeks_ago):
            if message.author == target and message.content:
                messages_text.append(message.content)

        if not messages_text:
            await ctx.send("分析対象のメッセージが見つかりませんでした。")
            return

        combined_messages = "\n".join(messages_text)
        
        prompt = (
            f"以下のテキストは、あるユーザーの過去2週間のチャット発言履歴です。\n"
            f"これらの発言から、対象者の精神状態、性格傾向、関心事などを分析し、要約してください。\n\n"
            f"発言履歴:\n{combined_messages}"
        )

        try:
            chat_completion = await self.client.chat.completions.create(
                messages=[
                    {
                        "role": "user",
                        "content": prompt,
                    }
                ],
                model=self.model,
            )
            analysis_result = chat_completion.choices[0].message.content
            
            if len(analysis_result) > 2000:
                for i in range(0, len(analysis_result), 2000):
                    await ctx.send(analysis_result[i:i+2000])
            else:
                await ctx.send(analysis_result)

        except Exception as e:
            await ctx.send(f"エラーが発生しました: {e}")

async def setup(bot):
    await bot.add_cog(MentalAnalysis(bot))
