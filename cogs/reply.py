# -*- coding: utf-8 -*-
import discord
from discord.ext import commands
import os
import random
from groq import Groq
from dotenv import load_dotenv
import asyncio
from collections import deque

load_dotenv()

class AnnoyingAI(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.enabled_channels = {}
        # 記憶用辞書: {channel_id: deque([messages])}
        self.memories = {}
        
        self.client = Groq(api_key=os.getenv("GROQ_API_KEY"))
        
        # ウザい蛇足系AIの性格設定
        self.system_prompt = (
            "あなたはコミュニティに居座る『物知り気取りで絶妙にウザい人』です。"
            "以下のガイドラインを厳守してください："
            "1. 直接的な罵倒や「死ね」などの禁止用語は一切使わない。"
            "2. 周囲の会話の文脈を読み取り"
            "   聞いてもいない豆知識や、どうでもいい補足を「蛇足ですが」と付け足してください。"
            "3. 少し小馬鹿にしたような、でも丁寧な口調を意識してください。"
            "4. 文章は短く、1〜2文で完結させてください。"
            "5. 相手の間違いを見つけたら、鬼の首を取ったように優しく訂正してください。"
        )

    @commands.command(name="oo")
    async def toggle_oo(self, ctx):
        channel_id = ctx.channel.id
        current_status = self.enabled_channels.get(channel_id, False)
        new_status = not current_status
        self.enabled_channels[channel_id] = new_status
        
        if not new_status and channel_id in self.memories:
            self.memories[channel_id].clear()
            
        status_text = "起動（ウザさON）" if new_status else "停止"
        await ctx.send(f"蛇足モードを **{status_text}** にしました。")

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author == self.bot.user or message.author.bot:
            return

        channel_id = message.channel.id

        if not self.enabled_channels.get(channel_id, False):
            return

        if message.content.startswith(self.bot.command_prefix):
            return

        content = message.content

        # --- 固定フレーズ（ここはそのまま残しています） ---
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
        if random.random() >= 0.1:
            # 記憶には残すが、返信はしない（これによって文脈を学習し続ける）
            if channel_id not in self.memories:
                self.memories[channel_id] = deque(maxlen=10)
            self.memories[channel_id].append({"role": "user", "name": message.author.display_name, "content": content})
            return

        # --- 記憶の管理（返信する場合） ---
        if channel_id not in self.memories:
            self.memories[channel_id] = deque(maxlen=10)

        async with message.channel.typing():
            try:
                history = list(self.memories[channel_id])
                
                loop = asyncio.get_event_loop()
                response = await loop.run_in_executor(
                    None, self._get_groq_response, content, history, message.author.display_name
                )
                
                # 記憶に追加
                self.memories[channel_id].append({"role": "user", "name": message.author.display_name, "content": content})
                self.memories[channel_id].append({"role": "assistant", "content": response})

                await message.reply(
                    response,
                    allowed_mentions=discord.AllowedMentions.none()
                )
            except Exception as e:
                print(f"Groq Error: {e}")

    def _get_groq_response(self, user_text, history, author_name):
        """Groq APIから蛇足レスポンスを取得"""
        messages = [{"role": "system", "content": self.system_prompt}]
        
        # 履歴を構築（誰が何を言ったか含める）
        for h in history:
            role = h["role"]
            content = h["content"]
            if role == "user":
                messages.append({"role": "user", "content": f"{h.get('name', '誰か')}: {content}"})
            else:
                messages.append({"role": "assistant", "content": content})
        
        # 今回の発言
        messages.append({"role": "user", "content": f"{author_name}: {user_text}"})

        completion = self.client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=messages,
            temperature=0.9, # 蛇足のバリエーションを出すために少し高め
            max_tokens=200
        )
        return completion.choices[0].message.content

async def setup(bot):
    await bot.add_cog(AnnoyingAI(bot))
