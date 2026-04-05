import discord
from discord import app_commands
from discord.ext import commands

# --- ワードウルフ専用の第2段階メニュー ---
class WordWolfGenreView(discord.ui.View):
    def __init__(self, bot):
        super().__init__(timeout=60)
        self.bot = bot

    @discord.ui.select(
        placeholder="ジャンルを選択してください",
        options=[
            discord.SelectOption(label="スタンダード", value="standard"),
            discord.SelectOption(label="原神", value="genshin"),
            discord.SelectOption(label="崩壊：スターレイル", value="starrail"),
        ]
    )
    async def select_genre(self, interaction: discord.Interaction, select: discord.ui.Select):
        genre = select.values[0]
        cog = self.bot.get_cog("CustomWordWolf")
        if cog:
            # wordwolf.py の募集開始処理へ
            # 注意: 元のコードに合わせて、ここから各ゲームの初期化ロジックを呼び出します
            cog.game_running = True
            cog.players = [interaction.user]
            
            embed = discord.Embed(title="ワードウルフ参加者募集", color=0xFFFFFF)
            embed.description = f"ジャンル: **{genre}**\n\n参加ボタンを押してください。"
            
            # 元のwordwolf.pyにあるJoinViewなどを流用
            from wordwolf import JoinView 
            await interaction.response.edit_message(content=None, embed=embed, view=JoinView(cog))
        else:
            await interaction.response.edit_message(content="エラー: WordWolf Cogが見つかりません。", view=None)

# --- 最初のゲーム選択メニュー ---
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
            cog = self.bot.get_cog("Pault")
            if cog:
                # Pault 3.py の初期化処理
                from Pault_3 import PaultGame, SetupView 
                game = PaultGame(interaction.user)
                embed = discord.Embed(title="Pault", description="布陣を選択してください（メイン、左、右）", color=0xFFFFFF)
                await interaction.response.edit_message(content=None, embed=embed, view=SetupView(game))
            
        elif game_value == "online_pault":
            cog = self.bot.get_cog("OnlinePault")
            if cog:
                from onlinePault import OnlineEntryView
                embed = discord.Embed(title="Online Pault 募集", description="対戦相手を待っています...", color=0xFFFFFF)
                await interaction.response.edit_message(content=None, embed=embed, view=OnlineEntryView(interaction.user))

        elif game_value == "jinrou":
            cog = self.bot.get_cog("JinrouCog")
            if cog:
                from jinrou_5 import RecruitView
                game = cog.get_game(interaction.channel_id)
                game.is_running = True
                game.players = [interaction.user]
                embed = discord.Embed(title="人狼ゲーム 参加者募集", description="参加ボタンを押してください。", color=0xFFFFFF)
                await interaction.response.edit_message(content=None, embed=embed, view=RecruitView(game, 60))

        elif game_value == "godfield":
            # god_field 2.py の募集開始ロジック
            embed = discord.Embed(title="God Field", description="ゲームを開始します。", color=0xFFFFFF)
            await interaction.response.edit_message(content=None, embed=embed, view=None)

# --- 窓口Cog ---
class PlayHub(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="play", description="ミニゲームメニューを開きます")
    async def play(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="GAME MENU",
            description="プレイしたいゲームをリストから選択してください。",
            color=0xFFFFFF
        )
        view = GameSelectView(self.bot)
        await interaction.response.send_message(embed=embed, view=view)

async def setup(bot):
    await bot.add_cog(PlayHub(bot))
