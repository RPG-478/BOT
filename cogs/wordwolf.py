# -*- coding: utf-8 -*-
import discord
from discord.ext import commands
from discord import app_commands
import asyncio
import random

class CustomWordWolf(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.game_running = False
        self.players = []
        self.alive_players = []
        self.wolf = None
        self.player_words = {}
        self.remaining_challenges = 3  # チャレンジ残り回数
        
        # 標準的なワードリスト（100語以上）
        self.word_pool = [
            "リンゴ", "ナシ", "バナナ", "イチゴ", "ブドウ", "メロン", "スイカ", "桃",
            "焼肉", "すき焼き", "寿司", "ラーメン", "カレー", "ハンバーグ", "パスタ", "牛丼",
            "学校", "塾", "会社", "公園", "図書館", "病院", "駅", "空港",
            "スマホ", "パソコン", "テレビ", "電子レンジ", "冷蔵庫", "洗濯機", "掃除機", "ドライヤー",
            "海", "プール", "山", "川", "砂漠", "森林", "湖", "滝",
            "ディズニーランド", "ユニバ", "富士急", "映画館", "水族館", "動物園", "美術館", "カラオケ",
            "シャンプー", "リンス", "石鹸", "洗剤", "歯磨き粉", "タオル", "ハンカチ", "ティッシュ",
            "犬", "猫", "うさぎ", "ハムスター", "ライオン", "ゾウ", "キリン", "ペンギン",
            "野球", "サッカー", "テニス", "バスケ", "バレー", "卓球", "水泳", "柔道",
            "数学", "英語", "国語", "理科", "社会", "音楽", "体育", "図工",
            "ピアノ", "ギター", "ドラム", "バイオリン", "フルート", "トランペット", "琴", "三味線",
            "教科書", "ノート", "鉛筆", "消しゴム", "定規", "コンパス", "筆箱", "ハサミ",
            "東京", "大阪", "名古屋", "福岡", "札幌", "沖縄", "京都", "横浜",
            "パン", "ごはん", "うどん", "そば", "餅", "ピザ", "サンドイッチ", "おにぎり"
        ]

    @app_commands.command(name="wordwolf", description="ワードウルフを開始（全体で3回までチャレンジ可能）")
    async def wordwolf(self, interaction: discord.Interaction):
        if self.game_running:
            await interaction.response.send_message("既にゲームが進行中です。", ephemeral=True)
            return

        self.game_running = False
        self.players = []
        self.alive_players = []
        self.player_words = {}
        self.remaining_challenges = 3 # ゲーム開始時にリセット
        
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

        selected_words = random.sample(self.word_pool, 2)
        common_word, wolf_word = selected_words
        self.wolf = random.choice(self.players)
        self.alive_players = self.players.copy()
        
        for p in self.players:
            self.player_words[p.id] = wolf_word if p == self.wolf else common_word

        check_view = CheckWordView(self)
        await interaction.channel.send(
            f"**ゲーム開始！** 参加者: {', '.join([p.display_name for p in self.players])}\n"
            f"各自ボタンでワードを確認してください。\n"
            f"⚠️ **【ルール】メンションで判定（全体で残り {self.remaining_challenges} 回まで）**\n"
            f"ウルフの自爆、または村人が回数内にウルフを当てれば村人勝利！",
            view=check_view
        )

        self.game_running = True
        self.bot.loop.create_task(self.game_timer(interaction.channel))

    async def game_timer(self, channel):
        """1分ごとに残り時間と生存プレイヤーリストを通知"""
        for i in range(4, 0, -1):
            await asyncio.sleep(60)
            if not self.game_running: return
            alive_names = [p.display_name for p in self.alive_players]
            await channel.send(
                f"⏰ **残り {i} 分** / **チャレンジ残り: {self.remaining_challenges}回**\n"
                f"生存者: {', '.join(alive_names)}"
            )
        
        await asyncio.sleep(60)
        if self.game_running:
            await self.end_game(channel, "time_up")

    @commands.Cog.listener()
    async def on_message(self, message):
        if not self.game_running or message.author.bot:
            return
        
        if message.mentions and message.author in self.alive_players:
            target = message.mentions[0]
            if target != message.author and target in self.alive_players:
                await self.execute_challenge(message.channel, message.author, target)

    async def execute_challenge(self, channel, challenger, target):
        self.remaining_challenges -= 1 # 回数を減らす
        role = discord.utils.get(channel.guild.roles, name="muted")
        
        # ウルフによるチャレンジ（自爆）
        if challenger == self.wolf:
            await channel.send(f"💥 **ウルフの自爆！** {challenger.mention} はウルフでしたが、村人 {target.mention} を指名したため敗北しました。")
            await self.end_game(channel, "villager_win")
            return

        # 村人によるチャレンジ
        if target == self.wolf:
            await channel.send(f"✅ **チャレンジ成功！** {target.mention} はウルフでした！村人の勝利です。")
            await self.end_game(channel, "villager_win")
        else:
            await channel.send(f"❌ **チャレンジ失敗！** {challenger.mention} は脱落。")
            await channel.send(f"⚠️ **チャレンジ残り回数: {self.remaining_challenges}回**")
            
            self.alive_players.remove(challenger)
            if role:
                try: await challenger.add_roles(role)
                except: pass
            
            # 勝利判定：残り回数が0、または生存者がウルフ含め2人以下
            if self.remaining_challenges <= 0:
                await channel.send("🚫 **チャレンジ回数が尽きました...**")
                await self.end_game(channel, "wolf_win")
            elif len(self.alive_players) <= 2:
                await self.end_game(channel, "wolf_win")
            else:
                alive_names = [p.display_name for p in self.alive_players]
                await channel.send(f"生存プレイヤー: {', '.join(alive_names)}")

    async def end_game(self, channel, result):
        self.game_running = False
        
        if result == "villager_win":
            msg = "🎉 **村人チームの勝利です！**"
        else:
            msg = f"🐺 **ウルフの勝利です！**\n正解は {self.wolf.mention} でした。"

        await channel.send(f"━━━━━━━━━━━━━━\n{msg}\n━━━━━━━━━━━━━━")
        
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
    await bot.add_cog(CustomWordWolf(bot))
