import discord
from discord.ext import commands
from discord import app_commands
from datetime import datetime, timezone
import os
from supabase import create_client, Client

# Supabase connection info
SUPABASE_URL = os.getenv("SUPABASE_URL", "YOUR_SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "YOUR_SUPABASE_ANON_KEY")

class GameCoreCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

    async def _get_or_create_nation(self, guild: discord.Guild) -> str:
        guild_id_str = str(guild.id)
        
        response = self.supabase.table("nations").select("id").eq("guild_id", guild_id_str).execute()
        if response.data:
            return response.data[0]["id"]
        
        new_nation = {
            "guild_id": guild_id_str,
            "name": f"{guild.name}合衆国",
            "treasury": 0,
            "tax_rate": 10.00
        }
        insert_response = self.supabase.table("nations").insert(new_nation).execute()
        return insert_response.data[0]["id"]

    async def _sync_stamina(self, user_id_str: str) -> dict:
        response = self.supabase.table("users").select("*").eq("id", user_id_str).execute()
        if not response.data:
            return None
        
        user_data = response.data[0]
        now = datetime.now(timezone.utc)
        last_update = datetime.fromisoformat(user_data["last_stamina_update"].replace("Z", "+00:00"))
        
        elapsed_seconds = (now - last_update).total_seconds()
        elapsed_hours = elapsed_seconds / 3600.0
        
        stamina_loss = int(elapsed_hours * 5)
        
        if stamina_loss > 0:
            new_stamina = max(0, user_data["stamina"] - stamina_loss)
            update_response = self.supabase.table("users").update({
                "stamina": new_stamina,
                "last_stamina_update": now.isoformat()
            }).eq("id", user_id_str).execute()
            return update_response.data[0]
            
        return user_data

    @commands.hybrid_command(name="join_game", description="ゲームに参加し、現在の国家に所属します。")
    async def join_game(self, ctx: commands.Context):
        if not ctx.guild:
            await ctx.send("このコマンドはサーバー内でのみ実行できます。")
            return

        await ctx.defer()
        user_id_str = str(ctx.author.id)
        
        response = self.supabase.table("users").select("id").eq("id", user_id_str).execute()
        if response.data:
            await ctx.send(f"⚠️ {ctx.author.mention} は既にゲームに参加しています。")
            return

        nation_id = await self._get_or_create_nation(ctx.guild)
        
        new_user = {
            "id": user_id_str,
            "nation_id": nation_id,
            "money": 1000,
            "stamina": 100,
            "last_stamina_update": datetime.now(timezone.utc).isoformat()
        }
        self.supabase.table("users").insert(new_user).execute()
        
        await ctx.send(f"🎮 {ctx.author.mention} がゲームに参加しました！初期資金として 1000G を支給しました。")

    @commands.hybrid_command(name="status", description="自分の現在のステータスを確認します。")
    async def status(self, ctx: commands.Context):
        await ctx.defer()
        user_id_str = str(ctx.author.id)
        
        user_data = await self._sync_stamina(user_id_str)
        
        if not user_data:
            await ctx.send(f"❌ ゲームに参加していません。`/join_game` で参加してください。")
            return
            
        nation_res = self.supabase.table("nations").select("name").eq("id", user_data["nation_id"]).execute()
        nation_name = nation_res.data[0]["name"] if nation_res.data else "無所属"

        embed = discord.Embed(title=f"👤 {ctx.author.display_name} のステータス", color=discord.Color.blue())
        embed.add_field(name="🌍 所属国家", value=nation_name, inline=False)
        embed.add_field(name="💰 所持金", value=f"{user_data['money']} G", inline=True)
        embed.add_field(name="🍖 スタミナ (空腹度)", value=f"{user_data['stamina']} / 100", inline=True)
        embed.set_footer(text="※スタミナは1時間に5減少します")
        
        await ctx.send(embed=embed)

    @commands.hybrid_command(name="work", description="国策労働を行い、お金を稼ぎます。（スタミナを20消費）")
    async def work(self, ctx: commands.Context):
        await ctx.defer()
        user_id_str = str(ctx.author.id)
        
        user_data = await self._sync_stamina(user_id_str)
        if not user_data:
            await ctx.send(f"❌ ゲームに参加していません。`/join_game` で参加してください。")
            return
            
        STAMINA_COST = 20
        if user_data["stamina"] < STAMINA_COST:
            await ctx.send(f"😫 スタミナが足りません！ (現在: {user_data['stamina']}/{STAMINA_COST}必要)\n飯屋で料理を食べるか、時間経過を待ってください。")
            return
            
        nation_res = self.supabase.table("nations").select("tax_rate, treasury").eq("id", user_data["nation_id"]).execute()
        if not nation_res.data:
            await ctx.send("❌ 所属国家のデータが見つかりません。")
            return
            
        tax_rate = float(nation_res.data[0]["tax_rate"])
        
        base_reward = 200
        tax_amount = int(base_reward * (tax_rate / 100.0))
        player_reward = base_reward - tax_amount
        
        new_stamina = user_data["stamina"] - STAMINA_COST
        new_money = user_data["money"] + player_reward
        self.supabase.table("users").update({
            "stamina": new_stamina,
            "money": new_money
        }).eq("id", user_id_str).execute()
        
        new_treasury = nation_res.data[0]["treasury"] + tax_amount
        self.supabase.table("nations").update({
            "treasury": new_treasury
        }).eq("id", user_data["nation_id"]).execute()
        
        await ctx.send(
            f"🛠️ {ctx.author.mention} は国策労働を行いました！\n"
            f"・消費スタミナ: -{STAMINA_COST} (残り: {new_stamina}/100)\n"
            f"・獲得報酬: +{player_reward} G (総額: {new_money} G)\n"
            f"・所得税納入 ({int(tax_rate)}%): {tax_amount} G が国庫に送られました。"
        )

async def setup(bot: commands.Bot):
    await bot.add_cog(GameCoreCog(bot))
