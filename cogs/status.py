import discord
from discord import app_commands
from discord.ext import commands
from supabase import create_client

# Supabase設定
url = "YOUR_SUPABASE_URL"
key = "YOUR_SUPABASE_KEY"
supabase = create_client(url, key)

class Wallet(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="status", description="現在の所持金とPランクを確認します")
    async def wallet(self, interaction: discord.Interaction):
        user_id = str(interaction.user.id)
        
        try:
            # Supabaseからユーザーデータを取得
            res = supabase.table("users").select("coins, p_rank").eq("discord_id", user_id).execute()
            
            if not res.data:
                # データがない場合の初期登録（必要に応じて）
                await interaction.response.send_message("データが見つかりませんでした。先にゲームに参加してください。", ephemeral=True)
                return

            data = res.data[0]
            coins = data.get("coins", 0)
            p_rank = data.get("p_rank", "N/A")

            # Embedの作成
            embed = discord.Embed(
                title=f"{interaction.user.display_name} のステータス",
                color=discord.Color.gold(),
                timestamp=discord.utils.utcnow()
            )
            
            # ユーザーのアイコンをサムネイルに
            embed.set_thumbnail(url=interaction.user.display_name if interaction.user.avatar else None)
            
            # フィールドの追加
            embed.add_field(name="所持金", value=f"**{coins:,}** コイン", inline=True)
            embed.add_field(name="Pランク", value=f"**{p_rank}**", inline=True)
            
            embed.set_footer(text="Play Hub System", icon_url=self.bot.user.avatar.url if self.bot.user.avatar else None)

            await interaction.response.send_message(embed=embed)

        except Exception as e:
            print(f"Error fetching wallet: {e}")
            await interaction.response.send_message("データの取得中にエラーが発生しました。", ephemeral=True)

async def setup(bot):
    await bot.add_cog(Status(bot))