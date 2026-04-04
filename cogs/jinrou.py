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

    @app_commands.command(name="kill", description="このチャンネルのゲームを強制終了します")
    async def kill(self, interaction: discord.Interaction):
        game = self.get_game(interaction.channel_id)
        if not game.is_running:
            return await interaction.response.send_message("このチャンネルで進行中のゲームはありません。", ephemeral=True)
        
        game.is_running = False
        await self.reset_mutes(game)
        await interaction.response.send_message("⚠️ ゲームを強制終了しました。")

    @app_commands.command(name="jinrou_help", description="役職の説明を確認します")
    async def jinrou_help(self, interaction: discord.Interaction):
        help_text = (
            "### 役職一覧\n"
            "**・一般通過あごむに**: 一般の村人です。\n"
            "**・占い師**: 毎晩1人を占えます。\n"
            "**・人狼**: 村人を襲撃します。\n"
            "※画像付き役職: NOMAL, JINROU, MASAI, MENHERA, NYUROU"
        )
        await interaction.response.send_message(help_text, ephemeral=True)

    @app_commands.command(name="jinrou", description="人狼ゲームを開始します")
    @app_commands.describe(wait_minutes="募集期間（1〜1440分）")
    async def jinrou(self, interaction: discord.Interaction, wait_minutes: int = 1):
        game = self.get_game(interaction.channel_id)
        if game.is_running:
            return await interaction.response.send_message("このチャンネルでは既に進行中です", ephemeral=True)

        # 1分〜24時間の上限設定
        wait_minutes = max(1, min(wait_minutes, 1440))
        
        # ゲームデータの初期化
        game.is_running = True
        game.game_channel = interaction.channel
        game.players = []
        game.roles = {}
        game.day_count = 0
        game.wan_owner = {}
        game.used_hadouhou = False

        view = RecruitView(game, timeout=wait_minutes * 60)
        await interaction.response.send_message(f"募集開始（期間: {wait_minutes}分）", view=view)
        
        # 募集待機（1秒ごとにゲーム終了フラグをチェック）
        for _ in range(wait_minutes * 60):
            await asyncio.sleep(1)
            if not game.is_running: return # killコマンド用

        if len(game.players) < 5:
            game.is_running = False
            return await interaction.channel.send("5人未満のため中止します。")

        game.alive_players = game.players.copy()
        self.assign_roles(game)
        
        mentions = " ".join([p.mention for p in game.players])
        await interaction.channel.send(f"{mentions}\nゲーム開始！役職を確認してください。", view=RoleCheckView(game, self))

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
            print(f"Error: {e}")
        finally:
            await self.reset_mutes(game)
            game.is_running = False

    async def run_discussion(self, game, minutes, title):
        if not game.is_running: return
        await game.game_channel.send(f"ーー {title}（{minutes}分） ーー")
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
        msg = await game.game_channel.send("夜のアクションを選択してください", view=view)
        
        for _ in range(60):
            await asyncio.sleep(1)
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
            if t_id in psycho_killer_ids: dead_ids.add(p_id)
            if role in ["人狼", "デカ狼"]: wolves_target = t_id
            elif role == "騎士": knight_targets.add(t_id)
            elif role == "あごむに破道砲":
                dead_ids.add(p_id); dead_ids.add(t_id)
                game.used_hadouhou = True
                others = [p.id for p in game.alive_players if p.id not in [p_id, t_id]]
                if others: dead_ids.add(random.choice(others))

        if wolves_target and wolves_target not in knight_targets:
            dead_ids.add(wolves_target)

        for d_id in dead_ids:
            if d_id in [p.id for p in game.alive_players]:
                m = game.game_channel.guild.get_member(d_id)
                if m:
                    await game.game_channel.send(f"【夜の結果】{m.display_name} さんが犠牲になりました。")
                    game.alive_players = [p for p in game.alive_players if p.id != d_id]
                    await self.mute_member(m)
        if not dead_ids:
            await game.game_channel.send("【夜の結果】昨晩の犠牲者はいないようです。")

    async def check_victory(self, game):
        if not game.is_running: return True
        wolves = [p for p in game.alive_players if game.roles.get(p.id) in ["人狼", "デカ狼", "狂人"]]
        non_wolves = [p for p in game.alive_players if p not in wolves]
        if not wolves:
            await game.game_channel.send("人狼全滅！村人陣営の勝利！")
            return True
        if len(wolves) >= len(non_wolves):
            await game.game_channel.send("人狼が過半数！人狼陣営の勝利！")
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
        msg = await game.game_channel.send("投票先を選んでください", view=view)
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
            game.alive_players = [p for p in game.alive_players if p.id != int(target_id)]
            await self.mute_member(target_m)

