import asyncio
import random
from collections import Counter
import discord
from discord import app_commands
from discord.ext import commands
import os

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
        self.day_count = 0        # 経過日数（夜が来るたびにカウント）
        self.wan_owner = {}       # {ワンころID: 飼い主ID}

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
        
        pro_roles = ["ハゲ", "メンヘラ", "あごむに破道砲", "デカ狼", "パン屋", "マサイ族", "入狼", "ワンころ", "タフむに"]
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

    @app_commands.command(name="jinrou_help", description="役職の説明を確認します")
    async def jinrou_help(self, interaction: discord.Interaction):
        help_text = (
            "### 🛡️ 村人陣営\n"
            "**・一般通過あごむに**: 一般通過あごむに。空気薄い。\n"
            "**・占い師**: 毎晩1人を占える、金はないのでビー玉で占っている。\n"
            "**・霊媒師**: 昨日追放された者の正体を知る。\n"
            "**・騎士**: 毎晩一人をつまようじで守る。\n"
            "**・パン屋**: 生きているうちは朝にパンを配る。ワンチャン死んでても配る。\n"
            "**・マサイ族**: 視力がいい。だがこのゲームにおいて視力は関係ない。\n"
            "**・入狼**: 生まれた名前が悪かったな！！人狼と誤解される村陣営。\n"
            "**・タフむに**: 殺された時に殺し返す一般通過あごむに（表示はあごむに）。\n\n"
            "### 🐺 人狼陣営\n"
            "**・人狼**: 仲間の人狼と協力して村人を襲撃する。\n"
            "**・デカ狼**: 占い師に賄賂を払って白判定にする。デカイだけである。\n"
            "**・狂人**: 人狼の味方。無能。\n"
            "**・メンヘラ**: 自分に関与した者を殺す。\n\n"
            "### 🃏 その他\n"
            "**・ハゲ**: 追放されたら勝てる。髪の毛が観測できないバグが発生中。\n"
            "**・あごむに破道砲**: 自らを弾にして1人を狙い撃ちできるが、誤発してもう1人殺す。\n"
            "**・ワンころ**: 最初の夜に飼い主を決める。飼い主がいれば村、いなければ人狼になる。占いは「人狼」。"
        )
        await interaction.response.send_message(help_text, ephemeral=True)

    @app_commands.command(name="jinrou", description="人狼ゲームを開始します")
    @app_commands.describe(wait_minutes="募集期間を分単位で指定してください（デフォルト1分）")
    async def jinrou(self, interaction: discord.Interaction, wait_minutes: int = 1):
        game = self.get_game(interaction.channel_id)
        if game.is_running:
            return await interaction.response.send_message("このチャンネルでは既に進行中です", ephemeral=True)

        new_game = JinrouGame()
        self.games[interaction.channel_id] = new_game
        game = new_game
        
        game.is_running = True
        game.game_channel = interaction.channel
        
        view = RecruitView(game, timeout=wait_minutes * 60)
        await interaction.response.send_message(f"募集開始({wait_minutes}分)", view=view)
        
        await asyncio.sleep(wait_minutes * 60)

        if len(game.players) < 5:
            game.is_running = False
            return await interaction.channel.send("5人未満のため中止します。")

        game.alive_players = game.players.copy()
        self.assign_roles(game)
        
        mentions = " ".join([p.mention for p in game.players])
        
        roles_for_display = []
        for r in game.roles.values():
            if r == "タフむに":
                roles_for_display.append("一般通過あごむに")
            elif r == "入狼":
                roles_for_display.append("人狼")
            else:
                roles_for_display.append(r)
        
        roles_list = " / ".join(set(roles_for_display))
        await interaction.channel.send(f"{mentions}\nゲーム開始！役職一覧: {roles_list}", view=RoleCheckView(game, self))

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
            print(f"Error in channel {interaction.channel_id}: {e}")
        finally:
            await self.reset_mutes(game)
            game.is_running = False

    async def run_discussion(self, game, minutes, title):
        await game.game_channel.send(f"ーー {title}（{minutes}分） ーー")
        if any(game.roles.get(p.id) == "パン屋" for p in game.alive_players):
            await game.game_channel.send("🍞 パン屋さんが美味しいパンを焼いてくれました。今日も一日頑張りましょう！")
        
        for _ in range(minutes * 60):
            await asyncio.sleep(1)
            if not game.is_running: return
        await game.game_channel.send(f"ーー {title}終了 ーー")

    async def run_night_phase(self, game):
        game.day_count += 1
        await game.game_channel.send(f"ーー 第{game.day_count}夜（1分） ーー")
        for p in game.alive_players:
            await self.mute_member(p)

        game.night_actions = {}
        view = NightActionView(game)
        msg = await game.game_channel.send("アクションを選択してください", view=view)
        
        req_roles = ["占い師", "騎士", "人狼", "デカ狼", "あごむに破道砲"]
        if game.day_count == 1: req_roles.append("ワンころ")
        
        req = sum(1 for p in game.alive_players if game.roles.get(p.id) in req_roles)
        
        t = 0
        while len(game.night_actions) < req and t < 60:
            await asyncio.sleep(1)
            t += 1
            if not game.is_running: break
        
        try: await msg.delete()
        except: pass

        for p in game.alive_players:
            await self.unmute_member(p)
            
        await self.process_night_results(game)

    async def process_night_results(self, game):
        dead_ids = set()
        wolves_target = None
        knight_targets = set()
        psycho_killer_ids = [p.id for p in game.alive_players if game.roles.get(p.id) == "メンヘラ"]

        for wan_id, owner_id in game.wan_owner.items():
            if wan_id in [p.id for p in game.alive_players]:
                knight_targets.add(owner_id)

        for p_id, t_id in game.night_actions.items():
            role = game.roles.get(p_id)
            if t_id in psycho_killer_ids:
                dead_ids.add(p_id)
                await game.game_channel.send(f"【悲報】誰かがメンヘラに返り討ちにされました...")

            if role in ["人狼", "デカ狼"]: wolves_target = t_id
            elif role == "騎士": knight_targets.add(t_id)
            elif role == "あごむに破道砲":
                dead_ids.add(p_id)
                dead_ids.add(t_id)
                game.used_hadouhou = True
                others = [p.id for p in game.alive_players if p.id not in [p_id, t_id]]
                if others: dead_ids.add(random.choice(others))
                await game.game_channel.send("💥 **あごむに破道砲が火を噴いた！** 辺りは火の海だ...")

        if wolves_target and wolves_target not in knight_targets:
            dead_ids.add(wolves_target)

        if dead_ids:
            for d_id in dead_ids:
                m = game.game_channel.guild.get_member(d_id)
                if m and d_id in [p.id for p in game.alive_players]:
                    await game.game_channel.send(f"【夜の結果】{m.display_name} さんが無残な姿で発見されました。")
                    if game.roles.get(d_id) == "タフむに":
                        killers = [p_id for p_id, t_id in game.night_actions.items() if t_id == d_id]
                        if killers:
                            k_id = random.choice(killers)
                            k_m = game.game_channel.guild.get_member(k_id)
                            if k_m:
                                await game.game_channel.send(f"💥 **タフむにの反撃！** {k_m.display_name} を道連れにした！")
                                game.alive_players = [p for p in game.alive_players if p.id != k_id]
                                await self.mute_member(k_m)
                    game.alive_players = [p for p in game.alive_players if p.id != d_id]
                    await self.mute_member(m)
        else:
            await game.game_channel.send("【夜の結果】昨晩の犠牲者はいないようです。")

    async def check_victory(self, game):
        if not game.is_running: return True
        def is_wolf_side(p_id):
            r = game.roles.get(p_id)
            if r in ["人狼", "デカ狼", "狂人"]: return True
            if r == "ワンころ" and p_id not in game.wan_owner: return True
            return False
        wolves = [p for p in game.alive_players if is_wolf_side(p.id)]
        non_wolves = [p for p in game.alive_players if not is_wolf_side(p.id)]
        if not wolves:
            await game.game_channel.send("人狼全滅！一般通過あごむに陣営の勝利！")
            game.is_running = False
            return True
        if len(wolves) >= len(non_wolves):
            await game.game_channel.send("人狼が一般通過あごむにと同数以上！人狼陣営の勝利！")
            game.is_running = False
            return True
        return False

    async def run_voting_phase(self, game):
        await game.game_channel.send("ーー 投票フェーズ（40秒） ーー")
        for p in game.alive_players:
            await self.mute_member(p)
        opts = [discord.SelectOption(label=p.display_name, value=str(p.id)) for p in game.alive_players]
        opts.append(discord.SelectOption(label="スキップ", value="skip"))
        game.voted_count = {}
        view = PublicVoteView(game, opts)
        msg = await game.game_channel.send("生存者は投票してください", view=view)
        await asyncio.sleep(40)
        try: await msg.delete()
        except: pass
        for p in game.alive_players:
            await self.unmute_member(p)
        if not game.voted_count:
            await game.game_channel.send("投票がなかったため追放なし。")
            return
        counts = Counter(game.voted_count.values())
        most = counts.most_common()
        if len(most) > 1 and most[0][1] == most[1][1]:
            return await game.game_channel.send("同数票のため追放なし。")
        target_id = most[0][0]
        if target_id == "skip": return await game.game_channel.send("スキップされました。")
        target_m = game.game_channel.guild.get_member(int(target_id))
        if target_m:
            await game.game_channel.send(f"投票の結果、{target_m.display_name} さんが追放されました。")
            game.last_executed = int(target_id)
            game.alive_players = [p for p in game.alive_players if p.id != int(target_id)]
            await self.mute_member(target_m)
            if game.roles.get(int(target_id)) == "ハゲ":
                await game.game_channel.send("ハゲが追放された！単独勝利！")
                game.is_running = False

