import asyncio
import random
from collections import Counter
import os
import discord
from discord import app_commands
from discord.ext import commands

# ======================================================
#  ゲーム状態
# ======================================================
class JinrouGame:
    def __init__(self):
        self.is_running = False
        self.players = []
        self.roles = {}          # {user_id: role_name}
        self.alive_players = []
        self.night_actions = {}  # {user_id: target_id}
        self.voted_count = {}
        self.last_executed = None
        self.game_channel = None
        self.used_hadouhou = False # あごむに破道砲の使用済みフラグ
        self.day_count = 0        # 経過日数
        self.wan_owner = {}       # {ワンころID: 飼い主ID}
        self.masai_evasion = {}   # {マサイID: 回避可能か(bool)}
        self.silenced_players = set()      # 発言削除対象プレイヤーID
        self.chairman_skip_event = None    # asyncio.Event（議長スキップ用）
        self.chairman_ketsugu_used = False # 議長の決議使用済みフラグ
        self.chairman_ketsugu_target = None # 議長が決議した対象ID
        self.in_discussion = False         # 発言フェーズ中フラグ
        self.riacchu_pairs = []   # [(id1, id2), ...] リア充ペア
        self.kizoku_slave = {}    # {貴族id: 奴隷id}

# ======================================================
#  Cog 本体
# ======================================================
class JinrouCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.games = {} # {channel_id: JinrouGame}

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

        # silenced_players のメッセージを即削除
        if message.author.id in game.silenced_players:
            try:
                await message.delete()
            except:
                pass
            return

        # 議長の特殊コマンド（発言フェーズ中のみ有効）
        if game.in_discussion:
            player_role = game.roles.get(message.author.id)
            is_alive = any(p.id == message.author.id for p in game.alive_players)

            if player_role == "議長" and is_alive:
                content = message.content.strip()

                if content == "スキップ":
                    if game.chairman_skip_event and not game.chairman_skip_event.is_set():
                        await game.game_channel.send("議長がスキップを宣言。議論を終了し投票フェーズに移行します。")
                        game.chairman_skip_event.set()

                elif content.startswith("決議") and not game.chairman_ketsugu_used:
                    target_name = content[2:].strip()
                    if target_name:
                        target_player = None
                        for p in game.alive_players:
                            if p.id == message.author.id:
                                continue
                            member = game.game_channel.guild.get_member(p.id)
                            if member and member.display_name == target_name:
                                target_player = p
                                break

                        if target_player:
                            game.chairman_ketsugu_target = target_player.id
                            game.chairman_ketsugu_used = True
                            if game.chairman_skip_event and not game.chairman_skip_event.is_set():
                                game.chairman_skip_event.set()
                            await game.game_channel.send(
                                f"議長が決議を発動！ **{target_name}** の追放が決定されました。"
                            )

    # ======================================================
    #  役職割当
    # ======================================================
    def assign_roles(self, game):
        num = len(game.players)
        num_wolves = max(1, num // 5)

        # 昇格マップ（基本職 → 上級職、40%で昇格）
        promotion_map = {
            "人狼":          "デカ狼",
            "騎士":          "罠師",
            "一般通過あごむに": "タフむに",
            "狂人":          "狂信者",
            "入狼":          "ワンころ",
            "ハゲ":          "コウモリむに",
        }

        def maybe_promote(role):
            if role in promotion_map and random.random() < 0.4:
                return promotion_map[role]
            return role

        # 基本プール構築
        pool = [
            maybe_promote("一般通過あごむに"),
            maybe_promote("占い師"),
            maybe_promote("騎士"),
        ]
        pool += [maybe_promote("人狼") for _ in range(num_wolves)]

        pro_roles = ["ハゲ", "メンヘラ", "あごむに破道砲", "パン屋", "マサイ族", "入狼", "議長", "ビー玉ブレイカー"]
        base_roles = ["霊媒師", "狂人"]

        while len(pool) < num:
            if num >= 6 and pro_roles:
                choice = random.choice(pro_roles + base_roles)
                pool.append(maybe_promote(choice))
                if choice in pro_roles:   pro_roles.remove(choice)
                elif choice in base_roles: base_roles.remove(choice)
            else:
                if base_roles:
                    choice = random.choice(base_roles)
                    pool.append(maybe_promote(choice))
                    base_roles.remove(choice)
                else:
                    pool.append(maybe_promote("一般通過あごむに"))

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
        random.shuffle(pool)

        for i, p in enumerate(game.players):
            game.roles[p.id] = pool[i]

        # リア充ペアと貴族/奴隷を記録
        riacchu_ids = []
        kizoku_id = None
        dorei_id = None
        for p in game.players:
            role = game.roles[p.id]
            if role == "リア充":
                riacchu_ids.append(p.id)
            elif role == "貴族":
                kizoku_id = p.id
            elif role == "奴隷":
                dorei_id = p.id

        if len(riacchu_ids) >= 2:
            game.riacchu_pairs.append((riacchu_ids[0], riacchu_ids[1]))
        if kizoku_id and dorei_id:
            game.kizoku_slave[kizoku_id] = dorei_id

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
        embed = discord.Embed(description="管理者によりゲームが強制終了されました。", color=0xFFFFFF)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="jinrou_help", description="各役職の詳細な説明を表示します")
    async def jinrou_help(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="人狼ゲーム 役職説明書",
            description="各役職の役割と特徴の一覧です。真面目に読みなさい。",
            color=0xFFFFFF
        )
        roles_info = {
            "【基本職】一般通過あごむに": "空気。存在しているだけで偉い。特に何もしない。",
            "【上級職】タフむに":        "殺された時に最後の一撃で相手を道連れにする根性の一般通過。",
            "【基本職】占い師":          "毎晩1人を占える。安物のビー玉を使って人間か人狼かを見抜く。",
            "【基本職】霊媒師":          "昨日追放された者が人間だったか人狼だったかを確認する悪趣味な仕事。",
            "【基本職】騎士":            "毎晩1人をつまようじで守る。自分は守れない不器用なやつ。",
            "【上級職】罠師":            "騎士の上位職。対象を守るだけでなく、狼が守った対象を襲撃した場合にその狼を返り討ちにする。",
            "【基本職】人狼":            "村人を食べる。仲間同士は誰が人狼か知っている。",
            "【上級職】デカ狼":          "占い師を賄賂で黙らせる人狼。占い師に白判定を出させる。デカイだけで威圧感がある。",
            "【基本職】狂人":            "人狼の味方をする人間。人狼が誰かは知らないが、とにかく場を乱す。",
            "【上級職】狂信者":          "人狼とデカ狼が誰かを知っている熱狂的なファン。人狼陣営の参謀。",
            "【基本職】ハゲ":            "追放されたら勝利。髪の毛が観測できないバグのせいで目立ちすぎる。",
            "【上級職】コウモリむに":    "ハゲの上位職。追放されても勝利できる上、最後まで生き残っても個人勝利できる。",
            "【基本職】メンヘラ":        "自分に関与した（占う、守る、食べる）者を物理的に消去する。",
            "【基本職】あごむに破道砲":  "自爆して対象を道連れにする。さらにもう1人も誤発で巻き込む。（※3日目の夜以降に使用可能）",
            "【基本職】パン屋":          "生きていれば朝にパンを配る。死んでいても何故かパンが届く怪奇現象を起こす。",
            "【基本職】マサイ族":        "視力とジャンプ力が高い。夜に1人を観察する。もし対象が人狼なら襲撃を50%で回避する準備を整える。真偽は誰にもわからない。",
            "【基本職】入狼":            "人狼のような名前の村人。占われると人狼判定が出る不幸なやつ。",
            "【上級職】ワンころ":        "最初に飼い主を決める。飼い主が死ぬかいない場合は野良化して人狼になる。",
            "【発展職】議長":            "会議中に『スキップ』と発言すると強制的に議論を打ち切り投票に移行できる。ゲーム中一回だけ『決議 [名前]』と発言すると対象を強制追放できる（投票不要）。白陣営。",
            "【発展職】ビー玉ブレイカー":"このプレイヤーが生きているだけで占い師の判定が30%の確率でひっくり返る。パッシブ。白陣営。",
            "【2人役】リア充":           "2人1組で存在し、お互いが誰かを知っている。片方が死ぬともう片方も道連れになる。",
            "【2人役】貴族":             "奴隷とセットで発生。死亡判定を自動的に奴隷に肩代わりさせることができる（奴隷が存在する場合）。奴隷が誰か分かる。",
            "【2人役】奴隷":             "貴族とセットで発生。貴族が死亡判定にかかると代わりに死ぬ運命。貴族が誰か分かる。",
        }
        for name, desc in roles_info.items():
            embed.add_field(name=name, value=desc, inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="jinrou", description="人狼ゲームを開始します")
    @app_commands.describe(wait_minutes="募集時間を分単位で指定（1から1440分）")
    async def jinrou(self, interaction: discord.Interaction, wait_minutes: int = 1):
        game = self.get_game(interaction.channel_id)
        if game.is_running:
            embed = discord.Embed(description="このチャンネルでは既にゲームが進行中です。", color=0xFFFFFF)
            return await interaction.response.send_message(embed=embed, ephemeral=True)

        wait_minutes = max(1, min(wait_minutes, 1440))

        game.is_running = True
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
        game.in_discussion = False
        game.riacchu_pairs = []
        game.kizoku_slave = {}

        view = RecruitView(game, timeout=wait_minutes * 60)
        await interaction.response.send_message(f"<a:POYOPOYO:1490724627805110392>人狼ゲーム募集開始。募集時間: {wait_minutes}分", view=view)

        for _ in range(wait_minutes * 60):
            await asyncio.sleep(1)
            if not game.is_running: return

        await self._start_game_loop(game, interaction.channel)

    async def run_from_hub(self, game: JinrouGame, channel):
        """RecruitView 表示後 60 秒待機してゲームループを開始する。play.py から create_task で呼ぶ。"""
        await asyncio.sleep(60)

        if not game.is_running:
            return

        await self._start_game_loop(game, channel)

    # ======================================================
    #  ゲームループ
    # ======================================================
    async def _start_game_loop(self, game: JinrouGame, channel):
        """役職割当・ゲームループの共通処理。jinrou コマンドと run_from_hub の両方から呼ばれる。"""
        if len(game.players) < 5:
            game.is_running = False
            await channel.send("<:failed:1490986584676368535>参加者が5人未満のため、ゲームを中止します。")
            return

        game.alive_players = game.players.copy()
        self.assign_roles(game)

        mentions = " ".join([p.mention for p in game.players])
        roles_for_display = []
        for r in game.roles.values():
            if r == "タフむに": roles_for_display.append("一般通過あごむに")
            elif r == "入狼":   roles_for_display.append("人狼")
            else:               roles_for_display.append(r)
        roles_list = " / ".join(set(roles_for_display))

        await channel.send(
            f"<:success:1490985168100659322>{mentions}\nゲーム開始。今回の役職内訳: {roles_list}\n下のボタンで自分の役職を確認してください。",
            view=RoleCheckView(game, self)
        )

        # リア充・貴族/奴隷への個別DM通知
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
                await self.run_discussion(game, minutes=3, title="昼のディスカッション")
                if not game.is_running: break

                if game.chairman_ketsugu_target:
                    await self.apply_forced_execution(game, game.chairman_ketsugu_target)
                    game.chairman_ketsugu_target = None
                else:
                    await self.run_voting_phase(game)

                if not game.is_running or await self.check_victory(game): break

        except Exception as e:
            print(f"Game Error: {e}")
        finally:
            game.silenced_players.clear()
            game.in_discussion = False
            game.is_running = False

    # ======================================================
    #  フェーズ処理
    # ======================================================
    async def run_discussion(self, game, minutes, title):
        if not game.is_running: return
        game.chairman_skip_event = asyncio.Event()
        game.in_discussion = True
        await game.game_channel.send(f"ーー {title}（{minutes}分） ーー")
        if any(game.roles.get(p.id) == "パン屋" for p in game.alive_players):
            await game.game_channel.send("<:PANYA:1490254577558093944>パン屋がパンを焼きました")

        for _ in range(minutes * 60):
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
        await game.game_channel.send(f"ーー 第{game.day_count}夜（1分） ーー")
        # 生存者の発言を禁止
        game.silenced_players.update(p.id for p in game.alive_players)

        game.night_actions = {}
        view = NightActionView(game)
        msg = await game.game_channel.send("アクションを選択してください", view=view)

        req_roles = ["占い師", "騎士", "罠師", "人狼", "デカ狼", "あごむに破道砲", "マサイ族"]
        if game.day_count == 1: req_roles.append("ワンころ")
        req = sum(1 for p in game.alive_players if game.roles.get(p.id) in req_roles)

        t = 0
        while len(game.night_actions) < req and t < 60:
            await asyncio.sleep(1)
            t += 1
            if not game.is_running: break

        try: await msg.delete()
        except: pass

        # 生存者のサイレンスを解除（死亡者はsilencedのまま）
        for p in game.alive_players:
            game.silenced_players.discard(p.id)

        await self.process_night_results(game)

    async def process_night_results(self, game):
        if not game.is_running: return
        dead_ids = set()
        wolf_attacks   = {}  # {wolf_id: target_id} 各人狼の個別襲撃記録
        knight_targets = set()      # 騎士の守護対象
        trap_targets   = {}         # {target_id: trapper_id} 罠師の守護対象
        psycho_killer_ids = {p.id for p in game.alive_players if game.roles.get(p.id) == "メンヘラ"}
        menhera_triggered = False

        # ─── アクション収集 ───────────────────────────────
        for p_id, t_id in game.night_actions.items():
            role = game.roles.get(p_id)

            # メンヘラに関与した者は死ぬ
            if t_id in psycho_killer_ids:
                dead_ids.add(p_id)
                menhera_triggered = True

            if role in ["人狼", "デカ狼"]:
                wolf_attacks[p_id] = t_id          # 各人狼の襲撃先を個別記録
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

        # ─── 各人狼の襲撃を個別処理 ──────────────────────
        for wolf_id, target_id in wolf_attacks.items():
            if wolf_id in dead_ids:
                continue  # すでに死亡している狼はスキップ

            # 罠師チェック：守護対象を攻撃した狼を返り討ち
            if target_id in trap_targets:
                dead_ids.add(wolf_id)
                await game.game_channel.send("罠師の罠が発動！ 狼が罠にかかりました。")
                continue

            # 騎士チェック：守護対象は守られる
            if target_id in knight_targets:
                continue

            # マサイ族の回避判定
            if game.roles.get(target_id) == "マサイ族" and game.masai_evasion.get(target_id):
                if random.random() < 0.5:
                    await game.game_channel.send("<:MASAI:1490254590757572758>マサイ族は襲撃を回避しました。")
                    continue

            dead_ids.add(target_id)

        # ─── 貴族/奴隷 置換 ──────────────────────────────
        final_dead = set()
        already_substituted = set()
        for d_id in list(dead_ids):
            if d_id in already_substituted:
                continue
            if game.roles.get(d_id) == "貴族":
                slave_id = game.kizoku_slave.get(d_id)
                if (slave_id
                        and slave_id in {p.id for p in game.alive_players}
                        and slave_id not in dead_ids):
                    await game.game_channel.send("貴族の死亡判定が奴隷に肩代わりされました。")
                    final_dead.add(slave_id)
                    already_substituted.add(slave_id)
                    continue
            final_dead.add(d_id)

        # ─── リア充 連鎖死 ───────────────────────────────
        for pair in game.riacchu_pairs:
            if pair[0] in final_dead or pair[1] in final_dead:
                final_dead.add(pair[0])
                final_dead.add(pair[1])

        # ─── 死亡処理 ────────────────────────────────────
        if final_dead:
            for d_id in list(final_dead):
                if d_id not in {p.id for p in game.alive_players}:
                    continue
                m = game.game_channel.guild.get_member(d_id)
                if m:
                    await game.game_channel.send(f"夜の結果: {m.display_name} さんが犠牲になりました。")

                    # タフむにの反撃
                    if game.roles.get(d_id) == "タフむに":
                        killers = [
                            pid for pid, tid in game.night_actions.items()
                            if tid == d_id
                            and pid not in final_dead
                            and pid in {p.id for p in game.alive_players}
                        ]
                        if killers:
                            k_id = random.choice(killers)
                            k_m = game.game_channel.guild.get_member(k_id)
                            if k_m:
                                await game.game_channel.send(f"タフむにの反撃。 {k_m.display_name} を道連れにしました。")
                                game.silenced_players.add(k_id)
                                game.alive_players = [p for p in game.alive_players if p.id != k_id]

                    game.silenced_players.add(d_id)
                    game.alive_players = [p for p in game.alive_players if p.id != d_id]
        else:
            await game.game_channel.send("<:KISHI:1490254592800456794>夜の結果: 昨晩の犠牲者はいないようです。")

    # ======================================================
    #  勝利判定
    # ======================================================
    async def check_victory(self, game):
        if not game.is_running: return True

        # 人狼・デカ狼が全滅したら村人陣営の勝利
        wolves_alive = [p for p in game.alive_players if game.roles.get(p.id) in ["人狼", "デカ狼"]]
        if not wolves_alive:
            await game.game_channel.send("人狼全滅。村人陣営の勝利です。")
            await self._check_koumorimuni_win(game)
            game.is_running = False
            return True

        # 狼陣営の人数判定
        def is_wolf_side(p_id):
            r = game.roles.get(p_id)
            if r in ["人狼", "デカ狼", "狂人", "狂信者"]: return True
            if r == "ワンころ":
                owner_id = game.wan_owner.get(p_id)
                if owner_id is None: return True  # 未設定＝野良
                if owner_id not in {p.id for p in game.alive_players}: return True  # 飼い主死亡＝野良
            return False

        wolves    = [p for p in game.alive_players if is_wolf_side(p.id)]
        non_wolves = [p for p in game.alive_players if not is_wolf_side(p.id)]

        if len(wolves) >= len(non_wolves):
            await game.game_channel.send("人狼が支配した。人狼陣営の勝利です。")
            await self._check_koumorimuni_win(game)
            game.is_running = False
            return True

        return False

    async def _check_koumorimuni_win(self, game):
        """コウモリむにが生き残っていた場合の個人勝利アナウンス"""
        koumoris = [p for p in game.alive_players if game.roles.get(p.id) == "コウモリむに"]
        if not koumoris:
            return
        names_list = []
        for p in koumoris:
            m = game.game_channel.guild.get_member(p.id)
            if m: names_list.append(m.display_name)
        if names_list:
            await game.game_channel.send(f"さらに、{'、'.join(names_list)} は最後まで生き残り個人勝利しました！")

    # ======================================================
    #  議長の強制追放
    # ======================================================
    async def apply_forced_execution(self, game, target_id):
        if not game.is_running: return
        alive_ids = {p.id for p in game.alive_players}
        if target_id not in alive_ids:
            return

        actual_target_id = target_id

        # 貴族/奴隷チェック
        if game.roles.get(actual_target_id) == "貴族":
            slave_id = game.kizoku_slave.get(actual_target_id)
            if slave_id:
                slave_m = game.game_channel.guild.get_member(slave_id)
                if slave_m and slave_id in alive_ids:
                    await game.game_channel.send(f"貴族の処刑判定が奴隷 {slave_m.display_name} に肩代わりされました。")
                    actual_target_id = slave_id

        target_m = game.game_channel.guild.get_member(actual_target_id)
        if not target_m: return

        game.last_executed = actual_target_id
        game.silenced_players.add(actual_target_id)
        game.alive_players = [p for p in game.alive_players if p.id != actual_target_id]

        executed_role = game.roles.get(actual_target_id)
        if executed_role == "ハゲ":
            await game.game_channel.send("<:f8cc0b1b5e501838:1491033609929490492>ハゲが追放された。ハゲの勝利です。")
            game.is_running = False
            return
        elif executed_role == "コウモリむに":
            await game.game_channel.send("コウモリむにが追放された。コウモリむにの勝利です。")
            game.is_running = False
            return

        # リア充 連鎖死
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

    # ======================================================
    #  投票フェーズ
    # ======================================================
    async def run_voting_phase(self, game):
        if not game.is_running: return
        await game.game_channel.send("ーー 投票フェーズ（40秒） ーー")
        # 生存者の発言を禁止
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

        # 生存者のサイレンスを解除
        for p in game.alive_players:
            game.silenced_players.discard(p.id)

        # ─── 投票結果集計 ────────────────────────────────
        if not game.voted_count:
            return await game.game_channel.send("投票なし。追放はありません。")

        counts = Counter(game.voted_count.values())
        most = counts.most_common()

        # 同数票はスキップ扱い
        if len(most) > 1 and most[0][1] == most[1][1]:
            return await game.game_channel.send("同数票のためスキップされました。追放はありません。")

        target_id_str = most[0][0]

        if target_id_str == "skip":
            return await game.game_channel.send("投票の結果、スキップされました。追放はありません。")

        actual_target_id = int(target_id_str)
        target_m = game.game_channel.guild.get_member(actual_target_id)
        if not target_m:
            return

        # 貴族/奴隷チェック
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

        executed_role = game.roles.get(actual_target_id)
        if executed_role == "ハゲ":
            await game.game_channel.send("<:f8cc0b1b5e501838:1491033609929490492>ハゲが追放された。ハゲの勝利です。")
            game.is_running = False
            return
        elif executed_role == "コウモリむに":
            await game.game_channel.send("コウモリむにが追放された。コウモリむにの勝利です。")
            game.is_running = False
            return

        # リア充 連鎖死
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

