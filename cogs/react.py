import discord
from discord import app_commands
from discord.ext import commands, tasks
import datetime
from datetime import timedelta
from config import supabase, JST

class React(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.success_emoji = "<:success:1490985168100659322>"
        # 起動時に過去ログ同期を開始
        self.initial_sync.start()

    # --- 1. リアルタイム保存ロジック ---

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """メッセージ送信を検知して保存"""
        if message.author.bot or supabase is None:
            return
        
        try:
            # message_logs テーブルへ挿入
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
        """リアクション追加を検知して保存"""
        if payload.user_id == self.bot.user.id or supabase is None:
            return
        
        try:
            # チャンネルとメッセージをフェッチ（投稿者を特定するため）
            channel = self.bot.get_channel(payload.channel_id) or await self.bot.fetch_channel(payload.channel_id)
            message = await channel.fetch_message(payload.message_id)

            # reaction_logs テーブルへ挿入
            data = {
                "guild_id": payload.guild_id,
                "channel_id": payload.channel_id,
                "message_id": payload.message_id,
                "user_id": payload.user_id,     # 押した人
                "author_id": message.author.id,  # もらった人（ポイント対象）
                "emoji": str(payload.emoji)
            }
            supabase.table("reaction_logs").insert(data).execute()
        except Exception as e:
            print(f"Error saving reaction log: {e}")

    # --- 2. 過去ログ同期ロジック (バックグラウンドタスク) ---

    @tasks.loop(count=1)
    async def initial_sync(self):
        """起動時に1回だけ、過去14日間の全ログをスキャンしてDBを埋める"""
        await self.bot.wait_until_ready()
        print("--- 過去ログの同期を開始します (過去14日間) ---")

        # 14日前を計算 (JST/UTC どちらでも対応できるようにUTCベース)
        after_date = datetime.datetime.now(datetime.timezone.utc) - timedelta(days=14)

        for guild in self.bot.guilds:
            for channel in guild.text_channels:
                # 履歴読み取り権限の確認
                if not channel.permissions_for(guild.me).read_message_history:
                    continue

                print(f"Scanning channel: {channel.name}...")
                try:
                    async for msg in channel.history(after=after_date, limit=None, oldest_first=True):
                        # 1. メッセージログの保存 (Bot以外)
                        if not msg.author.bot:
                            # 既にDBにあるかチェック（重複防止）
                            # ※本来は upsert 等が理想ですが、まずは簡易保存
                            msg_data = {
                                "guild_id": guild.id,
                                "channel_id": channel.id,
                                "author_id": msg.author.id,
                                "created_at": msg.created_at.isoformat()
                            }
                            supabase.table("message_logs").insert(msg_data).execute()

                        # 2. リアクションログの保存
                        if msg.reactions:
                            for reaction in msg.reactions:
                                async for user in reaction.users():
                                    if user.bot: continue
                                    
                                    react_data = {
                                        "guild_id": guild.id,
                                        "channel_id": channel.id,
                                        "message_id": msg.id,
                                        "user_id": user.id,
                                        "author_id": msg.author.id,
                                        "emoji": str(reaction.emoji),
                                        "created_at": msg.created_at.isoformat() # リアクション時刻はメッセージ時刻で代用
                                    }
                                    supabase.table("reaction_logs").insert(react_data).execute()
                except Exception as e:
                    print(f"Error scanning {channel.name}: {e}")
                    continue

        print("--- 過去ログの同期が完了しました ---")

    # --- 3. ランキング表示コマンド (フェーズ2/3で完成させる) ---

    @app_commands.command(name="rank", description="ステータスカードを表示します")
    async def create_card(self, user_name, avatar_url, stats_1d, stats_7d, stats_14d):
        """白基調のミニマルなステータスカードを生成"""
        # キャンバスサイズ
        W, H = 1000, 500
        bg_color = (252, 252, 252) # オフホワイト
        main_text = (44, 47, 51)   # ダークグレー
        sub_text = (114, 118, 125) # グレー
        accent_color = (88, 101, 242) # Discordブルー

        img = Image.new("RGB", (W, H), bg_color)
        draw = ImageDraw.Draw(img)

        # --- フォント設定 (環境に合わせてパスを変更してください) ---
        try:
            font_title = ImageFont.truetype("arial.ttf", 50)
            font_label = ImageFont.truetype("arial.ttf", 25)
            font_value = ImageFont.truetype("arial.ttf", 40)
        except:
            font_title = font_label = font_value = ImageFont.load_default()

        # --- デザイン描画 ---
        # ヘッダー背景
        draw.rectangle([0, 0, W, 120], fill=(240, 242, 245))
        
        # ユーザー名
        draw.text((50, 35), f"{user_name}", font=font_title, fill=main_text)
        draw.text((50, 85), "Reaction & Message Activity", font=font_label, fill=sub_text)

        # セクション分け (3列: 1d, 7d, 14d)
        periods = [("Past 24h", stats_1d), ("Past 7d", stats_7d), ("Past 14d", stats_14d)]
        for i, (label, data) in enumerate(periods):
            x_offset = 50 + (i * 310)
            y_offset = 160
            
            # 枠線
            draw.rounded_rectangle([x_offset, y_offset, x_offset+280, y_offset+300], radius=15, outline=(220, 225, 230), width=2)
            
            # ラベル
            draw.text((x_offset+20, y_offset+20), label, font=font_label, fill=accent_color)
            
            # メッセージ数
            draw.text((x_offset+20, y_offset+80), "Messages", font=font_label, fill=sub_text)
            draw.text((x_offset+20, y_offset+110), f"{data['msg']}", font=font_value, fill=main_text)
            
            # リアクション数
            draw.text((x_offset+20, y_offset+180), "Reactions", font=font_label, fill=sub_text)
            draw.text((x_offset+20, y_offset+210), f"{data['react']}", font=font_value, fill=main_text)

        # --- バッファ変換 ---
        buffer = io.BytesIO()
        img.save(buffer, format="PNG")
        buffer.seek(0)
        return discord.File(buffer, filename="rank_card.png")

    @app_commands.command(name="rank", description="ステータスカードを表示します")
    async def rank(self, interaction: discord.Interaction):
        """DBから集計して画像を出力"""
        await interaction.response.defer()

        user_id = interaction.user.id
        now = datetime.datetime.now(datetime.timezone.utc)
        
        # 期間リスト (1, 7, 14日前)
        days = [1, 7, 14]
        results = []

        for d in days:
            target_date = (now - timedelta(days=d)).isoformat()
            
            # メッセージ数集計
            msg_res = supabase.table("message_logs").select("*", count="exact")\
                .eq("author_id", user_id).gte("created_at", target_date).execute()
            
            # リアクション数集計
            react_res = supabase.table("reaction_logs").select("*", count="exact")\
                .eq("author_id", user_id).gte("created_at", target_date).execute()
            
            results.append({"msg": msg_res.count, "react": react_res.count})

        # 画像生成
        file = await self.create_card(
            interaction.user.display_name,
            interaction.user.display_avatar.url,
            results[0], results[1], results[2]
        )

        success_msg = f"{self.success_emoji} **{interaction.user.display_name}** の統計カードを生成しました"
        await interaction.followup.send(content=success_msg, file=file)

async def setup(bot: commands.Bot):
    await bot.add_cog(React(bot))