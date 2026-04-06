import discord
from discord import app_commands
from discord.ext import commands
import os
import random
import string
from datetime import datetime, timedelta, timezone
from supabase import create_client, Client

url: str = os.getenv("SUPABASE_URL")
key: str = os.getenv("SUPABASE_KEY")
supabase: Client = create_client(url, key)

def generate_random_code():
    """5桁の英数字コードを生成"""
    return "SVR-" + "".join(random.choices(string.ascii_uppercase + string.digits, k=5))

class InviteModal(discord.ui.Modal, title="紹介コード入力"):
    code_input = discord.ui.TextInput(
        label="紹介元のサーバーコード",
        placeholder="例: SVR-ABC12",
        min_length=3,
        max_length=50
    )

    async def on_submit(self, interaction: discord.Interaction):
        guild_b = interaction.guild
        input_code = self.code_input.value

        res_b = supabase.table("usage_limits").select("*").eq("guild_id", guild_b.id).execute()
        if not res_b.data:
            return await interaction.response.send_message("サーバーデータが見つかりません。", ephemeral=True)
        
        data_b = res_b.data[0]

        # 判定1: 24時間以内
        joined_at_str = data_b.get("joined_at")
        if not joined_at_str:
            return await interaction.response.send_message("導入日時データがありません。", ephemeral=True)
        joined_at = datetime.fromisoformat(joined_at_str.replace('Z', '+00:00'))
        if datetime.now(timezone.utc) > joined_at + timedelta(hours=24):
            return await interaction.response.send_message("期限切れです（導入から24時間経過）。", ephemeral=True)

        # 判定2: 新規判定
        if data_b.get("is_promoted"):
            return await interaction.response.send_message("既に報酬受取済みです。", ephemeral=True)

        # 判定3: 作成から1ヶ月
        one_month_ago = datetime.now(timezone.utc) - timedelta(days=30)
        if guild_b.created_at > one_month_ago:
            return await interaction.response.send_message("作成から1ヶ月以上経過している必要があります。", ephemeral=True)

        # 判定4: 15人以上
        if guild_b.member_count < 15:
            return await interaction.response.send_message(f"15人以上必要です（現在: {guild_b.member_count}人）。", ephemeral=True)

        # A鯖チェック
        res_a = supabase.table("usage_limits").select("*").eq("promo_code", input_code).execute()
        if not res_a.data:
            return await interaction.response.send_message("無効なコードです。", ephemeral=True)
        
        data_a = res_a.data[0]
        if data_a["guild_id"] == guild_b.id:
            return await interaction.response.send_message("自サーバーのコードは無効です。", ephemeral=True)

        today = datetime.now(timezone.utc).date().isoformat()
        if data_a.get("last_reward_at") == today:
            return await interaction.response.send_message("紹介元は本日の上限に達しています。", ephemeral=True)

        # 報酬付与
        supabase.table("usage_limits").update({"is_promoted": True, "max_limit": (data_b.get("max_limit") or 0) + 100}).eq("guild_id", guild_b.id).execute()
        supabase.table("usage_limits").update({"max_limit": (data_a.get("max_limit") or 0) + 100, "last_reward_at": today}).eq("guild_id", data_a["guild_id"]).execute()

        await interaction.response.send_message("認証成功。双方に100枠追加しました。", ephemeral=False)

class InviteView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.select(
        placeholder="項目を選択してください",
        options=[
            discord.SelectOption(label="自サーバーのコード確認", value="check"),
            discord.SelectOption(label="紹介コードを入力する", value="input")
        ]
    )
    async def select_callback(self, interaction: discord.Interaction, select: discord.ui.Select):
        guild_id = interaction.guild.id
        
        if select.values[0] == "check":
            res = supabase.table("usage_limits").select("*").eq("guild_id", guild_id).execute()
            
            # データがない、またはコードが空の場合に生成・更新する
            if not res.data:
                new_code = generate_random_code()
                supabase.table("usage_limits").insert({
                    "guild_id": guild_id,
                    "promo_code": new_code,
                    "joined_at": datetime.now(timezone.utc).isoformat(),
                    "max_limit": 10
                }).execute()
                code = new_code
            elif not res.data[0].get("promo_code"):
                new_code = generate_random_code()
                supabase.table("usage_limits").update({"promo_code": new_code}).eq("guild_id", guild_id).execute()
                code = new_code
            else:
                code = res.data[0]["promo_code"]

            await interaction.response.send_message(f"このサーバーのコード: `{code}`", ephemeral=True)
        
        elif select.values[0] == "input":
            await interaction.response.send_modal(InviteModal())

class Invite(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_guild_join(self, guild):
        """ボット参加時に自動登録"""
        now = datetime.now(timezone.utc).isoformat()
        supabase.table("usage_limits").upsert({
            "guild_id": guild.id,
            "promo_code": generate_random_code(),
            "joined_at": now,
            "max_limit": 10
        }).execute()

    @app_commands.command(name="invite", description="招待プログラムの利用")
    async def invite_cmd(self, interaction: discord.Interaction):
        await interaction.response.send_message("メニューを選択してください", view=InviteView(), ephemeral=True)

async def setup(bot):
    await bot.add_cog(Invite(bot))