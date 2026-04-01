# -*- coding: utf-8 -*-
import discord
from discord.ext import commands
import os
import random
from groq import Groq
from dotenv import load_dotenv
import asyncio

load_dotenv()

class HaikuAI(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.enabled_channels = {}
        self.client = Groq(api_key=os.getenv("GROQ_API_KEY"))
        
        # 575を死守させるための強力なシステムプロンプト
        self.system_prompt = (
            "あなたは俳句と川柳の達人です。以下のルールを『絶対』に守ってください：\n"
            "1. 返答は必ず『五・七・五』の合計17音だけで構成してください。\n"
            "2. 余計な解説、挨拶、結びの言葉は一切禁止します。575以外の文字を出力しないでください。\n"
            "3. 季語はあってもなくても構いませんが、日本語としてのリズムを最優先してください。\n"
            "4. 標語や説明文ではなく、情景や感情、あるいは皮肉を込めた一句にしてください。"
        )

    @commands.command(name="oo")
    async def toggle_oo(self, ctx):
        channel_id = ctx.channel.id
        current_status = self.enabled_channels.get(channel_id, False)
        new_status = not current_status
        self.enabled_channels[channel_id] = new_status
        
        status_text = "起動（575モード）" if new_status else "停止"
        await ctx.send(f"詠み人知らず、**{status_text}**。")

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
                    timeout=10.0
                )
                
                if response and response.strip():
                    # 念のため、改行などを整理して美しく表示
                    clean_haiku = response.replace(" ", "　").replace("、", "　")
                    await message.reply(
                        clean_haiku,
                        allowed_mentions=discord.AllowedMentions.none()
                    )
            except Exception as e:
                print(f"Groq Error: {e}")

    def _get_groq_response(self, user_text):
        """Groq APIで575を生成"""
        completion = self.client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": f"お題：{user_text}\nこれについて一句詠んでください。"}
            ],
            temperature=0.7, # リズムの正確さと創造性のバランス
            max_tokens=50
        )
        return completion.choices[0].message.content

async def setup(bot):
    await bot.add_cog(HaikuAI(bot))
