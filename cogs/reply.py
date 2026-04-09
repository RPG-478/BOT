import discord
from discord.ext import commands
import os
import asyncio
from datetime import datetime, timezone
from supabase import create_client, Client
from groq import Groq
from dotenv import load_dotenv

load_dotenv()

class ReplyAI(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # APIクライアント初期化
        self.groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))
        url: str = os.getenv("SUPABASE_URL")
        key: str = os.getenv("SUPABASE_KEY")
        self.supabase: Client = create_client(url, key)
        
        # システムプロンプト
        self.system_prompt = "自然な日本語で、親しみやすいタメ語で短く返答してください。"
        
        # 自動返答が有効なチャンネルIDを保持するセット
        self.active_channels = set()

    def get_guild_data(self, guild_id: int):
        """Supabaseからデータを取得。日付が変わっていたらリセット。"""
        try:
            res = self.supabase.table("usage_limits").select("*").eq("guild_id", guild_id).execute()
            today = datetime.now(timezone.utc).date().isoformat()

            if not res.data:
                data = {
                    "guild_id": guild_id,
                    "used_count": 0,
                    "max_limit": 50,
                    "joined_at": datetime.now(timezone.utc).isoformat(),
                    "last_reset_date": today,
                    "is_promoted": False
                }
                self.supabase.table("usage_limits").insert(data).execute()
                return data
            
            data = res.data[0]
            if data.get("last_reset_date") != today:
                data["used_count"] = 0
                data["last_reset_date"] = today
                self.supabase.table("usage_limits").update({
                    "used_count": 0, 
                    "last_reset_date": today
                }).eq("guild_id", guild_id).execute()
                
            return data
        except Exception as e:
            print(f"Supabase Select Error: {e}")
            return {"used_count": 999, "max_limit": 0}

    def update_usage(self, guild_id: int, new_count: int):
        """使用回数を更新"""
        try:
            self.supabase.table("usage_limits").update({"used_count": new_count}).eq("guild_id", guild_id).execute()
        except Exception as e:
            print(f"Supabase Update Error: {e}")

    @commands.command(name="ask")
    async def toggle_ask(self, ctx):
        """チャンネル毎に自動返答のオンオフを切り替え"""
        channel_id = ctx.channel.id
        embed = discord.Embed(color=0xFFFFFF) # 白色
        
        if channel_id in self.active_channels:
            self.active_channels.remove(channel_id)
            embed.description = "ask機能をオフにしました"
            await ctx.send(embed=embed)
        else:
            self.active_channels.add(channel_id)
            embed.description = "ask機能をオンにしました"
            await ctx.send(embed=embed)

    @commands.Cog.listener()
    async def on_message(self, message):
        """メッセージ受信時の処理"""
        if message.author.bot or message.content.startswith(self.bot.command_prefix):
            return

        if message.channel.id not in self.active_channels:
            return

        data = self.get_guild_data(message.guild.id)
        used = data["used_count"]
        limit = data["max_limit"]

        if used >= limit:
            # 制限に達した際の販促メッセージを白色Embedで送信
            promo_embed = discord.Embed(
                description=f"今日の制限（{used}/{limit}）に達しました。日付が変わるのを待つか、別のサーバーにこのボットを導入し、/inviteで招待コードを処理すると1日1回のみ無料枠を100枠増やすことができます。招待するサーバーが条件を満たしている場合のみです",
                color=0xFFFFFF
            )
            await message.channel.send(embed=promo_embed)
            return 

        async with message.channel.typing():
            try:
                loop = asyncio.get_event_loop()
                response = await asyncio.wait_for(
                    loop.run_in_executor(None, self._get_groq_response, message.content),
                    timeout=10.0
                )
                
                if response:
                    clean_res = response.replace("\n", " ")[:100]
                    
                    # 使用回数を更新（表示用）
                    new_used_count = used + 1
                    
                    # 埋め込み形式での返答（残り枠数を追加）
                    embed = discord.Embed(
                        title="AGOBOTが返答を行いました",
                        description=f"{clean_res}\n\n**残り枠数: {limit - new_used_count} ({new_used_count}/{limit})**",
                        color=0xFFFFFF # 白色
                    )
                    await message.reply(embed=embed, allowed_mentions=discord.AllowedMentions.none())
                    
                    self.update_usage(message.guild.id, new_used_count)
            
            except asyncio.TimeoutError:
                pass 
            except Exception as e:
                print(f"Groq API Error: {e}")

    def _get_groq_response(self, user_text):
        """Groq APIを使用して返答生成"""
        completion = self.groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": user_text}
            ],
            temperature=0.7,
            max_tokens=150
        )
        return completion.choices[0].message.content

async def setup(bot):
    await bot.add_cog(ReplyAI(bot))
