import os
import random
from datetime import datetime, timezone, timedelta
import discord
from discord import app_commands
from discord.ext import commands
from supabase import create_client, Client

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# 属性ごとのフレーバーテキスト
WORK_FLAVORS = {
    "虚": ["裏路地の怪しい依頼をこなした", "次元の歪みを調査した", "影の中で秘密の配達を行った"],
    "実": ["鉱山で頑丈な鉱石を掘り出した", "建築現場の重ち持ちを手伝った", "鍛冶屋の薪割りを助けた"],
    "正": ["街の警護巡回を行った", "迷子のペットを無事に保護した", "遺跡の浄化作業を手伝った"],
    "負": ["暗闇に乗じて珍しい素材を回収した", "モンスターの群れを追い払った", "毒沼の調査を行った"],
    "無": ["便利屋として雑用を引き受けた", "荷物の運搬を手伝った", "街の清掃活動に参加した"]
}

class MonsterWorkSelectView(discord.ui.View):
    def __init__(self, user_id: str, monsters: list):
        super().__init__(timeout=180)
        self.user_id = user_id
        self.monsters = monsters

        options = [
            discord.SelectOption(
                label=f"{m['name']} (Lv.{m['current_level']})",
                description=f"属性: {m['element_type']} | 才能: {m['dice_talent']}",
                value=str(m["id"]),
                emoji="💼"
            )
            for m in monsters[:25]
        ]

        select = discord.ui.Select(
            placeholder="お仕事に派遣するモンスターを選択...",
            min_values=1,
            max_values=1,
            options=options
        )
        select.callback = self.select_callback
        self.add_item(select)

    async def select_callback(self, interaction: discord.Interaction):
        if str(interaction.user.id) != self.user_id:
            await interaction.response.send_message("他のプレイヤーの操作です。", ephemeral=True)
            return

        selected_id = interaction.data["values"][0]
        monster = next((m for m in self.monsters if str(m["id"]) == selected_id), None)

        if not monster:
            await interaction.response.send_message("モンスターが見つかりませんでした。", ephemeral=True)
            return

        # 5分後の時間を算出
        now = datetime.now(timezone.utc)
        finish_time = now + timedelta(minutes=5)

        # DBに派遣セッションを記録
        supabase.table("work_sessions").insert({
            "user_id": self.user_id,
            "monster_id": monster["id"],
            "finish_time": finish_time.isoformat()
        }).execute()

        embed = discord.Embed(
            title="💼 お仕事派遣完了！",
            description=f"**{monster['name']}** がお仕事に出発しました。\n**5分後** に再度 `/ddd_work` を実行して結果を受け取ってください！",
            color=discord.Color.blue()
        )
        embed.set_thumbnail(url=monster["image_url"])
        embed.add_field(name="⏱️ 完了予定時刻", value=f"<t:{int(finish_time.timestamp())}:R>")

        await interaction.response.send_message(embed=embed)


class WorkCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def get_user_profile(self, user_id: str) -> dict:
        res = supabase.table("users").select("*").eq("user_id", user_id).execute()
        if res.data:
            return res.data[0]
        
        new_user = {"user_id": user_id, "balance": 0, "max_box_slots": 20, "unlocked_palettes": ["8x8"]}
        inserted = supabase.table("users").insert(new_user).execute()
        return inserted.data[0]

    @app_commands.command(name="ddd_work", description="モンスターをお仕事に行かせてコインとExpを獲得します（5分間）")
    async def ddd_work(self, interaction: discord.Interaction):
        user_id = str(interaction.user.id)
        await interaction.response.defer()

        # 1. アクティブな派遣セッションの確認
        session_res = supabase.table("work_sessions").select("*, monsters(*)").eq("user_id", user_id).execute()

        if session_res.data:
            session = session_res.data[0]
            monster = session["monsters"]
            finish_time = datetime.fromisoformat(session["finish_time"])
            now = datetime.now(timezone.utc)

            # 作業中（5分経過していない場合）
            if now < finish_time:
                remaining_sec = int((finish_time - now).total_seconds())
                mins, secs = divmod(remaining_sec, 60)

                embed = discord.Embed(
                    title="⏳ お仕事実行中...",
                    description=f"現在 **{monster['name']}** がお仕事中です！\nあと **{mins}分{secs}秒** で完了します。",
                    color=discord.Color.orange()
                )
                embed.set_thumbnail(url=monster["image_url"])
                embed.add_field(name="⏱️ 完了予定", value=f"<t:{int(finish_time.timestamp())}:R>")
                await interaction.followup.send(embed=embed)
                return

            # 作業完了（5分以上経過している場合）-> 報酬清算
            element = monster.get("element_type", "無")
            flavors = WORK_FLAVORS.get(element, WORK_FLAVORS["無"])
            action_text = random.choice(flavors)

            # 報酬計算
            base_reward = 1000
            bonus_reward = int(monster["current_level"] * 5 + (monster["dice_talent"] / 10))
            is_great_success = random.random() < 0.15  # 15%の確率で大成功

            total_coins = base_reward + bonus_reward
            if is_great_success:
                total_coins = int(total_coins * 1.5)

            # 1. コイン付与
            profile = self.get_user_profile(user_id)
            new_balance = profile["balance"] + total_coins
            supabase.table("users").update({"balance": new_balance}).eq("user_id", user_id).execute()
            
            supabase.table("transaction_history").insert({
                "sender_id": "SYSTEM_WORK",
                "receiver_id": user_id,
                "amount": total_coins,
                "reason": "work_reward"
            }).execute()

            # 2. モンスターExp付与 (Exp +15)
            exp_gained = 15
            new_exp = monster["current_exp"] + exp_gained
            new_lv = monster["current_level"]
            leveled_up = False

            if new_exp >= 100 and new_lv < 30:
                new_lv += 1
                new_exp -= 100
                leveled_up = True

            supabase.table("monsters").update({
                "current_level": new_lv,
                "current_exp": new_exp
            }).eq("id", monster["id"]).execute()

            # 3. 派遣セッション削除
            supabase.table("work_sessions").delete().eq("id", session["id"]).execute()

            # 4. 成果発表Embed
            title_text = "🎉 **大成功！** お仕事結果報告" if is_great_success else "✅ お仕事結果報告"
            embed = discord.Embed(title=title_text, color=discord.Color.gold() if is_great_success else discord.Color.green())
            embed.set_thumbnail(url=monster["image_url"])
            embed.description = f"**{monster['name']}** が {action_text}！"

            embed.add_field(name="💰 獲得コイン", value=f"**+{total_coins}** ago", inline=True)
            
            exp_text = f"+{exp_gained} Exp"
            if leveled_up:
                exp_text += f" 🎉 **Lv. {new_lv} にアップ！**"
            embed.add_field(name="⭐ 獲得経験値", value=exp_text, inline=True)

            embed.set_footer(text=f"現在の所持金: {new_balance} ago")
            await interaction.followup.send(embed=embed)
            return

        # 2. 新規お仕事派遣（セッションが存在しない場合）
        res = supabase.table("monsters").select("*").eq("user_id", user_id).order("created_at", desc=True).execute()
        monsters = res.data

        if not monsters:
            await interaction.followup.send("お仕事に派遣できるモンスターを所持していません。`/appraise` で鑑定を行いましょう！")
            return

        view = MonsterWorkSelectView(user_id, monsters)
        await interaction.followup.send("💼 お仕事に派遣するモンスターを選んでください（5分後に結果を受け取れます）:", view=view)


async def setup(bot):
    await bot.add_cog(WorkCog(bot))
