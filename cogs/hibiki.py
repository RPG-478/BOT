import discord
from discord.ext import commands
import os
import asyncio
import random
from groq import Groq
from dotenv import load_dotenv

load_dotenv()


class ReplyAI(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

        # ===== LLM =====
        self.groq = Groq(api_key=os.getenv("GROQ_API_KEY"))

        # ===== 設定 =====
        self.cooldown = 3
        self.last_used = {}

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
    def _cooldown_ok(self, key: int):
        now = asyncio.get_event_loop().time()
        if now - self.last_used.get(key, 0) < self.cooldown:
            return False
        self.last_used[key] = now
        return True

    def _clean(self, text: str, bot: discord.ClientUser):
        return (
            text.replace(f"<@{bot.id}>", "")
                .replace(f"<@!{bot.id}>", "")
                .strip()
        )

    # =========================
    # LLM
    # =========================
    def _generate(self, user_text: str):
        res = self.groq.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": user_text}
            ],
            temperature=0.7,
            max_tokens=120
        )

        return res.choices[0].message.content.strip()

    async def _run_llm(self, text: str):
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._generate, text)

    # =========================
    # main listener
    # =========================
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):

        if message.author.bot:
            return

        # メンション限定（既存botと干渉しにくい）
        if self.bot.user not in message.mentions:
            return

        # クールダウン（ユーザー単位）
        if not self._cooldown_ok(message.author.id):
            return

        user_text = self._clean(message.content, self.bot.user)
        if not user_text:
            user_text = "無言"

        async with message.channel.typing():
            try:
                # LLM
                try:
                    reply = await asyncio.wait_for(
                        self._run_llm(user_text),
                        timeout=8.0
                    )
                except asyncio.TimeoutError:
                    reply = random.choice(self.templates)

                # 安全フォールバック
                if not reply:
                    reply = random.choice(self.templates)

                await message.reply(
                    reply[:120],
                    allowed_mentions=discord.AllowedMentions.none()
                )

            except Exception as e:
                print(f"[ReplyAI Error] {e}")
                await message.channel.send("エラーで返せなかった")


# =========================
# setup
# =========================
async def setup(bot):
    await bot.add_cog(ReplyAI(bot))
