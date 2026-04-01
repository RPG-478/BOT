# -*- coding: utf-8 -*-
import discord
from discord.ext import commands
from discord import app_commands
import asyncio
import random
import time

class WordWolf(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.game_running = False
        self.players = []
        self.wolf = None
        self.player_words = {}
        self.start_time = 0
        self.word_pairs = [
            ("リンゴ", "ナシ"), ("焼肉", "すき焼き"), ("シャンプー", "リンス"),
            ("学校", "塾"), ("スマホ", "パソコン"), ("海", "プール"),
            ("ディズニーランド", "ユニバ"), ("少年ジャンプ", "週刊マガジン")
        ]

    @app_commands.command(name="wordwolf", description="ワードウルフを開始します（5分制限）")
    async def wordwolf(self, interaction: discord.Interaction):
        if self.game_running:
            await interaction.response.send_message("既にゲームが進行中です。", ephemeral=True)
            return

        self.game_running = False # 初期化
        self.players = []
        self.player_words = {}
        
        join_view = JoinView(self)
        await interaction.response.send_message(
            "🐺 **ワードウルフ参加者募集中！**\n1分以内に【参加】ボタンを押してください。", 
            view=join_view
        )
        
        await asyncio.sleep(60)
        join_view.stop()
        
        if len(self.players) < 3:
            await interaction.channel.send("人数不足（3人以上必要）のため中止します。")
            return

        # ワード選定と割り当て
        common, wolf_w = random.choice(self.word_pairs)
        if random.random() > 0.5:
            common, wolf_w = wolf_w, common
            
        self.wolf = random.choice(self.players)
        for p in self.players:
            self.player_words[p.id] = wolf_w if p == self.wolf else common

        # 確認用ボタンの送信
        check_view = CheckWordView(self)
        await interaction.channel.send(
            f"**募集終了！** 参加者: {', '.join([p.display_name for p in self.players])}\n"
            "各自、下のボタンでワードを確認してください。\n"
            "⚠️ **【ルール】誰かをメンションすると『チャレンジ（指名）』になります！**",
            view=check_view
        )

        # ゲーム開始処理
        self.game_running = True
        self.start_time = time.time()
        
        # 5分間のカウントダウンタスクを開始
        self.bot.loop.create_task(self.game_timer(interaction.channel))

    async def game_timer(self, channel):
        """1分ごとに通知し、5分で終了させるタイマー"""
        for i in range(4, 0, -1):
            await asyncio.sleep(60)
            if not self.game_running: return # 途中で決着がついたら終了
            await channel.send(f"⏰ **残り {i} 分** です。")
        
        await asyncio.sleep(60)
        if self.game_running:
            self.game_running = False
            await channel.send(f"⌛ **タイムアップ！ ウルフの勝利です！**\n正解のウルフは {self.wolf.mention} でした。")

    @commands.Cog.listener()
    async def on_message(self, message):
        """メンションを検知してチャレンジ判定を行う"""
        if not self.game_running or message.author.bot:
            return
        
        # プレイヤーが誰かをメンションしたかチェック
        if message.mentions and message.author in self.players:
            target = message.mentions[0] # 最初のメンション対象を取得
            
            # 自分へのメンションは無視
            if target == message.author:
                return
            
            # プレイヤー以外へのメンションも無視
            if target not in self.players:
                return

            # チャレンジ判定開始
            await self.execute_challenge(message.channel, message.author, target)

    async def execute_challenge(self, channel, challenger, target):
        """判定とミュート処理"""
        role = discord.utils.get(channel.guild.roles, name="muted")
        
        if target == self.wolf:
            await channel.send(f"✅ **チャレンジ成功！** {target.mention} はウルフでした！村人の勝利です。")
            punished = target
            self.game_running = False # 決着
        else:
            await channel.send(f"❌ **チャレンジ失敗！** {challenger.mention} は無実の者を疑ったため脱落です。")
            punished = challenger

        # ミュート処理
        if role:
            try:
                await punished.add_roles(role)
                await channel.send(f"{punished.mention} を1分間ミュートします。")
                await asyncio.sleep(60)
                await punished.remove_roles(role)
                await channel.send(f"{punished.mention} のミュートを解除しました。")
            except:
                pass

# --- UI Components ---

class JoinView(discord.ui.View):
    def __init__(self, cog):
        super().__init__(timeout=60)
        self.cog = cog

    @discord.ui.button(label="参加", style=discord.ButtonStyle.green)
    async def join(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user not in self.cog.players:
            self.cog.players.append(interaction.user)
            await interaction.response.send_message("参加完了。", ephemeral=True)
        else:
            await interaction.response.send_message("参加済みです。", ephemeral=True)

class CheckWordView(discord.ui.View):
    def __init__(self, cog):
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(label="自分のワードを確認", style=discord.ButtonStyle.secondary)
    async def check(self, interaction: discord.Interaction, button: discord.ui.Button):
        word = self.cog.player_words.get(interaction.user.id)
        if word:
            await interaction.response.send_message(f"あなたのワードは【**{word}**】です。", ephemeral=True)
        else:
            await interaction.response.send_message("プレイヤーではありません。", ephemeral=True)

async def setup(bot):
    await bot.add_cog(WordWolf(bot))
