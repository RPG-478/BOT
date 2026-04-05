import discord
from discord import app_commands
from discord.ext import commands
import asyncio

# --- インポートは先頭で行う (各ファイルが存在することが前提) ---
try:
    import wordwolf
    import Pault
    import onlinePault
    import jinrou
    import god_field
except ImportError as e:
    print(f"警告: 一部のゲームモジュールを読み込めませんでした: {e}")

# --- ワードウルフ専用：ジャンル選択メニュー ---
class WordWolfGenreView(discord.ui.View):
    def __init__(self, bot):
        super().__init__(timeout=60)
        self.bot = bot

    @discord.ui.select(
        placeholder="ジャンルを選択してください",
        options=[
            discord.SelectOption(label="スタンダード", value="standard"),
            discord.SelectOption(label="原神", value="genshin"),
            discord.SelectOption(label="崩壊：スターレイル", value="starail"),
        ]
    )
    async def select_genre(self, interaction: discord.Interaction, select: discord.ui.Select):
        genre = select.values[0]
        cog = self.bot.get_cog("CustomWordWolf")
        
        if not cog:
            await interaction.response.edit_message(content="エラー: WordWolf Cogが読み込まれていません。", view=None)
            return

        # 状態リセット
        cog.game_running = True # 募集開始時点でTrueにするのが一般的
        cog.players = [interaction.user]
        cog.alive_players = []
        cog.wolf = None
        cog.player_words = {}
        cog.remaining_challenges = 3

        list_names = {"standard": "標準", "genshin": "原神", "starail": "崩壊：スターレイル"}
        embed = discord.Embed(title="ワードウルフ参加者募集", color=0xFFFFFF)
        embed.description = f"ジャンル: **{list_names.get(genre, genre)}**\n\n「参加」ボタンを押してください。（60秒）"

        join_view = wordwolf.JoinView(cog)
        await interaction.response.edit_message(content=None, embed=embed, view=join_view)

        # タスクをスケジュール
        self.bot.loop.create_task(cog.begin_game(interaction.channel, genre))

# --- メイン：ゲーム選択メニュー ---
class GameSelectView(discord.ui.View):
    def __init__(self, bot):
        super().__init__(timeout=60)
        self.bot = bot

    @discord.ui.select(
        placeholder="遊ぶゲームを選択してください",
        options=[
            discord.SelectOption(label="ワードウルフ", value="wordwolf"),
            discord.SelectOption(label="Pault (シングル)", value="pault"),
            discord.SelectOption(label="Online Pault", value="online_pault"),
            discord.SelectOption(label="人狼ゲーム", value="jinrou"),
            discord.SelectOption(label="God Field", value="godfield"),
        ]
    )
    async def select_game(self, interaction: discord.Interaction, select: discord.ui.Select):
        game_value = select.values[0]

        if game_value == "wordwolf":
            view = WordWolfGenreView(self.bot)
            embed = discord.Embed(title="ワードウルフ設定", description="お題のジャンルを選んでください。", color=0xFFFFFF)
            await interaction.response.edit_message(content=None, embed=embed, view=view)

        elif game_value == "pault":
            game = Pault.PaultGame(interaction.user)
            embed = Pault.make_embed(game)
            embed.color = 0xFFFFFF
            await interaction.response.edit_message(content=None, embed=embed, view=Pault.SetupView(game))

        elif game_value == "online_pault":
            embed = discord.Embed(title="Online Pault 募集", description="対戦相手を待っています...", color=0xFFFFFF)
            await interaction.response.edit_message(content=None, embed=embed, view=onlinePault.OnlineEntryView(interaction.user))

        elif game_value == "jinrou":
            cog = self.bot.get_cog("JinrouCog")
            if not cog:
                await interaction.response.edit_message(content="エラー: JinrouCog が見つかりません。", view=None)
                return

            game = cog.get_game(interaction.channel_id)
            if game.is_running:
                await interaction.response.send_message("既に進行中です。", ephemeral=True)
                return

            # 初期化
            game.is_running = True
            game.game_channel = interaction.channel
            game.players = []
            
            embed = discord.Embed(title="人狼ゲーム 参加者募集", description="参加ボタンを押してください。（60秒）", color=0xFFFFFF)
            await interaction.response.edit_message(content=None, embed=embed, view=jinrou.RecruitView(game, 60))
            
            # 実行
            self.bot.loop.create_task(cog.run_from_hub(game, interaction.channel))

        elif game_value == "godfield":
            cog = self.bot.get_cog("GodField")
            if not cog or interaction.channel.id in cog.games:
                await interaction.response.edit_message(content="開始できません。Cog未登録か進行中です。", view=None)
                return

            wait_time = 60
            join_view = god_field.JoinView(timeout=wait_time)
            embed = discord.Embed(title="⚡ God Field 参加者募集", description="参戦ボタンを押してください。（60秒）", color=0xFFFFFF)
            await interaction.response.edit_message(content=None, embed=embed, view=join_view)
            
            self.bot.loop.create_task(cog.start_from_hub(interaction.channel, join_view))

class PlayHub(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="play", description="全てのミニゲームメニューを表示します")
    async def play(self, interaction: discord.Interaction):
        embed = discord.Embed(title="GAME MENU", description="プレイしたいゲームを選択してください。", color=0xFFFFFF)
        view = GameSelectView(self.bot)
        await interaction.response.send_message(embed=embed, view=view)

async def setup(bot):
    await bot.add_cog(PlayHub(bot))
