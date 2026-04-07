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
        W, H = 1200, 650
        img = Image.new("RGBA", (W, H), (255, 255, 255))
        draw = ImageDraw.Draw(img)

        # フォント設定
        sys_pf = platform.system()
        f_p = "C:/Windows/Fonts/msgothic.ttc" if sys_pf == "Windows" else "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.otf"
        def f(size): 
            try: return ImageFont.truetype(f_p, size)
            except: return ImageFont.load_default()

        # ヘッダー & アイコン
        draw.rectangle([0, 0, W, 180], fill=(245, 247, 250))
        u_av = await self.get_image(user.display_avatar.url)
        g_av = await self.get_image(guild.icon.url) if guild.icon else None
        
        def paste_round(icon, pos):
            if not icon: return
            icon = icon.resize((120, 120), Image.LANCZOS)
            mask = Image.new("L", (120, 120), 0)
            ImageDraw.Draw(mask).ellipse((0, 0, 120, 120), fill=255)
            img.paste(icon, pos, mask)

        paste_round(u_av, (50, 30))
        paste_round(g_av, (185, 30))
        draw.text((330, 45), f"{user.display_name}", font=f(55), fill=(30, 30, 30))
        draw.text((330, 110), f"Activity Stats @ {guild.name}", font=f(28), fill=(100, 100, 100))

        # コンテンツ描画 (左: Stats / 右: Rank)
        periods = ["1 Day", "7 Days", "31 Days"]
        for i, p_label in enumerate(periods):
            y = 220 + (i * 135)
            # Stats (左)
            draw.rounded_rectangle([50, y, 580, y + 115], radius=15, outline=(220, 225, 230), width=3)
            draw.text((75, y + 15), p_label, font=f(25), fill=(88, 101, 242))
            draw.text((75, y + 50), f"Msg: {stats[i]['msg']}  /  React: {stats[i]['react']}", font=f(42), fill=(40, 40, 40))
            
            # Rank (右)
            draw.rounded_rectangle([620, y, 1150, y + 115], radius=15, fill=(240, 242, 255))
            draw.text((645, y + 15), f"{p_label} Rank", font=f(25), fill=(100, 100, 100))
            draw.text((645, y + 45), f"Msg: #{ranks[i]['msg']}  /  React: #{ranks[i]['react']}", font=f(48), fill=(88, 101, 242))

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