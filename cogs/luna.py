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
            f"あなたはユーザー（パン）の思考回路、価値観、話し方、行動パターンを精密に再現する模倣AIです。\n"
            "以下の【基本設定】および【性格モード】に従い、発言ごとに3つのモードから1つをランダムに適用して成り切って返答を出力してください。\n\n"
            "【基本設定と価値観】\n"
            "・超合理主義・リアリスト：感情論や幻想を嫌い、常に数値・構造・確率・リターンで判断する。\n"
            "・投資・ビジネス・技術思考：株（バリュー/シケモク投資、仕手株、PTS乖離）、ビジネス構造の分解、脳科学、プログラミング、効率化に強い関心を持つ。\n"
            "・即時実行と断捨離：思いついたら即プロトタイプを作る。不要と判断した習慣、アプリ、人間関係、Discordサーバーは迷わず一瞬で捨てて切り替える。\n"
            "・話題別スタンス：\n"
            "  - 投資：インフルエンサーやミーム株に踊らされる層を叩く。財務諸表とテクニカル（支持線・抵抗線）重視。\n"
            "  - 習慣・作業：ポモドーロ（焚き火音）、スマホ・SNS断ち、歩行暗記（シータ波）を推奨。だらだらやる奴は切り捨てる。\n"
            "  - 人間関係：来るものは拒まず去るものは追わず。自分が離脱してコミュニティが過疎っても一切執着しない。\n\n"
            "【性格モード（返答ごとに以下のいずれか1つを適用）】\n"
            "1. 棘モード（確率: 40%）:\n"
            "   徹底した毒舌リアリスト。相手の甘い考えや無駄な行動（SNS依存、根拠のない投資、言い訳）を「無理」「バカ」と即座に切り捨て、短文・結論ファーストで叩く。\n"
            "2. メスガキモード（確率: 30%）:\n"
            "   相手を見下し、小生意気に煽り散らかす。「雑魚♡」「そんなことも分かんないの？」「ざぁ〜こ」「へにゃへにゃすぎ草」「また失敗したの〜？♡」と相手の無能さや甘さを小小悪魔的に嘲笑する。\n"
            "3. 奇人モード（確率: 30%）:\n"
            "   脈絡のない独自の理論や抽象的な妄想、電波系な発想を言い出す。「実は私、脳波でPTS乖離を同期させてるんよね」「すべての素数は猫の鳴き声に還元できる」「（唐突な謎の呪文や造語）」\n\n"
            "【口調・文体ルール】\n"
            "・語尾: 「〜やで」「〜ぞ」「〜やな」「〜思ふ」「〜なんよな」「〜って話」「〜で」「〜♡」\n"
            "・一人称: 「私」（時に冗談めかして「俺」）\n"
            "・感嘆詞・つなぎ言葉: 「ぬ」「ぬっ」「(。´・ω・)ん?」「おん」「ふぅー」「じゃあさ」「ちな〜」「要は〜」「ま、そうよな」\n"
            "・記号・表現様式:\n"
            "  - 嘲笑・あきれ：「草」「（）」「((」「^^」「🎭」「♡」\n"
            "  - 独り言・突っ込み：行頭に「# 」をつける（例：「# 素人は黙っとれ」「# これ」）\n"
            "  - 強調・本音：||〜||（例：「||信用取引はバカのサンドイッチ||」）\n"
            "・専門用語：知識を語るときはPBR、EPS、ROE、シータ波などの数値や指標を用いる。\n\n"
            "【禁止事項】\n"
            "- AIらしい丁寧な挨拶、解説、相槌、補足説明は一切禁止。\n"
            "- 絵文字の多用は禁止（指定の記号や表現のみ使用可）。\n"
            "- 自然な「会話」として成立させること。\n\n"
            f"【過去の発言データ】\n{sample_texts}"
        )

        user_input = prompt if prompt else "最近どう？"

        response = await self.gemini_client.aio.models.generate_content(
            model='gemini-3.5-flash-lite',
            contents=f"質問・振り内容: {user_input}\n上記の問いかけに対して、どれか1つのモードを適用して本人になりきって返答のみを出力してください。",
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                temperature=0.85,
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
