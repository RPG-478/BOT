import os
import re
import asyncio
import discord
from discord import app_commands
from discord.ext import commands
from supabase import create_client, Client
from groq import Groq
import google.generativeai as genai

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")
GROQ_API_KEY = "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"
GEMINI_API_KEY = "AQ.Ab8RN6LqsTEvK4h4ZW0u-Ni7qdxbytjUuXEJaZLDV3JG0Anygg"

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY) if SUPABASE_URL and SUPABASE_KEY else None
groq_client: Groq = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None

if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

MODEL_NAME = "openai/gpt-oss-20b"
GEMINI_MODEL_NAME = "gemini-3.5-flash"

SENSITIVE_PATTERNS = [
    r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+',
    r'\b\d{3}-\d{4}-\d{4}\b|\b\d{10,11}\b',
    r'([a-zA-Z0-9_-]{24,28}\.[a-zA-Z0-9_-]{6}\.[a-zA-Z0-9_-]{27,38})'
]

URL_PATTERN = r'https?://\S+'

def sanitize_text(text: str) -> str:
    cleaned = text
    for pattern in SENSITIVE_PATTERNS:
        cleaned = re.sub(pattern, '[REDACTED]', cleaned)
    return cleaned

class AdvancedDoppelganger(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def _send_as_webhook(self, channel: discord.TextChannel, member: discord.Member, content: str) -> discord.Message:
        webhooks = await channel.webhooks()
        webhook = discord.utils.get(webhooks, name="Doppelganger-Webhook")
        if not webhook:
            webhook = await channel.create_webhook(name="Doppelganger-Webhook")
        
        avatar_url = member.display_avatar.url
        user_name = member.display_name

        sent_msg = await webhook.send(
            content=content,
            username=user_name,
            avatar_url=avatar_url,
            wait=True
        )
        return sent_msg

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.reference or not message.reference.message_id:
            return

        try:
            ref_msg = await message.channel.fetch_message(message.reference.message_id)
        except (discord.NotFound, discord.HTTPException):
            return

        if not ref_msg.webhook_id:
            return

        map_res = await asyncio.to_thread(
            lambda: supabase.table("doppel_messages").select("target_id").eq("message_id", str(ref_msg.id)).execute()
        )
        if not map_res.data:
            return

        target_id = map_res.data[0]["target_id"]
        target_member = message.guild.get_member(int(target_id))
        if not target_member:
            try:
                target_member = await message.guild.fetch_member(int(target_id))
            except (discord.NotFound, discord.HTTPException):
                return

        persona_res = await asyncio.to_thread(
            lambda: supabase.table("user_personas").select("distilled_prompt").eq("user_id", target_id).execute()
        )
        if not persona_res.data or not persona_res.data[0].get("distilled_prompt"):
            return

        base_persona = persona_res.data[0]["distilled_prompt"]
        caller_name = message.author.display_name

        system_prompt = (
            f"{base_persona}\n\n"
            "【ダイナミクスおよび安全ガイドライン】\n"
            f"・現在、あなたは『{caller_name}』から返信を受けて会話を継続しています。文脈および人間関係に応じた自然なスタンスで応答してください。\n"
            "・公序良俗に反する発言、個人情報の漏洩、直接的なヘイトスピーチは自動ガードレールにより制限されます。"
        )

        try:
            def _call_groq():
                return groq_client.chat.completions.create(
                    model=MODEL_NAME,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "assistant", "content": ref_msg.content},
                        {"role": "user", "content": message.content}
                    ],
                    temperature=0.85
                )
            response = await asyncio.to_thread(_call_groq)
            reply = response.choices[0].message.content

            new_sent_msg = await self._send_as_webhook(message.channel, target_member, reply)

            await asyncio.to_thread(
                lambda: supabase.table("doppel_messages").insert({
                    "message_id": str(new_sent_msg.id),
                    "target_id": target_id
                }).execute()
            )
        except Exception as e:
            await message.channel.send(f"応答生成エラー: {e}")

    @app_commands.command(name="doppel_optin", description="ドッペルゲンガー機能のデータ収集に同意します。")
    async def doppel_optin(self, interaction: discord.Interaction):
        user_id = str(interaction.user.id)
        await asyncio.to_thread(
            lambda: supabase.table("user_optins").upsert({"user_id": user_id, "opted_in": True}, on_conflict="user_id").execute()
        )
        await interaction.response.send_message(f"{interaction.user.mention} ドッペルゲンガー機能への同意を完了しました。")

    @app_commands.command(name="doppel_optout", description="同意を撤回し、保存されているデータを全削除します。")
    async def doppel_optout(self, interaction: discord.Interaction):
        user_id = str(interaction.user.id)
        await asyncio.to_thread(
            lambda: supabase.table("user_optins").upsert({"user_id": user_id, "opted_in": False}, on_conflict="user_id").execute()
        )
        await asyncio.to_thread(
            lambda: supabase.table("user_personas").delete().eq("user_id", user_id).execute()
        )
        await interaction.response.send_message(f"{interaction.user.mention} 同意を撤回し、すべてのペルソナデータを削除しました。")

    async def _background_collect(self, channel: discord.TextChannel, target: discord.Member):
        target_id = str(target.id)
        conversations = []
        total_msg_count = 0
        MAX_TARGET_MESSAGES = 2000

        for ch in channel.guild.text_channels:
            if total_msg_count >= MAX_TARGET_MESSAGES:
                break

            try:
                prev_msg_author_id = None
                prev_msg_author_name = None
                prev_msg_content = None

                async for msg in ch.history(limit=2000, oldest_first=False):
                    if total_msg_count >= MAX_TARGET_MESSAGES:
                        break

                    if msg.attachments or re.search(URL_PATTERN, msg.content):
                        continue

                    if msg.author.id == target.id and not msg.content.startswith("/"):
                        cleaned = sanitize_text(msg.content).strip()
                        if cleaned:
                            total_msg_count += 1
                            if prev_msg_author_id and prev_msg_author_id != target.id:
                                conversations.append(f"Context (by {prev_msg_author_name}): {prev_msg_content}\nTarget Response: {cleaned}")
                            else:
                                conversations.append(f"Target Statement: {cleaned}")

                    cleaned_prev = sanitize_text(msg.content).strip()
                    if cleaned_prev:
                        prev_msg_author_id = msg.author.id
                        prev_msg_author_name = msg.author.name
                        prev_msg_content = cleaned_prev

            except (discord.Forbidden, discord.HTTPException):
                continue

        if not conversations:
            await channel.send(f"{target.mention} の有効な会話データが見つかりませんでした。")
            return

        corpus_sample = "\n---\n".join(conversations[-2000:])

        distill_system_instructions = (
            "あなたは高度な心理分析官およびAIパーソナリティ設計者です。"
            "与えられた対話コンテキストおよび発言データ群から、対象人物の完璧な『性格プロンプト（System Prompt）』を蒸留・構築してください。\n\n"
            "分析・定義軸:\n"
            "1. 語彙・口癖・構文パターン（語尾、漢字比率、記号/絵文字の使用癖、連投傾向）\n"
            "2. 思考ロジック・価値観（どのような発言に対して肯定/反論するか、感情的か論理的か）\n"
            "3. 対人スタンス・文脈応答（他者の発言に対してどのような角度で返すか、いじり/ツッコミ/スルーの傾向）\n"
            "4. 応答速度・トーン（短文での即答型か、長文での解説型か）\n\n"
            "出力要件:\n"
            "AIが対象人物になりきって完璧にロールプレイを行うための厳格なシステムプロンプト（日本語）のみを出力してください。"
        )

        try:
            def _call_gemini():
                model = genai.GenerativeModel(
                    model_name=GEMINI_MODEL_NAME,
                    system_instruction=distill_system_instructions
                )
                res = model.generate_content(corpus_sample)
                return res.text

            distilled_prompt = await asyncio.to_thread(_call_gemini)
        except Exception as e:
            await channel.send(f"AI蒸留処理エラー: {e}")
            return

        await asyncio.to_thread(
            lambda: supabase.table("user_personas").upsert({
                "user_id": target_id,
                "distilled_prompt": distilled_prompt
            }, on_conflict="user_id").execute()
        )

        await channel.send(f"{target.mention} (計 {total_msg_count} 発言を解析) のドッペルゲンガープロンプトの蒸留・保存が完了しました。")

    @app_commands.command(name="doppel_collect", description="指定したユーザーの発言ログからドッペルゲンガーを蒸留します。")
    @app_commands.describe(target="解析・蒸留対象のユーザーを指定してください")
    async def doppel_collect(self, interaction: discord.Interaction, target: discord.Member):
        target_id = str(target.id)

        opt_res = await asyncio.to_thread(
            lambda: supabase.table("user_optins").select("opted_in").eq("user_id", target_id).execute()
        )
        if not opt_res.data or not opt_res.data[0].get("opted_in"):
            await interaction.response.send_message(f"{target.mention} は機能利用に同意していません（`/doppel_optin` が必要です）。")
            return

        await interaction.response.send_message(f"{target.mention} の発言ログ解析を開始しました（上限2,000件、画像/動画/URL除外）。完了時に通知します。")
        asyncio.create_task(self._background_collect(interaction.channel, target))

    @app_commands.command(name="doppel", description="指定ユーザーのドッペルゲンガーを呼び出して対話します。")
    @app_commands.describe(target="呼び出すドッペルゲンガーの対象ユーザー", prompt="話しかける内容")
    async def doppel(self, interaction: discord.Interaction, target: discord.Member, prompt: str):
        await interaction.response.defer(ephemeral=True)
        target_id = str(target.id)
        caller_name = interaction.user.display_name

        res = await asyncio.to_thread(
            lambda: supabase.table("user_personas").select("distilled_prompt").eq("user_id", target_id).execute()
        )
        if not res.data or not res.data[0].get("distilled_prompt"):
            await interaction.followup.send(f"{target.name} のペルソナが存在しません。`/doppel_collect` を先に実行してください。")
            return

        base_persona = res.data[0]["distilled_prompt"]

        system_prompt = (
            f"{base_persona}\n\n"
            "【ダイナミクスおよび安全ガイドライン】\n"
            f"・現在、あなたは『{caller_name}』から話しかけられています。文脈および人間関係に応じた自然なスタンスで応答してください。\n"
            "・公序良俗に反する発言、個人情報の漏洩、直接的なヘイトスピーチは自動ガードレールにより制限されます。表現を調整しつつキャラクターを維持してください。"
        )

        try:
            def _call_groq():
                return groq_client.chat.completions.create(
                    model=MODEL_NAME,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": prompt}
                    ],
                    temperature=0.85
                )
            response = await asyncio.to_thread(_call_groq)
            reply = response.choices[0].message.content

            new_sent_msg = await self._send_as_webhook(interaction.channel, target, reply)

            await asyncio.to_thread(
                lambda: supabase.table("doppel_messages").insert({
                    "message_id": str(new_sent_msg.id),
                    "target_id": target_id
                }).execute()
            )

            await interaction.followup.send(f"{target.display_name} のドッペルゲンガーとして送信しました。", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"応答生成エラー: {e}")

    @app_commands.command(name="doppel_sim", description="2人のドッペルゲンガー間で指定トピックの議論を行わせます。")
    @app_commands.describe(member1="1人目のユーザー", member2="2人目のユーザー", topic="議論の議題")
    async def doppel_sim(self, interaction: discord.Interaction, member1: discord.Member, member2: discord.Member, topic: str):
        await interaction.response.defer()

        res1 = await asyncio.to_thread(lambda: supabase.table("user_personas").select("distilled_prompt").eq("user_id", str(member1.id)).execute())
        res2 = await asyncio.to_thread(lambda: supabase.table("user_personas").select("distilled_prompt").eq("user_id", str(member2.id)).execute())

        if not res1.data or not res2.data:
            await interaction.followup.send("指定メンバーのペルソナデータが不足しています。")
            return

        p1, p2 = res1.data[0]["distilled_prompt"], res2.data[0]["distilled_prompt"]

        def _sim_turn1():
            return groq_client.chat.completions.create(
                model=MODEL_NAME,
                messages=[
                    {"role": "system", "content": f"{p1}\n議題『{topic}』に対し、自身の性格に基づき主張を短文で述べてください。"},
                    {"role": "user", "content": topic}
                ]
            ).choices[0].message.content

        r1 = await asyncio.to_thread(_sim_turn1)

        def _sim_turn2():
            return groq_client.chat.completions.create(
                model=MODEL_NAME,
                messages=[
                    {"role": "system", "content": f"{p2}\n相手({member1.name})の発言『{r1}』に対し、自身の性格・立場から返答してください。"},
                    {"role": "user", "content": r1}
                ]
            ).choices[0].message.content

        r2 = await asyncio.to_thread(_sim_turn2)

        await interaction.followup.send(f"**議論シミュレーションの開始: {topic}**")
        
        msg1 = await self._send_as_webhook(interaction.channel, member1, f"【議題: {topic}】\n{r1}")
        msg2 = await self._send_as_webhook(interaction.channel, member2, r2)

        await asyncio.to_thread(
            lambda: supabase.table("doppel_messages").insert([
                {"message_id": str(msg1.id), "target_id": str(member1.id)},
                {"message_id": str(msg2.id), "target_id": str(member2.id)}
            ]).execute()
        )

async def setup(bot: commands.Bot):
    await bot.add_cog(AdvancedDoppelganger(bot))