# ======================================================
#  UI コンポーネント
# ======================================================
class NightActionView(discord.ui.View):
    def __init__(self, game):
        super().__init__(timeout=60)
        self.game = game

    @discord.ui.button(label="夜更かしする", style=discord.ButtonStyle.success)
    async def action(self, interaction, button):
        p_id = interaction.user.id
        if p_id not in [p.id for p in self.game.alive_players]: return
        if p_id in self.game.night_actions:
            return await interaction.response.send_message("既にアクションは完了しています。", ephemeral=True)
        role = self.game.roles.get(p_id)
        opts = [discord.SelectOption(label=p.display_name, value=str(p.id)) for p in self.game.alive_players if p.id != p_id]
        if role == "占い師":
            await interaction.response.send_message("ビー玉で占う対象:", view=ActionSelectView(self.game, opts, "占い"), ephemeral=True)
        elif role == "騎士":
            await interaction.response.send_message("つまようじで守る対象:", view=ActionSelectView(self.game, opts, "守る"), ephemeral=True)
        elif role in ["人狼", "デカ狼"]:
            await interaction.response.send_message("襲撃対象:", view=ActionSelectView(self.game, opts, "襲撃"), ephemeral=True)
        elif role == "ワンころ":
            if self.game.day_count == 1:
                await interaction.response.send_message("飼い主を選択:", view=ActionSelectView(self.game, opts, "飼い主"), ephemeral=True)
            else:
                await interaction.response.send_message("既に飼い主は決まっています。", ephemeral=True)
        elif role == "あごむに破道砲":
            if self.game.day_count <= 2:
                await interaction.response.send_message("3日目の夜から使用可能です。", ephemeral=True)
            elif self.game.used_hadouhou:
                await interaction.response.send_message("もう弾切れです...", ephemeral=True)
            else:
                await interaction.response.send_message("対象:", view=ActionSelectView(self.game, opts, "あごむに"), ephemeral=True)
        elif role == "霊媒師":
            if self.game.last_executed:
                r = self.game.roles.get(self.game.last_executed)
                is_wolf = "人狼" if r in ["人狼", "デカ狼"] else "人間"
                await interaction.response.send_message(f"追放者は【{is_wolf}】でした。", ephemeral=True)
            else:
                await interaction.response.send_message("昨日追放された人はいません。", ephemeral=True)
        else:
            await interaction.response.send_message("お前は寝てろ。", ephemeral=True)

