import discord
from discord import app_commands
from discord.ext import commands
from supabase import create_client

# Supabase設定
url = "SUPABASE_URL"
key = "SUPABASE_KEY"
supabase = create_client(url, key)

class Status(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="status", description="現在の所持金とPランクを確認します")
    async def status(self, interaction: discord.Interaction):
        user_id = str(interaction.user.id)
        
        try:
            # Supabaseからユーザーデータを取得
            res = supabase.table("users").select("coins, p_rank").eq("discord_id", user_id).execute()
            
            if not res.data:
                embed = discord.Embed(
                    description="データが見つかりませんでした。先にゲームに参加してください。",
                    color=0xFFFFFF
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return

            data = res.data[0]
            coins = data.get("coins", 0)
            p_rank = data.get("p_rank", "N/A")

            # Embedの作成（白色統一）
            embed = discord.Embed(
                title=f"{interaction.user.display_name} のステータス",
                color=0xFFFFFF,
                timestamp=discord.utils.utcnow()
            )
            
            # ユーザーのアイコンをサムネイルに設定
            embed.set_thumbnail(url=interaction.user.display_avatar.url)
            
            # フィールドの追加
            embed.add_field(name="所持金", value=f"**{coins:,}** コイン", inline=True)
            embed.add_field(name="Pランク", value=f"**{p_rank}**", inline=True)
            
            # フッターの設定
            embed.set_footer(text="Play Hub System")

            await interaction.response.send_message(embed=embed)

        except Exception as e:
            print(f"Error fetching status: {e}")
            embed = discord.Embed(
                description="データの取得中にエラーが発生しました。",
                color=0xFFFFFF
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)

async def setup(bot):
    await bot.add_cog(Status(bot))
