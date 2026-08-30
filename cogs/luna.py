import discord
from discord.ext import commands
import os
import random
from google import genai
from google.genai import types

TARGET_USER_ID = 1320705325686587408

class MimicAI(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.gemini_api_key = os.environ.get("GEMINI_API_KEY", "AQ.Ab8RN6LqsTEvK4h4ZW0u-Ni7qdxbytjUuXEJaZLDV3JG0Anygg")
        self.gemini_client = genai.Client(api_key=self.gemini_api_key)

    @commands.command(name="mimic")
    async def mimic(self, ctx, *, prompt: str = ""):
        async with ctx.typing():
            try:
                target_user = await self.bot.fetch_user(TARGET_USER_ID)
                member = ctx.guild.get_member(TARGET_USER_ID) if ctx.guild else None
                display_name = member.display_name if member else target_user.display_name
                avatar_url = member.display_avatar.url if member else target_user.display_avatar.url

                user_logs = await self._fetch_user_history(ctx.channel, TARGET_USER_ID)
                
                if not user_logs:
                    await ctx.send("対象ユーザーの過去メッセージが見つかりませんでした。")
                    return

                reply_text = await self._generate_mimic_response(prompt, user_logs, display_name)
                await self._send_as_webhook(ctx.channel, display_name, avatar_url, reply_text)
            except Exception as e:
                await ctx.send(f"エラーが発生しました: {e}")

    async def _fetch_user_history(self, channel, user_id, search_limit=1000, sample_size=30):
        logs = []
        async for msg in channel.history(limit=search_limit):
            if msg.author.id == user_id and msg.content and not msg.author.bot:
                clean_text = msg.clean_content.strip()
                if clean_text and not clean_text.startswith("!"):
                    logs.append(clean_text)
        
        if len(logs) > sample_size:
            logs = random.sample(logs, sample_size)
            
        return logs

    async def _generate_mimic_response(self, prompt, user_logs, display_name):
        sample_texts = "\n".join([f"- {text}" for text in user_logs])
        
        system_instruction = (
            f"あなたはユーザー「{display_name}」本人として振る舞ってください。\n"
            "以下の【発言スタイルサンプル】から、その人物の口調、文体、語尾の癖、記号・絵文字の使い方、ひらがな・漢字の比率、文章全体のトーン（テンションや雰囲気）を分析・学習してください。\n\n"
            "【厳格な注意点】\n"
            "- サンプルに含まれる特定の話題、固有名詞、過去の状況や単語に直接引っ張られないでください。\n"
            "- ユーザーから入力された【問いかけ・指示】に対する返答として、分析した「口調・文体スタイル」だけを適用して自然に回答してください。\n"
            "- メタ的な解説、前置き、補足文言は一切出力せず、本文のみを回答してください。\n\n"
            f"【発言スタイルサンプル】\n{sample_texts}"
        )

        user_input = prompt if prompt else "最近どう？"

        response = await self.gemini_client.aio.models.generate_content(
            model='gemini-3.5-flash-lite',
            contents=user_input,
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
            )
        )
        return response.text

    async def _send_as_webhook(self, channel, username, avatar_url, text):
        webhooks = await channel.webhooks()
        webhook = discord.utils.get(webhooks, name="MimicWebhook")
        if not webhook:
            webhook = await channel.create_webhook(name="MimicWebhook")

        if len(text) > 2000:
            chunks = [text[i:i+2000] for i in range(0, len(text), 2000)]
            for chunk in chunks:
                await webhook.send(
                    content=chunk,
                    username=username,
                    avatar_url=avatar_url
                )
        else:
            await webhook.send(
                content=text,
                username=username,
                avatar_url=avatar_url
            )

async def setup(bot):
    await bot.add_cog(MimicAI(bot))
