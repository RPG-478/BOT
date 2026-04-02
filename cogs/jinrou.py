import asyncio
import random
from collections import Counter
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

# ======================================================
#  Cog 本体
# ======================================================
class JinrouCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.game = JinrouGame()

    def get_wolves_names(self) -> str:
        wolves = []
        for p_id, role in self.game.roles.items():
            if role in ["人狼", "大狼"]:
                m = self.game.game_channel.guild.get_member(p_id)
                if m: wolves.append(m.display_name)
        return "、".join(wolves) if wolves else "なし"

    async def mute_member(self, member):
        """指定したメンバーにmutedロールを付与"""
        role = discord.utils.get(member.guild.roles, name="muted")
        if role:
            try: await member.add_roles(role)
            except: pass

    async def unmute_member(self, member):
        """指定したメンバーのmutedロールを解除"""
        role = discord.utils.get(member.guild.roles, name="muted")
        if role:
            try: await member.remove_roles(role)
            except: pass

    async def reset_mutes(self):
        """サーバー全体のmutedロールを全解除"""
        if not self.game.game_channel: return
        role = discord.utils.get(self.game.game_channel.guild.roles, name="muted")
        if role:
            for m in role.members:
                try: await m.remove_roles(role)
                except: pass

    # --------------------------------------------------
    #  役職配布ロジック
    # --------------------------------------------------
    def assign_roles(self):
        num = len(self.game.players)
        num_wolves = max(1, num // 5)
        
        # 1. 必須枠
        pool = ["村人", "占い師"]
        pool += ["人狼"] * num_wolves
        
        # 2. 6人以上ならプロ役職を混ぜる
        pro_roles = ["てるてる坊主", "サイコキラー", "あごむに破道砲", "大狼", "パン屋"]
        base_roles = ["霊媒師", "騎士", "狂人"]
        
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
                    pool.append("村人")

        pool = pool[:num]
        random.shuffle(pool)
        for i, p in enumerate(self.game.players):
            self.game.roles[p.id] = pool[i]

    # --------------------------------------------------
    #  メインループ
    # --------------------------------------------------
    @app_commands.command(name="jinrou", description="人狼ゲームを開始します")
    async def jinrou(self, interaction: discord.Interaction):
        if self.game.is_running:
            return await interaction.response.send_message("進行中です", ephemeral=True)

        self.game = JinrouGame()
        self.game.is_running = True
        self.game.game_channel = interaction.channel
        await interaction.response.send_message("募集開始(1分)", view=RecruitView(self.game))
        await asyncio.sleep(60)

        if len(self.game.players) < 5:
            self.game.is_running = False
            return await interaction.channel.send("5人未満のため中止します。")

        self.game.alive_players = self.game.players.copy()
        self.assign_roles()
        
        roles_list = " / ".join(set(self.game.roles.values()))
        await interaction.channel.send(f"ゲーム開始！役職一覧: {roles_list}", view=RoleCheckView(self.game, self))

        try:
            await self.run_discussion(minutes=2, title="特別ディスカッション")
            while self.game.is_running:
                await self.run_night_phase()
                if not self.game.is_running or await self.check_victory(): break
                await self.run_discussion(minutes=3, title="昼のディスカッション")
                if not self.game.is_running: break
                await self.run_voting_phase()
                if not self.game.is_running or await self.check_victory(): break
        except Exception as e:
            print(f"Error: {e}")
        finally:
            await self.reset_mutes()

    async def run_discussion(self, minutes, title):
        await self.game.game_channel.send(f"ーー {title}（{minutes}分） ーー")
        if any(self.game.roles.get(p.id) == "パン屋" for p in self.game.alive_players):
            await self.game.game_channel.send("🍞 パン屋さんが美味しいパンを焼いてくれました。今日も一日頑張りましょう！")
        
        for _ in range(minutes * 60):
            await asyncio.sleep(1)
            if not self.game.is_running: return
        await self.game.game_channel.send(f"ーー {title}終了 ーー")

    # --------------------------------------------------
    #  夜フェーズ & 特殊役職処理
    # --------------------------------------------------
    async def run_night_phase(self):
        await self.game.game_channel.send("ーー 夜のフェーズ（1分） ーー")
        
        # 夜フェーズ開始時に生存者をミュート
        for p in self.game.alive_players:
            await self.mute_member(p)

        self.game.night_actions = {}
        view = NightActionView(self.game)
        msg = await self.game.game_channel.send("アクションを選択してください", view=view)
        
        req = sum(1 for p in self.game.alive_players if self.game.roles.get(p.id) in ["占い師", "騎士", "人狼", "大狼", "あごむに破道砲"])
        
        t = 0
        while len(self.game.night_actions) < req and t < 60:
            await asyncio.sleep(1)
            t += 1
            if not self.game.is_running: break
        
        try: await msg.delete()
        except: pass

        # ミュート解除（死亡処理の前に一度リセット）
        for p in self.game.alive_players:
            await self.unmute_member(p)
            
        await self.process_night_results()

    async def process_night_results(self):
        dead_ids = set()
        wolves_target = None
        knight_target = None
        psycho_killer_ids = [p.id for p in self.game.alive_players if self.game.roles.get(p.id) == "サイコキラー"]

        for p_id, t_id in self.game.night_actions.items():
            role = self.game.roles.get(p_id)
            
            if t_id in psycho_killer_ids:
                dead_ids.add(p_id)
                await self.game.game_channel.send(f"【悲報】誰かがサイコキラーに返り討ちにされました...")

            if role in ["人狼", "大狼"]: wolves_target = t_id
            elif role == "騎士": knight_target = t_id
            elif role == "あごむに破道砲":
                dead_ids.add(p_id)
                dead_ids.add(t_id)
                self.game.used_hadouhou = True
                others = [p.id for p in self.game.alive_players if p.id not in [p_id, t_id]]
                if others: dead_ids.add(random.choice(others))
                await self.game.game_channel.send("💥 **あごむに破道砲が火を噴いた！** 辺りは火の海だ...")

        if wolves_target and wolves_target != knight_target:
            dead_ids.add(wolves_target)

        if dead_ids:
            for d_id in dead_ids:
                m = self.game.game_channel.guild.get_member(d_id)
                if m and d_id in [p.id for p in self.game.alive_players]:
                    await self.game.game_channel.send(f"【夜の結果】{m.display_name} さんが無残な姿で発見されました。")
                    self.game.alive_players = [p for p in self.game.alive_players if p.id != d_id]
                    await self.mute_member(m) # 死者は永続ミュート
        else:
            await self.game.game_channel.send("【夜の結果】昨晩の犠牲者はいないようです。")

    async def check_victory(self):
        if not self.game.is_running: return True
        wolves = [p for p in self.game.alive_players if self.game.roles.get(p.id) in ["人狼", "大狼"]]
        non_wolves = [p for p in self.game.alive_players if self.game.roles.get(p.id) not in ["人狼", "大狼"]]
        if not wolves:
            await self.game.game_channel.send("人狼全滅！村人陣営の勝利！")
            self.game.is_running = False
            return True
        if len(wolves) >= len(non_wolves):
            await self.game.game_channel.send("人狼が村人と同数以上！人狼陣営の勝利！")
            self.game.is_running = False
            return True
        return False

    async def run_voting_phase(self):
        await self.game.game_channel.send("ーー 投票フェーズ（1分） ーー")
        
        # 投票フェーズ開始時に生存者をミュート
        for p in self.game.alive_players:
            await self.mute_member(p)

        opts = [discord.SelectOption(label=p.display_name, value=str(p.id)) for p in self.game.alive_players]
        opts.append(discord.SelectOption(label="スキップ", value="skip"))
        self.game.voted_count = {}
        view = PublicVoteView(self.game, opts)
        msg = await self.game.game_channel.send("生存者は投票してください", view=view)
        await asyncio.sleep(60)
        
        try: await msg.delete()
        except: pass
        
        # 一旦ミュート解除
        for p in self.game.alive_players:
            await self.unmute_member(p)
        
        if not self.game.voted_count:
            await self.game.game_channel.send("投票がなかったため追放なし。")
            return
            
        counts = Counter(self.game.voted_count.values())
        most = counts.most_common()
        if len(most) > 1 and most[0][1] == most[1][1]:
            return await self.game.game_channel.send("同数票のため追放なし。")
        
        target_id = most[0][0]
        if target_id == "skip": return await self.game.game_channel.send("スキップされました。")
        
        target_m = self.game.game_channel.guild.get_member(int(target_id))
        if target_m:
            await self.game.game_channel.send(f"投票の結果、{target_m.display_name} さんが追放されました。")
            self.game.last_executed = int(target_id)
            self.game.alive_players = [p for p in self.game.alive_players if p.id != int(target_id)]
            await self.mute_member(target_m) # 追放者は永続ミュート
            if self.game.roles.get(int(target_id)) == "てるてる坊主":
                await self.game.game_channel.send("てるてる坊主が追放された！単独勝利！")
                self.game.is_running = False

# ======================================================
#  UI コンポーネント
# ======================================================
class NightActionView(discord.ui.View):
    def __init__(self, game):
        super().__init__(timeout=60)
        self.game = game

    @discord.ui.button(label="アクション実行", style=discord.ButtonStyle.success)
    async def action(self, interaction, button):
        p_id = interaction.user.id
        if p_id not in [p.id for p in self.game.alive_players]: return
        role = self.game.roles.get(p_id)
        opts = [discord.SelectOption(label=p.display_name, value=str(p.id)) for p in self.game.alive_players if p.id != p_id]

        if role == "占い師":
            await interaction.response.send_message("占う対象:", view=ActionSelectView(self.game, opts, "占い"), ephemeral=True)
        elif role == "騎士":
            await interaction.response.send_message("守る対象:", view=ActionSelectView(self.game, opts, "守る"), ephemeral=True)
        elif role in ["人狼", "大狼"]:
            await interaction.response.send_message("襲撃対象:", view=ActionSelectView(self.game, opts, "襲撃"), ephemeral=True)
        elif role == "あごむに破道砲":
            if self.game.used_hadouhou:
                await interaction.response.send_message("もう弾切れです...", ephemeral=True)
            else:
                await interaction.response.send_message("【警告】使用すると自分も死にます。対象:", view=ActionSelectView(self.game, opts, "あごむに"), ephemeral=True)
        elif role == "霊媒師":
            if self.game.last_executed:
                r = self.game.roles.get(self.game.last_executed)
                is_wolf = "人狼" if r in ["人狼", "大狼"] else "人間"
                await interaction.response.send_message(f"追放者は【{is_wolf}】でした。", ephemeral=True)
            else:
                await interaction.response.send_message("昨日追放された人はいません。", ephemeral=True)
        else:
            await interaction.response.send_message("アクションはありません。", ephemeral=True)

class ActionSelectView(discord.ui.View):
    def __init__(self, game, options, atype):
        super().__init__(timeout=60)
        self.game, self.atype = game, atype
        s = discord.ui.Select(options=options)
        s.callback = self.callback
        self.add_item(s)

    async def callback(self, interaction):
        t_id = int(self.children[0].values[0])
        self.game.night_actions[interaction.user.id] = t_id
        if self.atype == "占い":
            r = self.game.roles.get(t_id)
            res = "人間" if r == "大狼" else ("人狼" if r == "人狼" else "人間")
            await interaction.response.send_message(f"占いの結果、対象は【{res}】です。", ephemeral=True)
        else:
            await interaction.response.send_message("完了。", ephemeral=True)

class RecruitView(discord.ui.View):
    def __init__(self, game):
        super().__init__(timeout=60)
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
        role = self.game.roles.get(interaction.user.id)
        wolves = self.cog.get_wolves_names()
        descs = {
            "村人": "市民。", "占い師": "毎晩一人を占い、人狼か知る。", "霊媒師": "昨日追放された者の正体を知る。",
            "人狼": f"仲間: {wolves}", "騎士": "毎晩一人を守る。", "狂人": "人狼の味方。",
            "てるてる坊主": "追放されたら勝利。", "サイコキラー": "自分に関与した者を返り討ちにします。",
            "あごむに破道砲": "一度だけ自分と道連れに数人をキルできる。", "大狼": "占われてもバレない人狼。襲撃も可能。",
            "パン屋": "生きている間、朝にパンを配ります。"
        }
        await interaction.response.send_message(f"役職: {role}\n{descs.get(role, '詳細なし')}", ephemeral=True)

class PublicVoteView(discord.ui.View):
    def __init__(self, game, options):
        super().__init__(timeout=60)
        self.game = game
        s = discord.ui.Select(options=options)
        s.callback = self.callback
        self.add_item(s)
    async def callback(self, interaction):
        if interaction.user.id not in [p.id for p in self.game.alive_players]:
            return await interaction.response.send_message("死亡している方は投票できません。", ephemeral=True)
            
        self.game.voted_count[interaction.user.id] = self.children[0].values[0]
        await interaction.response.send_message(f"{interaction.user.display_name} さんが投票しました。")

async def setup(bot):
    await bot.add_cog(JinrouCog(bot))
