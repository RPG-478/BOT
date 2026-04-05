import discord
from discord import app_commands
from discord.ext import commands
import traceback
import sys
import os
import asyncio

# --- パスの自動解決 ---
current_dir = os.path.dirname(__file__)
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

# 送信先チャンネルID
DEBUG_CHANNEL_ID = 1476946191362166894

# --- 共通のログ送信関数 ---
async def send_debug_log(bot, message: str):
    channel = bot.get_channel(DEBUG_CHANNEL_ID)
    if channel:
        await channel.send(f"```py\n[DEBUG] {message}\n```")
    else:
        print(f"Debug channel not found: {message}")

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
        try:
            genre = select.values[0]
            cog = self.bot.get_cog("CustomWordWolf")
            
            if not cog:
                await send_debug_log(self.bot, "エラー: CustomWordWolf Cogが見つかりません。")
                await interaction.response.edit_message(content="エラー: Cogが見つかりません。", view=None)
                return

            cog.game_running = False
            cog.players = [interaction.user]
            
            import wordwolf
            join_view = wordwolf.JoinView(cog)
            
            list_names = {"standard": "標準", "genshin": "原神", "starail": "崩壊：スターレイル"}
            embed = discord.Embed(title="ワードウルフ参加者募集", color=0xFFFFFF)
            embed.description = f"ジャンル: **{list_names.get(genre, genre)}**\n\n「参加」ボタンを押してください。"
            
            await interaction.response.edit_message(content=None, embed=embed, view=join_view)
            self.bot.loop.create_task(cog.begin_game(interaction.channel, genre))
            await send_debug_log(self.bot, f"WordWolf ({genre}) のタスクを起動しました。")

        except Exception:
            await send_debug_log(self.bot, f"WordWolfエラー:\n{traceback.format_exc()}")

# --- メイン：ゲーム選択メニュー ---
class GameSelectView(discord.ui.View):
    def __init__(self, bot):
        super().__init__(timeout=60)
        self.bot = bot

    @discord.ui.select(
        placeholder="遊ぶゲームを選択してください",
        options=[
            discord.SelectOption(label="ワードウルフ", value="wordwolf"),
            discord.SelectOption(label="ダウト", value="doubt"),
            discord.SelectOption(label="Pault (シングル)", value="pault"),
            discord.SelectOption(label="Online Pault", value="online_pault"),
            discord.SelectOption(label="人狼ゲーム", value="jinrou"),
            discord.SelectOption(label="God Field", value="godfield"),
        ]
    )
    async def select_game(self, interaction: discord.Interaction, select: discord.ui.Select):
        game_value = select.values[0]
        await send_debug_log(self.bot, f"{interaction.user} が {game_value} を選択しました。")

        try:
            if game_value == "wordwolf":
                await interaction.response.edit_message(view=WordWolfGenreView(self.bot))

            elif game_value == "doubt":
                # 他のゲームと同様にCogを直接取得
                cog = self.bot.get_cog("Doubt")
                if not cog:
                    await send_debug_log(self.bot, "エラー: Doubt Cogが見つかりません。")
                    await interaction.response.edit_message(content="エラー: Doubtモジュールがロードされていません。", view=None)
                    return
                
                # doubt.py 内にある DoubtJoinView をインポートして使用
                import doubt
                join_view = doubt.DoubtJoinView(interaction.user.id)
                
                embed = discord.Embed(
                    title="Doubt 参加者募集", 
                    description="ボタンを押して参加してください（3名以上）\n制限時間: 60秒", 
                    color=0xFFFFFF
                )
                await interaction.response.edit_message(content=None, embed=embed, view=join_view)
                
                # 他のゲームと同じ流用形式で Cog の開始メソッドにプレイヤーリストを渡す
                self.bot.loop.create_task(cog.start_from_hub(interaction.channel, join_view.players))
                await send_debug_log(self.bot, "Doubtのタスクを流用形式で起動しました。")

            elif game_value == "pault":
                import Pault
                game = Pault.PaultGame(interaction.user)
                embed = Pault.make_embed(game)
                embed.color = 0xFFFFFF
                await interaction.response.edit_message(content=None, embed=embed, view=Pault.SetupView(game))

            elif game_value == "online_pault":
                import onlinePault
                embed = discord.Embed(title="Online Pault 募集", description="対戦相手を待っています...", color=0xFFFFFF)
                await interaction.response.edit_message(content=None, embed=embed, view=onlinePault.OnlineEntryView(interaction.user))

            elif game_value == "jinrou":
                import jinrou
                cog = self.bot.get_cog("JinrouCog")
                if not cog:
                    await send_debug_log(self.bot, "エラー: JinrouCog が見つかりません。")
                    return
                
                game = cog.get_game(interaction.channel_id)
                game.is_running = True
                game.game_channel = interaction.channel
                game.players = []
                
                await interaction.response.edit_message(content=None, view=jinrou.RecruitView(game, 60))
                self.bot.loop.create_task(cog.run_from_hub(game, interaction.channel))
                await send_debug_log(self.bot, "Jinrouのタスクを起動しました。")

            elif game_value == "godfield":
                import god_field
                cog = self.bot.get_cog("GodField")
                if not cog:
                    await send_debug_log(self.bot, "エラー: GodField Cogが見つかりません。")
                    return

                wait_time = 60
                join_view = god_field.JoinView(timeout=wait_time)
                embed = discord.Embed(title="⚡ God Field 参加者募集", description="参戦ボタンを押してください。", color=0xFFFFFF)
                await interaction.response.edit_message(content=None, embed=embed, view=join_view)
                
                self.bot.loop.create_task(cog.start_from_hub(interaction.channel, join_view))
                await send_debug_log(self.bot, "GodFieldのタスクを起動しました。")
            
        except Exception:
            await send_debug_log(self.bot, f"SelectGameエラー ({game_value}):\n{traceback.format_exc()}")

class PlayHub(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="play", description="全てのミニゲームメニューを表示します")
    async def play(self, interaction: discord.Interaction):
        await send_debug_log(self.bot, f"/play コマンドが実行されました (Channel: {interaction.channel.id})")
        view = GameSelectView(self.bot)
        embed = discord.Embed(title="GAME MENU", description="プレイしたいゲームを選択してください。", color=0xFFFFFF)
        await interaction.response.send_message(embed=embed, view=view)

async def setup(bot):
    await bot.add_cog(PlayHub(bot))
