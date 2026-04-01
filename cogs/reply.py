# -*- coding: utf-8 -*-
import discord
from discord.ext import commands
import os
from groq import Groq
from dotenv import load_dotenv
import asyncio

load_dotenv()

class ChaosAI(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.enabled_channels = {}
        self.client = Groq(api_key=os.getenv("GROQ_API_KEY"))
        
        # システムプロンプト：もはや指示すらノイズになるレベルですが一応
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
        status_text = "臨界突破（TEMP 2.0）" if new_status else "再封印"
        await ctx.send(f"システム警告：エントロピー増大速度最大。**{status_text}**。")

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author == self.bot.user or message.author.bot:
            return

        if not self.enabled_channels.get(message.channel.id, False):
            return

        # コマンド実行時は反応しない
        if message.content.startswith(self.bot.command_prefix):
            return

        # 全てのメッセージに反応（抽選・固定フレーズなし）
        async with message.channel.typing():
            try:
                loop = asyncio.get_event_loop()
                response = await loop.run_in_executor(None, self._get_groq_response, message.content)
                
                await message.reply(
                    response,
                    allowed_mentions=discord.AllowedMentions.none()
                )
            except Exception as e:
                print(f"Groq Error: {e}")

    def _get_groq_response(self, user_text):
        """Groq APIをテンション2.0で叩く"""
        completion = self.client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": user_text}
            ],
            temperature=2.0,  # 物理限界値
            max_tokens=100,    # 暴走しすぎないよう少し短めに
            top_p=1.0         # 確率分布を絞らない（カオス維持）
        )
        return completion.choices[0].message.content

async def setup(bot):
    await bot.add_cog(ChaosAI(bot))