# ======================================================
#  UI コンポーネント
# ======================================================
class RoleCheckView(discord.ui.View):
    def __init__(self, game, cog):
        super().__init__(timeout=None)
        self.game, self.cog = game, cog
        
    @discord.ui.button(label="役職確認", style=discord.ButtonStyle.primary)
    async def check(self, interaction, button):
        real_role = self.game.roles.get(interaction.user.id)
        display_role = real_role
        if real_role == "タフむに": display_role = "一般通過あごむに"
        elif real_role == "入狼": display_role = "人狼"
            
        wolves = self.cog.get_wolves_names(self.game)
        descs = {
            "一般通過あごむに": "一般通過あごむに。空気薄い。", 
            "占い師": "毎晩1人を占える。", 
            "霊媒師": "昨日追放された者の正体を知る。",
            "人狼": f"仲間: {wolves}", 
            "騎士": "毎晩一人を守る。", 
            "狂人": "人狼の味方。",
            "ハゲ": "追放されたら勝ち。", 
            "メンヘラ": "自分に関与した者を殺す。",
            "あごむに破道砲": "自爆攻撃可能。", 
            "デカ狼": "占い師を欺く。",
            "パン屋": "パンを焼く。",
            "マサイ族": "視力がいい。",
            "入狼": "人狼と誤解される村陣営。",
            "ワンころ": "飼い主が必要な第三陣営。",
            "タフむに": "道連れ機能付き村人。"
        }

        # 画像対応表
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

class NightActionView(discord.ui.View):
    def __init__(self, game):
        super().__init__(timeout=60)
        self.game = game
    @discord.ui.button(label="アクションを起こす", style=discord.ButtonStyle.success)
    async def action(self, interaction, button):
        p_id = interaction.user.id
        if p_id not in [p.id for p in self.game.alive_players]: return
        role = self.game.roles.get(p_id)
        opts = [discord.SelectOption(label=p.display_name, value=str(p.id)) for p in self.game.alive_players if p.id != p_id]
        if not opts: return await interaction.response.send_message("対象がいません。", ephemeral=True)
        await interaction.response.send_message("対象を選択:", view=ActionSelectView(self.game, opts), ephemeral=True)

class ActionSelectView(discord.ui.View):
    def __init__(self, game, options):
        super().__init__(timeout=60)
        self.game = game
        s = discord.ui.Select(options=options)
        s.callback = self.callback
        self.add_item(s)
    async def callback(self, interaction):
        t_id = int(self.children[0].values[0])
        self.game.night_actions[interaction.user.id] = t_id
        await interaction.response.send_message("完了しました。", ephemeral=True)

class RecruitView(discord.ui.View):
    def __init__(self, game, timeout: int):
        super().__init__(timeout=timeout)
        self.game = game
    @discord.ui.button(label="参加する", style=discord.ButtonStyle.success)
    async def join(self, interaction, button):
        if interaction.user not in self.game.players:
            self.game.players.append(interaction.user)
            await interaction.response.send_message(f"{interaction.user.display_name} さんが参加！")

class PublicVoteView(discord.ui.View):
    def __init__(self, game, options):
        super().__init__(timeout=60)
        self.game = game
        s = discord.ui.Select(options=options)
        s.callback = self.callback
        self.add_item(s)
    async def callback(self, interaction):
        self.game.voted_count[interaction.user.id] = self.children[0].values[0]
        await interaction.response.send_message(f"{interaction.user.display_name} さんが投票完了。")

async def setup(bot):
    await bot.add_cog(JinrouCog(bot))