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
        self.lovers = []          # [id1, id2]
        self.noble_slave = {}     # {noble_id: slave_id}
        self.chairman_used = False # 議長の決議権使用フラグ
        self.marble_breaker_present = False
        self.skip_requested = False # 議長によるスキップ

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

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot: return
        game = self.get_game(message.channel.id)
        if not game.is_running: return

        # 発言削除による擬似ミュート（夜フェーズ、投票フェーズ、または死亡者）
        is_alive = any(p.id == message.author.id for p in game.alive_players)
        # 現在の状態を判定するフラグが必要だが、簡易的に「alive_playersに含まれない」かつ「ゲーム中」なら削除
        if not is_alive:
            try: await message.delete()
            except: pass
            return

        # 議長のスキップ発言
        if game.roles.get(message.author.id) == "議長" and "スキップ" in message.content:
            game.skip_requested = True
            await message.channel.send("【議長権限】会議を打ち切り、投票に移行します。")

    def assign_roles(self, game):
        num = len(game.players)
        
        # 基本役職プール
        pool = ["一般通過あごむに", "占い師", "騎士"]
        num_wolves = max(1, num // 5)
        pool += ["人狼"] * num_wolves
        
        pro_roles = ["ハゲ", "メンヘラ", "あごむに破道砲", "デカ狼", "パン屋", "マサイ族", "入狼", "ワンころ", "タフむに", "狂信者", "罠師", "議長", "ビー玉ブレイカー", "コウモリむに"]
        base_roles = ["霊媒師", "狂人"]
        
        # 2人役職の選出 (8人以上かつ30%の確率)
        special_pairs = []
        if num >= 8 and random.random() < 0.3:
            pair_type = random.choice(["リア充", "貴族奴隷"])
            if pair_type == "リア充":
                special_pairs = ["リア充", "リア充"]
            else:
                special_pairs = ["貴族", "奴隷"]
        
        while len(pool) + len(special_pairs) < num:
            if num >= 6 and pro_roles:
                choice = random.choice(pro_roles + base_roles)
                pool.append(choice)
                if choice in pro_roles: pro_roles.remove(choice)
                elif choice in base_roles: base_roles.remove(choice)
            else:
                if base_roles:
                    choice = random.choice(base_roles)
                    pool.append(choice)
                    base_roles.remove(choice)
                else:
                    pool.append("一般通過あごむに")

        final_pool = pool + special_pairs
        random.shuffle(final_pool)
        
        # 上位職への昇格判定 (40%の確率)
        upgrade_map = {
            "人狼": "デカ狼",
            "騎士": "罠師",
            "一般通過あごむに": "タフむに",
            "狂人": "狂信者",
            "入狼": "ワンころ",
            "ハゲ": "コウモリむに"
        }
        
        for i in range(len(final_pool)):
            if final_pool[i] in upgrade_map and random.random() < 0.4:
                final_pool[i] = upgrade_map[final_pool[i]]

        player_ids = [p.id for p in game.players]
        for i, p_id in enumerate(player_ids):
            game.roles[p_id] = final_pool[i]

        # 特殊役職の紐付け
        lovers = [p_id for p_id, r in game.roles.items() if r == "リア充"]
        if len(lovers) >= 2: game.lovers = lovers[:2]
        
        nobles = [p_id for p_id, r in game.roles.items() if r == "貴族"]
        slaves = [p_id for p_id, r in game.roles.items() if r == "奴隷"]
        if nobles and slaves: game.noble_slave[nobles[0]] = slaves[0]
        
        if any(r == "ビー玉ブレイカー" for r in game.roles.values()):
            game.marble_breaker_present = True

    @app_commands.command(name="kill", description="このチャンネルで進行中の人狼ゲームを強制終了します")
    async def kill(self, interaction: discord.Interaction):
        game = self.get_game(interaction.channel_id)
        if not game.is_running:
            embed = discord.Embed(description="このチャンネルで実行中のゲームはありません。", color=0xFFFFFF)
            return await interaction.response.send_message(embed=embed, ephemeral=True)
        game.is_running = False
        embed = discord.Embed(description="管理者によりゲームが強制終了されました。", color=0xFFFFFF)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="jinrou_help", description="各役職の詳細な説明を表示します")
    async def jinrou_help(self, interaction: discord.Interaction):
        embed = discord.Embed(title="人狼ゲーム 役職説明書", description="各役職の役割と特徴の一覧です。", color=0xFFFFFF)
        roles_info = {
            "一般通過あごむに": "空気。特に何もしない。",
            "占い師": "毎晩1人を占える。人間か人狼かを見抜く。",
            "霊媒師": "昨日追放された者が人間だったか人狼だったかを確認する。",
            "騎士": "毎晩1人を守る。自分は守れない。",
            "人狼": "村人を食べる。仲間同士は誰が人狼か知っている。",
            "狂人": "人狼の味方をする人間。人狼が誰かは知らない。",
            "ハゲ": "追放されたら勝利。目立ちすぎる。",
            "メンヘラ": "自分に関与した者を物理的に消去する。",
            "あごむに破道砲": "自爆して対象と、さらにもう1人を誤発で巻き込む。（3日目夜以降）",
            "デカ狼": "占い師を賄賂で黙らせる人狼。",
            "パン屋": "朝にパンを配る。",
            "マサイ族": "夜に1人を観察。人狼なら襲撃を50%で回避準備。",
            "入狼": "占われると人狼判定が出る村人。",
            "ワンころ": "最初に飼い主を決める。飼い主が死ぬと人狼になる。",
            "タフむに": "殺された時に最後の一撃で相手を道連れにする。",
            "狂信者": "人狼とデカ狼を知っている人狼陣営の参謀。",
            "罠師": "騎士の上位職。守るだけでなく、襲撃した狼を返り討ちにする。",
            "議長": "「スキップ」で会議を打ち切れる。一度だけ「決議」で投票先を強制決定できる。",
            "ビー玉ブレイカー": "存在すると占い結果が30%で反転する。",
            "リア充": "2人1組。片方が死ぬともう片方も後を追う。",
            "貴族": "奴隷がいれば、死亡判定を奴隷に肩代わりさせることができる。",
            "奴隷": "貴族の代わりに死ぬ運命にある。",
            "コウモリむに": "最後まで生き残れば勝利。ハゲの上位職。"
        }
        for name, desc in roles_info.items():
            embed.add_field(name=name, value=desc, inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="jinrou", description="人狼ゲームを開始します")
    async def jinrou(self, interaction: discord.Interaction, wait_minutes: int = 1):
        game = self.get_game(interaction.channel_id)
        if game.is_running:
            return await interaction.response.send_message("既にゲーム進行中です。", ephemeral=True)

        game.is_running = True
        game.game_channel = interaction.channel
        game.players, game.roles, game.day_count = [], {}, 0
        game.wan_owner, game.used_hadouhou, game.last_executed = {}, False, None
        game.masai_evasion, game.lovers, game.noble_slave = {}, [], {}
        game.chairman_used, game.marble_breaker_present, game.skip_requested = False, False, False

        view = RecruitView(game, timeout=wait_minutes * 60)
        await interaction.response.send_message(f"人狼ゲーム募集開始。募集時間: {wait_minutes}分", view=view)
        await asyncio.sleep(wait_minutes * 60)
        if game.is_running: await self._start_game_loop(game, interaction.channel)

    async def _start_game_loop(self, game: JinrouGame, channel):
        if len(game.players) < 5:
            game.is_running = False
            return await channel.send("参加者が5人未満のため中止します。")

        game.alive_players = game.players.copy()
        self.assign_roles(game)

        mentions = " ".join([p.mention for p in game.players])
        roles_list = " / ".join(set(game.roles.values()))
        await channel.send(f"{mentions}\nゲーム開始。役職内訳: {roles_list}", view=RoleCheckView(game, self))

        try:
            while game.is_running:
                await self.run_night_phase(game)
                if not game.is_running or await self.check_victory(game): break
                await self.run_discussion(game, minutes=3, title="昼のディスカッション")
                if not game.is_running: break
                await self.run_voting_phase(game)
                if not game.is_running or await self.check_victory(game): break
        finally:
            game.is_running = False

    async def run_discussion(self, game, minutes, title):
        if not game.is_running: return
        await game.game_channel.send(f"ーー {title}（{minutes}分） ーー")
        game.skip_requested = False
        for _ in range(minutes * 60):
            await asyncio.sleep(1)
            if not game.is_running or game.skip_requested: break
        await game.game_channel.send(f"ーー {title}終了 ーー")

    async def run_night_phase(self, game):
        if not game.is_running: return
        game.day_count += 1
        await game.game_channel.send(f"ーー 第{game.day_count}夜 ーー")
        game.night_actions = {}
        view = NightActionView(game)
        msg = await game.game_channel.send("アクションを選択してください", view=view)
        
        req_roles = ["占い師", "騎士", "人狼", "デカ狼", "あごむに破道砲", "マサイ族", "罠師"]
        if game.day_count == 1: req_roles.append("ワンころ")
        req = sum(1 for p in game.alive_players if game.roles.get(p.id) in req_roles)
        
        t = 0
        while len(game.night_actions) < req and t < 60:
            await asyncio.sleep(1)
            t += 1
            if not game.is_running: break
        try: await msg.delete()
        except: pass
        await self.process_night_results(game)

    async def process_night_results(self, game):
        dead_ids = set()
        traps = {} # target_id -> trap_setter_id
        knight_protected = set()
        wolf_attacks = {} # attacker_id -> target_id
        
        psycho_killer_ids = [p.id for p in game.alive_players if game.roles.get(p.id) == "メンヘラ"]

        for p_id, t_id in game.night_actions.items():
            role = game.roles.get(p_id)
            if t_id in psycho_killer_ids: dead_ids.add(p_id)
            
            if role in ["人狼", "デカ狼"]: wolf_attacks[p_id] = t_id
            elif role == "騎士": knight_protected.add(t_id)
            elif role == "罠師":
                knight_protected.add(t_id)
                traps[t_id] = p_id
            elif role == "あごむに破道砲":
                dead_ids.add(p_id); dead_ids.add(t_id)
                others = [p.id for p in game.alive_players if p.id not in [p_id, t_id]]
                if others: dead_ids.add(random.choice(others))

        # 襲撃処理
        for attacker_id, target_id in wolf_attacks.items():
            if target_id in knight_protected:
                if target_id in traps:
                    dead_ids.add(attacker_id)
                    await game.game_channel.send("罠師が人狼を返り討ちにしました！")
                continue
            
            # マサイ族回避
            if game.roles.get(target_id) == "マサイ族" and game.masai_evasion.get(target_id) and random.random() < 0.5:
                await game.game_channel.send("マサイ族が襲撃を回避しました。")
                continue
            
            dead_ids.add(target_id)

        await self.handle_deaths(game, dead_ids, "夜の結果")

    async def handle_deaths(self, game, dead_ids, reason_prefix):
        actual_dead = set()
        for d_id in dead_ids:
            # 貴族・奴隷の身代わり
            if d_id in game.noble_slave:
                slave_id = game.noble_slave[d_id]
                if any(p.id == slave_id for p in game.alive_players):
                    actual_dead.add(slave_id)
                    await game.game_channel.send("貴族の身代わりに奴隷が犠牲になりました。")
                    continue
            actual_dead.add(d_id)

        # リア充連鎖
        for d_id in list(actual_dead):
            if d_id in game.lovers:
                other = game.lovers[1] if game.lovers[0] == d_id else game.lovers[0]
                if any(p.id == other for p in game.alive_players):
                    actual_dead.add(other)
                    await game.game_channel.send("リア充の片方が死に、もう片方も後を追いました。")

        for d_id in actual_dead:
            player = next((p for p in game.alive_players if p.id == d_id), None)
            if player:
                await game.game_channel.send(f"{reason_prefix}: {player.display_name} さんが犠牲になりました。")
                if game.roles.get(d_id) == "タフむに":
                    # 夜の襲撃者または投票者を道連れ（簡易化）
                    await game.game_channel.send("タフむにが道連れを発動しました。")
                game.alive_players = [p for p in game.alive_players if p.id != d_id]

    async def check_victory(self, game):
        wolves = [p for p in game.alive_players if game.roles.get(p.id) in ["人狼", "デカ狼"]]
        if not wolves:
            await game.game_channel.send("人狼とデカ狼が全滅しました。村人陣営の勝利です！")
            # コウモリむに勝利判定
            for p in game.alive_players:
                if game.roles.get(p.id) == "コウモリむに":
                    await game.game_channel.send(f"{p.display_name} (コウモリむに) も勝利しました！")
            return True
        
        # 従来の人狼勝利条件（狼数 >= 村人数）
        villagers = [p for p in game.alive_players if game.roles.get(p.id) not in ["人狼", "デカ狼"]]
        if len(wolves) >= len(villagers):
            await game.game_channel.send("人狼陣営の勝利です！")
            return True
        return False

    async def run_voting_phase(self, game):
        if not game.is_running: return
        await game.game_channel.send("ーー 投票フェーズ ーー")
        opts = [discord.SelectOption(label=p.display_name, value=str(p.id)) for p in game.alive_players]
        opts.append(discord.SelectOption(label="スキップ", value="skip"))
        game.voted_count = {}
        view = PublicVoteView(game, opts)
        msg = await game.game_channel.send("投票してください。議長は「決議」と発言で強制決定可能です。", view=view)
        
        # 議長の「決議」待ちループ（簡易実装）
        for _ in range(40):
            await asyncio.sleep(1)
            if not game.is_running: break
        
        try: await msg.delete()
        except: pass
        
        if not game.voted_count: return await game.game_channel.send("投票なし。")
        
        counts = Counter(game.voted_count.values())
        most = counts.most_common()
        
        # 同数票またはスキップが最多ならスキップ
        if (len(most) > 1 and most[0][1] == most[1][1]) or most[0][0] == "skip":
            return await game.game_channel.send("スキップされました。追放はありません。")
        
        target_id = int(most[0][0])
        await self.handle_deaths(game, {target_id}, "投票の結果")
        
        if game.roles.get(target_id) == "ハゲ":
            await game.game_channel.send("ハゲが追放されました。ハゲの勝利です！")
            game.is_running = False

