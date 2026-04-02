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
        self.is_running: bool = False
        self.players: list[discord.Member] = []
        self.roles: dict[int, str] = {}          # {user_id: role_name}
        self.alive_players: list[discord.Member] = []
        self.night_actions: dict[int, int] = {}  # {user_id: target_id}
        self.voted_count: dict[int, str] = {}    # {user_id: target_val}
        self.last_executed: int | None = None
        self.game_channel: discord.TextChannel | None = None


# ======================================================
#  Cog 本体
# ======================================================

class JinrouCog(commands.Cog):

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.game = JinrouGame()

    # --------------------------------------------------
    #  ヘルパー
    # --------------------------------------------------

    def get_wolves_names(self) -> str:
        wolves = []
        for p_id, role in self.game.roles.items():
            if role == "人狼":
                member = self.game.game_channel.guild.get_member(p_id)
                if member:
                    wolves.append(member.display_name)
        return "、".join(wolves) if wolves else "なし"

    def get_member_safe(self, user_id: int) -> discord.Member | None:
        return self.game.game_channel.guild.get_member(user_id)

    async def mute_dead_player(self, member: discord.Member) -> None:
        muted_role = discord.utils.get(member.guild.roles, name="muted")
        if muted_role is None:
            return
        try:
            await member.add_roles(muted_role, reason="人狼ゲーム：死亡")
        except Exception:
            pass

    async def reset_mutes(self) -> None:
        if self.game.game_channel is None:
            return
        muted_role = discord.utils.get(
            self.game.game_channel.guild.roles, name="muted"
        )
        if muted_role is None:
            return
        
        for member in muted_role.members:
            try:
                await member.remove_roles(muted_role, reason="人狼ゲーム終了")
            except Exception:
                pass

    # --------------------------------------------------
    #  メインコマンド
    # --------------------------------------------------

    @app_commands.command(
        name="jinrou", description="人狼ゲームを開始し、参加者を募集します"
    )
    async def jinrou(self, interaction: discord.Interaction) -> None:
        if self.game.is_running:
            await interaction.response.send_message(
                "既にゲームが進行中、または募集中です。", ephemeral=True
            )
            return

        self.game = JinrouGame()
        self.game.is_running = True
        self.game.game_channel = interaction.channel

        # 1. 参加募集
        await interaction.response.send_message(
            "【人狼ゲーム】参加者の募集を開始します！1分以内に下のボタンを押して参加してください。",
            view=RecruitView(self.game),
        )

        await asyncio.sleep(60)

        if len(self.game.players) < 5:
            await interaction.channel.send("参加者が5人未満のため、ゲームを中止します。")
            self.game.is_running = False
            return

        # 2. 役職振り分け
        self.game.alive_players = self.game.players.copy()
        self.assign_roles()

        active_roles = sorted(list(set(self.game.roles.values())))
        roles_display = " / ".join(active_roles)
        players_mentions = ", ".join([p.mention for p in self.game.players])

        await interaction.channel.send(
            f"【ゲーム開始】参加プレイヤー: {players_mentions}\n"
            f"今回の役職一覧: {roles_display}\n"
            "役職確認ボタンを押して、自分の役職を確認してください。",
            view=RoleCheckView(self.game, self),
        )

        try:
            # 3. 特別ディスカッション（初日の導入）
            await self.run_discussion(minutes=2, title="特別ディスカッション（導入）")
            if not self.game.is_running: return

            # --- ゲームループ ---
            while self.game.is_running:
                # 4. 夜フェーズ（アクション実行）
                await self.run_night_phase()
                if not self.game.is_running or await self.check_victory():
                    break

                # 5. 昼のディスカッション（夜の結果を受けて話し合い）
                await self.run_discussion(minutes=2, title="昼のディスカッション")
                if not self.game.is_running: 
                    break

                # 6. 投票フェーズ
                await self.run_voting_phase()
                if not self.game.is_running or await self.check_victory():
                    break
                
                # 投票が終わったらループの先頭に戻り「夜」へ

        except Exception as e:
            await interaction.channel.send(f"⚠️ エラーが発生しました: `{e}`")
            self.game.is_running = False
        finally:
            await self.reset_mutes()

    # --------------------------------------------------
    #  役職割り当て
    # --------------------------------------------------

    def assign_roles(self) -> None:
        num_players = len(self.game.players)
        num_wolves = max(1, num_players // 4)

        roles_pool: list[str] = ["人狼"] * num_wolves
        roles_pool += ["占い師", "霊媒師", "騎士", "てるてる坊主", "狂人"]

        remaining = num_players - len(roles_pool)
        if remaining > 0:
            roles_pool += ["村人"] * remaining
        else:
            roles_pool = roles_pool[:num_players]

        random.shuffle(roles_pool)

        for i, player in enumerate(self.game.players):
            self.game.roles[player.id] = roles_pool[i]

    # --------------------------------------------------
    #  フェーズ管理メソッド
    # --------------------------------------------------

    async def run_discussion(self, minutes: int = 2, title: str = "ディスカッション") -> None:
        await self.game.game_channel.send(f"ーー {title}開始（{minutes}分間） ーー")
        for remaining in range(minutes, 0, -1):
            await asyncio.sleep(60)
            if not self.game.is_running: return
            if remaining > 1:
                await self.game.game_channel.send(f"【{title}残り {remaining - 1} 分】")
        await self.game.game_channel.send(f"ーー {title}終了 ーー")

    async def run_night_phase(self) -> None:
        await self.game.game_channel.send(
            "ーー 夜のフェーズに入りました（制限時間1分） ーー\n"
            "役職をお持ちの方は、ボタンからアクションを行ってください。"
        )
        self.game.night_actions = {}
        view = NightActionView(self.game)
        msg = await self.game.game_channel.send("夜のアクションを受付中...", view=view)

        # アクションが必要な生存者の数
        required = sum(1 for p in self.game.alive_players if self.game.roles.get(p.id) in ["占い師", "騎士", "人狼"])

        timer = 0
        while len(self.game.night_actions) < required and timer < 60:
            await asyncio.sleep(1)
            timer += 1

        try: await msg.delete()
        except: pass

        await self.process_night_results()

    async def process_night_results(self) -> None:
        wolves_target = None
        knight_target = None

        for p_id, target in self.game.night_actions.items():
            role = self.game.roles.get(p_id)
            if role == "人狼": wolves_target = target
            elif role == "騎士": knight_target = target

        if wolves_target and wolves_target != knight_target:
            victim = self.get_member_safe(wolves_target)
            if victim:
                await self.game.game_channel.send(f"【夜の結果】朝、{victim.display_name} さんが無残な姿で発見されました。")
                self.game.alive_players = [p for p in self.game.alive_players if p.id != wolves_target]
                await self.mute_dead_player(victim)
        else:
            await self.game.game_channel.send("【夜の結果】朝になりました。昨晩の犠牲者はいないようです。")

    async def run_voting_phase(self) -> None:
        await self.game.game_channel.send("ーー 投票フェーズ ーー\n追放する人を1人選ぶか、スキップを選んでください。")

        options = [discord.SelectOption(label=p.display_name, value=str(p.id)) for p in self.game.alive_players]
        options.append(discord.SelectOption(label="スキップ", value="skip"))

        self.game.voted_count = {}
        view = PublicVoteView(self.game, options)
        msg = await self.game.game_channel.send("投票してください（制限時間1分）。", view=view)

        await asyncio.sleep(60)
        try: await msg.delete()
        except: pass

        if not self.game.voted_count:
            await self.game.game_channel.send("投票がなかったため、追放はありません。")
            self.game.last_executed = None
            return

        counts = Counter(self.game.voted_count.values())
        most_common = counts.most_common()
        max_votes = most_common[0][1]
        candidates = [t for t, cnt in most_common if cnt == max_votes]

        if len(candidates) > 1 or candidates[0] == "skip":
            await self.game.game_channel.send("同数票、またはスキップが最多のため追放はありません。")
            self.game.last_executed = None
            return

        target_id = int(candidates[0])
        target_member = self.get_member_safe(target_id)
        if target_member:
            await self.game.game_channel.send(f"投票の結果、{target_member.display_name} さんが追放されました。")
            self.game.last_executed = target_id
            self.game.alive_players = [p for p in self.game.alive_players if p.id != target_id]
            await self.mute_dead_player(target_member)

            if self.game.roles.get(target_id) == "てるてる坊主":
                await self.game.game_channel.send(f"🎉 {target_member.display_name} さんは【てるてる坊主】でした！単独勝利です！")
                self.game.is_running = False

    async def check_victory(self) -> bool:
        if not self.game.is_running: return True
        wolves = [p for p in self.game.alive_players if self.game.roles.get(p.id) == "人狼"]
        non_wolves = [p for p in self.game.alive_players if self.game.roles.get(p.id) != "人狼"]

        if not wolves:
            await self.game.game_channel.send("【終了】人狼が全滅しました！村人陣営の勝利です！")
            self.game.is_running = False
            return True
        if len(wolves) >= len(non_wolves):
            await self.game.game_channel.send("【終了】人狼が村人と同数以上になりました！人狼陣営の勝利です！")
            self.game.is_running = False
            return True
        return False


# ======================================================
#  UI コンポーネント (View)
# ======================================================

class RecruitView(discord.ui.View):
    def __init__(self, game: JinrouGame):
        super().__init__(timeout=60)
        self.game = game

    @discord.ui.button(label="参加する", style=discord.ButtonStyle.success)
    async def join_game(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user not in self.game.players:
            self.game.players.append(interaction.user)
            await interaction.response.send_message(f"{interaction.user.display_name} さんが参加！")
        else:
            await interaction.response.send_message("既に参加しています。", ephemeral=True)


class RoleCheckView(discord.ui.View):
    def __init__(self, game, cog):
        super().__init__(timeout=None)
        self.game, self.cog = game, cog

    @discord.ui.button(label="役職を確認する", style=discord.ButtonStyle.primary)
    async def check_role(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        player_id = interaction.user.id
        if player_id not in self.game.roles:
            await interaction.followup.send("不参加です。", ephemeral=True)
            return

        role = self.game.roles[player_id]
        wolves = self.cog.get_wolves_names() 
        desc = {
            "村人": "【村人】能力なし。議論で人狼を見つけましょう。",
            "人狼": f"【人狼】夜に襲撃可能。仲間: {wolves}",
            "狂人": f"【人狼陣営】人狼の味方。人狼: {wolves}",
            "てるてる坊主": "【第3陣営】追放されると勝利！",
            "占い師": "【村人】毎晩、一人を占えます。",
            "霊媒師": "【村人】追放された人の正体を知れます。",
            "騎士": "【村人】毎晩、一人を守れます。",
        }
        await interaction.followup.send(f"役職: **{role}**\n{desc.get(role, '')}", ephemeral=True)


class NightActionView(discord.ui.View):
    def __init__(self, game):
        super().__init__(timeout=60)
        self.game = game

    @discord.ui.button(label="アクションを実行", style=discord.ButtonStyle.success)
    async def night_action(self, interaction: discord.Interaction, button: discord.ui.Button):
        p_id = interaction.user.id
        if p_id not in [p.id for p in self.game.alive_players]:
            await interaction.response.send_message("生存していません。", ephemeral=True)
            return

        role = self.game.roles.get(p_id)
        opts = [discord.SelectOption(label=p.display_name, value=str(p.id)) for p in self.game.alive_players if p.id != p_id]

        if role == "占い師":
            await interaction.response.send_message("占う対象:", view=ActionSelectView(self.game, opts, "占い"), ephemeral=True)
        elif role == "騎士":
            await interaction.response.send_message("守る対象:", view=ActionSelectView(self.game, opts, "守る"), ephemeral=True)
        elif role == "人狼":
            await interaction.response.send_message("襲撃対象:", view=ActionSelectView(self.game, opts, "襲撃"), ephemeral=True)
        elif role == "霊媒師":
            await interaction.response.defer(ephemeral=True)
            if self.game.last_executed:
                res = "人狼" if self.game.roles.get(self.game.last_executed) == "人狼" else "人間"
                await interaction.followup.send(f"昨日追放された人は【{res}】でした。", ephemeral=True)
            else:
                await interaction.followup.send("昨日追放された人はいません。", ephemeral=True)
        else:
            await interaction.response.send_message("アクションはありません。", ephemeral=True)


class ActionSelectView(discord.ui.View):
    def __init__(self, game, options, action_type):
        super().__init__(timeout=60)
        self.game, self.action_type = game, action_type
        select = discord.ui.Select(placeholder=f"対象選択（{action_type}）", options=options)
        select.callback = self.select_callback
        self.add_item(select)

    async def select_callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        t_id = int(self.children[0].values[0])
        self.game.night_actions[interaction.user.id] = t_id
        if self.action_type == "占い":
            res = "人狼" if self.game.roles.get(t_id) == "人狼" else "人間"
            await interaction.followup.send(f"結果: 【{res}】です。", ephemeral=True)
        else:
            await interaction.followup.send("完了しました。", ephemeral=True)
        self.stop()


class PublicVoteView(discord.ui.View):
    def __init__(self, game, options):
        super().__init__(timeout=60)
        self.game = game
        select = discord.ui.Select(placeholder="投票先:", options=options)
        select.callback = self.select_callback
        self.add_item(select)

    async def select_callback(self, interaction: discord.Interaction):
        if interaction.user.id not in [p.id for p in self.game.alive_players]:
            await interaction.response.send_message("死亡者は投票不可です。", ephemeral=True)
            return
        self.game.voted_count[interaction.user.id] = self.children[0].values[0]
        await interaction.response.send_message(f"{interaction.user.display_name} さんが投票しました。")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(JinrouCog(bot))
