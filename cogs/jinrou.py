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

    async def mute_member(self, member):
        role = discord.utils.get(member.guild.roles, name="muted")
        if role:
            try: await member.add_roles(role)
            except: pass

    async def unmute_member(self, member):
        role = discord.utils.get(member.guild.roles, name="muted")
        if role:
            try: await member.remove_roles(role)
            except: pass

    async def reset_mutes(self, game):
        if not game.game_channel: return
        role = discord.utils.get(game.game_channel.guild.roles, name="muted")
        if role:
            for m in role.members:
                try: await m.remove_roles(role)
                except: pass

    def assign_roles(self, game):
        num = len(game.players)
        num_wolves = max(1, num // 5)
        
        pool = ["一般通過あごむに", "占い師", "騎士"]
        pool += ["人狼"] * num_wolves
        
        pro_roles = ["ハゲ", "メンヘラ", "あごむに破道砲", "デカ狼", "パン屋", "マサイ族", "入狼", "ワンころ", "タフむに", "狂信者"]
        base_roles = ["霊媒師", "狂人"]
        
        while len(pool) < num:
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

        pool = pool[:num]
        random.shuffle(pool)
        for i, p in enumerate(game.players):
            game.roles[p.id] = pool[i]

    @app_commands.command(name="kill", description="このチャンネルで進行中の人狼ゲームを強制終了します")
    async def kill(self, interaction: discord.Interaction):
        game = self.get_game(interaction.channel_id)
        if not game.is_running:
            return await interaction.response.send_message("このチャンネルで実行中のゲームはありません。", ephemeral=True)
        
        game.is_running = False
        await self.reset_mutes(game)
        await interaction.response.send_message("管理者によりゲームが強制終了されました。")

    @app_commands.command(name="jinrou_help", description="各役職の詳細な説明を表示します")
    async def jinrou_help(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="人狼ゲーム 役職説明書",
            description="各役職の役割と特徴の一覧です。絵文字はありません。真面目に読みなさい。",
            color=discord.Color.dark_gray()
        )
        roles_info = {
            "一般通過あごむに": "空気。存在しているだけで偉い。特に何もしない。",
            "占い師": "毎晩1人を占える。安物のビー玉を使って人間か人狼かを見抜く。",
            "霊媒師": "昨日追放された者が人間だったか人狼だったかを確認する悪趣味な仕事。",
            "騎士": "毎晩1人をつまようじで守る。自分は守れない不器用なやつ。",
            "人狼": "村人を食べる。仲間同士は誰が人狼か知っている。",
            "狂人": "人狼の味方をする人間。人狼が誰かは知らないが、とにかく場を乱す。",
            "ハゲ": "追放されたら勝利。髪の毛が観測できないバグのせいで目立ちすぎる。",
            "メンヘラ": "自分に関与した（占う、守る、食べる）者を物理的に消去する。",
            "あごむに破道砲": "自爆して対象を道連れにする。さらにもう1人も誤発で巻き込む。",
            "デカ狼": "占い師を賄賂で黙らせる人狼。デカイだけで威圧感がある。",
            "パン屋": "生きていれば朝にパンを配る。死んでいても何故かパンが届く怪奇現象を起こす。",
            "マサイ族": "視力とジャンプ力が高い。夜に1人を観察する。もし対象が人狼なら襲撃を50%で回避する準備を整える。真偽は誰にもわからない。",
            "入狼": "人狼のような名前の村人。占われると人狼判定が出る不幸なやつ。",
            "ワンころ": "最初に飼い主を決める。飼い主が死ぬかいない場合は野良化して人狼になる。",
            "タフむに": "殺された時に最後の一撃で相手を道連れにする根性の一般通過。",
            "狂信者": "人狼とデカ狼が誰かを知っている熱狂的なファン。人狼陣営の参謀。"
        }
        for name, desc in roles_info.items():
            embed.add_field(name=name, value=desc, inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="jinrou", description="人狼ゲームを開始します")
    @app_commands.describe(wait_minutes="募集時間を分単位で指定（1から1440分）")
    async def jinrou(self, interaction: discord.Interaction, wait_minutes: int = 1):
        game = self.get_game(interaction.channel_id)
        if game.is_running:
            return await interaction.response.send_message("このチャンネルでは既にゲームが進行中です。", ephemeral=True)

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

        view = RecruitView(game, timeout=wait_minutes * 60)
        await interaction.response.send_message(f"人狼ゲーム募集開始。募集時間: {wait_minutes}分", view=view)
        
        for _ in range(wait_minutes * 60):
            await asyncio.sleep(1)
            if not game.is_running: return

        if len(game.players) < 5:
            game.is_running = False
            return await interaction.channel.send("参加者が5人未満のため、ゲームを中止します。")

        game.alive_players = game.players.copy()
        self.assign_roles(game)
        
        mentions = " ".join([p.mention for p in game.players])
        
        roles_for_display = []
        for r in game.roles.values():
            if r == "タフむに": roles_for_display.append("一般通過あごむに")
            elif r == "入狼": roles_for_display.append("人狼")
            else: roles_for_display.append(r)
        
        roles_list = " / ".join(set(roles_for_display))
        await interaction.channel.send(
            f"{mentions}\nゲーム開始。今回の役職内訳: {roles_list}\n下のボタンで自分の役職を確認してください。",
            view=RoleCheckView(game, self)
        )

        try:
            await self.run_discussion(game, minutes=2, title="特別ディスカッション")
            
            while game.is_running:
                await self.run_night_phase(game)
                if not game.is_running or await self.check_victory(game): break
                
                await self.run_discussion(game, minutes=3, title="昼のディスカッション")
                if not game.is_running: break
                
                await self.run_voting_phase(game)
                if not game.is_running or await self.check_victory(game): break
                
        except Exception as e:
            print(f"Game Error: {e}")
        finally:
            await self.reset_mutes(game)
            game.is_running = False

    async def run_discussion(self, game, minutes, title):
        if not game.is_running: return
        await game.game_channel.send(f"ーー {title}（{minutes}分） ーー")
        if any(game.roles.get(p.id) == "パン屋" for p in game.alive_players):
            await game.game_channel.send("パン屋さんが美味しいパンを焼いてくれました。")
        
        for _ in range(minutes * 60):
            await asyncio.sleep(1)
            if not game.is_running: return
        await game.game_channel.send(f"ーー {title}終了 ーー")

    async def run_night_phase(self, game):
        if not game.is_running: return
        game.day_count += 1
        await game.game_channel.send(f"ーー 第{game.day_count}夜（1分） ーー")
        for p in game.alive_players: await self.mute_member(p)

        game.night_actions = {}
        view = NightActionView(game)
        msg = await game.game_channel.send("アクションを選択してください", view=view)
        
        req_roles = ["占い師", "騎士", "人狼", "デカ狼", "あごむに破道砲", "マサイ族"]
        if game.day_count == 1: req_roles.append("ワンころ")
        req = sum(1 for p in game.alive_players if game.roles.get(p.id) in req_roles)
        
        t = 0
        while len(game.night_actions) < req and t < 60:
            await asyncio.sleep(1)
            t += 1
            if not game.is_running: break
        
        try: await msg.delete()
        except: pass

        for p in game.alive_players: await self.unmute_member(p)
        await self.process_night_results(game)

    async def process_night_results(self, game):
        if not game.is_running: return
        dead_ids = set()
        wolves_target = None
        knight_targets = set()
        psycho_killer_ids = [p.id for p in game.alive_players if game.roles.get(p.id) == "メンヘラ"]

        for p_id, t_id in game.night_actions.items():
            role = game.roles.get(p_id)
            if t_id in psycho_killer_ids:
                dead_ids.add(p_id)
                await game.game_channel.send("誰かがメンヘラに返り討ちにされました。")

            if role in ["人狼", "デカ狼"]: wolves_target = t_id
            elif role == "騎士": knight_targets.add(t_id)
            elif role == "あごむに破道砲":
                dead_ids.add(p_id); dead_ids.add(t_id)
                game.used_hadouhou = True
                others = [p.id for p in game.alive_players if p.id not in [p_id, t_id]]
                if others: dead_ids.add(random.choice(others))
                await game.game_channel.send("あごむに破道砲が火を噴きました。")

        if wolves_target and wolves_target not in knight_targets:
            # マサイ族の回避判定
            if game.roles.get(wolves_target) == "マサイ族" and game.masai_evasion.get(wolves_target):
                if random.random() < 0.5:
                    await game.game_channel.send("マサイ族はジャンプ力が高いので襲撃を回避しました。")
                else:
                    dead_ids.add(wolves_target)
            else:
                dead_ids.add(wolves_target)

        if dead_ids:
            for d_id in dead_ids:
                if d_id in [p.id for p in game.alive_players]:
                    m = game.game_channel.guild.get_member(d_id)
                    if m:
                        await game.game_channel.send(f"夜の結果: {m.display_name} さんが犠牲になりました。")
                        if game.roles.get(d_id) == "タフむに":
                            killers = [pid for pid, tid in game.night_actions.items() if tid == d_id]
                            if killers:
                                k_id = random.choice(killers)
                                k_m = game.game_channel.guild.get_member(k_id)
                                if k_m:
                                    await game.game_channel.send(f"タフむにの反撃。 {k_m.display_name} を道連れにしました。")
                                    game.alive_players = [p for p in game.alive_players if p.id != k_id]
                                    await self.mute_member(k_m)
                        game.alive_players = [p for p in game.alive_players if p.id != d_id]
                        await self.mute_member(m)
        else:
            await game.game_channel.send("夜の結果: 昨晩の犠牲者はいないようです。")

    async def check_victory(self, game):
        if not game.is_running: return True
        def is_wolf_side(p_id):
            r = game.roles.get(p_id)
            if r in ["人狼", "デカ狼", "狂人", "狂信者"]: return True
            if r == "ワンころ" and p_id not in game.wan_owner: return True
            return False
        wolves = [p for p in game.alive_players if is_wolf_side(p.id)]
        non_wolves = [p for p in game.alive_players if not is_wolf_side(p.id)]
        if not wolves:
            await game.game_channel.send("人狼全滅。村人陣営の勝利です。")
            return True
        if len(wolves) >= len(non_wolves):
            await game.game_channel.send("人狼が支配した。人狼陣営の勝利です。")
            return True
        return False

    async def run_voting_phase(self, game):
        if not game.is_running: return
        await game.game_channel.send("ーー 投票フェーズ（40秒） ーー")
        for p in game.alive_players: await self.mute_member(p)
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
        for p in game.alive_players: await self.unmute_member(p)
        if not game.voted_count: return await game.game_channel.send("投票なし。")
        counts = Counter(game.voted_count.values())
        most = counts.most_common()
        if len(most) > 1 and most[0][1] == most[1][1]:
            return await game.game_channel.send("同数票のため追放なし。")
        target_id = most[0][0]
        if target_id == "skip": return await game.game_channel.send("スキップされました。")
        target_m = game.game_channel.guild.get_member(int(target_id))
        if target_m:
            await game.game_channel.send(f"{target_m.display_name} さんが追放されました。")
            game.last_executed = int(target_id)
            game.alive_players = [p for p in game.alive_players if p.id != int(target_id)]
            await self.mute_member(target_m)
            if game.roles.get(int(target_id)) == "ハゲ":
                await game.game_channel.send("ハゲが追放された。ハゲの勝利です。")
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
        real_role = self.game.roles.get(interaction.user.id)
        if real_role is None:
            return await interaction.response.send_message("あなたはゲームに参加していません。", ephemeral=True)
            
        display_role = real_role
        if real_role == "タフむに": display_role = "一般通過あごむに"
        elif real_role == "入狼": display_role = "人狼"
        
        wolves = self.cog.get_wolves_names(self.game)
        descs = {
            "一般通過あごむに": "一般通過あごむに。空気より存在感が薄い。", 
            "占い師": "毎晩1人を占える。金がないのでビー玉で占っている。", 
            "霊媒師": "昨日追放された者の正体を覗き見る趣味がある。",
            "人狼": f"仲間: {wolves}", 
            "騎士": "毎晩一人をつまようじで守る。", 
            "狂人": "人狼の味方。基本的に無能である。",
            "ハゲ": "追放されたら勝てる。髪の毛が観測できないバグが発生している。", 
            "メンヘラ": "自分に関与した者を物理的に消す。",
            "あごむに破道砲": "自らを弾にして1人を狙い撃ちできるが、誤発してもう1人殺す。", 
            "デカ狼": "占い師に賄賂を払って白判定にする。デカイだけである。",
            "パン屋": "生きているうちは朝にパンを配る。死んでいてもなぜかパンが届く。",
            "マサイ族": "視力とジャンプ力が高い。夜に1人を観察する。もし対象が人狼なら襲撃を50%で回避する準備を整える。真偽は誰にもわからない。",
            "入狼": "生まれた名前が悪かった。ビー玉で占ってるやつに人狼と誤解される哀れな村陣営。",
            "ワンころ": "最初の夜に飼い主を決める。飼い主がいないと野生化して人狼になる。",
            "タフむに": "殺された時に殺し返す根性のある一般通過あごむに。",
            "狂信者": f"人狼とデカ狼を知っている熱狂的な人狼ファン。 仲間: {wolves}"
        }

        role_image_map = {
            "一般通過あごむに": "NOMAL.PNG",
            "人狼": "JINROU.PNG",
            "マサイ族": "MASAI.PNG",
            "メンヘラ": "MENHERA.PNG",
            "入狼": "NYUROU.PNG",
            "騎士": "KISHI.PNG",
            "占い師": "URANAI.PNG",
            "霊媒師": "REIBAI.PNG",
            "パン屋": "PANYA.PNG",
            "狂人": "KYOJIN.PNG",
        }

        embed = discord.Embed(
            title=f"あなたの役職は 【{display_role}】 です",
            description=descs.get(real_role, "詳細なし"),
            color=discord.Color.blue()
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
        
        # 二重アクション防止チェック
        if p_id in self.game.night_actions:
            return await interaction.response.send_message("アクションは既に完了しています。欲張らないでください。", ephemeral=True)

        role = self.game.roles.get(p_id)
        
        # 夜に行動がない役職の判定
        passive_roles = ["一般通過あごむに", "霊媒師", "狂人", "ハゲ", "メンヘラ", "パン屋", "入狼", "タフむに", "狂信者"]
        if role in passive_roles:
            return await interaction.response.send_message("お前は寝てろ。明日の朝までじっとしてなさい。", ephemeral=True)
            
        opts = [discord.SelectOption(label=p.display_name, value=str(p.id)) for p in self.game.alive_players if p.id != p_id]
        if not opts: return await interaction.response.send_message("対象がいません。", ephemeral=True)
        await interaction.response.send_message("対象を選択:", view=ActionSelectView(self.game, opts, role), ephemeral=True)

class ActionSelectView(discord.ui.View):
    def __init__(self, game, options, role):
        super().__init__(timeout=60)
        self.game, self.role = game, role
        s = discord.ui.Select(options=options)
        s.callback = self.callback
        self.add_item(s)
    async def callback(self, interaction):
        p_id = interaction.user.id
        # 二重アクション防止（セレクトボックス経由）
        if p_id in self.game.night_actions:
            return await interaction.response.send_message("既にアクションは受理されています。", ephemeral=True)

        t_id = int(self.children[0].values[0])
        self.game.night_actions[p_id] = t_id

        if self.role == "占い師":
            r = self.game.roles.get(t_id)
            res = "人狼" if r in ["人狼", "入狼", "ワンころ"] else "人間"
            await interaction.response.send_message(f"結果: 【{res}】", ephemeral=True)
        elif self.role == "マサイ族":
            r = self.game.roles.get(t_id)
            # マサイ族の真偽を隠蔽
            if r in ["人狼", "デカ狼"]:
                self.game.masai_evasion[p_id] = True
            await interaction.response.send_message("対象の観察を完了しました。人狼であれば回避の準備を整えます。", ephemeral=True)
        else:
            await interaction.response.send_message("完了。", ephemeral=True)

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
        p_id = interaction.user.id
        
        # 生存確認
        if p_id not in [p.id for p in self.game.alive_players]:
            return await interaction.response.send_message("死人に口なし。墓場で大人しくしていなさい。", ephemeral=True)
            
        # 二重投票確認
        if p_id in self.game.voted_count:
            return await interaction.response.send_message("既に投票済みです。意志を何度も変えることはできません。", ephemeral=True)

        self.game.voted_count[p_id] = self.children[0].values[0]
        await interaction.response.send_message(f"{interaction.user.display_name} さんが投票を完了しました。")

async def setup(bot):
    await bot.add_cog(JinrouCog(bot))