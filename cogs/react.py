import discord
from discord import app_commands
from discord.ext import commands, tasks
import datetime
import io
from datetime import timedelta
from PIL import Image, ImageDraw, ImageFont # ←ここを追加
from config import supabase, JST

class React(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.success_emoji = "<:success:1490985168100659322>"
        # 起動時に過去ログ同期を開始
        if supabase:
            self.initial_sync.start()

    # --- 1. リアルタイム保存ロジック ---

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or supabase is None or not message.guild:
            return
        try:
            data = {
                "guild_id": message.guild.id,
                "channel_id": message.channel.id,
                "author_id": message.author.id
            }
            supabase.table("message_logs").insert(data).execute()
        except Exception as e:
            print(f"Error saving message log: {e}")

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        if payload.user_id == self.bot.user.id or supabase is None:
            return
        try:
            channel = self.bot.get_channel(payload.channel_id) or await self.bot.fetch_channel(payload.channel_id)
            message = await channel.fetch_message(payload.message_id)
            data = {
                "guild_id": payload.guild_id,
                "channel_id": payload.channel_id,
                "message_id": payload.message_id,
                "user_id": payload.user_id,
                "author_id": message.author.id,
                "emoji": str(payload.emoji)
            }
            supabase.table("reaction_logs").insert(data).execute()
        except Exception as e:
            print(f"Error saving reaction log: {e}")

    # --- 2. 過去ログ同期ロジック ---

    @tasks.loop(count=1)
    async def initial_sync(self):
        await self.bot.wait_until_ready()
        print("--- 過去ログの同期を開始します (過去14日間) ---")
        after_date = datetime.datetime.now(datetime.timezone.utc) - timedelta(days=14)

        for guild in self.bot.guilds:
            for channel in guild.text_channels:
                if not channel.permissions_for(guild.me).read_message_history:
                    continue
                try:
                    async for msg in channel.history(after=after_date, limit=None, oldest_first=True):
                        if not msg.author.bot:
                            supabase.table("message_logs").insert({
                                "guild_id": guild.id,
                                "channel_id": channel.id,
                                "author_id": msg.author.id,
                                "created_at": msg.created_at.isoformat()
                            }).execute()
                        if msg.reactions:
                            for reaction in msg.reactions:
                                async for user in reaction.users():
                                    if user.bot: continue
                                    supabase.table("reaction_logs").insert({
                                        "guild_id": guild.id, "channel_id": channel.id,
                                        "message_id": msg.id, "user_id": user.id,
                                        "author_id": msg.author.id, "emoji": str(reaction.emoji),
                                        "created_at": msg.created_at.isoformat()
                                    }).execute()
                except Exception:
                    continue
        print("--- 過去ログの同期が完了しました ---")

    # --- 3. 画像生成ヘルパー (デコレータなし) ---

    async def create_card(self, user_name, stats_1d, stats_7d, stats_14d):
        W, H = 1000, 500
        bg_color = (252, 252, 252) 
        main_text, sub_text, accent_color = (44, 47, 51), (114, 118, 125), (88, 101, 242)

        img = Image.new("RGB", (W, H), bg_color)
        draw = ImageDraw.Draw(img)

        try:
            # フォントは環境に合わせて適宜修正
            font_title = ImageFont.truetype("arial.ttf", 50)
            font_label = ImageFont.truetype("arial.ttf", 25)
            font_value = ImageFont.truetype("arial.ttf", 40)
        except:
            font_title = font_label = font_value = ImageFont.load_default()

        draw.rectangle([0, 0, W, 120], fill=(240, 242, 245))
        draw.text((50, 35), f"{user_name}", font=font_title, fill=main_text)
        draw.text((50, 85), "Reaction & Message Activity", font=font_label, fill=sub_text)

        periods = [("Past 24h", stats_1d), ("Past 7d", stats_7d), ("Past 14d", stats_14d)]
        for i, (label, data) in enumerate(periods):
            x = 50 + (i * 310)
            draw.rounded_rectangle([x, 160, x+280, 460], radius=15, outline=(220, 225, 230), width=2)
            draw.text((x+20, 180), label, font=font_label, fill=accent_color)
            draw.text((x+20, 240), "Messages", font=font_label, fill=sub_text)
            draw.text((x+20, 270), f"{data['msg']}", font=font_value, fill=main_text)
            draw.text((x+20, 340), "Reactions", font=font_label, fill=sub_text)
            draw.text((x+20, 370), f"{data['react']}", font=font_value, fill=main_text)

        buffer = io.BytesIO()
        img.save(buffer, format="PNG")
        buffer.seek(0)
        return discord.File(buffer, filename="rank_card.png")

    # --- 4. スラッシュコマンド ---

    @app_commands.command(name="rank", description="ステータスカードを表示します")
    async def rank(self, interaction: discord.Interaction):
        """DBから集計して画像を出力"""
        # 3秒ルールを回避するために最初に応答を保留
        await interaction.response.defer(thinking=True)

        try:
            user_id = interaction.user.id
            now = datetime.datetime.now(datetime.timezone.utc)
            results = []

            # 1. データベース集計セクション
            for d in [1, 7, 14]:
                target_date = (now - timedelta(days=d)).isoformat()
                
                # ここでタイムアウトやエラーが起きやすいので注意
                m_res = supabase.table("message_logs").select("*", count="exact").eq("author_id", user_id).gte("created_at", target_date).execute()
                r_res = supabase.table("reaction_logs").select("*", count="exact").eq("author_id", user_id).gte("created_at", target_date).execute()
                
                results.append({"msg": m_res.count, "react": r_res.count})

            # 2. 画像生成セクション
            file = await self.create_card(interaction.user.display_name, results[0], results[1], results[2])
            
            # 3. 最終応答の送信 (followupを使用)
            await interaction.followup.send(
                content=f"{self.success_emoji} **{interaction.user.display_name}** の統計を生成しました", 
                file=file
            )

        except Exception as e:
            # エラー内容をターミナルに出力
            print(f"Error in rank command: {e}")
            # ユーザーにもエラーを通知
            await interaction.followup.send("データの取得中または画像生成中にエラーが発生しました。コンソールを確認してください。")

async def setup(bot: commands.Bot):
    await bot.add_cog(React(bot))
