import discord  # 小文字に修正
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

    def get_guild_data(self, guild_id: int):
        """Supabaseからデータを取得。日付が変わっていたらリセット。"""
        # APIを叩く際にエラーが出ても止まらないようtry-except推奨
        try:
            res = self.supabase.table("usage_limits").select("*").eq("guild_id", guild_id).execute()
            today = datetime.now(timezone.utc).date().isoformat()

            if not res.data:
                # 新規サーバー用初期設定
                data = {
                    "guild_id": guild_id,
                    "used_count": 0,
                    "max_limit": 10,
                    "joined_at": datetime.now(timezone.utc).isoformat(),
                    "last_reset_date": today,
                    "is_promoted": False
                }
                self.supabase.table("usage_limits").insert(data).execute()
                return data
            
            data = res.data[0]
            # 日付が変わっていれば使用回数を0にリセット
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
            return {"used_count": 999, "max_limit": 0} # エラー時は安全のため制限状態にする

    def update_usage(self, guild_id: int, new_count: int):
        """使用回数を更新"""
        try:
            self.supabase.table("usage_limits").update({"used_count": new_count}).eq("guild_id", guild_id).execute()
        except Exception as e:
            print(f"Supabase Update Error: {e}")

    @commands.command(name="ask")
    async def ask_command(self, ctx, *, question: str = None):
        """!ask [質問] でAIが確定応答"""
        # 実行時にコンソールで確認するためのログ
        print(f"DEBUG: !ask received: {question} (Server: {ctx.guild.name})")

        if not question:
            return await ctx.send("質問を入力してね。例: `!ask 今日は何の日？`")

        # 1. データの取得と制限チェック
        data = self.get_guild_data(ctx.guild.id)
        used = data["used_count"]
        limit = data["max_limit"]

        if used >= limit:
            return await ctx.send(f"今日の制限（{used}/{limit}）に達したよ。日付が変わるのを待つか、/invite で枠を増やしてね。")

        # 2. 応答生成
        async with ctx.typing():
            try:
                # Groq APIの呼び出しを非同期実行
                loop = asyncio.get_event_loop()
                response = await asyncio.wait_for(
                    loop.run_in_executor(None, self._get_groq_response, question),
                    timeout=10.0
                )
                
                if response:
                    # 応答を整形して返信
                    clean_res = response.replace("\n", " ")[:100] # 文字制限を少し緩和
                    await ctx.reply(clean_res, allowed_mentions=discord.AllowedMentions.none())
                    
                    # 3. カウントアップ
                    self.update_usage(ctx.guild.id, used + 1)
            
            except asyncio.TimeoutError:
                await ctx.send("ごめん、AIが考えるのに時間がかかりすぎちゃった。")
            except Exception as e:
                print(f"Groq API Error: {e}")
                await ctx.send("ごめん、エラーで答えられなかった。")

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