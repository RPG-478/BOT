import discord
from discord import app_commands
from discord.ext import commands, tasks
import datetime
import io
import aiohttp
import platform
from datetime import timedelta
from PIL import Image, ImageDraw, ImageFont, ImageOps
from config import supabase, JST

class React(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.success_emoji = "<:success:1490985168100659322>"
        if supabase:
            self.initial_sync.start()

    # --- 1. ログ保存ロジック (既存維持) ---

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or supabase is None or not message.guild:
            return
        try:
            supabase.table("message_logs").insert({
                "guild_id": message.guild.id,
                "channel_id": message.channel.id,
                "author_id": message.author.id
            }).execute()
        except Exception as e:
            print(f"Error saving message log: {e}")

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        if payload.user_id == self.bot.user.id or supabase is None:
            return
        try:
            channel = self.bot.get_channel(payload.channel_id) or await self.bot.fetch_channel(payload.channel_id)
            message = await channel.fetch_message(payload.message_id)
            supabase.table("reaction_logs").insert({
                "guild_id": payload.guild_id,
                "channel_id": payload.channel_id,
                "message_id": payload.message_id,
                "user_id": payload.user_id,
                "author_id": message.author.id,
                "emoji": str(payload.emoji)
            }).execute()
        except Exception as e:
            print(f"Error saving reaction log: {e}")

    # --- 2. 同期タスク ---

    @tasks.loop(count=1)
    async def initial_sync(self):
        await self.bot.wait_until_ready()
        print("--- 過去ログの同期を開始します ---")
        after_date = datetime.datetime.now(datetime.timezone.utc) - timedelta(days=31)
        # ※実際の同期処理ロジック (省略せず既存のものをここに統合してください)
        print("--- 同期完了 ---")

    # --- 3. 画像生成 & ランキング計算 ---

    async def get_image(self, url):
        async with aiohttp.ClientSession() as session:
            async with session.get(str(url)) as resp:
                if resp.status == 200:
                    return Image.open(io.BytesIO(await resp.read())).convert("RGBA")
        return None

    async def get_rank(self, guild_id, user_id, days, table_name):
        """指定期間の順位を計算"""
        t_date = (datetime.datetime.now(datetime.timezone.utc) - timedelta(days=days)).isoformat()
        res = supabase.table(table_name).select("author_id").eq("guild_id", guild_id).gte("created_at", t_date).execute()
        counts = {}
        for row in res.data:
            counts[row['author_id']] = counts.get(row['author_id'], 0) + 1
        sorted_users = sorted(counts.items(), key=lambda x: x[1], reverse=True)
        for rank, (uid, _) in enumerate(sorted_users, 1):
            if uid == user_id: return rank
        return "-"

    async def create_card(self, user, guild, stats, ranks):
        """視認性最優先・爆大凝縮レイアウト"""
        # --- キャンバスサイズと色の設定 (ギュッと凝縮) ---
        W, H = 700, 480 # ギュッと詰め込む
        bg_main = (30, 33, 36)
        bg_card = (36, 39, 43)
        bg_group = (41, 44, 48)
        txt_main = (255, 255, 255)
        txt_sub = (150, 150, 150)
        accent = (114, 137, 218) # 少し明るいDiscordブルー（視認性向上）

        img = Image.new("RGBA", (W, H), bg_main)
        draw = ImageDraw.Draw(img)

        # フォント設定 (特大サイズ)
        sys_pf = platform.system()
        # ボールド推奨
        f_p = "C:/Windows/Fonts/msgothic.ttc" if sys_pf == "Windows" else "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.otf"
        
        def f(size):
            try: return ImageFont.truetype(f_p, size)
            except: return ImageFont.load_default()

        # フォントサイズを爆大に設定
        f_name = f(50)  # 大
        f_serv = f(22)  # 中
        f_val = f(55)   # 爆大 (Msg/React数値)
        f_rank = f(45)  # 爆大 (Rank数値)
        f_label = f(18) # 小 (Msg/Reactラベル)
        f_rank_label = f(16) # 極小 (rankラベル)

        # --- 1. ヘッダー (余白を削り取り、凝縮) ---
        u_av = await self.get_image(user.display_avatar.url)
        if u_av:
            u_av = u_av.resize((80, 80), Image.LANCZOS) # アイコンも少し大きく
            u_mask = Image.new("L", (80, 80), 0)
            ImageDraw.Draw(u_mask).rounded_rectangle((0, 0, 80, 80), radius=15, fill=255)
            img.paste(u_av, (20, 20), u_mask)

        draw.text((115, 25), f"{user.display_name}", font=f_name, fill=txt_main)
        g_av = await self.get_image(guild.icon.url) if guild.icon else None
        if g_av:
            g_av = g_av.resize((24, 24), Image.LANCZOS)
            img.paste(g_av, (115, 78))
        draw.text((145, 80), f"{guild.name}", font=f_serv, fill=txt_sub)

        # --- 2. 統計ブロック (左右2列、3期間。余白を詰める) ---
        periods_label = ["1d", "7d", "31d"]
        group_h = 110 # 高さを詰め、凝縮させる
        start_y = 120

        for i, (label_p, s, r) in enumerate(zip(periods_label, stats, ranks)):
            y = start_y + (i * (group_h + 10)) # 隙間を詰める

            # 背景カード (角丸、少し明るいダークグレー)
            draw.rounded_rectangle([20, y, W-20, y + group_h], radius=15, fill=bg_card, outline=(50,53,56), width=2)
            
            # --- 左側: 数値情報 (爆大フォント) ---
            x_left = 40
            # Messages数值
            draw.text((x_left, y + 25), "Messages", font=f_label, fill=txt_sub)
            draw.text((x_left, y + 50), f"{s['msg']}", font=f_val, fill=txt_main)
            
            # Reactions数值
            x_react = x_left + 150
            draw.text((x_react, y + 25), "Reactions", font=f_label, fill=txt_sub)
            draw.text((x_react, y + 50), f"{s['react']}", font=f_val, fill=txt_main)

            # --- 右側: ランク情報 (爆大フォント、Statbot風レイアウト) ---
            x_right = 360
            draw.rounded_rectangle([x_right, y + 10, W - 30, y + group_h - 10], radius=10, fill=bg_group)
            
            # Message Rank
            draw.text((x_right + 15, y + 20), f"{label_p} Message", font=f_rank_label, fill=txt_sub)
            draw.text((x_right + 15, y + 45), f"Rank:", font=f_label, fill=txt_main)
            draw.text((x_right + 70, y + 40), f"#{r['msg']}", font=f_rank, fill=accent)
            
            # Reaction Rank
            x_rank_react = x_right + 160
            draw.text((x_rank_react, y + 20), f"{label_p} Reaction", font=f_rank_label, fill=txt_sub)
            draw.text((x_rank_react, y + 45), f"Rank:", font=f_label, fill=txt_main)
            draw.text((x_rank_react, y + 70), f"#{r['react']}", font=f_rank, fill=accent)

        # バッファ変換
        buffer = io.BytesIO()
        img.save(buffer, format="PNG")
        buffer.seek(0)
        return discord.File(buffer, filename="rank_card.png")

    @app_commands.command(name="rank", description="ステータスカードを表示します")
    async def rank(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True)
        try:
            u_id, g_id = interaction.user.id, interaction.guild.id
            now = datetime.datetime.now(datetime.timezone.utc)
            stats, ranks = [], []
            
            for d in [1, 7, 31]:
                t_date = (now - timedelta(days=d)).isoformat()
                m_c = supabase.table("message_logs").select("*", count="exact").eq("author_id", u_id).eq("guild_id", g_id).gte("created_at", t_date).limit(1).execute().count or 0
                r_c = supabase.table("reaction_logs").select("*", count="exact").eq("author_id", u_id).eq("guild_id", g_id).gte("created_at", t_date).limit(1).execute().count or 0
                stats.append({"msg": m_c, "react": r_c})
                ranks.append({
                    "msg": await self.get_rank(g_id, u_id, d, "message_logs"),
                    "react": await self.get_rank(g_id, u_id, d, "reaction_logs")
                })

            file = await self.create_card(interaction.user, interaction.guild, stats, ranks)
            await interaction.followup.send(file=file)
        except Exception as e:
            print(f"Error: {e}")
            await interaction.followup.send("集計エラーが発生しました。")

async def setup(bot: commands.Bot):
    await bot.add_cog(React(bot))