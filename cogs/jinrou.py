import asyncio
import random
from collections import Counter
import os
import discord
from discord import app_commands
from discord.ext import commands

# ======================================================
#  白黒判定ユーティリティ
# ======================================================
BLACK_ROLES_URANAI = {"人狼", "入狼", "ワンころ", "メンヘラ", "ヤンデレ"}
BLACK_ROLES_REIBAI = {"人狼", "デカ狼", "入狼", "ワンころ", "メンヘラ", "ヤンデレ"}

def uranai_color(role: str) -> str:
    return "黒" if role in BLACK_ROLES_URANAI else "白"

def reibai_color(role: str) -> str:
    return "黒" if role in BLACK_ROLES_REIBAI else "白"

# ======================================================
#  ヘルプ用役職リスト（役職名, 陣営, 説明, 画像ファイル名）
# ======================================================
HELP_ROLES = [
    ("一般通過あごむに", "村人陣営", "空気。", "NOMAL.PNG"),
    ("タフむに", "村人陣営", "殺された時に最後の一撃で相手を道連れにする根性の一般通過。", "TAHUMUNI.PNG"),
    ("占い師", "村人陣営", "毎晩1人を占える。安物のビー玉を使って白か黒かを見抜く。", "URANAI.PNG"),
    ("霊媒師", "村人陣営", "昨日追放された者が白か黒か分かる。占い師とは商売敵なので中が悪い。", "REIBAI.PNG"),
    ("大霊媒師", "村人陣営", "霊媒師の上位職。追放者の白黒を自動通知に加え、夜に死者ならば誰でも調べられ役職まで判明する。", "DAIREIBAI.PNG"),
    ("騎士", "村人陣営", "毎晩1人をつまようじで守る。自分は守れない不器用なやつ。", "KISHI.PNG"),
    ("罠師", "村人陣営", "騎士の上位職。対象を守るだけでなく、狼が守った対象を襲撃した場合にその狼を返り討ちにする。", "WANASI.PNG"),
    ("入狼", "村人陣営", "人狼のような名前の村人。占われると黒判定が出る不幸なやつ。", "NYUROU.PNG"),
    ("パン屋", "村人陣営", "生きていれば朝にパンを配る。飯を食え。", "PANYA.PNG"),
    ("マサイ族", "村人陣営", "夜に1人を観察する。もし対象が人狼なら襲撃を50%で回避する準備を整える。真偽は誰にもわからない。", "MASAI.PNG"),
    ("議長", "村人陣営", "会議中に『スキップ』で議論を即終了→通常投票へ。ゲーム中一回だけ『強制投票』と発言すると議長専用の投票箱が設置され、議長が直接追放対象を選べる。", "GITYO.PNG"),
    ("ビー玉ブレイカー", "村人陣営", "占い師の判定が30%の確率でひっくり返る。", "BI-BURE.PNG"),
    ("リア充", "村人陣営", "2人1組で存在し、お互いが誰かを知っている。片方が死ぬともう片方も道連れになる。実は片方が不倫しているが見た目が同じにしか見えないのでどちらかかは分からない", "RIAJUU.PNG"),
    ("貴族", "村人陣営", "奴隷とセットで発生。死亡判定を自動的に奴隷に肩代わりさせることができる（奴隷が存在する場合）。奴隷が誰か分かる。", "KIZOKU.PNG"),
    ("奴隷", "村人陣営", "貴族とセットで発生。貴族が死ぬと代わりに死ぬ。貴族が誰か分かる。", "DOREI.PNG"),
    ("陽キャ", "村人陣営", "毎晩1人をℳ𝓎𝒽ℴ𝓂ℯに連れ込む。相手が人狼/デカ狼なら陽キャが死ぬ。相手がメンヘラなら2人ともリア充に変化。それ以外は酔い潰してそのプレイヤーの夜のアクションをキャンセルする。", "YOUKYA.PNG"),
    ("ミュージシャン", "村人陣営", "陽キャの発展職。ゲーム中1度だけ夜にパーティを開催してランダムに4人を招待できる。招待者は殺されなくなり夜のアクションもキャンセル。ただし人狼/デカ狼が混じっていた場合30%で招待者の中の非狼陣営が1人死亡。", "MUSICIAN.PNG"),
    ("ネット民", "村人陣営", "昼夜の発言タイミングが逆転する。昼に沈黙し、夜にのみ自由に発言できる。", "NETTAMIN.PNG"),
    ("人狼", "人狼陣営", "村人を食べる。仲間同士は誰が人狼か知っている。", "JINROU.PNG"),
    ("デカ狼", "人狼陣営", "占い師を賄賂で黙らせる人狼。占い師に白判定を出させる。霊媒師には黒と出る。", "DEKAROU.PNG"),
    ("狂人", "人狼陣営", "人狼の味方をする人間。人狼が誰かは知らないが、とにかく場を乱す。", "KYOJIN.PNG"),
    ("狂信者", "人狼陣営", "人狼とデカ狼が誰かを知っている熱狂的なファン。人狼陣営の参謀。", "KYOUSINSYA.PNG"),
    ("ヤンデレ", "人狼陣営", "メンヘラの発展職。人狼の中からランダムに1人を選び、その人狼に夜関わった人間を殺す。", "YANDERE.PNG"),
    ("ハゲ", "第三者陣営", "追放されたら勝利。髪の毛が観測できないバグのせいで目立ちすぎる。", "HAGE.PNG"),
    ("コウモリむに", "第三者陣営", "ハゲの上位職。ただし最後まで生き残れば追加勝利できる。", "KOUMORI.PNG"),
    ("メンヘラ", "人狼陣営", "自分に関与した（占う、守る、食べる）者を物理的に消去する。占うと黒判定が出る。", "MENHERA.PNG"),
    ("あごむに破道砲", "第三者陣営", "<a:BAKUHATU:1490259644717993995>自爆して対象を道連れにする。さらにもう1人も誤発で巻き込む。（※3日目の夜以降に使用可能）", "AGOMUNIHADOHOU.PNG"),
    ("ワンころ", "第三者陣営", "最初に飼い主を決める。飼い主が死ぬかいない場合は野良化して人狼になる。占うと黒判定が出る。", "WANKORO.PNG"),
    ("もくもく", "第三者陣営", "ビー玉ブレイカーの発展職。生きている間は全員の役職構成が非公開になる。死ぬと役職構成が公開される。夜のアクション終了時のゲームマスタログ報告が全てもくもくに差し替わる。効果は3ターンで終了。タバコではなくココアシガレット愛好家。", "MOKUMOKU.PNG"),
]

# ======================================================
#  ゲーム状態
# ======================================================
class JinrouGame:
    def __init__(self):
        self.is_running = False
        self.players = []
        self.roles = {}
        self.alive_players = []
        self.night_actions = {}
        self.voted_count = {}
        self.last_executed = None
        self.game_channel = None
        self.used_hadouhou = False
        self.day_count = 0
        self.wan_owner = {}
        self.masai_evasion = {}
        self.silenced_players = set()
        self.chairman_skip_event = None
        self.chairman_ketsugu_used = False
        self.chairman_ketsugu_target = None
        self.chairman_forced_vote = False
        self.chairman_vote_event = None
        self.in_discussion = False
        self.riacchu_pairs = []
        self.kizoku_slave = {}
        self.musician_party_used = False
        self.required_roles = []
        self.excluded_roles = []
        self.host_id = None
        self.game_mode = "pro"  # "basic" or "pro"
        self.mokumoku_turn_count = 0  # もくもくの効果ターンカウント

