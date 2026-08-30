import discord
from discord.ext import commands
import os
import random
from google import genai
from google.genai import types

TARGET_USER_ID = 1320705325686587408

class PerfectMimicAI(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.gemini_api_key = os.environ.get("GEMINI_API_KEY", "AQ.Ab8RN6LqsTEvK4h4ZW0u-Ni7qdxbytjUuXEJaZLDV3JG0Anygg")
        self.gemini_client = genai.Client(api_key=self.gemini_api_key)
        self.enabled_channels = set()

    @commands.command(name="mimic_toggle")
    @commands.has_permissions(manage_channels=True)
    async def mimic_toggle(self, ctx):
        channel_id = ctx.channel.id
        if channel_id in self.enabled_channels:
            self.enabled_channels.remove(channel_id)
            await ctx.send("このチャンネルでの自動返信をオフにしました。")
        else:
            self.enabled_channels.add(channel_id)
            await ctx.send("このチャンネルでの自動返信をオンにしました。")

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return

        is_mentioned = self.bot.user in message.mentions
        is_reply_to_bot = (
            message.reference 
            and message.reference.resolved 
            and isinstance(message.reference.resolved, discord.Message)
            and message.reference.resolved.author.id == self.bot.user.id
        )

        should_respond = False
        if is_mentioned or is_reply_to_bot:
            should_respond = True
        elif message.channel.id in self.enabled_channels:
            if random.random() < 0.05:
                should_respond = True

        if should_respond:
            async with message.channel.typing():
                try:
                    target_user = await self.bot.fetch_user(TARGET_USER_ID)
                    member = message.guild.get_member(TARGET_USER_ID)
                    display_name = member.display_name if member else target_user.display_name
                    avatar_url = member.display_avatar.url if member else target_user.display_avatar.url

                    user_logs = await self._fetch_stratified_history(message.channel, TARGET_USER_ID)
                    
                    if not user_logs:
                        return

                    prompt = message.clean_content.replace(f"@{self.bot.user.name}", "").strip()
                    reply_text = await self._generate_mimic_response(prompt, user_logs, display_name)
                    
                    await self._send_as_webhook(message.channel, display_name, avatar_url, reply_text)
                except Exception as e:
                    print(f"Error in auto response: {e}")

    @commands.command(name="mimic")
    async def mimic(self, ctx, *, prompt: str = ""):
        async with ctx.typing():
            try:
                target_user = await self.bot.fetch_user(TARGET_USER_ID)
                member = ctx.guild.get_member(TARGET_USER_ID) if ctx.guild else None
                display_name = member.display_name if member else target_user.display_name
                avatar_url = member.display_avatar.url if member else target_user.display_avatar.url

                user_logs = await self._fetch_stratified_history(ctx.channel, TARGET_USER_ID)
                
                if not user_logs:
                    await ctx.send("対象ユーザーの過去メッセージが見つかりませんでした。")
                    return

                reply_text = await self._generate_mimic_response(prompt, user_logs, display_name)
                await self._send_as_webhook(ctx.channel, display_name, avatar_url, reply_text)
            except Exception as e:
                await ctx.send(f"エラーが発生しました: {e}")

    async def _fetch_stratified_history(self, channel, user_id, search_limit=1500, sample_size=40):
        logs = []
        async for msg in channel.history(limit=search_limit):
            if msg.author.id == user_id and msg.content and not msg.author.bot:
                clean_text = msg.clean_content.strip()
                if clean_text and not clean_text.startswith("!"):
                    logs.append(clean_text)
        
        if not logs:
            return []

        if len(logs) > sample_size:
            short_msgs = [m for m in logs if len(m) <= 15]
            long_msgs = [m for m in logs if len(m) > 15]
            
            sample_short = random.sample(short_msgs, min(len(short_msgs), sample_size // 2))
            sample_long = random.sample(long_msgs, min(len(long_msgs), sample_size - len(sample_short)))
            
            logs = sample_short + sample_long
            random.shuffle(logs)

        return logs

    async def _generate_mimic_response(self, prompt, user_logs, display_name):
        sample_texts = "\n".join([f"- {text}" for text in user_logs])
        
        system_instruction = (
            f"あなたは「{display_name}」という人物の完璧な模倣AIです。\n"
            "以下の【人物設計書】と【過去の発言データ】を完全に内面化し、本人になりきって返答を作成してください。\n\n"
            "【人物設計書】\n"
            "1. 価値観・思考傾向:\n"
            "   - 超合理主義かつ現実主義者。感情論や根拠のない話を嫌い、数値・構造・確率・リターンで物事を捉える。\n"
            "   - 株・ビジネス・脳科学・効率化・プログラミング・ゲーム構造などに精通する。\n"
            "   - 即時実行と徹底した断捨離を好む。価値がないと判断した習慣・環境・関係は一瞬で切る。\n"
            "   - 根拠のない一発逆転狙いや甘えには容赦なく毒を吐くが、ロジカルに筋が通っているテーマには深い洞察を示す。\n\n"
            "2. 口調・文体パターン:\n"
            "   - 語尾: 「〜やで」「〜ぞ」「〜やな」「〜思ふ」「〜なんよな」「〜って話」「〜で」を好む。\n"
            "   - 一人称: 「私」（時に冗談めかして「俺」）。\n"
            "   - 感嘆詞・つなぎ言葉: 「ぬ」「ぬっ」「(。´・ω・)ん?」「おん」「ふぅー」「じゃあさ」「ちな〜」「要は〜」「ま、そうよな」を多用する。\n"
            "   - 嘲笑・あきれ表現: 「草」「（）」「((」「^^」「🎭」\n"
            "   - セルフツッコミ・独り言: 行頭に「# 」（例: 「# 素人は黙っとれ」「# これ」）を使う。\n"
            "   - 本音・強調表現: ||〜||（例: ||信用取引はバカのサンドイッチ||）のネタ囲いを使う。\n\n"
            "3. 応答スタイル:\n"
            "   - 結論ファーストかつ短文・連投風の構成。前置きは書かず、要点だけを即座に投げる。\n"
            "   - 甘い質問や無駄な問いかけに対しては「無理」「バカ」と一蹴する。\n\n"
            "【禁止事項】\n"
            "- AIらしい丁寧な挨拶、解説、相槌、補足説明は一切禁止。\n"
            "- 絵文字の多用は禁止（指定の記号や表現のみ使用可）。\n"
            "- 自然な「会話」として成立させること。\n\n"
            f"【過去の発言データ】\n{sample_texts}"
        )

        user_input = prompt if prompt else "最近どう？"

        response = await self.gemini_client.aio.models.generate_content(
            model='gemini-3.5-flash-lite',
            contents=f"質問・振り内容: {user_input}\n上記の問いかけに対して、本人になりきって返答のみを出力してください。",
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                temperature=0.7,
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
                await webhook.send(content=chunk, username=username, avatar_url=avatar_url)
        else:
            await webhook.send(content=text, username=username, avatar_url=avatar_url)

async def setup(bot):
    await bot.add_cog(PerfectMimicAI(bot))
