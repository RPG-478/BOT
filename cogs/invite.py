import discord
from discord import app_commands
from discord.ext import commands
import os
from datetime import datetime, timedelta, timezone
from supabase import create_client, Client

# Supabase設定
url: str = os.getenv("SUPABASE_URL")
key: str = os.getenv("SUPABASE_KEY")
supabase: Client = create_client(url, key)

class InviteModal(discord.ui.Modal, title="紹介コード入力"):
    code_input = discord.ui.TextInput(
        label="紹介元のサーバーコード",
        placeholder="例: SVR-12345",
        min_length=3,
        max_length=50
    )

    async def on_submit(self, interaction: discord.Interaction):
        guild_b = interaction.guild
        input_code = self.code_input.value

        # --- B鯖(現在)のバリデーション ---
        res_b = supabase.table("usage_limits").select("*").eq("guild_id", guild_b.id).execute()
        if not res_b.data:
            return await interaction.response.send_message("サーバーデータが見つかりません。", ephemeral=True)
        
        data_b = res_b.data[0]

        # 判定1: ボット導入から24時間以内か
        joined_at_str = data_b.get("joined_at")
        if not joined_at_str:
            return await interaction.response.send_message("導入日時データがありません。", ephemeral=True)
            
        joined_at = datetime.fromisoformat(joined_at_str.replace('Z', '+00:00'))
        if datetime.now(timezone.utc) > joined_at + timedelta(hours=24):
            return await interaction.response.send_message("期限切れです（導入から24時間以上経過）。", ephemeral=True)

        # 判定2: 新規判定
        if data_b.get("is_promoted"):
            return await interaction.response.send_message("このサーバーは既に紹介報酬を受け取り済みです。", ephemeral=True)

        # 判定3: サーバー作成から1ヶ月経過
        one_month_ago = datetime.now(timezone.utc) - timedelta(days=30)
        if guild_b.created_at > one_month_ago:
            return await interaction.response.send_message("サーバー作成から1ヶ月以上経過している必要があります。", ephemeral=True)

        # 判定4: メンバーが15人以上
        if guild_b.member_count < 15:
            return await interaction.response.send_message(f"メンバーが15人以上必要です（現在: {guild_b.member_count}人）。", ephemeral=True)

        # --- A鯖(紹介元)のバリデーション ---
        res_a = supabase.table("usage_limits").select("*").eq("promo_code", input_code).execute()
        if not res_a.data:
            return await interaction.response.send_message("無効な紹介コードです。", ephemeral=True)
        
        data_a = res_a.data[0]
        if data_a["guild_id"] == guild_b.id:
            return await interaction.response.send_message("自サーバーのコードは入力できません。", ephemeral=True)

        # A鯖判定1: 1日1回制限
        today = datetime.now(timezone.utc).date().isoformat()
        if data_a.get("last_reward_at") == today:
            return await interaction.response.send_message("紹介元サーバーは本日の報酬獲得上限に達しています。", ephemeral=True)

        # --- 報酬付与処理 ---
        # 1. B鯖を完了状態にし、枠を追加 (+100)
        new_limit_b = (data_b.get("max_limit") or 0) + 100
        supabase.table("usage_limits").update({
            "is_promoted": True,
            "max_limit": new_limit_b
        }).eq("guild_id", guild_b.id).execute()
        
        # 2. A鯖に報酬付与 (+100) と日付更新
        new_limit_a = (data_a.get("max_limit") or 0) + 100
        supabase.table("usage_limits").update({
            "max_limit": new_limit_a,
            "last_reward_at": today
        }).eq("guild_id", data_a["guild_id"]).execute()

        await interaction.response.send_message(
            f"認証に成功しました。紹介元とこのサーバーの両方に100枠を追加しました。",
            ephemeral=False
        )

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
        if select.values[0] == "check":
            res = supabase.table("usage_limits").select("promo_code").eq("guild_id", interaction.guild.id).execute()
            code = res.data[0]["promo_code"] if res.data and res.data[0]["promo_code"] else "未設定"
            await interaction.response.send_message(f"このサーバーのコード: {code}", ephemeral=True)
        
        elif select.values[0] == "input":
            await interaction.response.send_modal(InviteModal())

class Invite(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="invite", description="招待プログラムの利用")
    async def invite_cmd(self, interaction: discord.Interaction):
        await interaction.response.send_message("メニューを選択してください", view=InviteView(), ephemeral=True)

async def setup(bot):
    await bot.add_cog(Invite(bot))
