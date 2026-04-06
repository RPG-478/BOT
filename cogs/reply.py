import discord
from discord.ext import commands
import os
import random
import asyncio
from datetime import datetime, timezone
from supabase import create_client, Client
from groq import Groq
from dotenv import load_dotenv

load_dotenv()

class SimpleAI(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.enabled_channels = {}
        
        # APIクライアント初期化
        self.groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))
        url: str = os.getenv("SUPABASE_URL")
        key: str = os.getenv("SUPABASE_KEY")
        self.supabase: Client = create_client(url, key)
        
        # システムプロンプト（シンプルなタメ語）
        self.system_prompt = "自然な日本語で、親しみやすいタメ語で短く返答してください。"

    def get_guild_data(self, guild_id: int):
        """Supabaseからデータを取得。日付が変わっていたらカウントをリセットして返す。"""
        res = self.supabase.table("usage_limits").select("*").eq("guild_id", guild_id).execute()
        
        # 現在のUTC日付を取得 (YYYY-MM-DD)
        today = datetime.now(timezone.utc).date().isoformat()

        if not res.data:
            # 新規サーバー用：テスト制限10回、初期プロモーションコード生成
            default_code = f"SVR-{str(guild_id)[-5:]}"
            data = {
                "guild_id": guild_id,
                "used_count": 0,
                "max_limit": 10,
                "joined_at": datetime.now(timezone.utc).isoformat(),
                "promo_code": default_code,
                "last_reset_date": today # カウントリセット日を記録
            }
            self.supabase.table("usage_limits").insert(data).execute()
            return data
        
        data = res.data[0]
        
        # 日付が変わっているかチェック（1日ごとの上限設定のため）
        if data.get("last_reset_date") != today:
            # 日付を更新し、使用回数を0にリセット
            data["used_count"] = 0
            data["last_reset_date"] = today
            self.supabase.table("usage_limits").update({
                "used_count": 0, 
                "last_reset_date": today
            }).eq("guild_id", guild_id).execute()
            
        return data

    def update_usage(self, guild_id: int, new_count: int):
        """使用回数を更新"""
        self.supabase.table("usage_limits").update({"used_count": new_count}).eq("guild_id", guild_id).execute()

    @commands.command(name="oo")
    async def toggle_oo(self, ctx):
        """AI応答のON/OFF切り替え"""
        channel_id = ctx.channel.id
        status = not self.enabled_channels.get(channel_id, False)
        self.enabled_channels[channel_id] = status
        await ctx.send(f"AI応答を{'起動' if status else '停止'}したよ。")

    @commands.Cog.listener()
    async def on_message(self, message):
        # Bot自身の発言、Bot、DM、無効化チャンネル、コマンド開始文字を除外
        if message.author.bot or not message.guild or not self.enabled_channels.get(message.channel.id):
            return
        if message.content.startswith(self.bot.command_prefix):
            return

        # 1. データの取得とリセット判定
        data = self.get_guild_data(message.guild.id)
        used = data["used_count"]
        limit = data["max_limit"]

        # 2. 制限チェック（1日10回など）
        if used >= limit:
            return

        # 3. 20%の確率で応答（テスト中は100%にしたい場合は 1.0 に変更してください）
        if random.random() >= 0.2:
            return

        async with message.channel.typing():
            try:
                loop = asyncio.get_event_loop()
                response = await asyncio.wait_for(
                    loop.run_in_executor(None, self._get_groq_response, message.content),
                    timeout=8.0
                )
                
                if response:
                    clean_res = response.replace("\n", " ")[:30]
                    await message.reply(clean_res, allowed_mentions=discord.AllowedMentions.none())
                    
                    # 4. カウントアップ
                    new_used = used + 1
                    self.update_usage(message.guild.id, new_used)
                    
                    # 5. 上限到達時に一度だけ通知
                    if new_used >= limit:
                        await message.channel.send(
                            f"⚠️ 今日の制限（{limit}/{limit}）に達したよ。\n"
                            f"日付が変わるとリセットされるよ。招待プログラム（/invite）でもっと増やせるよ！"
                        )
            
            except Exception as e:
                print(f"Error: {e}")

    def _get_groq_response(self, user_text):
        """Groq APIを使用して返答生成"""
        completion = self.groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": user_text}
            ],
            temperature=0.7,
            max_tokens=100
        )
        return completion.choices[0].message.content

async def setup(bot):
    await bot.add_cog(SimpleAI(bot))