class ActionSelectView(discord.ui.View):
    def __init__(self, game, options, atype):
        super().__init__(timeout=60)
        self.game, self.atype = game, atype
        s = discord.ui.Select(options=options)
        s.callback = self.callback
        self.add_item(s)
    async def callback(self, interaction):
        if interaction.user.id in self.game.night_actions and self.atype != "飼い主":
            return await interaction.response.send_message("既に完了しています。", ephemeral=True)
        t_id = int(self.children[0].values[0])
        if self.atype == "飼い主":
            self.game.wan_owner[interaction.user.id] = t_id
            self.game.night_actions[interaction.user.id] = t_id
            await interaction.response.send_message(f"飼い主を決定しました。", ephemeral=True)
        else:
            self.game.night_actions[interaction.user.id] = t_id
            if self.atype == "占い":
                r = self.game.roles.get(t_id)
                res = "人狼" if r in ["人狼", "入狼", "ワンころ"] else "人間"
                await interaction.response.send_message(f"結果: 【{res}】", ephemeral=True)
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
            await interaction.response.send_message(f"{interaction.user.display_name} さんが参加しました！")

class RoleCheckView(discord.ui.View):
    def __init__(self, game, cog):
        super().__init__(timeout=None)
        self.game, self.cog = game, cog
        
    @discord.ui.button(label="役職確認", style=discord.ButtonStyle.primary)
    async def check(self, interaction, button):
        real_role = self.game.roles.get(interaction.user.id)
        display_role = real_role
        if real_role == "タフむに":
            display_role = "一般通過あごむに"
        elif real_role == "入狼":
            display_role = "人狼"
            
        wolves = self.cog.get_wolves_names(self.game)
        descs = {
            "一般通過あごむに": "一般通過あごむに。空気薄い。", 
            "占い師": "毎晩1人を占える、金はないのでビー玉で占っている。", 
            "霊媒師": "昨日追放された者の正体を知る。",
            "人狼": f"仲間: {wolves}", 
            "騎士": "毎晩一人をつまようじで守る。", 
            "狂人": "人狼の味方。無能。",
            "ハゲ": "追放されたら勝てる。髪の毛が観測できないバグが発生中。", 
            "メンヘラ": "自分に関与した者を殺す。",
            "あごむに破道砲": "自らを弾にして1人を狙い撃ちできるが、誤発してもう1人殺す", 
            "デカ狼": "占い師に賄賂を払って白判定にする。デカイだけである。",
            "パン屋": "生きているうちは朝にパンを配る。ワンチャン死んでても配る",
            "マサイ族": "視力がいい。だがこのゲームにおいて視力は関係ない。",
            "入狼": "人狼と誤解される村陣営。占われても人狼判定。",
            "ワンころ": "最初の夜に飼い主を決める。飼い主がいれば村、いなければ人狼になる。占いは「人狼」。",
            "タフむに": "殺された時に殺し返す一般通過あごむに。"
        }

        # 役職名とファイル名の対応
        # NOMAL.PNG, JINROU.PNG, MASAI.PNG, MENHERA.PNG, NYUROU.PNG
        role_image_map = {
            "一般通過あごむに": "NOMAL.PNG",
            "人狼": "JINROU.PNG",
            "マサイ族": "MASAI.PNG",
            "メンヘラ": "MENHERA.PNG",
            "入狼": "NYUROU.PNG"
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
                file = discord.File(file_path, filename="role.png")
                embed.set_image(url="attachment://role.png")
                await interaction.response.send_message(embed=embed, file=file, ephemeral=True)
                return

        await interaction.response.send_message(embed=embed, ephemeral=True)

class PublicVoteView(discord.ui.View):
    def __init__(self, game, options):
        super().__init__(timeout=60)
        self.game = game
        s = discord.ui.Select(options=options)
        s.callback = self.callback
        self.add_item(s)
    async def callback(self, interaction):
        if interaction.user.id not in [p.id for p in self.game.alive_players]:
            return await interaction.response.send_message("死亡者は投票できません。", ephemeral=True)
        self.game.voted_count[interaction.user.id] = self.children[0].values[0]
        await interaction.response.send_message(f"{interaction.user.display_name} さんが投票しました。")

async def setup(bot):
    await bot.add_cog(JinrouCog(bot))