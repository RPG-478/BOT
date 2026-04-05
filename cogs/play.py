import discord
from discord import app_commands
from discord.ext import commands
import asyncio

# 各ファイルをあらかじめインポートしておく（呼び出し時の遅延を防ぐ）
import wordwolf
import Pault
import onlinePault
import jinrou
import god_field

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
        # 処理が長引く可能性を考慮して、まず「考え中」の状態にする
        await interaction.response.defer(ephemeral=True)
        
        genre = select.values[0]
        cog = self.bot.get_cog("CustomWordWolf")
        if cog:
            cog.game_running = True
            cog.players = [interaction.user]
            embed = discord.Embed(title="ワードウルフ参加者募集", color=0xFFFFFF)
            embed.description = f"ジャンル: **{genre}**\n\n参加者は下のボタンを押してください。"
            # deferした後は followup.send を使う
            await interaction.followup.send(embed=embed, view=wordwolf.JoinView(cog))
        else:
            await interaction.followup.send("エラー: WordWolf Cogが見つかりません。", ephemeral=True)

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
            embed = discord.Embed(title="ワードウルフ設定", description="ジャンルを選択してください。", color=0xFFFFFF)
            await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
        
        # 2. Pault (シングル)
        elif game_value == "pault":
            # 念のため defer してタイムアウトを防ぐ
            await interaction.response.defer()
            game = Pault.PaultGame(interaction.user)
            embed = Pault.make_embed(game)
            embed.color = 0xFFFFFF
            await interaction.followup.send(embed=embed, view=Pault.SetupView(game))
            
        # 3. Online Pault
        elif game_value == "online_pault":
            await interaction.response.defer()
            embed = discord.Embed(title="Online Pault 募集", description="対戦相手を待っています...", color=0xFFFFFF)
            await interaction.followup.send(embed=embed, view=onlinePault.OnlineEntryView(interaction.user))

        # 4. 人狼ゲーム
        elif game_value == "jinrou":
            await interaction.response.defer()
            cog = self.bot.get_cog("JinrouCog")
            if cog:
                game = cog.get_game(interaction.channel_id)
                game.is_running = True
                game.players = [interaction.user]
                embed = discord.Embed(title="人狼ゲーム 参加者募集", description="参加ボタンを押してください。", color=0xFFFFFF)
                await interaction.followup.send(embed=embed, view=jinrou.RecruitView(game, 60))
            else:
                await interaction.followup.send("JinrouCogが見つかりません。", ephemeral=True)

        # 5. God Field
        elif game_value == "godfield":
            embed = discord.Embed(title="God Field", description="ゲームを開始します。", color=0xFFFFFF)
            await interaction.response.send_message(embed=embed)

class PlayHub(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="play", description="ミニゲームメニューを表示")
    async def play(self, interaction: discord.Interaction):
        embed = discord.Embed(title="GAME MENU", description="プレイするゲームを選択してください。", color=0xFFFFFF)
        view = GameSelectView(self.bot)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

async def setup(bot):
    await bot.add_cog(PlayHub(bot))
