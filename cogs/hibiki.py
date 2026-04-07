import discord
from discord.ext import commands
import asyncio
import random
import re

from groq import Groq
from supabase import create_client, Client

import config


class ReplyAI(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

        # ===== API =====
        self.groq_client = Groq(api_key=config.GROQ_API_KEY)

        self.supabase: Client | None = None
        if getattr(config, "SUPABASE_URL", None) and getattr(config, "SUPABASE_KEY", None):
            self.supabase = create_client(
                config.SUPABASE_URL,
                config.SUPABASE_KEY
            )
        else:
            print("⚠ Supabase未設定（機能制限あり）")

        # ===== 状態管理 =====
        self.cooldown = 3
        self.user_last_used: dict[int, float] = {}

        self.channel_state: dict[int, bool] = {}   # ON/OFF
        self.channel_prob: dict[int, float] = {}    # 返信確率
        self.default_prob = 0.3

        # ===== 人格 =====
        self.system_prompt = (
            "あなたは短く自然な日本語で返答するAI。"
            "タメ口で軽く返し、長文は禁止。"
        )

    # =========================
    # util
    # =========================
    def _cooldown_ok(self, user_id: int) -> bool:
        now = asyncio.get_event_loop().time()
        last = self.user_last_used.get(user_id, 0)

        if now - last < self.cooldown:
            return False

        self.user_last_used[user_id] = now
        return True

    def _get_prob(self, channel_id: int) -> float:
        return self.channel_prob.get(channel_id, self.default_prob)

    def _clean_text(self, text: str, bot_user: discord.ClientUser) -> str:
        # mention削除強化
        text = re.sub(rf"<@!?{bot_user.id}>", "", text)
        return text.strip()

    # =========================
    # LLM
    # =========================
    def _generate(self, text: str) -> str:
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

    async def _run_llm(self, text: str) -> str:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._generate, text)

    # =========================
    # Supabase（任意）
    # =========================
    def _log_usage(self, guild_id: int):
        if not self.supabase:
            return

        try:
            self.supabase.table("usage_limits").upsert({
                "guild_id": guild_id,
                "used_count": 1
            }).execute()
        except Exception as e:
            print(f"[Supabase Error] {e}")

    # =========================
    # ON/OFF + Message Handler
    # =========================
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):

        # bot無視
        if message.author.bot:
            return

        # コマンド処理を必ず通す（重要バグ対策）
        await self.bot.process_commands(message)

        channel_id = message.channel.id

        # ===== トグル =====
        if message.content.strip() == "!oo":
            state = not self.channel_state.get(channel_id, False)
            self.channel_state[channel_id] = state

            await message.channel.send(
                "うおｗAIモードONｗ" if state else "AIモードOFF"
            )
            return

        # ===== OFFなら何もしない =====
        if not self.channel_state.get(channel_id, False):
            return

        # ===== ランダム返信 =====
        if random.random() > self._get_prob(channel_id):
            return

        # ===== クールダウン =====
        if not self._cooldown_ok(message.author.id):
            return

        text = self._clean_text(message.content, self.bot.user)
        if not text:
            text = "無言"

        async with message.channel.typing():
            try:
                reply = await asyncio.wait_for(
                    self._run_llm(text),
                    timeout=8.0
                )

            except asyncio.TimeoutError:
                reply = "考えるの遅いｗ"
            except Exception as e:
                print(f"[ReplyAI Error] {e}")
                reply = "エラーで無理だった"

        await message.reply(
            reply[:120],
            allowed_mentions=discord.AllowedMentions.none()
        )

        # usageログ（任意）
        self._log_usage(message.guild.id)


async def setup(bot):
    await bot.add_cog(ReplyAI(bot))
