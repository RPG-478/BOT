import discord
from discord.ext import commands
from janome.tokenizer import Tokenizer
import random
import re

class ZogoCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.tokenizer = Tokenizer()
        self.is_active = False  # 自動モードのフラグ
        self.message_pool = []  # 素材（名詞・形容詞・ユーザー名）を貯めるリスト

    @commands.hybrid_command(name="zogo", description="自動造語生成モードを切り替えます")
    async def toggle_zogo(self, ctx):
        """自動生成のON/OFF切り替え"""
        self.is_active = not self.is_active
        state = "有効" if self.is_active else "無効"
        await ctx.send(f"<:success:1490985168100659322> 自動造語モードを **{state}** にしました。")

    @commands.Cog.listener()
    async def on_message(self, message):
        # ボット自身の発言や、モードOFF時は無視
        if message.author.bot or not self.is_active:
            return

        # 10文字以上のコメントのみ対象
        content = message.content.strip()
        if len(content) < 10:
            return

        # URLやメンションの除去
        content = re.sub(r'https?://[\w/:%#\$&\?\(\)~\.=\+\-]+', '', content)
        content = re.sub(r'<@!?\d+>', '', content)

        # --- 素材の抽出（1コメントから1つだけ） ---
        possible_words = []
        
        # 1. 確率でユーザー名を選択肢に入れる (15%)
        if random.random() < 0.15:
            possible_words.append(message.author.display_name)
        
        # 2. 形態素解析で言葉を拾う
        tokens = self.tokenizer.tokenize(content)
        for token in tokens:
            pos = token.part_of_speech
            # 名詞（記号以外）
            if pos.startswith('名詞') and len(token.surface) > 1:
                if not re.match(r'^[!-/:-@[-`{-~、。！-？]+$', token.surface):
                    possible_words.append(token.surface)
            # 形容詞
            elif pos.startswith('形容詞'):
                possible_words.append(token.base_form)

        # 抽出できた中からランダムに「1語だけ」採用
        if possible_words:
            chosen_word = random.choice(possible_words)
            self.message_pool.append(chosen_word)

        # --- 造語の生成タイミング（10件たまったら） ---
        if len(self.message_pool) >= 10:
            # 2〜7語をランダムに組み合わせてガッチャンコ
            num = random.randint(2, 7)
            # プールからランダムに選ぶ（重複OKにするとカオス感が増す）
            zogo_parts = [random.choice(self.message_pool) for _ in range(num)]
            
            # ボケ感を出すためにシャッフルして結合
            random.shuffle(zogo_parts)
            zogo = "".join(zogo_parts)
            
            await message.channel.send(f"**{zogo}**")
            
            # プールをリセット（または古いものから消すなら self.message_pool.pop(0)）
            self.message_pool = []

async def setup(bot):
    await bot.add_cog(ZogoCog(bot))