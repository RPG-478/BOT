import discord
from discord.ext import commands
import asyncio
import random

from groq import Groq
from supabase import create_client, Client

import config  # ★ここが変更点

# =========================
# AI Cog
# =========================
class ReplyAI(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

        # ===== API初期化（config経由）=====
        self.groq_client = Groq(api_key=config.GROQ_API_KEY)

        if config.SUPABASE_URL and config.SUPABASE_KEY:
            self.supabase: Client = create_client(
                config.SUPABASE_URL,
                config.SUPABASE_KEY
            )
        else:
            self.supabase = None
            print("⚠ Supabase未設定")

        # ===== 状態管理 =====
        self.cooldown = 3
        self.last_used = {}

        self.channel_state = {}   # ON/OFF（初期OFF）
        self.channel_prob = {}    # 返信確率（デフォ0.3）
        self.default_prob = 0.3

        # ===== AI人格 =====
        self.system_prompt = (
            "自然な日本語で短く返答。"
            "タメ口で軽く返す。長文禁止。"
        )

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
        res = self.groq_client.chat.completions.create(
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
    # ON/OFF
    # =========================
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):

        if message.author.bot:
            return

        channel_id = message.channel.id

        # ===== スイッチ =====
        if message.content.strip() == "!oo":
            state = not self.channel_state.get(channel_id, False)
            self.channel_state[channel_id] = state

            await message.channel.send(
                "うおｗクールアゴモード、起動ｗ"
                if state else
                "クールアゴモード、停止。"
            )
            return

        # ===== 初期OFF =====
        if self.channel_state.get(channel_id) != True:
            return

        # ===== 返信確率 =====
        if random.random() > self._get_prob(channel_id):
            return

        # ===== クールダウン =====
        if not self._cooldown_ok(message.author.id):
            return

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
                    reply = "うまく返せなかった"

            except asyncio.TimeoutError:
                reply = "考えるの遅いわｗ"
            except Exception as e:
                print(f"[ReplyAI Error] {e}")
                reply = "エラーで無理だった"

        await message.reply(
            reply[:120],
            allowed_mentions=discord.AllowedMentions.none()
        )


async def setup(bot):
    await bot.add_cog(ReplyAI(bot))
