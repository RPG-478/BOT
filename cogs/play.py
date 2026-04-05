import discord
from discord import app_commands
from discord.ext import commands
import importlib

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
        # wordwolf.py内のクラス名は CustomWordWolf です
        cog = self.bot.get_cog("CustomWordWolf")
        if cog:
            import wordwolf
            cog.game_running = True
            cog.players = [interaction.user]
            # 選択されたジャンルでお題を決定する処理（元のコードのロジックに準拠）
            # ここでは募集Viewに移行します
            embed = discord.Embed(title="ワードウルフ参加者募集", color=0xFFFFFF)
            embed.description = f"ジャンル: **{genre}**\n\n「参加」ボタンを押してください。"
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

        # 1. ワードウルフ (wordwolf.py)
        if game_value == "wordwolf":
            view = WordWolfGenreView(self.bot)
            embed = discord.Embed(title="ワードウルフ設定", description="お題のジャンルを選んでください。", color=0xFFFFFF)
            await interaction.response.edit_message(content=None, embed=embed, view=view)
        
        # 2. Pault (Pault.py)
        elif game_value == "pault":
            import Pault
            game = Pault.PaultGame(interaction.user)
            embed = Pault.make_embed(game)
            embed.color = 0xFFFFFF
            await interaction.response.edit_message(content=None, embed=embed, view=Pault.SetupView(game))
            
        # 3. Online Pault (onlinePault.py)
        elif game_value == "online_pault":
            import onlinePault
            embed = discord.Embed(title="Online Pault 募集", description="対戦相手を待っています...", color=0xFFFFFF)
            await interaction.response.edit_message(content=None, embed=embed, view=onlinePault.OnlineEntryView(interaction.user))

        # 4. 人狼ゲーム (jinrou.py)
        elif game_value == "jinrou":
            import jinrou
            cog = self.bot.get_cog("JinrouCog")
            if cog:
                game = cog.get_game(interaction.channel_id)
                game.is_running = True
                game.players = [interaction.user]
                embed = discord.Embed(title="人狼ゲーム 参加者募集", description="参加ボタンを押してください。", color=0xFFFFFF)
                await interaction.response.edit_message(content=None, embed=embed, view=jinrou.RecruitView(game, 60))

        # 5. God Field (god_field.py)
        elif game_value == "godfield":
            import god_field
            embed = discord.Embed(title="God Field", description="ゲームを開始します。参加者を募集してください。", color=0xFFFFFF)
            # 必要に応じて募集Viewを追加
            await interaction.response.edit_message(content=None, embed=embed, view=None)

# --- 窓口Cog本体 ---
class PlayHub(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="play", description="全てのミニゲームメニューを表示します")
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