# ======================================================
#  UI Components
# ======================================================
class RoleCheckView(discord.ui.View):
    def __init__(self, game, cog):
        super().__init__(timeout=None)
        self.game, self.cog = game, cog

    @discord.ui.button(label="役職確認", style=discord.ButtonStyle.primary)
    async def check(self, interaction, button):
        role = self.game.roles.get(interaction.user.id)
        if not role: return await interaction.response.send_message("不参加です。", ephemeral=True)
        
        desc = f"あなたの役職は【{role}】です。"
        if role == "リア充":
            other = [p_id for p_id in self.game.lovers if p_id != interaction.user.id]
            if other:
                m = interaction.guild.get_member(other[0])
                desc += f"\n相方は {m.display_name if m else '不明'} です。"
        elif role == "貴族":
            slave_id = self.game.noble_slave.get(interaction.user.id)
            m = interaction.guild.get_member(slave_id) if slave_id else None
            desc += f"\nあなたの奴隷は {m.display_name if m else '不在'} です。"
        elif role == "奴隷":
            noble_id = next((k for k, v in self.game.noble_slave.items() if v == interaction.user.id), None)
            m = interaction.guild.get_member(noble_id) if noble_id else None
            desc += f"\nあなたの主人は {m.display_name if m else '不在'} です。"

        await interaction.response.send_message(desc, ephemeral=True)

