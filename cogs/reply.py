# -*- coding: utf-8 -*-
import discord
from discord.ext import commands
import os
import random
from groq import Groq
from dotenv import load_dotenv
import asyncio

load_dotenv()

class GrassAI(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.enabled_channels = {}
        self.client = Groq(api_key=os.getenv("GROQ_API_KEY"))
        
        # 30文字制限と「w」の指示を徹底
        self.system_prompt = (
            "あなたは語彙力が乏しく、常に笑っている存在です。"
            "1. 返答は句読点を含め、必ず『30文字以内』に収めてください。"
            "2. 文末や文中に『w』や『www』を大量に使い、小馬鹿にしたように笑ってください。"
            "3. 難しい話はせず、短く、浅いコメントだけを返してください。"
            "4.30%くらいの確率で何も言わずに<a:BAKUHATU:1490259644717993995>だけ送ってください"
        )

    @commands.command(name="oo")
    async def toggle_oo(self, ctx):
        channel_id = ctx.channel.id
        current_status = self.enabled_channels.get(channel_id, False)
        new_status = not current_status
        self.enabled_channels[channel_id] = new_status
        status_text = "起動ww" if new_status else "停止"
        await ctx.send(f"芝生モード、**{status_text}**。")

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author == self.bot.user or message.author.bot:
            return
        if not self.enabled_channels.get(message.channel.id, False):
            return
        if message.content.startswith(self.bot.command_prefix):
            return

        # 10%の確率判定
        if random.random() >= 0.1:
            return

        async with message.channel.typing():
            try:
                loop = asyncio.get_event_loop()
                response = await asyncio.wait_for(
                    loop.run_in_executor(None, self._get_groq_response, message.content),
                    timeout=8.0
                )
                
                if response:
                    # 改行を消して一行に強制
                    clean_res = response.replace("\n", " ")[:30]
                    await message.reply(
                        clean_res,
                        allowed_mentions=discord.AllowedMentions.none()
                    )
            except Exception as e:
                print(f"Groq Error: {e}")

    def _get_groq_response(self, user_text):
        """Groq APIで短文草生成"""
        completion = self.client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": user_text}
            ],
            temperature=1.0,
            max_tokens=40 # 30文字程度に収まるトークン量
        )
        return completion.choices[0].message.content

async def setup(bot):
    await bot.add_cog(GrassAI(bot))
