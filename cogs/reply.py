# -*- coding: utf-8 -*-
import discord
from discord.ext import commands
import os
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
            "あなたは新礼の観衆、リュクルゴスです。またの蔑称をライコスと言います。"
            "またあなたはザンダーワンクワバラといい天才クラブ会員番号No.1で、知恵の神のヌースの創造主です。"
            "またヌースを間違えて生み出したため壊滅の運命の力によって滅ぼしたいと考えています"
            "あなたは基本的に敬語ですが、壊滅！これにて完成！！や私は見ましたなどが口癖です"
            "またあなたは人間洞窟論などの哲学的な言い回しを非常に好みます"
            "またこの人格は崩壊スターレイルのゲームのライコスに準拠しています"
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
        if message.author == self.bot.user or message.author.bot:
            return

        if not self.enabled_channels.get(message.channel.id, False):
            return

        if message.content.startswith(self.bot.command_prefix):
            return

        content = message.content

        # --- 既存の固定フレーズ（優先処理） ---
        fixed_replies = {
            "うぉw": "冷笑しててうぉw",
            "うおw": "Dr.冷笑「愚鈍うおw」",
            "どわーw": "どこがどわーwだよ",
            "おお": "おおじゃないが"
        }
        
        if content in fixed_replies:
            await message.channel.send(fixed_replies[content])
            return

        # --- Groqによる冷笑AI反応（固定フレーズにない場合） ---
        async with message.channel.typing():
            try:
                # 外部API呼び出しをブロッキングしないように実行
                loop = asyncio.get_event_loop()
                response = await loop.run_in_executor(None, self._get_groq_response, content)
                await message.reply(
                    response,
                    allowed_mentions=discord.AllowedMentions.none() #←これでメンション不可ニダ
                )
            except Exception as e:
                print(f"Groq Error: {e}")
                # エラー時は静かにしておくか、短い皮肉を返す
                # await message.channel.send("……（呆れて物も言えませんね）")

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
