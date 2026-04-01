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
        self.players = []
        self.alive_players = []
        self.wolf = None
        self.player_words = {}
        
        # 100語以上のワードリスト
        self.word_pool = [
            "雪衣", "霊砂", "椒丘", "トパーズ", "愉悦", "調和", "ペラ", "ルカ",
            "青雀", "昼夜の狭間を駆ける鷹", "成り上がりチャンピオン", "星の如く輝く天才", "泥の如き眠り", "存護", "均衡", "貪欲",
            "壊滅", "姫子", "ジェパード", "ゴーナウス", "これがウチだよ！", "防衛", "彼女が観ると決めた時", "きらびやかな世界",
            "繁殖", "記憶", "タケタケ冒険記", "ルアン・メェイ", "停雲", "帰忘の流離人", "乱破", "アルジェンティ",
            "2度目の生に向かって", "フォローして！", "論剣", "夜の帷の中で", "燃え盛る黎明のように", "フレイムスティーラー", "フォフォ", "Dr.レイシオ",
            "獲物の視線", "彼女の炎を忘れずに", "待つのみ", "だが戦争は終わらない", "ヘルタ", "マダムヘルタ", "その一刻、目に焼き付けて", "ブートヒル",
            "初めてのクエストの前に", "星海巡行", "銀河鉄道の夜", "折れた竜骨", "天体階差機関", "ウェンワーク", "サルソット", "爻光",
            "セイバー", "サフェル", "アーチャー", "アーラン", "雲璃", "丹恒", "丹恒飲月", "丹恒騰荒",
            "刃", "銀狼", "開拓者", "羅刹", "サンポ", "アグライア", "黄泉", "カカワーシャ",
            "景元", "モゼ", "虚照", "花火", "火花", "フェルマータ", "輪形", "アベンチュリン",
            "トリビー", "ホタル", "ダリア", "空の虹が消えぬように", "生命、消滅すべし", "ダンスダンスダンス", "ライコス", "鉄墓",
            "ケリュドラ", "セイレンス", "ロビン", "ブラックスワン", "カフカ", "アキヴィリ", "薬師", "アッハ",
            "百露", "ゼーレ", "フック", "エリシア", "キュレネ", "長夜月", "三月なのか", "ヴェルト",
            "鏡流", "不死途", "飛霄", "ヒアンシー", "ファイノン", "キャストリス", "クラーラ", "彦"
        ]

    @app_commands.command(name="wordwolf", description="ワードウルフを開始（生存者リスト通知あり）")
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
            "⚠️ **【ルール】メンションでチャレンジ判定！**\n"
            "村人が失敗：脱落。ウルフが失敗：即敗北。",
            view=check_view
        )

        self.game_running = True
        self.bot.loop.create_task(self.game_timer(interaction.channel))

    async def game_timer(self, channel):
        """1分ごとに残り時間と生存プレイヤーリストを通知"""
        for i in range(4, 0, -1):
            await asyncio.sleep(60)
            if not self.game_running: return
            
            # 生存者の名前をリスト化
            alive_names = [p.display_name for p in self.alive_players]
            await channel.send(
                f"⏰ **残り {i} 分**\n"
                f"生存プレイヤー: {', '.join(alive_names)}"
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
        role = discord.utils.get(channel.guild.roles, name="muted")
        
        if challenger == self.wolf:
            await channel.send(f"💥 **ウルフの自爆！** {challenger.mention} はウルフでしたが、村人 {target.mention} を指名したため敗北しました。")
            await self.end_game(channel, "villager_win")
            return

        if target == self.wolf:
            await channel.send(f"✅ **チャレンジ成功！** {target.mention} はウルフでした！村人の勝利です。")
            await self.end_game(channel, "villager_win")
        else:
            await channel.send(f"❌ **チャレンジ失敗！** {challenger.mention} は脱落しました。")
            self.alive_players.remove(challenger)
            
            if role:
                try: await challenger.add_roles(role)
                except: pass
            
            if len(self.alive_players) <= 2:
                await self.end_game(channel, "wolf_win")
            else:
                # 脱落後の生存者リストも表示
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
