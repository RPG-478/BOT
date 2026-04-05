import discord
from discord import app_commands
from discord.ext import commands

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
            discord.SelectOption(label="崩壊：スターレイル", value="starrail"),
        ]
    )
    async def select_genre(self, interaction: discord.Interaction, select: discord.ui.Select):
        genre = select.values[0]
        # wordwolf.py内のクラス名は CustomWordWolf
        cog = self.bot.get_cog("CustomWordWolf")
        if cog:
            import wordwolf
            # 状態のリセット
            cog.game_running = True
            cog.players = [interaction.user]
            cog.wolf = None
            cog.player_words = {}
            # wordwolf.py内の JoinView を呼び出し
            embed = discord.Embed(title="ワードウルフ参加者募集", color=0xFFFFFF)
            embed.description = f"ジャンル: **{genre}**\n\n参加者は下のボタンを押してください。"
            await interaction.response.edit_message(content=None, embed=embed, view=wordwolf.JoinView(cog))
        else:
            await interaction.response.edit_message(content="エラー: WordWolf Cogが見つかりません。", view=None)

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

        # 1. ワードウルフ
        if game_value == "wordwolf":
            view = WordWolfGenreView(self.bot)
            embed = discord.Embed(title="ワードウルフ設定", description="お題のジャンルを選んでください。", color=0xFFFFFF)
            await interaction.response.edit_message(content=None, embed=embed, view=view)
        
        # 2. Pault (シングル)
        elif game_value == "pault":
            import Pault
            # ゲームインスタンスの作成と初期化
            game = Pault.PaultGame(interaction.user)
            embed = Pault.make_embed(game)
            embed.color = 0xFFFFFF
            await interaction.response.edit_message(content=None, embed=embed, view=Pault.SetupView(game))
            
        # 3. Online Pault
        elif game_value == "online_pault":
            import onlinePault
            embed = discord.Embed(title="Online Pault 募集", description="対戦相手を待っています...", color=0xFFFFFF)
            # onlinePault.py の OnlineEntryView を使用
            await interaction.response.edit_message(content=None, embed=embed, view=onlinePault.OnlineEntryView(interaction.user))

        # 4. 人狼ゲーム
        elif game_value == "jinrou":
            import jinrou
            cog = self.bot.get_cog("JinrouCog")
            if cog:
                game = cog.get_game(interaction.channel_id)
                # 状態のリセット
                game.is_running = True
                game.players = [interaction.user]
                game.roles = {}
                game.day_count = 0
                
                embed = discord.Embed(title="人狼ゲーム 参加者募集", description="参加者は「参加する」ボタンを押してください。", color=0xFFFFFF)
                await interaction.response.edit_message(content=None, embed=embed, view=jinrou.RecruitView(game, 60))
            else:
                await interaction.response.edit_message(content="エラー: JinrouCogが見つかりません。", view=None)

        # 5. God Field
        elif game_value == "godfield":
            # god_field.py の中身を確認し、募集開始が必要な場合はViewを指定
            embed = discord.Embed(title="God Field", description="ゲームを開始します。準備ができたら対戦を開始してください。", color=0xFFFFFF)
            await interaction.response.edit_message(content=None, embed=embed, view=None)

# --- 窓口Cog本体 ---
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
