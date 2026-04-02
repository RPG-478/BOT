import asyncio
import random
from collections import Counter
import discord
from discord import app_commands
from discord.ext import commands


# ゲームの状態管理用クラス
class JinrouGame:

    def __init__(self):
        self.is_running = False
        self.players = []  # 参加プレイヤー
        self.roles = {}  # {user_id: role_name}
        self.alive_players = []  # 生存プレイヤー
        self.night_actions = {}  # 夜のアクション {user_id: target_id}
        self.voted_count = {}  # 投票数 {user_id: target_val}
        self.last_executed = None  # 最後に追放されたプレイヤーのID
        self.game_channel = None


class JinrouCog(commands.Cog):

    def __init__(self, bot):
        self.bot = bot
        self.game = JinrouGame()

    # 人狼リストを取得するヘルパー関数
    def get_wolves_names(self):
        wolves = []
        for p_id, role in self.game.roles.items():
            if role == "人狼":
                member = self.game.game_channel.guild.get_member(p_id)
                if member:
                    wolves.append(member.display_name)
        return "、".join(wolves) if wolves else "なし"

    # 1. 参加者募集と役職配布
    @app_commands.command(
        name="jinrou", description="人狼ゲームを開始し、参加者を募集します"
    )
    async def jinrou(self, interaction: discord.Interaction):
        if self.game.is_running:
            await interaction.response.send_message(
                "既にゲームが進行中、または募集中です。", ephemeral=True
            )
            return

        self.game = JinrouGame()
        self.game.is_running = True
        self.game.game_channel = interaction.channel

        # 参加者募集（1分間）
        await interaction.response.send_message(
            "【人狼ゲーム】参加者の募集を開始します！1分以内に下のボタンを押して参加してください。",
            view=RecruitView(self.game),
        )

        await asyncio.sleep(60)

        if len(self.game.players) < 5:
            await interaction.channel.send(
                "参加者が5人未満のため、ゲームを中止します。（最低5人必要です）"
            )
            self.game.is_running = False
            return

        self.game.alive_players = self.game.players.copy()

        # 役職割り当て
        self.assign_roles()

        # 開始メッセージとボタン
        players_mentions = ", ".join([p.mention for p in self.game.players])
        await interaction.channel.send(
            f"【ゲーム開始】参加プレイヤー: {players_mentions}\n"
            f"今回の役職一覧: 村人, 人狼, 騎士, てるてる坊主, 狂人, 霊媒師, 占い師\n"
            f"役職確認ボタンを押して、自分の役職を確認してください。",
            view=RoleCheckView(self.game),
        )

        # 2. 最初の2分間ディスカッションタイム
        await self.run_discussion(minutes=2)

        # 3~5のループ開始
        while self.game.is_running:
            # 3. 夜のアクション（特殊フェーズ）
            await self.run_night_phase()

            # 2分間ディスカッションタイム
            await self.run_discussion(minutes=2)

            # 4 & 5. 投票フェーズ
            await self.run_voting_phase()

            # 勝利判定
            if await self.check_victory():
                break

    # 役職割り当てロジック
    def assign_roles(self):
        num_players = len(self.game.players)
        num_wolves = max(1, num_players // 4)  # 4:1で出現

        roles_pool = []
        roles_pool.extend(["人狼"] * num_wolves)
        roles_pool.extend(["占い師", "霊媒師", "騎士", "てるてる坊主", "狂人"])

        # 足りない分は村人
        remaining = num_players - len(roles_pool)
        if remaining > 0:
            roles_pool.extend(["村人"] * remaining)
        else:
            roles_pool = roles_pool[:num_players]

        random.shuffle(roles_pool)

        for i, player in enumerate(self.game.players):
            self.game.roles[player.id] = roles_pool[i]

    # ディスカッションタイマー（1分おきに通知）
    async def run_discussion(self, minutes=2):
        await self.game.game_channel.send(
            f"ーー ディスカッションタイム開始（{minutes}分間） ーー"
        )
        for i in range(minutes, 0, -1):
            await asyncio.sleep(60)
            if i > 1:
                await self.game.game_channel.send(
                    f"【ディスカッション残り {i-1} 分です】"
                )
        await self.game.game_channel.send(
            "ーー ディスカッションタイム終了です ーー"
        )

    # 3. 夜のフェーズ
    async def run_night_phase(self):
        await self.game.game_channel.send(
            "ーー 夜のフェーズに入りました（制限時間1分） ーー\n役職をお持ちの方は、下のボタンを押してアクションを行ってください。"
        )
        self.game.night_actions = {}

        view = NightActionView(self.game)
        msg = await self.game.game_channel.send(
            "夜のアクションを実行してください。", view=view
        )

        # 生存している役職持ちの数をカウント
        required_actions = 0
        for p in self.game.alive_players:
            role = self.game.roles.get(p.id)
            if role in ["占い師", "騎士", "人狼"]:
                required_actions += 1

        # 全員が行動し終えるか、1分経つまで待つ
        timer = 0
        while len(self.game.night_actions) < required_actions and timer < 60:
            await asyncio.sleep(1)
            timer += 1

        await msg.delete()
        await self.process_night_results()

    # 夜のアクション結果の処理
    async def process_night_results(self):
        wolves_target = None
        knight_target = None

        for p_id, target in self.game.night_actions.items():
            role = self.game.roles.get(p_id)
            if role == "人狼":
                wolves_target = target
            elif role == "騎士":
                knight_target = target

        if wolves_target and wolves_target != knight_target:
            victim = self.game.game_channel.guild.get_member(wolves_target)
            if victim:
                await self.game.game_channel.send(
                    f"【夜の結果】朝になると、{victim.display_name} さんが無残な姿で発見されました。"
                )
                self.game.alive_players = [
                    p for p in self.game.alive_players if p.id != wolves_target
                ]
        else:
            await self.game.game_channel.send(
                "【夜の結果】朝になりました。昨晩は誰も死にませんでした。"
            )

    # 4 & 5. 投票フェーズ
    async def run_voting_phase(self):
        await self.game.game_channel.send(
            "ーー 投票フェーズ ーー\n追放する人を1人選ぶか、スキップを選んでください。全員が見えるセレクトメニューで投票を行います。"
        )

        options = [
            discord.SelectOption(label=p.display_name, value=str(p.id))
            for p in self.game.alive_players
        ]
        options.append(discord.SelectOption(label="スキップ", value="skip"))

        view = PublicVoteView(self.game, options)
        msg = await self.game.game_channel.send(
            "下のメニューから投票してください（制限時間1分）。", view=view
        )

        self.game.voted_count = {}
        await asyncio.sleep(60)  # 投票時間1分
        await msg.delete()

        if not self.game.voted_count:
            await self.game.game_channel.send(
                "誰も投票しなかったため、今回はスキップされました。"
            )
            self.game.last_executed = None
            return

        counts = Counter(self.game.voted_count.values())
        most_common = counts.most_common()
        max_votes = most_common[0][1]
        candidates = [target for target, cnt in most_common if cnt == max_votes]

        if "skip" in candidates and len(candidates) == 1:
            await self.game.game_channel.send(
                "スキップが最多だったため、追放はありませんでした。"
            )
            self.game.last_executed = None
            return

        if len(candidates) > 1:
            await self.game.game_channel.send(
                "最多得票が同票だったため、今回は追放なし（スキップ）となります。"
            )
            self.game.last_executed = None
            return

        target_id = candidates[0]
        if target_id == "skip":
            await self.game.game_channel.send(
                "スキップが選択されたため、追放はありませんでした。"
            )
            self.game.last_executed = None
        else:
            target_member = self.game.game_channel.guild.get_member(
                int(target_id)
            )
            await self.game.game_channel.send(
                f"投票の結果、{target_member.display_name} さんが追放されました。"
            )
            self.game.last_executed = int(target_id)
            self.game.alive_players = [
                p for p in self.game.alive_players if p.id != int(target_id)
            ]

            # てるてる坊主の判定
            if self.game.roles.get(int(target_id)) == "てるてる坊主":
                await self.game.game_channel.send(
                    f"🎉 {target_member.display_name} さんは 【てるてる坊主】 でした！てるてる坊主の単独勝利です！"
                )
                self.game.is_running = False

    # 勝利判定
    async def check_victory(self):
        if not self.game.is_running:
            return True

        wolves = [
            p
            for p in self.game.alive_players
            if self.game.roles.get(p.id) == "人狼"
        ]
        non_wolves = [
            p
            for p in self.game.alive_players
            if self.game.roles.get(p.id) != "人狼"
        ]

        if len(wolves) == 0:
            await self.game.game_channel.send(
                "【ゲーム終了】人狼が全滅しました！村人陣営の勝利です！"
            )
            self.game.is_running = False
            return True

        if len(wolves) >= len(non_wolves):
            await self.game.game_channel.send(
                "【ゲーム終了】人狼の数が村人の数を上回りました！人狼陣営の勝利です！"
            )
            self.game.is_running = False
            return True

        return False


# ---------------- UI コンポーネント ----------------


# 参加募集ビュー
class RecruitView(discord.ui.View):

    def __init__(self, game):
        super().__init__(timeout=60)
        self.game = game

    @discord.ui.button(
        label="参加する", style=discord.ButtonStyle.success, custom_id="join_game"
    )
    async def join_game(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        if interaction.user not in self.game.players:
            self.game.players.append(interaction.user)
            await interaction.response.send_message(
                f"{interaction.user.display_name} さんが参加しました！",
                ephemeral=False,
            )
        else:
            await interaction.response.send_message(
                "既に参加しています。", ephemeral=True
            )


# 役職確認ビュー（狂人や人狼に仲間を通知）
class RoleCheckView(discord.ui.View):

    def __init__(self, game):
        super().__init__(timeout=None)
        self.game = game

    @discord.ui.button(
        label="役職を確認する", style=discord.ButtonStyle.primary, custom_id="check_role"
    )
    async def check_role(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        player_id = interaction.user.id
        if player_id not in self.game.roles:
            await interaction.response.send_message(
                "あなたはゲームに参加していません。", ephemeral=True
            )
            return

        role = self.game.roles[player_id]
        wolves_str = self.game.get_wolves_names()

        descriptions = {
            "村人": "【村人陣営】特殊な能力はありません。議論で人狼を見つけ出しましょう。",
            "人狼": f"【人狼陣営】夜に一人を襲撃できます。仲間（人狼）は「{wolves_str}」です。",
            "狂人": f"【人狼陣営】人狼の味方をする人間です。人狼は「{wolves_str}」です。",
            "てるてる坊主": "【第3陣営】自分が追放（釣られる）されると単独勝利です！議論を惑わしましょう。",
            "占い師": "【村人陣営】毎晩、一人を選んで人狼か人間かを知ることができます。",
            "霊媒師": "【村人陣営】毎晩、前日に追放された人が人狼だったかを知ることができます。",
            "騎士": "【村人陣営】毎晩、一人を守ることができます。自分自身は守れません。",
        }

        await interaction.response.send_message(
            f"あなたの役職は **{role}** です。\n{descriptions.get(role, '')}",
            ephemeral=True,
        )


# 夜のアクション受付ビュー
class NightActionView(discord.ui.View):

    def __init__(self, game):
        super().__init__(timeout=60)
        self.game = game

    @discord.ui.button(
        label="アクションを実行",
        style=discord.ButtonStyle.success,
        custom_id="night_action",
    )
    async def night_action(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        player_id = interaction.user.id
        if player_id not in [p.id for p in self.game.alive_players]:
            await interaction.response.send_message(
                "あなたは生存していないか、参加していません。", ephemeral=True
            )
            return

        role = self.game.roles.get(player_id)
        options = [
            discord.SelectOption(label=p.display_name, value=str(p.id))
            for p in self.game.alive_players
            if p.id != player_id
        ]

        if not options and role in ["占い師", "騎士", "人狼"]:
            await interaction.response.send_message(
                "対象となるプレイヤーがいません。", ephemeral=True
            )
            return

        if role == "占い師":
            view = ActionSelectView(self.game, options, "占い")
            await interaction.response.send_message(
                "占う対象を選んでください：", view=view, ephemeral=True
            )
        elif role == "騎士":
            view = ActionSelectView(self.game, options, "守る")
            await interaction.response.send_message(
                "守る対象を選んでください：", view=view, ephemeral=True
            )
        elif role == "人狼":
            view = ActionSelectView(self.game, options, "襲撃")
            await interaction.response.send_message(
                "襲撃する対象を選んでください：", view=view, ephemeral=True
            )
        elif role == "霊媒師":
            if self.game.last_executed:
                executed_role = self.game.roles.get(self.game.last_executed)
                is_wolf = "人狼" if executed_role == "人狼" else "人間"
                await interaction.response.send_message(
                    f"昨日追放された人は 【{is_wolf}】 でした。",
                    ephemeral=True,
                )
            else:
                await interaction.response.send_message(
                    "昨日追放された人はいません。", ephemeral=True
                )
        else:
            await interaction.response.send_message(
                "あなたには夜のアクションはありません。", ephemeral=True
            )


# 夜の個別セレクトメニュービュー
class ActionSelectView(discord.ui.View):

    def __init__(self, game, options, action_type):
        super().__init__(timeout=30)
        self.game = game
        self.action_type = action_type
        select = discord.ui.Select(
            placeholder=f"対象を選んでください（{action_type}）",
            options=options,
        )
        select.callback = self.select_callback
        self.add_item(select)

    async def select_callback(self, interaction: discord.Interaction):
        target_id = int(self.children[0].values[0])
        self.game.night_actions[interaction.user.id] = target_id

        if self.action_type == "占い":
            target_role = self.game.roles.get(target_id)
            is_wolf = "人狼" if target_role == "人狼" else "人間"
            await interaction.response.send_message(
                f"占いの結果、そのプレイヤーは 【{is_wolf}】 です。",
                ephemeral=True,
            )
        else:
            await interaction.response.send_message(
                "対象を選択しました。", ephemeral=True
            )
        self.stop()


# 公開投票セレクトメニュー
class PublicVoteView(discord.ui.View):

    def __init__(self, game, options):
        super().__init__(timeout=60)
        self.game = game
        select = discord.ui.Select(
            placeholder="投票先を選んでください", options=options
        )
        select.callback = self.select_callback
        self.add_item(select)

    async def select_callback(self, interaction: discord.Interaction):
        target_val = self.children[0].values[0]
        self.game.voted_count[interaction.user.id] = target_val
        await interaction.response.send_message(
            f"{interaction.user.display_name} さんが投票しました。",
            ephemeral=False,
        )


async def setup(bot):
    await bot.add_cog(JinrouCog(bot))
