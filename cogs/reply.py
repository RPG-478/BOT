# -*- coding: utf-8 -*-
import discord
from discord.ext import commands
import os
import random  # ← 追加：確率計算用
from groq import Groq
from dotenv import load_dotenv
import asyncio

load_dotenv()

class CynicalAI(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.enabled_channels = {}
        # Groqクライアントの初期化
        self.client = Groq(api_key=os.getenv("GROQ_API_KEY"))
        # 冷笑AIの性格設定
        self.system_prompt = (
            "あなたはネット民の中の冷笑人間です"
            "うぉwやwを多用してコメントします、また相手を徹底的に馬鹿にします"
            "文章は短くしてください"
            "度を過ぎた悪口は禁止(死ね等)"
        )

    @commands.command(name="oo")
    async def toggle_oo(self, ctx):
        channel_id = ctx.channel.id
        current_status = self.enabled_channels.get(channel_id, False)
        new_status = not current_status
        self.enabled_channels[channel_id] = new_status
        status_text = "オン" if new_status else "オフ"
        await ctx.send(f"冷笑モードを **{status_text}** にしました。")

    @commands.Cog.listener()
    async def on_message(self, message):
        # Bot自身の発言や他のBotには反応しない
        if message.author == self.bot.user or message.author.bot:
            return

        # チャンネルで有効化されているかチェック
        if not self.enabled_channels.get(message.channel.id, False):
            return

        # コマンドには反応しない
        if message.content.startswith(self.bot.command_prefix):
            return

        content = message.content

        # --- 既存の固定フレーズ（優先処理） ---
        # 固定フレーズは「10%」に関わらず即座に返信したい場合はこのまま
        fixed_replies = {
            "うぉw": "冷笑しててうぉw",
            "うおw": "Dr.冷笑「愚鈍うおw」",
            "どわーw": "どこがどわーwだよ",
            "おお": "おおじゃないが"
        }
        
        if content in fixed_replies:
            await message.channel.send(fixed_replies[content])
            return

        # --- 10%の確率判定を追加 ---
        # random.random() は 0.0 以上 1.0 未満の数値を返します
        # 0.1 未満であれば 10% の確率に当選
        if random.random() >= 0.1:
            return  # 90%の確率でここで処理を終了（無視）する

        # --- Groqによる冷笑AI反応（10%に当選した場合のみ実行） ---
        async with message.channel.typing():
            try:
                loop = asyncio.get_event_loop()
                response = await loop.run_in_executor(None, self._get_groq_response, content)
                await message.reply(
                    response,
                    allowed_mentions=discord.AllowedMentions.none()
                )
            except Exception as e:
                print(f"Groq Error: {e}")

    def _get_groq_response(self, user_text):
        """Groq APIからレスポンスを取得する（同期関数）"""
        completion = self.client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": user_text}
            ],
            temperature=0.7,
            max_tokens=150
        )
        return completion.choices[0].message.content

async def setup(bot):
    await bot.add_cog(CynicalAI(bot))
