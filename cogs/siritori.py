import discord
from discord import app_commands
from discord.ext import commands

class Siritori(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # チャンネルごとのゲーム状態を保持 {channel_id: {"last_word": str, "count": int}}
        self.games = {}

    def get_next_char(self, word):
        """単語の最後の文字を判定し、次の開始文字を返す"""
        if not word:
            return ""
        
        last_char = word[-1]
        
        # 伸ばし棒「ー」で終わる場合、一つ前の文字を参照
        if last_char == "ー" and len(word) > 1:
            last_char = word[-2]
            
        # 拗音・小書き文字の変換（例：しゃ -> や）
        mapping = {
            "ぁ": "あ", "ぃ": "い", "ぅ": "う", "ぇ": "え", "ぉ": "お",
            "ゃ": "や", "ゅ": "ゆ", "ょ": "よ", "っ": "つ", "ゎ": "わ"
        }
        return mapping.get(last_char, last_char)

    @app_commands.command(name="siritori", description="しりとりを開始します。")
    @app_commands.describe(start_word="最初の単語（デフォルト：しりとり）")
    async def siritori(self, interaction: discord.Interaction, start_word: str = "しりとり"):
        """スラッシュコマンドでしりとりを開始"""
        channel_id = interaction.channel_id
        
        if channel_id in self.games:
            await interaction.response.send_message("このチャンネルでは既にゲームが進行中です。", ephemeral=True)
            return

        # 「ん」で終わる単語での開始を防止
        if start_word.endswith(("ん", "ン")):
            await interaction.response.send_message("「ん」で終わる単語からは始められません。", ephemeral=True)
            return

        # ゲーム状態を初期化
        self.games[channel_id] = {
            "last_word": start_word,
            "count": 1
        }
        
        next_char = self.get_next_char(start_word)
        
        embed = discord.Embed(title="しりとり開始", color=discord.Color.blue())
        embed.add_field(name="最初の単語", value=f"{start_word}", inline=False)
        embed.set_footer(text=f"次は「{next_char}」から始まる言葉を入力してください。")
        
        await interaction.response.send_message(embed=embed)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """メッセージを監視してしりとりを判定"""
        # Bot自身の発言、またはゲームが開始されていないチャンネルは無視
        if message.author.bot or message.channel.id not in self.games:
            return

        # スラッシュコマンド自体には反応しない
        if message.content.startswith("/"):
            return

        game = self.games[message.channel.id]
        input_word = message.content.strip()
        
        if not input_word:
            return

        # --- 判定ロジック ---
        
        # 1. 前の単語の語尾から始まっているか確認
        required_char = self.get_next_char(game["last_word"])
        if not input_word.startswith(required_char):
            # 条件を満たさないメッセージを削除
            try:
                await message.delete()
            except discord.Forbidden:
                pass
            return

        # 2. 「ん」で終わっていないか確認（ゲームオーバー）
        if input_word.endswith(("ん", "ン")):
            count = game["count"]
            embed = discord.Embed(title="ゲームオーバー", color=discord.Color.red())
            embed.description = f"「ん」がついたので終了です。\n単語: {input_word}"
            embed.add_field(name="リザルト", value=f"合計: {count}回 続きました")
            
            await message.channel.send(embed=embed)
            
            # 該当チャンネルのゲームデータを削除
            del self.games[message.channel.id]
            return

        # 3. 成功：状態を更新
        game["last_word"] = input_word
        game["count"] += 1

async def setup(bot):
    await bot.add_cog(Siritori(bot))
