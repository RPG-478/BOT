import discord
from discord import app_commands
from discord.ext import commands
import traceback # エラー詳細を取得するために追加

# 送信先チャンネルID
DEBUG_CHANNEL_ID = 1476170098673717414

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
                await send_debug_log(self.bot, "エラー: CustomWordWolf Cogが見つかりません。main.pyでload_extensionされていますか？")
                await interaction.response.edit_message(content="エラー: Cogが見つかりません。", view=None)
                return

            # 状態リセット
            cog.game_running = False
            cog.players = [interaction.user]
            
            import wordwolf
            join_view = wordwolf.JoinView(cog)
            
            list_names = {"standard": "標準", "genshin": "原神", "starail": "崩壊：スターレイル"}
            embed = discord.Embed(title="ワードウルフ参加者募集", color=0xFFFFFF)
            embed.description = f"ジャンル: **{list_names.get(genre, genre)}**\n\n「参加」ボタンを押してください。"
            
            await interaction.response.edit_message(content=None, embed=embed, view=join_view)
            
            # タスク起動
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

            elif game_value == "jinrou":
                import jinrou
                cog = self.bot.get_cog("JinrouCog")
                if not cog:
                    await send_debug_log(self.bot, "エラー: JinrouCog が見つかりません。")
                    return
                
                game = cog.get_game(interaction.channel_id)
                # ... (中略: jinrouの初期化処理) ...
                
                await interaction.response.edit_message(view=jinrou.RecruitView(game, 60))
                self.bot.loop.create_task(cog.run_from_hub(game, interaction.channel))
                await send_debug_log(self.bot, "Jinrouのタスクを起動しました。")

            # 他のゲームも同様に try-except で囲むと安全です
            
        except Exception:
            await send_debug_log(self.bot, f"SelectGameエラー:\n{traceback.format_exc()}")

class PlayHub(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="play", description="全てのミニゲームメニューを表示します")
    async def play(self, interaction: discord.Interaction):
        await send_debug_log(self.bot, f"/play コマンドが {interaction.channel.name} で実行されました。")
        view = GameSelectView(self.bot)
        await interaction.response.send_message(content="ゲームメニュー", view=view)

async def setup(bot):
    await bot.add_cog(PlayHub(bot))