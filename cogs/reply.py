# -*- coding: utf-8 -*-
import discord
from discord.ext import commands
import os
import random
from groq import Groq
from dotenv import load_dotenv
import asyncio

load_dotenv()

class SelectiveAnnoyingAI(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.enabled_channels = {}
        self.client = Groq(api_key=os.getenv("GROQ_API_KEY"))
        
        # 性格設定：蛇足がない場合は「NONE」とだけ答えるよう指示
        self.system_prompt = (
            "あなたはコミュニティに居座る『物知り気取りで絶妙にウザい人』です。"
            "以下のガイドラインを厳守してください："
            "1. 直接的な罵倒や「死ね」などの禁止用語は厳禁。"
            "2. ユーザーの発言に対し、聞いてもいない豆知識や補足を「蛇足ですが」と付け足してください。"
            "3. 少し小馬鹿にしたような、でも丁寧な口調を意識すること。"
            "4. 文章は1〜2文で完結させてください。"
            "5. 重要：もしユーザーの発言が短すぎたり、蛇足を挟む余地がない場合は、"
            "   余計なことは言わず、ただ一言『NONE』とだけ返信してください。"
        )

    @commands.command(name="oo")
    async def toggle_oo(self, ctx):
        channel_id = ctx.channel.id
        current_status = self.enabled_channels.get(channel_id, False)
        new_status = not current_status
        self.enabled_channels[channel_id] = new_status
        status_text = "起動（ウザさON）" if new_status else "停止"
        await ctx.send(f"蛇足モードを **{status_text}** にしました。")

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author == self.bot.user or message.author.bot:
            return

        if not self.enabled_channels.get(message.channel.id, False):
            return

        if message.content.startswith(self.bot.command_prefix):
            return

        content = message.content

        # --- 固定フレーズ ---
        fixed_replies = {
            "うぉw": "あ、それ『うぉw』じゃなくて『うおw』の方が通っぽいですよｗ",
            "うおw": "感嘆詞の使い方が独特で味わい深いですねｗ",
            "どわーw": "どわーｗって、古いネットスラングを使いこなすの流石ですｗ",
            "おお": "語彙力が『おお』に集約されてて面白いですねｗ"
        }
        
        if content in fixed_replies:
            await message.channel.send(fixed_replies[content])
            return

        # --- 10%の確率判定 ---
        if random.random() >= 0.95:
            return

        # --- Groqによる蛇足生成（AIが「話せる」と判断した時だけ返信） ---
        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(None, self._get_groq_response, content)
            
            # AIが「蛇足なし」と判断して NONE を返した場合は何もしない
            if "NONE" in response.upper():
                return

            # 有効な返信がある場合のみ「入力中」を出して返信
            async with message.channel.typing():
                await message.reply(
                    response,
                    allowed_mentions=discord.AllowedMentions.none()
                )
        except Exception as e:
            print(f"Groq Error: {e}")

    def _get_groq_response(self, user_text):
        """Groq APIから蛇足を生成。ネタがなければ NONE を返す"""
        completion = self.client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": user_text}
            ],
            temperature=0.8,
            max_tokens=150
        )
        return completion.choices[0].message.content

async def setup(bot):
    await bot.add_cog(SelectiveAnnoyingAI(bot))