# ======================================================
#  Cog 本体
# ======================================================
class JinrouCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.games = {}

    def get_game(self, channel_id) -> JinrouGame:
        if channel_id not in self.games:
            self.games[channel_id] = JinrouGame()
        return self.games[channel_id]

    def get_wolves_names(self, game) -> str:
        wolves = []
        for p_id, role in game.roles.items():
            if role in ["人狼", "デカ狼"]:
                m = game.game_channel.guild.get_member(p_id)
                if m: wolves.append(m.display_name)
        return "、".join(wolves) if wolves else "なし"

    # ======================================================
    #  メッセージ監視（サイレンス＆議長コマンド）
    # ======================================================
    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot:
            return

        game = self.games.get(message.channel.id)
        if not game or not game.is_running:
            return

        player_role = game.roles.get(message.author.id)
        is_alive = any(p.id == message.author.id for p in game.alive_players)

        if player_role:
            if not is_alive:
                try:
                    await message.delete()
                except:
                    pass
                return

            if game.in_discussion:
                if player_role == "ネット民":
                    try:
                        await message.delete()
                    except:
                        pass
                    return
            else:
                is_chairman_voting = any(game.roles.get(p.id) == "議長" and p.id not in game.silenced_players for p in game.alive_players)
                if is_chairman_voting:
                    if player_role != "議長":
                        try:
                            await message.delete()
                        except:
                            pass
                        return
                elif player_role != "ネット民":
                    try:
                        await message.delete()
                    except:
                        pass
                    return

        if message.author.id in game.silenced_players:
            try:
                await message.delete()
            except:
                pass
            return

        if game.in_discussion:
            player_role = game.roles.get(message.author.id)
            is_alive = any(p.id == message.author.id for p in game.alive_players)

            if player_role == "議長" and is_alive:
                content = message.content.strip()

                if content == "スキップ":
                    if game.chairman_skip_event and not game.chairman_skip_event.is_set():
                        await game.game_channel.send("議長がスキップを宣言。議論を終了し投票フェーズに移行します。")
                        game.chairman_skip_event.set()

                elif content == "強制投票" and not game.chairman_ketsugu_used:
                    game.chairman_ketsugu_used = True
                    game.chairman_forced_vote = True
                    if game.chairman_skip_event and not game.chairman_skip_event.is_set():
                        game.chairman_skip_event.set()
                    await game.game_channel.send(
                        "議長が強制投票を宣言！ 議論を中断し、議長による投票に移行します。"
                    )

    # ======================================================
    #  役職割当
    # ======================================================
    def assign_roles(self, game):
        num = len(game.players)
        num_wolves = max(1, num // 4)

        # プロモーションマップ
        promotion_map = {
            "人狼":             "デカ狼",
            "騎士":             "罠師",
            "一般通過あごむに": "タフむに",
            "狂人":             "狂信者",
            "入狼":             "ワンころ",
            "ハゲ":             "コウモリむに",
            "霊媒師":           "大霊媒師",
            "陽キャ":           "ミュージシャン",
            "ビー玉ブレイカー": "もくもく",
            "メンヘラ":         "ヤンデレ",
        }

        def maybe_promote(role):
            # ベーシックモードでは発展職にしない
            if game.game_mode == "basic":
                return role
            if role in promotion_map and random.random() < 0.35:
                return promotion_map[role]
            return role

        excluded = set(game.excluded_roles)
        required = list(game.required_roles)

        # 必須役職（発展なし）
        pool = list(required)

        # 人狼の保証（必須役職の人狼系を差し引く）
        wolf_in_req = sum(1 for r in required if r in ["人狼", "デカ狼"])
        additional_wolves = max(0, num_wolves - wolf_in_req)
        for _ in range(min(additional_wolves, num - len(pool))):
            pool.append("人狼")

        # ランダム補充
        available = [r for r in [
            "一般通過あごむに", "占い師", "騎士", "霊媒師", "パン屋", "マサイ族",
            "入狼", "議長", "ビー玉ブレイカー", "リア充", "貴族", "奴隷", "陽キャ",
            "狂人", "ハゲ", "メンヘラ", "あごむに破道砲", "ネット民"
        ] if r not in excluded]

        while len(pool) < num and available:
            pool.append(random.choice(available))

        pool = pool[:num]

        # 2人役職（8人以上かつ30%の確率）
        if num >= 8 and random.random() < 0.3:
            pair_type = random.choice(["リア充", "貴族奴隷"])
            pair_roles = ["リア充", "リア充"] if pair_type == "リア充" else ["貴族", "奴隷"]

            replaceable = [i for i, r in enumerate(pool) if r in ["一般通過あごむに", "タフむに"]]
            if len(replaceable) >= 2:
                idxs = random.sample(replaceable, 2)
                for i, idx in enumerate(idxs):
                    pool[idx] = pair_roles[i]
            elif len(replaceable) == 1:
                pool[replaceable[0]] = pair_roles[0]
                if len(pool) < num:
                    pool.append(pair_roles[1])
                else:
                    pool[-1] = pair_roles[1]
            else:
                safe = [i for i, r in enumerate(pool) if r not in ["人狼", "デカ狼", "占い師"]]
                if len(safe) >= 2:
                    idxs = random.sample(safe, 2)
                    for i, idx in enumerate(idxs):
                        pool[idx] = pair_roles[i]

        pool = pool[:num]
        
        # プロモーション適用
        pool = [maybe_promote(r) for r in pool]
        random.shuffle(pool)

        for i, p in enumerate(game.players):
            game.roles[p.id] = pool[i]

        riacchu_ids = []
        kizoku_id = dorei_id = None
        for p in game.players:
            role = game.roles[p.id]
            if role == "リア充":   riacchu_ids.append(p.id)
            elif role == "貴族":   kizoku_id = p.id
            elif role == "奴隷":   dorei_id = p.id

        if len(riacchu_ids) >= 2:
            game.riacchu_pairs.append((riacchu_ids[0], riacchu_ids[1]))
        if kizoku_id and dorei_id:
            game.kizoku_slave[kizoku_id] = dorei_id

    # ======================================================
    #  もくもく死亡時の役職構成公開
    # ======================================================
    async def _check_mokumoku_reveal(self, game, dead_id):
        if game.roles.get(dead_id) != "もくもく":
            return
        if any(game.roles.get(p.id) == "もくもく" for p in game.alive_players):
            return
        roles_for_display = []
        for r in game.roles.values():
            if r == "タフむに":         roles_for_display.append("一般通過あごむに")
            elif r == "入狼":           roles_for_display.append("人狼")
            elif r == "大霊媒師":       roles_for_display.append("霊媒師")
            elif r == "ミュージシャン":  roles_for_display.append("陽キャ")
            elif r == "ヤンデレ":       roles_for_display.append("メンヘラ")
            elif r == "もくもく":       roles_for_display.append("ビー玉ブレイカー")
            else:                       roles_for_display.append(r)
        roles_list = " / ".join(set(roles_for_display))
        await game.game_channel.send(f"もくもくが姿を消した。役職構成が明らかになります！\n{roles_list}")

    # ======================================================
    #  コマンド
    # ======================================================
    @app_commands.command(name="kill", description="このチャンネルで進行中の人狼ゲームを強制終了します")
    async def kill(self, interaction: discord.Interaction):
        game = self.get_game(interaction.channel_id)
        if not game.is_running:
            embed = discord.Embed(description="このチャンネルで実行中のゲームはありません。", color=0xFFFFFF)
            return await interaction.response.send_message(embed=embed, ephemeral=True)

        game.is_running = False
        game.silenced_players.clear()
        game.in_discussion = False
        if game.chairman_skip_event:
            game.chairman_skip_event.set()
        if game.chairman_vote_event:
            game.chairman_vote_event.set()
        embed = discord.Embed(description="管理者によりゲームが強制終了されました。", color=0xFFFFFF)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="jinrou_help", description="各役職の詳細な説明を表示します")
    @app_commands.describe(private="自分だけに表示する場合はTrue、全員に表示する場合はFalse")
    async def jinrou_help(self, interaction: discord.Interaction, private: bool = True):
        view = HelpView()
        embed, file = view.make_embed_and_file()
        if file:
            await interaction.response.send_message(embed=embed, file=file, view=view, ephemeral=private)
        else:
            await interaction.response.send_message(embed=embed, view=view, ephemeral=private)

    @app_commands.command(name="jinrou", description="人狼ゲームを開始します")
    async def jinrou(self, interaction: discord.Interaction):
        game = self.get_game(interaction.channel_id)
        if game.is_running:
            embed = discord.Embed(description="このチャンネルでは既にゲームが進行中です。", color=0xFFFFFF)
            return await interaction.response.send_message(embed=embed, ephemeral=True)

        game.is_running = True
        game.host_id = interaction.user.id
        game.game_channel = interaction.channel
        game.players = []
        game.roles = {}
        game.day_count = 0
        game.wan_owner = {}
        game.used_hadouhou = False
        game.last_executed = None
        game.masai_evasion = {}
        game.silenced_players = set()
        game.chairman_ketsugu_used = False
        game.chairman_ketsugu_target = None
        game.chairman_forced_vote = False
        game.chairman_vote_event = None
        game.in_discussion = False
        game.riacchu_pairs = []
        game.kizoku_slave = {}
        game.musician_party_used = False
        game.required_roles = []
        game.excluded_roles = []
        game.game_mode = "pro"

        # モード選択パネル
        embed = discord.Embed(
            title="人狼ゲーム設定",
            description="ゲームモードを選択してください。",
            color=0xFFFFFF
        )
        await interaction.response.send_message(
            embed=embed,
            view=ModeSelectView(game, self, interaction.channel),
            ephemeral=True
        )

    async def run_from_hub(self, game: JinrouGame, channel, host_id: int = None):
        """play.py から create_task で呼ぶ。60秒待機してゲームループを開始。"""
        if host_id:
            game.host_id = host_id
        await asyncio.sleep(60)
        if not game.is_running:
            return
        await self._start_game_loop(game, channel)

    # ======================================================
    #  ゲームループ
    # ======================================================
    async def _start_game_loop(self, game: JinrouGame, channel):
        if len(game.players) < 5:
            game.is_running = False
            await channel.send("<:failed:1490986584676368535>参加者が5人未満のため、ゲームを中止します。")
            return

        game.alive_players = game.players.copy()
        self.assign_roles(game)

        mentions = " ".join([p.mention for p in game.players])

        # もくもく生存中は役職構成を非公開
        if any(game.roles.get(p.id) == "もくもく" for p in game.alive_players):
            roles_list = "（もくもくにより非公開）"
        else:
            roles_for_display = []
            for r in game.roles.values():
                if r == "タフむに":         roles_for_display.append("一般通過あごむに")
                elif r == "入狼":           roles_for_display.append("人狼")
                elif r == "大霊媒師":       roles_for_display.append("霊媒師")
                elif r == "ミュージシャン":  roles_for_display.append("陽キャ")
                elif r == "ヤンデレ":       roles_for_display.append("メンヘラ")
                elif r == "もくもく":       roles_for_display.append("ビー玉ブレイカー")
                else:                       roles_for_display.append(r)
            roles_list = " / ".join(set(roles_for_display))

        await channel.send(
            f"<:success:1490985168100659322>{mentions}\nゲーム開始。今回の役職内訳: {roles_list}\n下のボタンで自分の役職を確認してください。",
            view=RoleCheckView(game, self)
        )

        for pair in game.riacchu_pairs:
            for i, p_id in enumerate(pair):
                partner_id = pair[1] if i == 0 else pair[0]
                member  = channel.guild.get_member(p_id)
                partner = channel.guild.get_member(partner_id)
                if member and partner:
                    try:
                        await member.send(
                            f"あなたは **リア充** です。パートナーは **{partner.display_name}** です。"
                            f"片方が死ぬともう片方も道連れになります。"
                        )
                    except:
                        pass

        for kizoku_id, dorei_id in game.kizoku_slave.items():
            kizoku_m = channel.guild.get_member(kizoku_id)
            dorei_m  = channel.guild.get_member(dorei_id)
            if kizoku_m and dorei_m:
                try:
                    await kizoku_m.send(
                        f"あなたは **貴族** です。あなたの奴隷は **{dorei_m.display_name}** です。"
                        f"死亡判定がかかった際、奴隷が生存していれば自動的に肩代わりされます。"
                    )
                    await dorei_m.send(
                        f"あなたは **奴隷** です。あなたの貴族は **{kizoku_m.display_name}** です。"
                        f"貴族に死亡判定がかかると、代わりにあなたが死にます。"
                    )
                except:
                    pass

        try:
            await self.run_discussion(game, minutes=2, title="特別ディスカッション")

            while game.is_running:
                await self.run_night_phase(game)
                if not game.is_running or await self.check_victory(game): break

                game.chairman_ketsugu_target = None
                game.chairman_forced_vote = False
                await self.run_discussion(game, minutes=2.5, title="昼のディスカッション")
                if not game.is_running: break

                if game.chairman_forced_vote:
                    game.chairman_forced_vote = False
                    await self.run_chairman_vote_phase(game)
                else:
                    await self.run_voting_phase(game)

                if not game.is_running or await self.check_victory(game): break

        except Exception as e:
            print(f"Game Error: {e}")
        finally:
            game.silenced_players.clear()
            game.in_discussion = False
            if game.roles:
                try:
                    await self._announce_final_roles(game)
                except Exception:
                    pass
            game.is_running = False

    # ======================================================
    #  フェーズ処理
    # ======================================================
    async def run_discussion(self, game, minutes, title):
        if not game.is_running: return
        game.chairman_skip_event = asyncio.Event()
        game.in_discussion = True
        game._is_night = False  # ネット民の昼判定用
        await game.game_channel.send(f"ーー {title}（{minutes}分） ーー")
        if any(game.roles.get(p.id) == "パン屋" for p in game.alive_players):
            await game.game_channel.send("<:PANYA:1490254577558093944>パン屋がパンを焼きました")

        seconds = int(minutes * 60)
        for _ in range(seconds):
            if game.chairman_skip_event.is_set():
                break
            await asyncio.sleep(1)
            if not game.is_running:
                game.in_discussion = False
                return

        game.in_discussion = False
        await game.game_channel.send(f"ーー {title}終了 ーー")

    async def run_night_phase(self, game):
        if not game.is_running: return
        game.day_count += 1
        game._is_night = True  # ネット民の夜判定用
        game.mokumoku_turn_count += 1  # もくもくターンカウント
        await game.game_channel.send(f"ーー 第{game.day_count}夜（1分） ーー")
        game.silenced_players.update(p.id for p in game.alive_players)

        game.night_actions = {}
        view = NightActionView(game)
        msg = await game.game_channel.send("アクションを選択してください", view=view)

        req_roles = ["占い師", "騎士", "罠師", "人狼", "デカ狼", "あごむに破道砲", "マサイ族", "陽キャ"]
        if game.day_count == 1: req_roles.append("ワンころ")
        req = sum(1 for p in game.alive_players if game.roles.get(p.id) in req_roles)

        alive_ids = {p.id for p in game.alive_players}
        has_dead = any(p.id not in alive_ids for p in game.players)
        req += sum(1 for p in game.alive_players if game.roles.get(p.id) == "大霊媒師" and has_dead)
        req += sum(1 for p in game.alive_players if game.roles.get(p.id) == "ミュージシャン" and not game.musician_party_used)

        t = 0
        while len(game.night_actions) < req and t < 60:
            await asyncio.sleep(1)
            t += 1
            if not game.is_running: break

        try: await msg.delete()
        except: pass

        for p in game.alive_players:
            game.silenced_players.discard(p.id)

        await self.process_night_results(game)

    async def process_night_results(self, game):
        if not game.is_running: return
        dead_ids = set()
        wolf_attacks   = {}
        knight_targets = set()
        trap_targets   = {}
        psycho_killer_ids = {p.id for p in game.alive_players if game.roles.get(p.id) == "メンヘラ"}
        yandere_killer_ids = {p.id for p in game.alive_players if game.roles.get(p.id) == "ヤンデレ"}
        menhera_triggered = False
        cancelled_ids = set()
        musician_protected = set()

        for p_id, t_id in game.night_actions.items():
            role = game.roles.get(p_id)
            if role == "ミュージシャン" and t_id == 0 and not game.musician_party_used:
                game.musician_party_used = True
                candidates = [p for p in game.alive_players if p.id != p_id]
                party_count = min(4, len(candidates))
                if party_count > 0:
                    party_members = random.sample(candidates, party_count)
                    party_ids = {p.id for p in party_members}
                    party_names = []
                    for pid in party_ids:
                        m = game.game_channel.guild.get_member(pid)
                        if m: party_names.append(m.display_name)

                    await game.game_channel.send(
                        f"ミュージシャンがパーティを開催！ {', '.join(party_names)} が招待されました！"
                    )

                    for pid in party_ids:
                        cancelled_ids.add(pid)
                        musician_protected.add(pid)

                    wolf_in_party = [pid for pid in party_ids if game.roles.get(pid) in ["人狼", "デカ狼"]]
                    if wolf_in_party and random.random() < 0.3:
                        non_wolf_party = [pid for pid in party_ids if game.roles.get(pid) not in ["人狼", "デカ狼"]]
                        if non_wolf_party:
                            victim_id = random.choice(non_wolf_party)
                            dead_ids.add(victim_id)
                            victim_m = game.game_channel.guild.get_member(victim_id)
                            if victim_m:
                                await game.game_channel.send(
                                    f"<:JINROU:1490254581358264382> パーティに人狼が紛れ込んでいた！ {victim_m.display_name} が犠牲になりました..."
                                )
                break

        for p_id, t_id in list(game.night_actions.items()):
            role = game.roles.get(p_id)
            if role != "陽キャ":
                continue
            if p_id in cancelled_ids:
                continue

            t_role = game.roles.get(t_id)
            target_m = game.game_channel.guild.get_member(t_id)
            target_name = target_m.display_name if target_m else "不明"
            yoikya_m = game.game_channel.guild.get_member(p_id)
            yoikya_name = yoikya_m.display_name if yoikya_m else "不明"

            if t_role in ["人狼", "デカ狼"]:
                dead_ids.add(p_id)
                await game.game_channel.send(
                    f"<:NYUROU:1490254582977134672>{yoikya_name} が {target_name} をℳ𝓎𝒽ℴ𝓂ℯに誘ったが人狼に返り討ちにあった..."
                )
            elif t_role == "メンヘラ":
                game.roles[p_id] = "リア充"
                game.roles[t_id] = "リア充"
                game.riacchu_pairs.append((p_id, t_id))
                psycho_killer_ids.discard(t_id)
                await game.game_channel.send(
                    f"{yoikya_name} が {target_name}（メンヘラ）を堕とした！ 2人はリア充へと変化しました！"
                )
            else:
                cancelled_ids.add(t_id)
                await game.game_channel.send(
                    f"{yoikya_name} が {target_name} をℳ𝓎𝒽ℴ𝓂ℯに誘って酔い潰した！ {target_name} の夜のアクションはキャンセルされました。"
                )

        for p_id, t_id in game.night_actions.items():
            role = game.roles.get(p_id)

            if p_id in cancelled_ids:
                continue
            if t_id == 0:
                continue

            if t_id in psycho_killer_ids:
                dead_ids.add(p_id)
                menhera_triggered = True
            
            if t_id in yandere_killer_ids and role in ["人狼", "デカ狼"]:
                # ヤンデレの対象人狼が関わった者が殺される
                pass  # ここでは標記のみ

            if role in ["人狼", "デカ狼"]:
                wolf_attacks[p_id] = t_id
            elif role == "騎士":
                knight_targets.add(t_id)
            elif role == "罠師":
                trap_targets[t_id] = p_id
            elif role == "あごむに破道砲":
                dead_ids.add(p_id); dead_ids.add(t_id)
                game.used_hadouhou = True
                others = [p.id for p in game.alive_players if p.id not in [p_id, t_id]]
                if others: dead_ids.add(random.choice(others))
                await game.game_channel.send("あごむに破道砲が火を噴きました。")
            elif role == "ワンころ" and game.day_count == 1:
                game.wan_owner[p_id] = t_id

        if menhera_triggered:
            await game.game_channel.send("<:MENHERA:1490254584739008522>誰かがメンヘラに返り討ちにされました。")

        # ヤンデレ処理
        yandere_player_id = None
        for p_id in yandere_killer_ids:
            if p_id in {p.id for p in game.alive_players}:
                yandere_player_id = p_id
                break
        
        if yandere_player_id:
            # ヤンデレの対象人狼をランダムに選ぶ
            yandere_target_wolf = None
            target_wolves = [p_id for p_id in game.night_actions.keys() 
                            if game.roles.get(p_id) in ["人狼", "デカ狼"]]
            if target_wolves:
                yandere_target_wolf = random.choice(target_wolves)
                # その人狼が関わった者を殺す
                if yandere_target_wolf in game.night_actions:
                    victim_id = game.night_actions[yandere_target_wolf]
                    if victim_id != 0:
                        dead_ids.add(victim_id)
                        victim_m = game.game_channel.guild.get_member(victim_id)
                        if victim_m:
                            await game.game_channel.send(
                                f"<:MENHERA:1490254584739008522>ヤンデレの怨念が {victim_m.display_name} を襲った..."
                            )

        for wolf_id, target_id in wolf_attacks.items():
            if target_id in knight_targets and target_id not in musician_protected:
                if target_id not in masai_evasion_set:
                    continue
                trap = trap_targets.get(target_id)
                if trap:
                    dead_ids.add(wolf_id)
                    wolf_m = game.game_channel.guild.get_member(wolf_id)
                    if wolf_m:
                        await game.game_channel.send(
                            f"<:WANASI:1490254583948353556>罠師の罠が {wolf_m.display_name} を返り討ちにした！"
                        )
            elif target_id not in dead_ids and target_id not in musician_protected:
                dead_ids.add(target_id)

        masai_evasion_set = set(game.masai_evasion.keys())
        for wolf_id, target_id in wolf_attacks.items():
            if target_id in masai_evasion_set:
                if random.random() < 0.5:
                    del game.masai_evasion[target_id]
                    continue
            
            if target_id in knight_targets and target_id not in musician_protected:
                trap = trap_targets.get(target_id)
                if trap:
                    dead_ids.add(wolf_id)
                    wolf_m = game.game_channel.guild.get_member(wolf_id)
                    if wolf_m:
                        await game.game_channel.send(
                            f"<:WANASI:1490254583948353556>罠師の罠が {wolf_m.display_name} を返り討ちにした！"
                        )
            elif target_id not in dead_ids and target_id not in musician_protected:
                if target_id not in knight_targets:
                    dead_ids.add(target_id)

        game.masai_evasion.clear()

        # 通知用メッセージ（もくもくがいればもくもくに差し替え）
        mokumoku_exists = any(game.roles.get(p.id) == "もくもく" for p in game.alive_players)
        mokumoku_active = mokumoku_exists and game.mokumoku_turn_count <= 3
        
        report_msg = "ーー 夜のアクション終了 ーー\n"
        if dead_ids:
            dead_names = []
            for did in dead_ids:
                dm = game.game_channel.guild.get_member(did)
                if dm:
                    dead_names.append(dm.display_name)
            report_msg += f"<:NYUROU:1490254582977134672>死亡者: {', '.join(dead_names)}\n"
        else:
            report_msg += "夜間に死亡者はいません。\n"

        if mokumoku_active:
            # もくもくがいる場合、メッセージをもくもくに送信
            mokumoku_id = None
            for p_id in game.alive_players:
                if game.roles.get(p_id) == "もくもく":
                    mokumoku_id = p_id
                    break
            if mokumoku_id:
                try:
                    user = await game.game_channel.guild.fetch_member(mokumoku_id)
                    await user.send(report_msg)
                except:
                    await game.game_channel.send(report_msg)
        else:
            await game.game_channel.send(report_msg)

        # 死亡判定の適用
        for dead_id in dead_ids:
            if dead_id in {p.id for p in game.alive_players}:
                game.silenced_players.add(dead_id)
                game.alive_players = [p for p in game.alive_players if p.id != dead_id]

        for dead_id in dead_ids:
            await self._notify_reibai(game, dead_id)
            await self._check_mokumoku_reveal(game, dead_id)

    async def _notify_reibai(self, game, dead_id):
        dead_role = game.roles.get(dead_id)
        if not dead_role: return
        for p in game.alive_players:
            if game.roles.get(p.id) == "霊媒師":
                m = game.game_channel.guild.get_member(p.id)
                if m:
                    try:
                        embed = discord.Embed(
                            description=f"<:REIBAI:1490254585413148703>夜の霊媒結果: 【{reibai_color(dead_role)}】",
                            color=0xFFFFFF
                        )
                        await m.send(embed=embed)
                    except:
                        pass
            elif game.roles.get(p.id) == "大霊媒師":
                m = game.game_channel.guild.get_member(p.id)
                if m:
                    try:
                        embed = discord.Embed(
                            description=f"<:REIBAI:1490254585413148703>大霊媒結果: 【{reibai_color(dead_role)}】 役職: 【{dead_role}】",
                            color=0xFFFFFF
                        )
                        await m.send(embed=embed)
                    except:
                        pass

    async def check_victory(self, game) -> bool:
        if not game.is_running: return True

        alive_ids = {p.id for p in game.alive_players}
        wolves = [p for p in game.players if p.id in alive_ids and game.roles.get(p.id) in ["人狼", "デカ狼", "ヤンデレ"]]
        villagers = [p for p in game.players if p.id in alive_ids and game.roles.get(p.id) not in ["人狼", "デカ狼", "ハゲ", "コウモリむに", "メンヘラ", "ヤンデレ", "あごむに破道砲", "ワンころ"]]
        
        # ワンころの野良化チェック
        for p in game.players:
            if p.id in alive_ids and game.roles.get(p.id) == "ワンころ":
                owner_id = game.wan_owner.get(p.id)
                if owner_id is None or owner_id not in alive_ids:
                    wolves.append(p)

        if not wolves:
            await game.game_channel.send("<:success:1490985168100659322> 村人陣営の勝利です！")
            return True
        elif not villagers:
            await game.game_channel.send("<:f8cc0b1b5e501838:1491033609929490492> 人狼陣営の勝利です！")
            return True

        return False

    async def apply_forced_execution(self, game, target_id):
        if target_id not in {p.id for p in game.alive_players}:
            return
        
        target_m = game.game_channel.guild.get_member(target_id)
        if not target_m: return

        if game.roles.get(target_id) == "貴族":
            slave_id = game.kizoku_slave.get(target_id)
            if slave_id:
                slave_m = game.game_channel.guild.get_member(slave_id)
                if slave_m and slave_id in {p.id for p in game.alive_players}:
                    await game.game_channel.send(f"貴族の処刑判定が奴隷 {slave_m.display_name} に肩代わりされました。")
                    target_id = slave_id
                    target_m = slave_m

        await game.game_channel.send(f"{target_m.display_name} さんが追放されました。")

        await self._notify_reibai(game, target_id)
        await self._check_mokumoku_reveal(game, target_id)

        executed_role = game.roles.get(target_id)
        if executed_role == "ハゲ":
            await game.game_channel.send("<:f8cc0b1b5e501838:1491033609929490492>ハゲが追放された。ハゲの勝利です。")
            game.is_running = False
            return
        elif executed_role == "コウモリむに":
            await game.game_channel.send("コウモリむにが追放された。しかし追放ではコウモリむには勝利できない...")

        for pair in game.riacchu_pairs:
            if target_id in pair:
                partner_id = pair[1] if pair[0] == target_id else pair[0]
                if partner_id in {p.id for p in game.alive_players}:
                    partner_m = game.game_channel.guild.get_member(partner_id)
                    if partner_m:
                        await game.game_channel.send(f"リア充のパートナー {partner_m.display_name} も道連れになりました。")
                        game.silenced_players.add(partner_id)
                        game.alive_players = [p for p in game.alive_players if p.id != partner_id]
                break

        game.silenced_players.add(target_id)
        game.alive_players = [p for p in game.alive_players if p.id != target_id]

    async def _announce_final_roles(self, game):
        roles_str = " / ".join([f"{p.mention}: {game.roles.get(p.id)}" for p in game.players])
        await game.game_channel.send(f"ゲーム終了。最終役職:\n{roles_str}", view=ReplayView(game, self))

    async def run_voting_phase(self, game):
        if not game.is_running: return
        await game.game_channel.send("ーー 投票フェーズ（40秒） ーー")
        game.silenced_players.update(p.id for p in game.alive_players)

        opts = [discord.SelectOption(label=p.display_name, value=str(p.id)) for p in game.alive_players]
        opts.append(discord.SelectOption(label="スキップ", value="skip"))
        game.voted_count = {}
        view = PublicVoteView(game, opts)
        msg = await game.game_channel.send("生存者は投票してください", view=view)
        for _ in range(40):
            await asyncio.sleep(1)
            if not game.is_running: break
        try: await msg.delete()
        except: pass

        for p in game.alive_players:
            game.silenced_players.discard(p.id)

        if not game.voted_count:
            return await game.game_channel.send("投票なし。追放はありません。")

        counts = Counter(game.voted_count.values())
        most = counts.most_common()

        if len(most) > 1 and most[0][1] == most[1][1]:
            return await game.game_channel.send("同数票のためスキップされました。追放はありません。")

        target_id_str = most[0][0]
        if target_id_str == "skip":
            return await game.game_channel.send("投票の結果、スキップされました。追放はありません。")

        actual_target_id = int(target_id_str)
        target_m = game.game_channel.guild.get_member(actual_target_id)
        if not target_m:
            return

        if game.roles.get(actual_target_id) == "貴族":
            slave_id = game.kizoku_slave.get(actual_target_id)
            if slave_id:
                slave_m = game.game_channel.guild.get_member(slave_id)
                if slave_m and slave_id in {p.id for p in game.alive_players}:
                    await game.game_channel.send(f"貴族の処刑判定が奴隷 {slave_m.display_name} に肩代わりされました。")
                    actual_target_id = slave_id
                    target_m = slave_m

        await game.game_channel.send(f"{target_m.display_name} さんが追放されました。")
        game.last_executed = actual_target_id
        game.silenced_players.add(actual_target_id)
        game.alive_players = [p for p in game.alive_players if p.id != actual_target_id]

        await self._notify_reibai(game, actual_target_id)
        await self._check_mokumoku_reveal(game, actual_target_id)

        executed_role = game.roles.get(actual_target_id)
        if executed_role == "ハゲ":
            await game.game_channel.send("<:f8cc0b1b5e501838:1491033609929490492>ハゲが追放された。ハゲの勝利です。")
            game.is_running = False
            return
        elif executed_role == "コウモリむに":
            await game.game_channel.send("コウモリむにが追放された。しかし追放ではコウモリむには勝利できない...")

        for pair in game.riacchu_pairs:
            if actual_target_id in pair:
                partner_id = pair[1] if pair[0] == actual_target_id else pair[0]
                if partner_id in {p.id for p in game.alive_players}:
                    partner_m = game.game_channel.guild.get_member(partner_id)
                    if partner_m:
                        await game.game_channel.send(f"リア充のパートナー {partner_m.display_name} も道連れになりました。")
                        game.silenced_players.add(partner_id)
                        game.alive_players = [p for p in game.alive_players if p.id != partner_id]
                break

    async def run_chairman_vote_phase(self, game):
        if not game.is_running: return
        game.chairman_vote_event = asyncio.Event()
        game.chairman_ketsugu_target = None

        opts = [
            discord.SelectOption(label=p.display_name, value=str(p.id))
            for p in game.alive_players
            if game.roles.get(p.id) != "議長"
        ]
        if not opts:
            await game.game_channel.send("追放できる対象がいません。")
            return

        for p in game.alive_players:
            if game.roles.get(p.id) != "議長":
                game.silenced_players.add(p.id)

        view = ChairmanVoteView(game, opts)
        msg = await game.game_channel.send(
            "ーー 強制投票（60秒） ーー\n**議長のみ**が投票できます。追放する対象を選んでください。",
            view=view
        )

        t = 0
        while not game.chairman_vote_event.is_set() and t < 60:
            await asyncio.sleep(1)
            t += 1
            if not game.is_running: break

        try: await msg.delete()
        except: pass

        for p in game.alive_players:
            game.silenced_players.discard(p.id)

        if game.chairman_ketsugu_target:
            await self.apply_forced_execution(game, game.chairman_ketsugu_target)
            game.chairman_ketsugu_target = None
        else:
            await game.game_channel.send("議長が時間内に投票しなかった。追放はありません。")


