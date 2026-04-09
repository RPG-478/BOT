import discord
from discord.ext import commands
from janome.tokenizer import Tokenizer
import random
import re

class ZogoCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.tokenizer = Tokenizer()
        # チャンネルごとの設定とプールを保持
        # 構造: {channel_id: {"active": bool, "pool": list}}
        self.channels_config = {}

    def get_config(self, channel_id):
        """チャンネルの設定を取得、なければ初期化（デフォルトOFF）"""
        if channel_id not in self.channels_config:
            self.channels_config[channel_id] = {
                "active": False, # デフォルトはOFF
                "pool": []
            }
        return self.channels_config[channel_id]

    @commands.hybrid_command(name="zogo", description="このチャンネルでの自動造語モードを切り替えます")
    async def toggle_zogo(self, ctx):
        config = self.get_config(ctx.channel.id)
        config["active"] = not config["active"]
        
        state = "有効" if config["active"] else "無効"
        # モードオフ時はプールも掃除しておく
        if not config["active"]:
            config["pool"] = []
            
        embed = discord.Embed(description=f"このチャンネルの自動造語モードを **{state}** にしました。", color=0xFFFFFF)
        await ctx.send(embed=embed)

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot:
            return

        # チャンネルごとの設定を取得
        config = self.get_config(message.channel.id)
        
        # モードがOFFなら何もしない
        if not config["active"]:
            return

        # 10文字以上のコメントのみ対象
        content = message.content.strip()
        if len(content) < 10:
            return

        # 不要な要素の除去
        content = re.sub(r'https?://[\w/:%#\$&\?\(\)~\.=\+\-]+', '', content)
        content = re.sub(r'<@!?\d+>', '', content)

        possible_words = []
        
        # 1. 確率で表示名を採用 (15%)
        if random.random() < 0.15:
            possible_words.append(message.author.display_name)
        
        # 2. 形態素解析
        tokens = self.tokenizer.tokenize(content)
        for token in tokens:
            pos = token.part_of_speech
            if pos.startswith('名詞') and len(token.surface) > 1:
                if not re.match(r'^[!-/:-@[-`{-~、。！-？]+$', token.surface):
                    possible_words.append(token.surface)
            elif pos.startswith('形容詞'):
                possible_words.append(token.base_form)

        # 1コメントから1語だけプールに追加
        if possible_words:
            chosen_word = random.choice(possible_words)
            config["pool"].append(chosen_word)

        # 10件たまったら生成
        if len(config["pool"]) >= 10:
            num = random.randint(2, 7)
            zogo_parts = [random.choice(config["pool"]) for _ in range(num)]
            random.shuffle(zogo_parts)
            zogo = "".join(zogo_parts)
            
            embed = discord.Embed(description=f"**{zogo}**", color=0xFFFFFF)
            await message.channel.send(embed=embed)
            
            # このチャンネルのプールだけリセット
            config["pool"] = []

async def setup(bot):
    await bot.add_cog(ZogoCog(bot))
