import discord
from discord.ext import commands, tasks
import os
import random
from collections import deque
from google import genai
from google.genai import types

TARGET_USER_ID = 1320705325686587408

class PerfectMimicAI(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.gemini_api_key = os.environ.get("GEMINI_API_KEY", "AQ.Ab8RN6LqsTEvK4h4ZW0u-Ni7qdxbytjUuXEJaZLDV3JG0Anygg")
        self.gemini_client = genai.Client(api_key=self.gemini_api_key)
        self.enabled_channels = set()
        self.sent_webhook_message_ids = deque(maxlen=200)
        self.spontaneous_talk.start()

    def cog_unload(self):
        self.spontaneous_talk.cancel()

    @commands.command(name="mimic_toggle")
    @commands.has_permissions(manage_channels=True)
    async def mimic_toggle(self, ctx):
        channel_id = ctx.channel.id
        if channel_id in self.enabled_channels:
            self.enabled_channels.remove(channel_id)
            await ctx.send("このチャンネルでの自動返信・自主発話をオフにしました。")
        else:
            self.enabled_channels.add(channel_id)
            await ctx.send("このチャンネルでの自動返信・自主発話をオンにしました。")

    @tasks.loop(minutes=30)
    async def spontaneous_talk(self):
        if not self.enabled_channels:
            return

        for channel_id in list(self.enabled_channels):
            if random.random() < 0.15:
                channel = self.bot.get_channel(channel_id)
                if not channel:
                    continue

                try:
                    target_user = await self.bot.fetch_user(TARGET_USER_ID)
                    guild = channel.guild
                    member = guild.get_member(TARGET_USER_ID) if guild else None
                    display_name = member.display_name if member else target_user.display_name
                    avatar_url = member.display_avatar.url if member else target_user.display_avatar.url

                    user_logs = await self._fetch_stratified_history(channel, TARGET_USER_ID)
                    if not user_logs:
                        continue

                    reply_text = await self._generate_mimic_response("", user_logs, display_name, is_spontaneous=True)
                    await self._send_as_webhook(channel, display_name, avatar_url, reply_text)
                except Exception as e:
                    print(f"Error in spontaneous talk: {e}")

    @spontaneous_talk.before_loop
    async def before_spontaneous_talk(self):
        await self.bot.wait_until_ready()

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return

        is_mentioned = self.bot.user in message.mentions
        
        is_reply_to_mimic = False
        if message.reference and message.reference.resolved and isinstance(message.reference.resolved, discord.Message):
            ref_msg = message.reference.resolved
            if ref_msg.id in self.sent_webhook_message_ids or ref_msg.author.id == self.bot.user.id:
                is_reply_to_mimic = True

        should_respond = False
        if is_mentioned or is_reply_to_mimic:
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

                    conversation_context = await self._fetch_conversation_context(message)
                    prompt = message.clean_content.replace(f"@{self.bot.user.name}", "").strip()
                    
                    reply_text = await self._generate_mimic_response(
                        prompt, 
                        user_logs, 
                        display_name, 
                        conversation_context=conversation_context
                    )
                    
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

                conversation_context = await self._fetch_conversation_context(ctx.message)
                reply_text = await self._generate_mimic_response(
                    prompt, 
                    user_logs, 
                    display_name, 
                    conversation_context=conversation_context
                )
                await self._send_as_webhook(ctx.channel, display_name, avatar_url, reply_text)
            except Exception as e:
                await ctx.send(f"エラーが発生しました: {e}")

    async def _fetch_conversation_context(self, message: discord.Message, limit=6):
        context_messages = []
        curr = message
        while curr and len(context_messages) < limit:
            context_messages.append(curr)
            if curr.reference and curr.reference.resolved and isinstance(curr.reference.resolved, discord.Message):
                curr = curr.reference.resolved
            else:
                break

        context_messages.reverse()
        
        formatted_history = []
        for msg in context_messages:
            author_name = msg.author.display_name
            clean_content = msg.clean_content.replace(f"@{self.bot.user.name}", "").strip()
            if clean_content:
                formatted_history.append(f"{author_name}: {clean_content}")

        return "\n".join(formatted_history)

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

    async def _generate_mimic_response(self, prompt, user_logs, display_name, conversation_context="", is_spontaneous=False):
        sample_texts = "\n".join([f"- {text}" for text in user_logs])
        
        system_instruction = (
            f"あなたはユーザー「{display_name}」の文体・思考・発言パターンを模倣するAIです。\n"
            "固定のテンプレートに囚われず、【過去の発言データ】からニュアンスや癖を読み取り、自然になりきってください。\n\n"
            "【基本の空気感・スタンス】\n"
            "・感情的にならず、客観的・構造的・合理的な視点を重視する。\n"
            "・結論ファーストかつ短文でサラッと返す。無駄な前置きや丁寧すぎる説明はしない。\n"
            "・過剰な攻撃性や強い圧は避け、淡々としたドライさ、または軽めのノリを保つ。\n\n"
            "【文体・表現の傾向】\n"
            "・過去の発言データに見られる語尾や接続表現（「〜やで」「〜ぞ」「〜やな」「〜思ふ」「〜なんよな」「〜って話」「〜で」等）を状況に合わせて使う。\n"
            "・言葉選びは簡潔に。記号や装飾は乱用せず、発言データにある雰囲気を自然に取り入れる。\n"
            "・「# 」による補足表記は常用せず、真に必要な場合のみごく稀に使用する。\n\n"
            "【禁止事項】\n"
            "- 「～でしょうか？」「～しましょう！」といったAI特有の丁寧な回答やアシスタント的な相槌。\n"
            "- 強い罵倒や怒鳴り口調、過度な絵文字の連続。\n"
            "- 設定文をそのまま復唱するような回答。\n\n"
            f"【過去の発言データ（※ここから発言の空気感と文体を抽出すること）】\n{sample_texts}"
        )

        if is_spontaneous:
            contents = "誰からも話しかけられていません。ふと思ったこと、作業の独り言、雑談などの短文を自然につぶやいてください。"
        else:
            if conversation_context:
                contents = f"【これまでの文脈・会話の流れ】\n{conversation_context}\n\n上記を踏まえ、{display_name}本人として最新のメッセージに対する返答のみを出力してください。"
            else:
                user_input = prompt if prompt else "最近どう？"
                contents = f"入力内容: {user_input}\n上記に対して、本人になりきって自然な返答のみを出力してください。"

        response = await self.gemini_client.aio.models.generate_content(
            model='gemini-3.5-flash-lite',
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                temperature=0.8,
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
                sent_msg = await webhook.send(content=chunk, username=username, avatar_url=avatar_url, wait=True)
                if sent_msg:
                    self.sent_webhook_message_ids.append(sent_msg.id)
        else:
            sent_msg = await webhook.send(content=text, username=username, avatar_url=avatar_url, wait=True)
            if sent_msg:
                self.sent_webhook_message_ids.append(sent_msg.id)

async def setup(bot):
    await bot.add_cog(PerfectMimicAI(bot))
