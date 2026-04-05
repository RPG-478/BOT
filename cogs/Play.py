import discord
from discord import app_commands
from discord.ext import commands

# 各ファイルから必要なクラスやViewをインポート
# ファイル名にスペースがある場合はインポート時に工夫が必要なため、
# 読み込みエラーを防ぐために内部で get_cog を多用する構成にします。

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
            discord.SelectOption(label="数学", value="math"),
        ]
    )
    async def select_genre(self, interaction: discord.Interaction, select: discord.ui.Select):
        genre = select.values[0]
        # wordwolf.py内のクラス名は CustomWordWolf となっています
        cog = self.bot.get_cog("CustomWordWolf")
        if cog:
            import wordwolf # wordwolf.py をインポート
            cog.game_running = True
            cog.players = [interaction.user]
            
            embed = discord.Embed(title="ワードウルフ参加者募集", color=0xFFFFFF)
            embed.description = f"ジャンル: **{genre}**\n\n「参加」ボタンを押してください。"
            # wordwolf.py 内の JoinView を使用
            await interaction.response.edit_message(content=None, embed=embed, view=wordwolf.JoinView(cog))
        else:
            await interaction.response.edit_message(content="エラー: WordWolf Cogが見つかりません。", view=None)

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

        # --- ワードウルフ ---
        if game_value == "wordwolf":
            view = WordWolfGenreView(self.bot)
            embed = discord.Embed(title="ワードウルフ設定", description="お題のジャンルを選んでください。", color=0xFFFFFF)
            await interaction.response.edit_message(content=None, embed=embed, view=view)
        
        # --- Pault (シングル) ---
        elif game_value == "pault":
            # Pault 3.py 内のクラス名は Pault となっています
            import importlib
            pault_module = importlib.import_module("Pault 3") # スペース対策
            game = pault_module.PaultGame(interaction.user)
            embed = pault_module.make_embed(game)
            embed.color = 0xFFFFFF
            await interaction.response.edit_message(content=None, embed=embed, view=pault_module.SetupView(game))
            
        # --- Online Pault ---
        elif game_value == "online_pault":
            import onlinePault
            embed = discord.Embed(title="Online Pault 募集", description="対戦相手を待っています...", color=0xFFFFFF)
            await interaction.response.edit_message(content=None, embed=embed, view=onlinePault.OnlineEntryView(interaction.user))

        # --- 人狼ゲーム ---
        elif game_value == "jinrou":
            import importlib
            jinrou_module = importlib.import_module("jinrou 5") # スペース対策
            cog = self.bot.get_cog("JinrouCog")
            if cog:
                game = cog.get_game(interaction.channel_id)
                game.is_running = True
                game.players = [interaction.user]
                embed = discord.Embed(title="人狼ゲーム 参加者募集", description="参加ボタンを押してください。", color=0xFFFFFF)
                await interaction.response.edit_message(content=None, embed=embed, view=jinrou_module.RecruitView(game, 60))

        # --- God Field ---
        elif game_value == "godfield":
            import importlib
            gf_module = importlib.import_module("god_field 2")
            embed = discord.Embed(title="God Field", description="ゲームを開始します。現在準備中...", color=0xFFFFFF)
            await interaction.response.edit_message(content=None, embed=embed, view=None)

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