# -*- coding: utf-8 -*-
import discord
from discord.ext import commands
from discord import app_commands
import asyncio
import random

class GenshinWordWolfGame(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.game_running = False
        self.players = []
        self.alive_players = []
        self.wolf = None
        self.player_words = {}
        self.remaining_challenges = 3  # チャレンジ残り回数
        
        # 原神版ワードリスト（100語以上）
        self.word_pool = [
        "集光の異獣", "純水精霊", "遺跡サーペント", "山隠れの猊獣", "恒常からくり陣形", "魔偶剣鬼", "雷音権現", "黄金王獣", "マッシュラプトル", "半永久統制マトリックス", "兆載永劫ドレイク", "風蝕ウェネト", "深罪の浸礼者", "氷風組曲", "鉄甲溶炎帝王", "実験用フィールド生成装置", "千年真珠の海酸", "水形タルパ", "魔像レガトゥス", "貪食のユムカ竜", "金焔のクク竜", "秘源機兵・機巧デバイス", "深遠なるミミックパピラ", 
        "迷える霊覚の修験者", "輝ける溶岩の龍像", "秘源機兵・統御デバイス", "ボコボコダック", "集光の幻月蝶", "エゲリア", "原神", "七神", "七天神像", "天空", "モンド", "ウェンティ", "西風騎士団", "団長", "ジン", "ガイア", "ディルック", "アカツキワイナリー", "北風", "ファルカ", "ミカ", "アンバー", "レザー", "クレー", "ノエル", "空", "蛍", "パイモン", "トワリン", "リサ", "バーバラ", "ベネット", "フィッシュル", 
        "スクロース", "モナ", "ディオナ", "アルベド", "ロサリア", "エウルア", "ダリア", "アリス", "ドゥリン", "バーベロス", "レインドット", "ロノヴァ", "魈", "北斗", "凝光", "香菱", "行秋", "重雲", "七七", "刻晴", "鍾離", "辛炎", "甘雨", "胡桃", "白朮", "煙緋", "申鶴", "雲菫", "夜蘭", "ヨォーヨ", "閑雲", "嘉明", "藍硯", "璃月港", "仙人", "魔人", "禁忌滅却の札", "帰終機", "沈玉", "真君", "塵歌壺", 
        "神里綾華", "楓原万葉", "宵宮", "早柚", "雷電将軍", "雷電影", "八重神子", "トーマ", "ゴロー", "九条裟羅", "珊瑚宮心海", "荒瀧一斗", "神里綾人", "久岐忍", "鹿野院平蔵", "綺良々", "千織", "夢見月瑞希", "稲妻城", "天守閣", "鳴神大社", "淵下宮", "鶴観", "死兆星号", "ティナリ", "ドリー", "コレイ", "アルハイゼン", "ディシア", "ニィロウ", "ナヒーダ", "セノ", "キャンディス", "レイラ", "放浪者", 
        "ファルザン", "カーヴェ", "セトス", "スメール", "マハールッカデヴァータ", "アランナラ", "シャルロット", "リネ", "リネット", "フレミネ", "ナヴィア", "クロリンデ", "シグウィン", "リオセスリ", "ヌヴィレット", "フリーナ", "シュヴルーズ", "エミリエ", "エスコフィエ", "フォンテーヌ", "エピクレシス歌劇場", "フォンティナリア号", "アルケー", "ウーシア", "メロピデ要塞", "グロシ", "壁炉の家", "命の契約", 
        "往日の海", "メリュジーヌ", "水仙十字軍", "ムアラニ", "カチーナ", "キィニチ", "シトラリ", "シロネン", "イアンサ", "チャスカ", "マーヴィカ", "オロルン", "イファ", "ヴァレサ", "カクーク", "アハウ", "ナタ", "こだまの子", "懸木の民", "流泉の衆", "花翼の集い", "謎煙の主", "豊穣の邦", "夜魂", "燃素", "聖火", "アシャ", "古の聖山", "テペトル", "ユムカ", "コホラ", "クク", "イクトミ", "ライノ", "ドラゴンスパイン", "仙霊", 
        "層岩巨淵", "海灯祭", "風花祭", "花神誕祭", "光華容彩祭", "天理", "執政", "聖遺物", "七聖召喚", "エンジェルズシェア", "キャッツテール", "幾千のメロディー", "冒険者協会", "鹿狩り", "栄光の風", "合成台", "西風大聖堂", "燼寂海", "道化", "隊長", "博士", "少女", "召使", "雄鶏", "散兵", "傀儡", "淑女", "富者", "公子", "女皇", "モラクス", "ブエル", "バアル", "フォカロルス", "レムリア", "ハボリム", "イネファ", "ラウマ", 
        "アイノ", "ヤフォダ", "ネフェル", "フリンズ", "ニコ・リヤン", "ナシャタウン", "ヴォイニッチ商会", "スネージナヤ", "スネージナヤパレス", "教令院", "アルカサルザライパレス", "パルディスディアイ", "神の缶詰知識", "冬忍びの樹", "幽境の激戦", "幻想シアター", "深境螺旋", "「西風騎士団」後方支援", "「璃月総務司」幹事", "釣り協会", "明星斎", "群玉閣", "黄金屋", "春茶々房", "錦落の庭・祀瓏", "神櫻", "「社奉行」", "「設計者」若紫", 
        "鍛冶屋", "天目鍛冶屋", "木漏茶屋", "志村屋", "秋沙銭湯", "根付の源", "知恵の殿堂", "スラサタンナ聖処", "メナケリーショップ", "ランバト酒場", "「教令院」連絡官", "プスパカフェ", "夢の樹", "花海・甘露の池", "キングデシェレトの霊廟", "層岩巨淵安全技術員・瑾武", "カノティラと啓示の書", "ルキナの泉", "バーティンの珍奇館", "パレ-メルモニア", "ボーモント工房", "カフェ・リュテス", "スチームバード新聞", "ホテル・ドゥボール", 
        "神殿・灼石の円盤", "サルタリー溶鉱炉", "「談議室」", "ザカンの屋台", "「龍の遺物研究会」", "草臥の家", "部族秘蔵所", "源火の玉座", "天蛇の船", "フォルトゥナ号", "夜明かしの墓", "ライトキーパー", "クーヴァキ", "ワイルドハント", "アビス", "ファデュイ", "執行官", "魔女会", "霜月の子", "宝盗団", "雪国の妖精", "ツァーリ・ベールイ", "秘聞の館", "ダインスレイヴ", "アーロイ", "スカーク", "I・イヴァノヴナ・N", "アンデシュドッテル", 
        "オクタヴィア", "歌塵浪市真君", "削月築陽真君", "理水畳山真君", "移霄導天真君", "騰蛇大元師 浮舎", "螺巻大将 伐難", "火鼠大将 応達", "心猿大将 弥怒", "浮錦", "天空紀行", "脆弱樹脂", "冒険の証", "モラ", "空月の祝福", "紡がれた運命", "出会いの縁", "知恵の冠", "創世結晶", "原石", "仕上げ用雑鉱", "仕上げ用良鉱", "仕上げ用魔鉱", "霧切の廻光", "赦罪", "蒼耀", "風鷹剣", "ダークアレイの閃光", "波乱月白経津", "天空の刃", "斬山の刃", 
        "蒼古なる自由への誓い", "斬岩試作", "ストロングボーン", "厄水の災い", "黒岩の長剣", "月紡ぎの曙光", "原木刀", "海淵のフィナーレ", "有楽御簾切", "静水流転の輝き", "萃光の裁葉", "聖顕の鍵", "磐岩結緑", "岩峰を巡る歌", "腐植の剣", "狼牙", "旧貴族長剣", "水仙十字の剣", "笛の剣", "匣中龍吟", "籠釣瓶一心", "鉄峰の刺し", "サイフォスの月明かり", "黒剣", "船渠剣", "東花坊時雨", "サーンドルの渡し守", "シナバースピンドル", "天目影打", 
        "エズピツァルの笛", "祭礼の剣", "西風剣", "静謐の笛", "旅道の剣", "降臨の剣", "冷刃", "黎明の神剣", "チ虎魚の刀", "暗鉄剣", "飛天御剣", "銀の剣", "無鋒の剣", "松韻の響く頃", "千烈の日輪", "山の王の長牙", "裁断", "天空の傲", "葦海の標", "狼の末路", "無工の剣", "話死合い棒", "雪葬の星銀", "旧貴族大剣"
        ]


    @app_commands.command(name="genshin_wolf", description="原神版ワードウルフを開始（全体で3回までチャレンジ可能）")
    async def genshin_wolf(self, interaction: discord.Interaction):
        if self.game_running:
            await interaction.response.send_message("既にゲームが進行中です。", ephemeral=True)
            return

        self.game_running = False
        self.players = []
        self.alive_players = []
        self.player_words = {}
        self.remaining_challenges = 3 # リセット
        
        join_view = JoinView(self)
        await interaction.response.send_message(
            "🐺 **【原神版】ワードウルフ参加者募集中！**\n1分以内に【参加】ボタンを押してください。", 
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
        self.remaining_challenges -= 1
        role = discord.utils.get(channel.guild.roles, name="muted")
        
        if challenger == self.wolf:
            await channel.send(f"💥 **ウルフの自爆！** {challenger.mention} はウルフでしたが、村人 {target.mention} を指名したため敗北しました。")
            await self.end_game(channel, "villager_win")
            return

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
    await bot.add_cog(GenshinWordWolfGame(bot))