# ======================================================
#  UI Components
# ======================================================

class ModeSelectView(discord.ui.View):
    """ゲームモード選択パネル"""
    def __init__(self, game, cog, channel):
        super().__init__(timeout=60)
        self.game = game
        self.cog = cog
        self.channel = channel

    @discord.ui.button(label="ベーシック（発展職なし）", style=discord.ButtonStyle.primary)
    async def basic_mode(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.game.game_mode = "basic"
        await self._proceed_to_setup(interaction)

    @discord.ui.button(label="プロ（発展職あり）", style=discord.ButtonStyle.success)
    async def pro_mode(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.game.game_mode = "pro"
        await self._proceed_to_setup(interaction)

    async def _proceed_to_setup(self, interaction: discord.Interaction):
        self.stop()
        embed = discord.Embed(
            title="人狼ゲーム設定",
            description="必須役職・除外役職を設定してください。\nモード: " + ("ベーシック" if self.game.game_mode == "basic" else "プロ"),
            color=0xFFFFFF
        )
        await interaction.response.edit_message(
            embed=embed,
            view=SetupView(self.game, self.cog, self.channel)
        )

    async def on_timeout(self):
        self.game.is_running = False


class SetupView(discord.ui.View):
    """役職指定パネル（基本職選択）"""
    BASIC_ROLES = [
        "一般通過あごむに", "占い師", "騎士", "霊媒師", "パン屋", "マサイ族",
        "入狼", "議長", "ビー玉ブレイカー", "リア充", "貴族", "奴隷", "陽キャ", "ネット民",
        "人狼", "狂人", "ハゲ", "メンヘラ", "あごむに破道砲",
    ]

    def __init__(self, game, cog, channel):
        super().__init__(timeout=120)
        self.game = game
        self.cog = cog
        self.channel = channel
        self.selected_basic = []

        opts = [discord.SelectOption(label=r, value=r) for r in self.BASIC_ROLES]

        req_sel = discord.ui.Select(
            placeholder="必須役職を選択（最大4つ・基本職のみ）",
            options=opts,
            min_values=0, max_values=4,
            row=0
        )
        req_sel.callback = self._req_callback
        self.add_item(req_sel)

        exc_sel = discord.ui.Select(
            placeholder="除外役職を選択（最大4つ）",
            options=[discord.SelectOption(label=r, value=r) for r in self.BASIC_ROLES],
            min_values=0, max_values=4,
            row=1
        )
        exc_sel.callback = self._exc_callback
        self.add_item(exc_sel)

    async def _req_callback(self, interaction: discord.Interaction):
        self.selected_basic = list(interaction.data.get("values", []))
        self.game.required_roles = list(self.selected_basic)
        await interaction.response.defer()

    async def _exc_callback(self, interaction: discord.Interaction):
        self.game.excluded_roles = list(interaction.data.get("values", []))
        await interaction.response.defer()

    @discord.ui.button(label="確定して発展職を指定", style=discord.ButtonStyle.primary, row=2)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.stop()
        remaining_slots = 4 - len(self.selected_basic)
        
        if remaining_slots > 0 and self.game.game_mode == "pro":
            embed = discord.Embed(
                description=f"基本職を確定しました。発展職を{remaining_slots}つ選択してください。",
                color=0xFFFFFF
            )
            await interaction.response.edit_message(
                embed=embed,
                view=AdvancedRoleSelectView(self.game, self.cog, self.channel, remaining_slots)
            )
        else:
            await self._finalize_setup(interaction)

    async def _finalize_setup(self, interaction: discord.Interaction):
        req_str = "、".join(self.game.required_roles) if self.game.required_roles else "なし"
        exc_str = "、".join(self.game.excluded_roles) if self.game.excluded_roles else "なし"
        await interaction.response.edit_message(
            embed=discord.Embed(
                description=f"設定完了。\n必須: **{req_str}**\n除外: **{exc_str}**",
                color=0xFFFFFF
            ),
            view=None
        )
        view = RecruitView(self.game, self.cog)
        req_str2 = f" 【必須: {req_str}】" if self.game.required_roles else ""
        await self.channel.send(
            f"<a:POYOPOYO:1490724627805110392>人狼ゲーム募集開始！{req_str2}",
            view=view
        )

    async def on_timeout(self):
        self.game.is_running = False


class AdvancedRoleSelectView(discord.ui.View):
    """発展職選択パネル"""
    ADVANCED_ROLES = [
        "タフむに", "大霊媒師", "罠師", "ミュージシャン",
        "デカ狼", "狂信者", "コウモリむに", "ワンころ", "もくもく", "ヤンデレ"
    ]

    def __init__(self, game, cog, channel, remaining_slots):
        super().__init__(timeout=120)
        self.game = game
        self.cog = cog
        self.channel = channel
        self.remaining_slots = remaining_slots
        self.selected_advanced = []

        opts = [discord.SelectOption(label=r, value=r) for r in self.ADVANCED_ROLES]
        adv_sel = discord.ui.Select(
            placeholder=f"発展職を選択（最大{remaining_slots}つ）",
            options=opts,
            min_values=0, max_values=remaining_slots,
            row=0
        )
        adv_sel.callback = self._adv_callback
        self.add_item(adv_sel)

    async def _adv_callback(self, interaction: discord.Interaction):
        self.selected_advanced = list(interaction.data.get("values", []))
        self.game.required_roles.extend(self.selected_advanced)
        await interaction.response.defer()

    @discord.ui.button(label="確定してパネルを送信", style=discord.ButtonStyle.primary, row=1)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.stop()
        req_str = "、".join(self.game.required_roles) if self.game.required_roles else "なし"
        exc_str = "、".join(self.game.excluded_roles) if self.game.excluded_roles else "なし"
        await interaction.response.edit_message(
            embed=discord.Embed(
                description=f"設定完了。\n必須: **{req_str}**\n除外: **{exc_str}**\nモード: **{('ベーシック' if self.game.game_mode == 'basic' else 'プロ')}**",
                color=0xFFFFFF
            ),
            view=None
        )
        view = RecruitView(self.game, self.cog)
        req_str2 = f" 【必須: {req_str}】" if self.game.required_roles else ""
        await self.channel.send(
            f"<a:POYOPOYO:1490724627805110392>人狼ゲーム募集開始！{req_str2}",
            view=view
        )

    async def on_timeout(self):
        self.game.is_running = False


class RecruitView(discord.ui.View):
    def __init__(self, game, cog):
        super().__init__(timeout=None)
        self.game = game
        self.cog = cog

    @discord.ui.button(label="参加する", style=discord.ButtonStyle.success)
    async def join(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user in self.game.players:
            embed = discord.Embed(description="既に参加しています。", color=0xFFFFFF)
            return await interaction.response.send_message(embed=embed, ephemeral=True)
        self.game.players.append(interaction.user)
        await interaction.response.send_message(
            f"<a:AGOMUNIMUNI:1490255555632037909>{interaction.user.display_name} さんが参加しました。"
        )

    @discord.ui.button(label="キャンセル", style=discord.ButtonStyle.danger)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user not in self.game.players:
            embed = discord.Embed(description="参加していません。", color=0xFFFFFF)
            return await interaction.response.send_message(embed=embed, ephemeral=True)
        self.game.players.remove(interaction.user)
        await interaction.response.send_message(
            f"{interaction.user.display_name} さんが参加をキャンセルしました。"
        )

    @discord.ui.button(label="スタート", style=discord.ButtonStyle.primary)
    async def start(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.game.host_id:
            embed = discord.Embed(description="スタートできるのはゲームを起動した人のみです。", color=0xFFFFFF)
            return await interaction.response.send_message(embed=embed, ephemeral=True)
        self.stop()
        await interaction.response.send_message("ゲームを開始します！")
        asyncio.create_task(self.cog._start_game_loop(self.game, self.game.game_channel))


class ReplayView(discord.ui.View):
    """最終役職開示後の再戦ボタン"""
    def __init__(self, game, cog):
        super().__init__(timeout=300)
        self.game = game
        self.cog = cog

    @discord.ui.button(label="再戦", style=discord.ButtonStyle.primary)
    async def replay(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.game.host_id:
            embed = discord.Embed(description="再戦を開始できるのはゲームを起動した人のみです。", color=0xFFFFFF)
            return await interaction.response.send_message(embed=embed, ephemeral=True)

        old_required = self.game.required_roles[:]
        old_excluded = self.game.excluded_roles[:]
        host_id = self.game.host_id
        channel = interaction.channel

        new_game = JinrouGame()
        new_game.is_running = True
        new_game.host_id = host_id
        new_game.game_channel = channel
        new_game.required_roles = old_required
        new_game.excluded_roles = old_excluded
        self.cog.games[channel.id] = new_game

        self.stop()
        req_str = "、".join(old_required) if old_required else "なし"
        exc_str = "、".join(old_excluded) if old_excluded else "なし"
        await interaction.response.send_message(
            f"<a:POYOPOYO:1490724627805110392>再戦開始！ 必須: {req_str} / 除外: {exc_str}",
            view=RecruitView(new_game, self.cog)
        )


class HelpView(discord.ui.View):
    """ページめくり型ヘルプ"""
    def __init__(self):
        super().__init__(timeout=120)
        self.page = 0

    def make_embed_and_file(self):
        role_name, faction, desc, img_filename = HELP_ROLES[self.page]
        embed = discord.Embed(
            title=f"【{faction}】 {role_name}",
            description=desc,
            color=0xFFFFFF
        )
        embed.set_footer(text=f"{self.page + 1} / {len(HELP_ROLES)}")
        file = None
        if img_filename:
            path = f"Assets/{img_filename}"
            if os.path.exists(path):
                file = discord.File(path, filename="role_img.png")
                embed.set_image(url="attachment://role_img.png")
        return embed, file

    @discord.ui.button(label="◀", style=discord.ButtonStyle.secondary)
    async def prev_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page = (self.page - 1) % len(HELP_ROLES)
        embed, file = self.make_embed_and_file()
        if file:
            await interaction.response.edit_message(embed=embed, view=self, attachments=[file])
        else:
            await interaction.response.edit_message(embed=embed, view=self, attachments=[])

    @discord.ui.button(label="▶", style=discord.ButtonStyle.secondary)
    async def next_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page = (self.page + 1) % len(HELP_ROLES)
        embed, file = self.make_embed_and_file()
        if file:
            await interaction.response.edit_message(embed=embed, view=self, attachments=[file])
        else:
            await interaction.response.edit_message(embed=embed, view=self, attachments=[])


class RoleCheckView(discord.ui.View):
    def __init__(self, game, cog):
        super().__init__(timeout=None)
        self.game, self.cog = game, cog

    @discord.ui.button(label="役職確認", style=discord.ButtonStyle.primary)
    async def check(self, interaction: discord.Interaction, button: discord.ui.Button):
        real_role = self.game.roles.get(interaction.user.id)
        if real_role is None:
            embed = discord.Embed(description="あなたはゲームに参加していません。", color=0xFFFFFF)
            return await interaction.response.send_message(embed=embed, ephemeral=True)

        display_role = real_role
        if real_role == "タフむに":       display_role = "一般通過あごむに"
        elif real_role == "入狼":         display_role = "人狼"
        elif real_role == "大霊媒師":     display_role = "霊媒師"
        elif real_role == "ミュージシャン": display_role = "陽キャ"
        elif real_role == "もくもく":     display_role = "ビー玉ブレイカー"

        role_info = next((item for item in HELP_ROLES if item[0] == real_role), None)
        if not role_info:
            embed = discord.Embed(description="役職の詳細が見つかりません。", color=0xFFFFFF)
            return await interaction.response.send_message(embed=embed, ephemeral=True)

        role_name, faction, desc, img_filename = role_info

        if real_role in ["人狼", "デカ狼", "狂信者"]:
            wolves = self.cog.get_wolves_names(self.game)
            desc += f" 仲間: {wolves}"
        elif real_role == "リア充":
            partner_name = "不明"
            for pair in self.game.riacchu_pairs:
                if interaction.user.id in pair:
                    partner_id = pair[1] if pair[0] == interaction.user.id else pair[0]
                    partner_m = self.game.game_channel.guild.get_member(partner_id)
                    if partner_m: partner_name = partner_m.display_name
            desc += f" パートナー: {partner_name}"
        elif real_role == "貴族":
            slave_name = "不明"
            slave_id = self.game.kizoku_slave.get(interaction.user.id)
            if slave_id:
                slave_m = self.game.game_channel.guild.get_member(slave_id)
                if slave_m: slave_name = slave_m.display_name
            desc += f" 奴隷: {slave_name}"
        elif real_role == "奴隷":
            kizoku_name = "不明"
            for k_id, s_id in self.game.kizoku_slave.items():
                if s_id == interaction.user.id:
                    k_m = self.game.game_channel.guild.get_member(k_id)
                    if k_m: kizoku_name = k_m.display_name
                    break
            desc += f" 貴族: {kizoku_name}"

        embed = discord.Embed(
            title=f"あなたの役職は 【{display_role}】 です",
            description=f"【{faction}】 {desc}",
            color=0xFFFFFF
        )

        if img_filename:
            file_path = f"Assets/{img_filename}"
            if os.path.exists(file_path):
                file = discord.File(file_path, filename="role_img.png")
                embed.set_image(url="attachment://role_img.png")
                await interaction.response.send_message(embed=embed, file=file, ephemeral=True)
                return

        await interaction.response.send_message(embed=embed, ephemeral=True)

class NightActionView(discord.ui.View):
    def __init__(self, game):
        super().__init__(timeout=60)
        self.game = game

    @discord.ui.button(label="夜のアクション", style=discord.ButtonStyle.success)
    async def action(self, interaction: discord.Interaction, button: discord.ui.Button):
        p_id = interaction.user.id
        if p_id not in [p.id for p in self.game.alive_players]: return

        if p_id in self.game.night_actions:
            embed = discord.Embed(description="アクションは既に完了しています。欲張らないでください。", color=0xFFFFFF)
            return await interaction.response.send_message(embed=embed, ephemeral=True)

        role = self.game.roles.get(p_id)

        if role == "あごむに破道砲" and self.game.day_count < 3:
            embed = discord.Embed(description=f"あごむに破道砲は第3夜からしか使用できません。(現在は第{self.game.day_count}夜)", color=0xFFFFFF)
            return await interaction.response.send_message(embed=embed, ephemeral=True)

        if role == "大霊媒師":
            alive_ids = {p.id for p in self.game.alive_players}
            dead_players = [p for p in self.game.players if p.id not in alive_ids and p.id != p_id]
            if not dead_players:
                embed = discord.Embed(description="調べられる死者がいません。今夜は待機です。", color=0xFFFFFF)
                return await interaction.response.send_message(embed=embed, ephemeral=True)
            opts = [discord.SelectOption(label=p.display_name, value=str(p.id)) for p in dead_players]
            embed = discord.Embed(description="調べる死者を選択してください：", color=0xFFFFFF)
            return await interaction.response.send_message(embed=embed, view=ActionSelectView(self.game, opts, role), ephemeral=True)

        if role == "ミュージシャン":
            if self.game.musician_party_used:
                embed = discord.Embed(description="パーティは既に開催済みです。今夜は待機してください。", color=0xFFFFFF)
                return await interaction.response.send_message(embed=embed, ephemeral=True)
            self.game.night_actions[p_id] = 0
            embed = discord.Embed(description="🎵 パーティを開催します！ランダムに4人を招待します。", color=0xFFFFFF)
            return await interaction.response.send_message(embed=embed, ephemeral=True)

        passive_roles = [
            "一般通過あごむに", "霊媒師", "狂人", "ハゲ", "コウモリむに",
            "メンヘラ", "パン屋", "入狼", "タフむに", "狂信者",
            "ビー玉ブレイカー", "もくもく", "リア充", "貴族", "奴隷", "議長", "ネット民"
        ]
        if role in passive_roles:
            embed = discord.Embed(description="お前は寝てろ。明日の朝までじっとしてなさい。", color=0xFFFFFF)
            return await interaction.response.send_message(embed=embed, ephemeral=True)

        opts = [discord.SelectOption(label=p.display_name, value=str(p.id)) for p in self.game.alive_players if p.id != p_id]
        if not opts:
            embed = discord.Embed(description="対象がいません。", color=0xFFFFFF)
            return await interaction.response.send_message(embed=embed, ephemeral=True)

        embed = discord.Embed(description="対象を選択してください：", color=0xFFFFFF)
        await interaction.response.send_message(embed=embed, view=ActionSelectView(self.game, opts, role), ephemeral=True)


class ActionSelectView(discord.ui.View):
    def __init__(self, game, options, role):
        super().__init__(timeout=60)
        self.game, self.role = game, role
        s = discord.ui.Select(options=options)
        s.callback = self.callback
        self.add_item(s)

    async def callback(self, interaction: discord.Interaction):
        p_id = interaction.user.id
        if p_id in self.game.night_actions:
            embed = discord.Embed(description="既にアクションは受理されています。", color=0xFFFFFF)
            return await interaction.response.send_message(embed=embed, ephemeral=True)

        t_id = int(self.children[0].values[0])
        self.game.night_actions[p_id] = t_id

        if self.role == "占い師":
            r = self.game.roles.get(t_id)
            if r == "デカ狼":
                res = "白"
            else:
                res = uranai_color(r)
            # ビー玉ブレイカー/もくもく生存で30%逆転
            if any(self.game.roles.get(p.id) in ["ビー玉ブレイカー", "もくもく"] for p in self.game.alive_players):
                if random.random() < 0.3:
                    res = "白" if res == "黒" else "黒"
            embed = discord.Embed(description=f"<:URANAI:1490255412837093568>占い結果: 【{res}】", color=0xFFFFFF)
            await interaction.response.send_message(embed=embed, ephemeral=True)

        elif self.role == "大霊媒師":
            r = self.game.roles.get(t_id)
            color = reibai_color(r)
            embed = discord.Embed(
                description=f"<:REIBAI:1490254585413148703>大霊媒師の結果: 【{color}】 役職: 【{r}】",
                color=0xFFFFFF
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)

        elif self.role == "マサイ族":
            r = self.game.roles.get(t_id)
            if r in ["人狼", "デカ狼"]:
                self.game.masai_evasion[p_id] = True
            embed = discord.Embed(description="<:MASAI:1490254590757572758>対象の観察を完了しました。人狼であれば回避の準備を整える。", color=0xFFFFFF)
            await interaction.response.send_message(embed=embed, ephemeral=True)
        elif self.role == "罠師":
            embed = discord.Embed(description="対象に罠を設置しました。狼が攻撃した場合、返り討ちにします。", color=0xFFFFFF)
            await interaction.response.send_message(embed=embed, ephemeral=True)
        elif self.role == "ワンころ" and self.game.day_count == 1:
            master_m = self.game.game_channel.guild.get_member(t_id) if self.game.game_channel else None
            master_name = master_m.display_name if master_m else "不明"
            embed = discord.Embed(description=f"飼い主を **{master_name}** に決めました。飼い主が生きている間はあなたも村人陣営です。", color=0xFFFFFF)
            await interaction.response.send_message(embed=embed, ephemeral=True)
        elif self.role == "陽キャ":
            t_m = self.game.game_channel.guild.get_member(t_id)
            t_name = t_m.display_name if t_m else "不明"
            embed = discord.Embed(description=f"🎉 {t_name} をℳ𝓎𝒽ℴ𝓂ℯに誘います。", color=0xFFFFFF)
            await interaction.response.send_message(embed=embed, ephemeral=True)
        else:
            embed = discord.Embed(description="完了。", color=0xFFFFFF)
            await interaction.response.send_message(embed=embed, ephemeral=True)


class PublicVoteView(discord.ui.View):
    def __init__(self, game, options):
        super().__init__(timeout=60)
        self.game = game
        s = discord.ui.Select(options=options)
        s.callback = self.callback
        self.add_item(s)

    async def callback(self, interaction: discord.Interaction):
        p_id = interaction.user.id
        if p_id not in [p.id for p in self.game.alive_players]:
            embed = discord.Embed(description="死人に口なし。墓場で大人しくしていなさい。", color=0xFFFFFF)
            return await interaction.response.send_message(embed=embed, ephemeral=True)

        if p_id in self.game.voted_count:
            embed = discord.Embed(description="既に投票済みです。意志を何度も変えることはできません。", color=0xFFFFFF)
            return await interaction.response.send_message(embed=embed, ephemeral=True)

        self.game.voted_count[p_id] = self.children[0].values[0]
        await interaction.response.send_message(f"<:success:1490985168100659322> {interaction.user.display_name} さんが投票を完了しました。")


class ChairmanVoteView(discord.ui.View):
    def __init__(self, game, options):
        super().__init__(timeout=60)
        self.game = game
        self.voted = False
        s = discord.ui.Select(options=options, placeholder="追放する対象を選んでください")
        s.callback = self.callback
        self.add_item(s)

    async def callback(self, interaction: discord.Interaction):
        p_id = interaction.user.id

        if self.game.roles.get(p_id) != "議長":
            embed = discord.Embed(description="この投票は議長のみ行えます。", color=0xFFFFFF)
            return await interaction.response.send_message(embed=embed, ephemeral=True)

        if self.voted:
            embed = discord.Embed(description="既に投票済みです。", color=0xFFFFFF)
            return await interaction.response.send_message(embed=embed, ephemeral=True)

        self.voted = True
        t_id = int(self.children[0].values[0])
        self.game.chairman_ketsugu_target = t_id

        if self.game.chairman_vote_event:
            self.game.chairman_vote_event.set()

        target_m = self.game.game_channel.guild.get_member(t_id)
        target_name = target_m.display_name if target_m else "不明"
        await interaction.response.send_message(
            f"議長が **{target_name}** を選びました。強制投票完了。"
        )


async def setup(bot):
    await bot.add_cog(JinrouCog(bot))