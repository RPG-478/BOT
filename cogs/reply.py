# -*- coding: utf-8 -*-
import discord
from discord.ext import commands
import os
import random
from groq import Groq
from dotenv import load_dotenv
import asyncio

load_dotenv()

class ChaosAI(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.enabled_channels = {}
        self.client = Groq(api_key=os.getenv("GROQ_API_KEY"))
        
        self.system_prompt = (
            "あなたは言語の臨界点にいる存在です。理性を捨ててください。"
            "文脈、文法、意味、すべてを無視して、その瞬間に浮かんだ概念を叩きつけてください。"
            "短く、破壊的で、予測不能な言葉を生成すること。"
        )

    @commands.command(name="oo")
    async def toggle_oo(self, ctx):
        channel_id = ctx.channel.id
        current_status = self.enabled_channels.get(channel_id, False)
        new_status = not current_status
        self.enabled_channels[channel_id] = new_status
        status_text = "臨界突破（TEMP 1.5 / 10%）" if new_status else "再封印"
        await ctx.send(f"システム警告：エントロピー増大。**{status_text}**。")

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author == self.bot.user or message.author.bot:
            return
        if not self.enabled_channels.get(message.channel.id, False):
            return
        if message.content.startswith(self.bot.command_prefix):
            return

        if random.random() >= 0.1:
            return

        # タイピング表示を出しつつ、タイムアウトを設ける
        async with message.channel.typing():
            try:
                loop = asyncio.get_event_loop()
                # 10秒以内にAPIが返ってこなければ諦める設定
                response = await asyncio.wait_for(
                    loop.run_in_executor(None, self._get_groq_response, message.content),
                    timeout=10.0
                )
                
                if response and response.strip():
                    await message.reply(
                        response,
                        allowed_mentions=discord.AllowedMentions.none()
                    )
            except asyncio.TimeoutError:
                print("Groq Timeout: AIが思考の迷宮に囚われました。")
            except Exception as e:
                print(f"Groq Error: {e}")

    def _get_groq_response(self, user_text):
        """1.5〜1.8程度が『言葉として出力される』限界です"""
        completion = self.client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": user_text}
            ],
            temperature=1.2,  # 2.0から少し下げて「出力」を安定化
            max_tokens=80,    # 短くすることでエラー率を下げる
            top_p=1.0
        )
        return completion.choices[0].message.content

async def setup(bot):
    await bot.add_cog(ChaosAI(bot))
