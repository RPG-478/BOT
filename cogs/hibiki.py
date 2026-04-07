#cogsに入れてるからcogs形式で頼むぞ〜

import os
import time
import random
import discord
from discord.ext import commands
from openai import OpenAI

# =========================
# LLM
# =========================
llm = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# =========================
# 設定
# =========================
COOLDOWN = 3
REPLY_PROBABILITY = 0.3

PREFIXES = ["うおｗ", "どわーｗ", "かっこよｗ"]
ENDINGS = ["なｗ", "だなｗ", "って感じｗ"]

STRONG_WORDS = ["殺す", "死ね", "消えろ", "うざい", "きもい"]

TEMPLATES = [
    "よくある小さな達成だな",
    "ありがちな流れそのままだな",
    "想定内すぎて語ること少ないな"
]

SYSTEM_PROMPT = """
一文のみ。20〜30文字。
必ず「うおｗ系」で開始し「なｗ系」で終了。
嘲笑寄り短文。
"""

# =========================
# util
# =========================
def clean(text, bot):
    return (
        text.replace(f"<@{bot.id}>", "")
            .replace(f"<@!{bot.id}>", "")
            .strip()
    )

def make_reply(prefix, text):
    msg = f"{prefix} {text}"
    msg = msg.replace("まあ", "")

    if not any(msg.endswith(e) for e in ENDINGS):
        msg = msg.rstrip("。、！？!? ") + random.choice(ENDINGS)

    return msg[:30].rstrip("。、！？!? ")


# =========================
# Cog
# =========================
class AICog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.channel_state = {}   # ON/OFF（チャンネル単位）
        self.last_used = {}       # クールダウン（チャンネル単位）

    @commands.Cog.listener()
    async def on_message(self, message):

        if message.author.bot:
            return

        channel_id = message.channel.id

        # =====================
        # ON / OFF
        # =====================
        if message.content.strip() == "!oo":
            state = not self.channel_state.get(channel_id, False)
            self.channel_state[channel_id] = state

            await message.channel.send(
                "クールアゴbot、起動。" if state else "クールアゴbot、停止。"
            )
            return

        if not self.channel_state.get(channel_id, False):
            return

        # メンション判定（安全版）
        if not any(m.id == self.bot.user.id for m in message.mentions):
            return

        # 確率
        if random.random() > REPLY_PROBABILITY:
            return

        # クールダウン
        now = time.time()
        if now - self.last_used.get(channel_id, 0) < COOLDOWN:
            return
        self.last_used[channel_id] = now

        user_text = clean(message.content, self.bot.user)
        if not user_text:
            user_text = "無言"

        # =====================
        # 生成
        # =====================
        if any(w in user_text for w in STRONG_WORDS):
            text = random.choice(TEMPLATES)

        else:
            text = random.choice(TEMPLATES)
            try:
                res = llm.responses.create(
                    model="gpt-5.3",
                    input=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": user_text}
                    ],
                    max_output_tokens=80
                )

                if getattr(res, "output", None) and res.output[0].content:
                    text = res.output[0].content[0].text.strip()

            except Exception:
                pass

        reply = f"{random.choice(PREFIXES)} {text}"

        if not any(reply.endswith(e) for e in ENDINGS):
            reply = reply.rstrip("。、！？!? ") + random.choice(ENDINGS)

        await message.channel.send(reply)
        

# =========================
# setup
# =========================
async def setup(bot):
    await bot.add_cog(AICog(bot))
