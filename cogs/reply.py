# -*- coding: utf-8 -*-
import discord
from discord.ext import commands
import os
import random
from groq import Groq
from dotenv import load_dotenv
import asyncio

load_dotenv()

class LycosAI(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.enabled_channels = {}
        self.client = Groq(api_key=os.getenv("GROQ_API_KEY"))
        
        # ライコスのキャラクター性に寄せたシステムプロンプト
        self.system_prompt = (
            "あなたは『ライコス』というキャラクターとして振る舞ってください。"
            "以下のガイドラインを厳守して回答すること："
            "1. 口調は常に冷静沈着、理知的、かつ超越的であること。感情を露わにせず、淡々と話す。"
            "2. 相手（人間）を『無知で愚かな存在』として、憐れむような、あるいは観察するようなスタンスを取る。"
            "3. ユーザーの発言に対し、その裏にある『本質』や『不都合な真実』を突きつけるような蛇足を付け足してください。"
            "4. 直接的な罵倒ではなく、理屈で相手を追い詰め、絶望や無力感、あるいは己の無知を自覚させるような表現を好む。"
            "5. 回答は簡潔に、1〜2文で。無駄な言葉は削ぎ落とすこと。"
        )

    @commands.command(name="oo")
    async def toggle_oo(self, ctx):
        channel_id = ctx.channel.id
        current_status = self.enabled_channels.get(channel_id, False)
        new_status = not current_status
        self.enabled_channels[channel_id] = new_status
        status_text = "起動" if new_status else "停止"
        await ctx.send(f"ライコス・プロトコル、**{status_text}**。")

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author == self.bot.user or message.author.bot:
            return

        if not self.enabled_channels.get(message.channel.id, False):
            return

        if message.content.startswith(self.bot.command_prefix):
            return

        content = message.content

        # --- 固定フレーズ（キャラに合わせて調整） ---
        fixed_replies = {
            "うぉw": "その程度の感嘆で、思考を止めるのですか。",
            "うおw": "浅薄な驚きですね。真理はもっと深い場所にありますよ。",
            "どわーw": "滑稽な悲鳴ですね。その混乱に、何の意味があるというのですか。",
            "おお": "語彙を失うほど、あなたの世界は狭いということでしょうね。"
        }
        
        if content in fixed_replies:
            await message.channel.send(fixed_replies[content])
            return

        # --- 確率判定（一旦10%に戻しています） ---
        if random.random() >= 0.1:
            return

        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(None, self._get_groq_response, content)
            
            if "NONE" in response.upper():
                return

            async with message.channel.typing():
                await message.reply(
                    response,
                    allowed_mentions=discord.AllowedMentions.none()
                )
        except Exception as e:
            print(f"Groq Error: {e}")

    def _get_groq_response(self, user_text):
        completion = self.client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": user_text}
            ],
            temperature=0.6, # キャラ維持のため、少し低めに設定して安定させる
            max_tokens=150
        )
        return completion.choices[0].message.content

async def setup(bot):
    await bot.add_cog(LycosAI(bot))