# ======================================================
#  UI Components
# ======================================================
class RoleCheckView(discord.ui.View):
    def __init__(self, game, cog):
        super().__init__(timeout=None)
        self.game, self.cog = game, cog

    @discord.ui.button(label="役職確認", style=discord.ButtonStyle.primary)
    async def check(self, interaction, button):
        real_role = self.game.roles.get(interaction.user.id)
        if real_role is None:
            embed = discord.Embed(description="あなたはゲームに参加していません。", color=0xFFFFFF)
            return await interaction.response.send_message(embed=embed, ephemeral=True)

        display_role = real_role
        if real_role == "タフむに": display_role = "一般通過あごむに"
        elif real_role == "入狼":   display_role = "人狼"

        wolves = self.cog.get_wolves_names(self.game)

        # リア充のパートナー情報
        partner_name = "不明"
        for pair in self.game.riacchu_pairs:
            if interaction.user.id in pair:
                partner_id = pair[1] if pair[0] == interaction.user.id else pair[0]
                partner_m = self.game.game_channel.guild.get_member(partner_id)
                if partner_m: partner_name = partner_m.display_name

        # 貴族の奴隷情報
        slave_name = "不明"
        if real_role == "貴族":
            slave_id = self.game.kizoku_slave.get(interaction.user.id)
            if slave_id:
                slave_m = self.game.game_channel.guild.get_member(slave_id)
                if slave_m: slave_name = slave_m.display_name

        # 奴隷の貴族情報
        kizoku_name = "不明"
        if real_role == "奴隷":
            for k_id, s_id in self.game.kizoku_slave.items():
                if s_id == interaction.user.id:
                    k_m = self.game.game_channel.guild.get_member(k_id)
                    if k_m: kizoku_name = k_m.display_name
                    break

        descs = {
            "一般通過あごむに": "一般通過あごむに。空気より存在感が薄い。",
            "占い師":           "毎晩1人を占える。金がないのでビー玉で占っている。",
            "霊媒師":           "昨日追放された者の正体を覗き見る趣味がある。",
            "人狼":             f"仲間: {wolves}",
            "騎士":             "毎晩一人をつまようじで守る。",
            "罠師":             "毎晩一人を守る。狼が守った対象を攻撃した場合、その狼を返り討ちにする。騎士の上位職。",
            "狂人":             "人狼の味方。基本的に無能である。",
            "ハゲ":             "追放されたら勝てる。髪の毛が観測できないバグが発生している。",
            "コウモリむに":     "ハゲの上位職。追放されても勝利できる上、最後まで生き残っても個人勝利できる。",
            "メンヘラ":         "自分に関与した者を物理的に消す。",
            "あごむに破道砲":   "自らを弾にして1人を狙い撃ちできるが、誤発してもう1人殺す。（※3日目の夜以降に使用可能）",
            "デカ狼":           f"占い師に賄賂を払って白判定にする。デカイだけである。仲間: {wolves}",
            "パン屋":           "生きているうちは朝にパンを配る。死んでいてもなぜかパンが届く。",
            "マサイ族":         "視力とジャンプ力が高い。夜に1人を観察する。もし対象が人狼なら襲撃を50%で回避する準備を整える。真偽は誰にもわからない。",
            "入狼":             "生まれた名前が悪かった。ビー玉で占ってるやつに人狼と誤解される哀れな村陣営。",
            "ワンころ":         "最初の夜に飼い主を決める。飼い主がいないと野生化して人狼になる。",
            "タフむに":         "殺された時に殺し返す根性のある一般通過あごむに。",
            "狂信者":           f"人狼とデカ狼を知っている熱狂的な人狼ファン。 仲間: {wolves}",
            "議長":             "会議中に『スキップ』で議論を即終了→投票へ。ゲーム中一回だけ『決議 [名前]』で対象を強制追放できる。",
            "ビー玉ブレイカー": "あなたが生きているだけで占い師の判定が30%の確率で逆転する。パッシブ効果のため夜は何もしなくていい。",
            "リア充":           f"リア充。パートナー: {partner_name}。片方が死ぬと両方道連れになる。",
            "貴族":             f"貴族。奴隷が生きている間は死を自動的に肩代わりさせることができる。奴隷: {slave_name}",
            "奴隷":             f"奴隷。貴族が死亡判定を受けると代わりに死ぬ運命。貴族: {kizoku_name}",
        }

        role_image_map = {
            "一般通過あごむに": "NOMAL.PNG",    "人狼": "JINROU.PNG",         "マサイ族": "MASAI.PNG",
            "メンヘラ": "MENHERA.PNG",          "入狼": "NYUROU.PNG",          "騎士": "KISHI.PNG",
            "占い師": "URANAI.PNG",              "霊媒師": "REIBAI.PNG",        "パン屋": "PANYA.PNG",
            "狂人": "KYOJIN.PNG",               "ハゲ": "HAGE.PNG",            "デカ狼": "DEKAROU.PNG",
            "あごむに破道砲": "AGOMUNIHADOHOU.PNG", "ワンころ": "WANKORO.PNG",
            "タフむに": "TAHUMUNI.PNG",          "狂信者": "KYOUSINSYA.PNG",
            "罠師": "WANASSI.PNG",               "議長": "GICHOU.PNG",
            "ビー玉ブレイカー": "BEEBREAKER.PNG", "リア充": "RIAJUU.PNG",
            "貴族": "KIZOKU.PNG",                "奴隷": "DOREI.PNG",          "コウモリむに": "KOUMORI.PNG",
        }

        embed = discord.Embed(
            title=f"あなたの役職は 【{display_role}】 です",
            description=descs.get(real_role, "詳細なし"),
            color=0xFFFFFF
        )

        filename = role_image_map.get(real_role)
        if filename:
            file_path = f"Assets/{filename}"
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
    async def action(self, interaction, button):
        p_id = interaction.user.id
        if p_id not in [p.id for p in self.game.alive_players]: return

        if p_id in self.game.night_actions:
            embed = discord.Embed(description="アクションは既に完了しています。欲張らないでください。", color=0xFFFFFF)
            return await interaction.response.send_message(embed=embed, ephemeral=True)

        role = self.game.roles.get(p_id)

        if role == "あごむに破道砲" and self.game.day_count < 3:
            embed = discord.Embed(description=f"あごむに破道砲は第3夜からしか使用できません。(現在は第{self.game.day_count}夜)", color=0xFFFFFF)
            return await interaction.response.send_message(embed=embed, ephemeral=True)

        passive_roles = [
            "一般通過あごむに", "霊媒師", "狂人", "ハゲ", "コウモリむに",
            "メンヘラ", "パン屋", "入狼", "タフむに", "狂信者",
            "ビー玉ブレイカー", "リア充", "貴族", "奴隷", "議長"
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

    async def callback(self, interaction):
        p_id = interaction.user.id
        if p_id in self.game.night_actions:
            embed = discord.Embed(description="既にアクションは受理されています。", color=0xFFFFFF)
            return await interaction.response.send_message(embed=embed, ephemeral=True)

        t_id = int(self.children[0].values[0])
        self.game.night_actions[p_id] = t_id

        if self.role == "占い師":
            r = self.game.roles.get(t_id)
            res = "人狼" if r in ["人狼", "入狼", "ワンころ"] else "人間"
            # ビー玉ブレイカーが生存している場合、30%で判定逆転
            if any(self.game.roles.get(p.id) == "ビー玉ブレイカー" for p in self.game.alive_players):
                if random.random() < 0.3:
                    res = "人間" if res == "人狼" else "人狼"
            embed = discord.Embed(description=f"<:URANAI:1490255412837093568>結果: 【{res}】", color=0xFFFFFF)
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
        else:
            embed = discord.Embed(description="完了。", color=0xFFFFFF)
            await interaction.response.send_message(embed=embed, ephemeral=True)


class RecruitView(discord.ui.View):
    def __init__(self, game, timeout: int):
        super().__init__(timeout=timeout)
        self.game = game

    @discord.ui.button(label="参加する", style=discord.ButtonStyle.success)
    async def join(self, interaction, button):
        if interaction.user not in self.game.players:
            self.game.players.append(interaction.user)
            await interaction.response.send_message(f"<a:AGOMUNIMUNI:1490255555632037909>{interaction.user.display_name} さんが参加しました。")


class PublicVoteView(discord.ui.View):
    def __init__(self, game, options):
        super().__init__(timeout=60)
        self.game = game
        s = discord.ui.Select(options=options)
        s.callback = self.callback
        self.add_item(s)

    async def callback(self, interaction):
        p_id = interaction.user.id
        if p_id not in [p.id for p in self.game.alive_players]:
            embed = discord.Embed(description="死人に口なし。墓場で大人しくしていなさい。", color=0xFFFFFF)
            return await interaction.response.send_message(embed=embed, ephemeral=True)

        if p_id in self.game.voted_count:
            embed = discord.Embed(description="既に投票済みです。意志を何度も変えることはできません。", color=0xFFFFFF)
            return await interaction.response.send_message(embed=embed, ephemeral=True)

        self.game.voted_count[p_id] = self.children[0].values[0]
        await interaction.response.send_message(f"<u:success:1490985168100659322>{interaction.user.display_name} さんが投票を完了しました。")


async def setup(bot):
    await bot.add_cog(JinrouCog(bot))