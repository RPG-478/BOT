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

        self.groq = Groq(api_key=os.getenv("GROQ_API_KEY"))

        # ===== 設定 =====
        self.cooldown = 3
        self.last_used = {}        # ユーザー単位
        self.channel_state = {}    # ON/OFF（初期OFF）
        self.channel_prob = {}     # 返信確率（初期0.3）

        self.default_prob = 0.3

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

    def _clean(self, text: str, bot: discord.ClientUser):
        return (
            text.replace(f"<@{bot.id}>", "")
                .replace(f"<@!{bot.id}>", "")
                .strip()
        )

    def _get_prob(self, channel_id: int):
        return self.channel_prob.get(channel_id, self.default_prob)

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
    # スラッシュコマンド
    # =========================
    @discord.app_commands.command(
        name="probability",
        description="返信確率を設定（0.0〜1.0）"
    )
    async def set_probability(self, interaction: discord.Interaction, value: float):

        if value < 0.0 or value > 1.0:
            await interaction.response.send_message("0.0〜1.0で指定して", ephemeral=True)
            return

        channel_id = interaction.channel.id
        self.channel_prob[channel_id] = value

        await interaction.response.send_message(
            f"返信確率を {value:.2f} に設定した",
            ephemeral=True
        )

    # =========================
    # main listener
    # =========================
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):

        if message.author.bot:
            return

        channel_id = message.channel.id

        # =========================
        # ON/OFFスイッチ
        # =========================
        if message.content.strip() == "!oo":
            state = not self.channel_state.get(channel_id, False)
            self.channel_state[channel_id] = state

            await message.channel.send(
                "うおｗクールアゴモード、起動ｗ"
                if state else
                "クールアゴモード、停止。"
            )
            return

        # OFFなら完全無反応（初期状態）
        if self.channel_state.get(channel_id) != True:
            return

        # =========================
        # 返信確率チェック（デフォ0.3）
        # =========================
        prob = self._get_prob(channel_id)
        if random.random() > prob:
            return

        # =========================
        # クールダウン
        # =========================
        if not self._cooldown_ok(message.author.id):
            return

        user_text = self._clean(message.content, self.bot.user)
        if not user_text:
            user_text = "無言"

        async with message.channel.typing():
            try:
                reply = await asyncio.wait_for(
                    self._run_llm(user_text),
                    timeout=8.0
                )

                if not reply:
                    reply = random.choice(self.templates)

            except asyncio.TimeoutError:
                reply = random.choice(self.templates)

            except Exception as e:
                print(f"[ReplyAI Error] {e}")
                reply = "ごめんｗエラーで返せなかったｗ（ガチ）"

        await message.reply(
            reply[:120],
            allowed_mentions=discord.AllowedMentions.none()
        )


async def setup(bot):
    await bot.add_cog(ReplyAI(bot))