class NightActionView(discord.ui.View):
    def __init__(self, game):
        super().__init__(timeout=60)
        self.game = game
    @discord.ui.button(label="夜のアクション", style=discord.ButtonStyle.success)
    async def action(self, interaction, button):
        p_id = interaction.user.id
        if p_id not in [p.id for p in self.game.alive_players]: return
        role = self.game.roles.get(p_id)
        opts = [discord.SelectOption(label=p.display_name, value=str(p.id)) for p in self.game.alive_players if p.id != p_id]
        if not opts: return
        await interaction.response.send_message("対象を選択：", view=ActionSelectView(self.game, opts, role), ephemeral=True)

class ActionSelectView(discord.ui.View):
    def __init__(self, game, options, role):
        super().__init__(timeout=60)
        self.game, self.role = game, role
        s = discord.ui.Select(options=options)
        s.callback = self.callback
        self.add_item(s)
    async def callback(self, interaction):
        t_id = int(self.children[0].values[0])
        self.game.night_actions[interaction.user.id] = t_id
        
        res_text = "完了。"
        if self.role == "占い師":
            r = self.game.roles.get(t_id)
            is_wolf = r in ["人狼", "入狼", "ワンころ"]
            if self.game.marble_breaker_present and random.random() < 0.3:
                is_wolf = not is_wolf # 反転
            res_text = f"占い結果: {'人狼' if is_wolf else '人間'}"
            
        await interaction.response.send_message(res_text, ephemeral=True)

class RecruitView(discord.ui.View):
    def __init__(self, game, timeout: int):
        super().__init__(timeout=timeout)
        self.game = game
    @discord.ui.button(label="参加する", style=discord.ButtonStyle.success)
    async def join(self, interaction, button):
        if interaction.user not in self.game.players:
            self.game.players.append(interaction.user)
            await interaction.response.send_message(f"{interaction.user.display_name} さんが参加しました。")

class PublicVoteView(discord.ui.View):
    def __init__(self, game, options):
        super().__init__(timeout=60)
        self.game = game
        s = discord.ui.Select(options=options)
        s.callback = self.callback
        self.add_item(s)
    async def callback(self, interaction):
        self.game.voted_count[interaction.user.id] = self.children[0].values[0]
        await interaction.response.send_message(f"{interaction.user.display_name} さんが投票しました。", ephemeral=True)

async def setup(bot):
    await bot.add_cog(JinrouCog(bot))
