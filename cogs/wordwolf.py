# -*- coding: utf-8 -*-
import discord
from discord.ext import commands
from discord import app_commands
import asyncio
import random

class WordWolf(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.game_running = False
        self.players = []        # 初期参加者
        self.alive_players = []  # 生存者リスト
        self.wolf = None
        self.player_words = {}
        
        # 50語のワードリスト
        self.word_pool = [
            "リンゴ", "ナシ", "バナナ", "イチゴ", "焼肉", "すき焼き", "寿司", "ラーメン",
            "カレー", "ハンバーグ", "学校", "塾", "会社", "公園", "スマホ", "パソコン",
            "テレビ", "電子レンジ", "冷蔵庫", "洗濯機", "海", "プール", "山", "川",
            "ディズニーランド", "ユニバ", "富士急", "映画館", "シャンプー", "リンス",
            "石鹸", "洗剤", "犬", "猫", "うさぎ", "ハムスター", "野球", "サッカー",
            "テニス", "バスケ", "数学", "英語", "国語", "理科", "社会", "ピアノ",
            "ギター", "ドラム", "バイオリン", "教科書", "ノート", "鉛筆", "消しゴム"
        ]

    @app_commands.command(name="wordwolf", description="50語からランダムペアで開始（サバイバル形式）")
    async def wordwolf(self, interaction: discord.Interaction):
        if self.game_running:
            await interaction.response.send_message("既にゲームが進行中です。", ephemeral=True)
            return

        self.game_running = False
        self.players = []
        self.alive_players = []
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

        # 50語の中からランダムに2つ選んでペアを作る
        selected_words = random.sample(self.word_pool, 2)
        common_word, wolf_word = selected_words
            
        self.wolf = random.choice(self.players)
        self.alive_players = self.players.copy()
        
        for p in self.players:
            self.player_words[p.id] = wolf_word if p == self.wolf else common_word

        check_view = CheckWordView(self)
        await interaction.channel.send(
            f"**ゲーム開始！** 参加者: {', '.join([p.display_name for p in self.players])}\n"
            "各自ボタンでワードを確認してください。\n"
            "⚠️ **【ルール】メンションでチャレンジ！失敗すると即脱落＆ミュートです。**",
            view=check_view
        )

        self.game_running = True
        self.bot.loop.create_task(self.game_timer(interaction.channel))

    async def game_timer(self, channel):
        """5分タイマー（1分ごとに通知）"""
        for i in range(4, 0, -1):
            await asyncio.sleep(60)
            if not self.game_running: return
            await channel.send(f"⏰ **残り {i} 分** です。 生存者: {len(self.alive_players)}名")
        
        await asyncio.sleep(60)
        if self.game_running:
            await self.end_game(channel, "time_up")

    @commands.Cog.listener()
    async def on_message(self, message):
        if not self.game_running or message.author.bot:
            return
        
        # メンション検知（生存者によるものか確認）
        if message.mentions and message.author in self.alive_players:
            target = message.mentions[0]
            
            # 自分以外かつ生存者リストにいる相手へのメンションのみ反応
            if target != message.author and target in self.alive_players:
                await self.execute_challenge(message.channel, message.author, target)

    async def execute_challenge(self, channel, challenger, target):
        role = discord.utils.get(channel.guild.roles, name="muted")
        
        if target == self.wolf:
            await channel.send(f"✅ **チャレンジ成功！** {target.mention} はウルフでした！")
            await self.end_game(channel, "villager_win")
        else:
            await channel.send(f"❌ **チャレンジ失敗！** {challenger.mention} は脱落しました。")
            self.alive_players.remove(challenger)
            
            if role:
                try: await challenger.add_roles(role)
                except: pass
            
            # 勝利判定：生存者が2人（ウルフ1名、村人1名）になったらウルフ勝利
            if len(self.alive_players) <= 2:
                await self.end_game(channel, "wolf_win")
            else:
                await channel.send(f"生存者は残り {len(self.alive_players)} 名です。")

    async def end_game(self, channel, result):
        self.game_running = False
        
        if result == "villager_win":
            msg = "🎉 **村人チームの勝利です！**"
        else:
            msg = f"🐺 **ウルフの勝利です！**\n正解は {self.wolf.mention} でした。"

        await channel.send(f"━━━━━━━━━━━━━━\n{msg}\n━━━━━━━━━━━━━━")
        
        # 全員のMutedロールを解除
        role = discord.utils.get(channel.guild.roles, name="muted")
        if role:
            for p in self.players:
                try: await p.remove_roles(role)
                except: pass

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
