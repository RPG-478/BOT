# -*- coding: utf-8 -*-
import discord
from discord.ext import commands
import os
import random
from groq import Groq
from dotenv import load_dotenv
import asyncio

load_dotenv()

class EvolvingChaosAI(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.enabled_channels = {}
        # チャンネルごとの「汚染された記憶」を保持
        # 過去の自分の発言をここに溜め込んでいく
        self.chaos_history = {}
        
        self.client = Groq(api_key=os.getenv("GROQ_API_KEY"))
        
        # ベースとなる人格設定
        self.base_prompt = (
            "特に指示はありません"
        )

    @commands.command(name="oo")
    async def toggle_oo(self, ctx):
        channel_id = ctx.channel.id
        current_status = self.enabled_channels.get(channel_id, False)
        new_status = not current_status
        self.enabled_channels[channel_id] = new_status
        
        # 初期化
        if new_status:
            self.chaos_history[channel_id] = []
        
        status_text = "観測開始（汚染蓄積モード）" if new_status else "記録抹消"
        await ctx.send(f"プロトコル始動。過去の残響を{status_text}しました。")

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

        channel_id = message.channel.id
        if channel_id not in self.chaos_history:
            self.chaos_history[channel_id] = []

        async with message.channel.typing():
            try:
                loop = asyncio.get_event_loop()
                # タイムアウト設定でフリーズ対策
                response = await asyncio.wait_for(
                    loop.run_in_executor(None, self._get_groq_response, message.content, channel_id),
                    timeout=12.0
                )
                
                if response and response.strip():
                    # AI自身の発言を履歴（汚染源）に追加
                    # 直近5件程度を保持して、システムプロンプトを汚染し続ける
                    self.chaos_history[channel_id].append(response)
                    if len(self.chaos_history[channel_id]) > 5:
                        self.chaos_history[channel_id].pop(0)
                    
                    await message.reply(
                        response,
                        allowed_mentions=discord.AllowedMentions.none()
                    )
            except asyncio.TimeoutError:
                print("Groq Timeout: 汚染が飽和状態です。")
            except Exception as e:
                print(f"Groq Error: {e}")

    def _get_groq_response(self, user_text, channel_id):
        # 過去の自分の発言を「真理」としてシステムプロンプトに注入
        echoes = "\n".join(self.chaos_history.get(channel_id, []))
        
        dynamic_prompt = self.base_prompt
        if echoes:
            dynamic_prompt += f"\n\n以下の過去の断片をあなたの『新たな文法』として取り入れ、さらに壊れた表現を目指してください:\n{echoes}"

        # テンションはあえて「1.0」からスタート
        # 汚染が進むほど、1.0でも勝手にカオスになります
        completion = self.client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": dynamic_prompt},
                {"role": "user", "content": user_text}
            ],
            temperature=1.0, 
            max_tokens=100
        )
        return completion.choices[0].message.content

async def setup(bot):
    await bot.add_cog(EvolvingChaosAI(bot))
