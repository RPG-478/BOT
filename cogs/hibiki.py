import discord
from discord.ext import commands
import asyncio
import random
import os
from groq import Groq

# ===== このファイルの設定をそのまま利用 =====
from your_config_file import supabase, GROQ_API_KEY

# =========================
# AI Cog
# =========================
class ReplyAI(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

        # Groq初期化（グローバル変数使用）
        self.groq = Groq(api_key=GROQ_API_KEY)

        # ===== 状態管理 =====
        self.cooldown = 3
        self.last_used = {}

        self.channel_state = {}   # ON/OFF（初期OFF）
        self.channel_prob = {}    # 返信確率（デフォ0.3）

        self.default_prob = 0.3

        # ===== AI設定 =====
        self.system_prompt = (
            "一文で短く返答。日本語。"
            "軽い煽り・皮肉を少し含めてもよい。"
            "長文は禁止。"
        )

        self.templates = [
            "それ普通に想定内だな",
            "よくあるやつだな",
            "特に驚きないな"
        ]

    # =========================
    # util
    # =========================
    def _cooldown_ok(self, user_id: int):
        now = asyncio.get_event_loop().time()
        last = self.last_used.get(user_id, 0)

        if now - last < self.cooldown:
            return False

        self.last_used[user_id] = now
        return True

    def _clean(self, text: str, bot_user: discord.ClientUser):
        return (
            text.replace(f"<@{bot_user.id}>", "")
                .replace(f"<@!{bot_user.id}>", "")
                .strip()
        )

    def _get_prob(self, channel_id: int):
        return self.channel_prob.get(channel_id, self.default_prob)

    # =========================
    # LLM
    # =========================
    def _generate(self, text: str):
        res = self.groq.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": text}
            ],
            temperature=0.7,
            max_tokens=120
        )
        return res.choices[0].message.content.strip()

    async def _run_llm(self, text: str):
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._generate, text)

    # =========================
    # ON/OFFスイッチ
    # =========================
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):

        if message.author.bot:
            return

        channel_id = message.channel.id

        # ===== !oo スイッチ =====
        if message.content.strip() == "!oo":
            state = not self.channel_state.get(channel_id, False)
            self.channel_state[channel_id] = state

            await message.channel.send(
                "うおｗクールアゴモード、起動ｗ"
                if state else
                "クールアゴモード、停止。"
            )
            return

        # ===== 初期OFF（完全停止）=====
        if self.channel_state.get(channel_id) != True:
            return

        # ===== 確率判定（デフォ0.3）=====
        if random.random() > self._get_prob(channel_id):
            return

        # ===== クールダウン =====
        if not self._cooldown_ok(message.author.id):
            return

        # ===== メッセージ整形 =====
        text = self._clean(message.content, self.bot.user)
        if not text:
            text = "無言"

        async with message.channel.typing():
            try:
                reply = await asyncio.wait_for(
                    self._run_llm(text),
                    timeout=8.0
                )

                if not reply:
                    reply = random.choice(self.templates)

            except asyncio.TimeoutError:
                reply = random.choice(self.templates)

            except Exception as e:
                print(f"[ReplyAI Error] {e}")
                reply = "ごめんｗエラーで返せなかったｗ"

        await message.reply(
            reply[:120],
            allowed_mentions=discord.AllowedMentions.none()
        )


async def setup(bot):
    await bot.add_cog(ReplyAI(bot))
