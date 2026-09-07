import asyncio
import logging
import random
from datetime import datetime, timedelta, timezone

import discord
from discord import app_commands
from discord.ext import commands
from supabase import Client, create_client

from .ddd_battle import add_experience

SUPABASE_URL = __import__("os").getenv("SUPABASE_URL")
SUPABASE_KEY = __import__("os").getenv("SUPABASE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

WORK_TYPES = {
    "normal": {"label": "通常作業", "duration": timedelta(minutes=5), "exp": 15},
    "training": {"label": "トレーニング", "duration": timedelta(hours=1), "exp": 500},
}

WORK_FLAVORS = {
    "虚": ["裏路地の依頼をこなした", "次元の歪みを調査した", "影の中で秘密の配達を行った"],
    "実": ["鉱山で鉱石を掘り出した", "建築現場を手伝った", "鍛冶屋の薪割りを助けた"],
    "正": ["街の警護巡回を行った", "迷子のペットを保護した", "遺跡の浄化作業を手伝った"],
    "負": ["珍しい素材を回収した", "モンスターの群れを追い払った", "毒沼の調査を行った"],
    "無": ["便利屋として雑用を引き受けた", "荷物の運搬を手伝った", "街の清掃活動に参加した"],
}


def parse_datetime(value: str) -> datetime:
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


class MonsterWorkSelectView(discord.ui.View):
    def __init__(self, cog, user_id: str, monsters: list, work_type: str):
        super().__init__(timeout=180)
        self.cog = cog
        self.user_id = user_id
        self.monsters = monsters
        self.work_type = work_type
        options = [
            discord.SelectOption(
                label=f"{monster['name']} (Lv.{monster['current_level']})"[:100],
                description=f"属性: {monster['element_type']} | 才能: {monster['dice_talent']}"[:100],
                value=str(monster["id"]),
            )
            for monster in monsters[:25]
        ]
        select = discord.ui.Select(
            placeholder="派遣するモンスターを選択",
            min_values=1,
            max_values=1,
            options=options,
        )
        select.callback = self.select_callback
        self.add_item(select)

    async def interaction_check(self, interaction):
        if str(interaction.user.id) != self.user_id:
            await interaction.response.send_message("この派遣画面は操作できません。", ephemeral=True)
            return False
        return True

    async def select_callback(self, interaction: discord.Interaction):
        selected_id = interaction.data["values"][0]
        monster = next((row for row in self.monsters if str(row["id"]) == selected_id), None)
        if not monster:
            await interaction.response.send_message("モンスターが見つかりませんでした。", ephemeral=True)
            return
        await interaction.response.defer()
        try:
            finish_time = await asyncio.to_thread(self.cog.start_work, self.user_id, monster["id"], self.work_type)
        except ValueError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            return
        except Exception:
            logging.getLogger(__name__).exception("DDD work start failed")
            await interaction.followup.send("派遣を開始できませんでした。もう一度試してください。", ephemeral=True)
            return
        self.stop()
        settings = WORK_TYPES[self.work_type]
        embed = discord.Embed(
            title=f"{settings['label']}を開始しました",
            description=f"**{monster['name']}** を派遣しました。完了後に `/ddd_work` を実行して結果を受け取ってください。",
            color=discord.Color.blue(),
        )
        if monster.get("image_url"):
            embed.set_thumbnail(url=monster["image_url"])
        embed.add_field(name="完了予定", value=f"<t:{int(finish_time.timestamp())}:R>")
        await interaction.edit_original_response(embed=embed, view=None)


class WorkCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def get_user_profile(self, user_id: str) -> dict:
        result = supabase.table("users").select("*").eq("user_id", user_id).execute()
        if result.data:
            return result.data[0]
        created = supabase.table("users").insert({"user_id": user_id, "balance": 0, "max_box_slots": 20}).execute()
        return created.data[0]

    def start_work(self, user_id: str, monster_id: str, work_type: str) -> datetime:
        if work_type not in WORK_TYPES:
            raise ValueError("作業種別が不正です。")
        current = supabase.table("work_sessions").select("id").eq("user_id", user_id).limit(1).execute()
        if current.data:
            raise ValueError("通常作業またはトレーニングがすでに進行中です。完了後に受け取ってください。")
        finish_time = datetime.now(timezone.utc) + WORK_TYPES[work_type]["duration"]
        try:
            inserted = supabase.table("work_sessions").insert({
                "user_id": user_id,
                "monster_id": monster_id,
                "work_type": work_type,
                "finish_time": finish_time.isoformat(),
            }).execute()
        except Exception as exc:
            if "duplicate" in str(exc).lower() or "unique" in str(exc).lower():
                raise ValueError("通常作業またはトレーニングがすでに進行中です。完了後に受け取ってください。") from exc
            raise
        if not inserted.data:
            raise RuntimeError("派遣セッションの作成に失敗しました。")
        return finish_time

    def finish_work(self, session: dict, monster: dict) -> dict:
        user_id = str(session["user_id"])
        work_type = session.get("work_type") if session.get("work_type") in WORK_TYPES else "normal"
        settings = WORK_TYPES[work_type]
        old_level = int(monster.get("current_level") or 1)
        old_exp = int(monster.get("current_exp") or 0)
        new_level, new_exp = add_experience(old_level, old_exp, settings["exp"], monster.get("breakthrough_stage", 0))

        coin_reward = 0
        chest_awarded = False
        if work_type == "normal":
            base_reward = 1000
            bonus_reward = int(old_level * 5 + int(monster.get("dice_talent") or 0) / 10)
            coin_reward = base_reward + bonus_reward
            if random.random() < 0.15:
                coin_reward = int(coin_reward * 1.5)
            chest_awarded = random.random() < 0.25

        finalized = supabase.rpc("ddd_finalize_work", {
            "p_session_id": session["id"],
            "p_user_id": user_id,
            "p_old_level": old_level,
            "p_old_exp": old_exp,
            "p_new_level": new_level,
            "p_new_exp": new_exp,
            "p_coins": coin_reward,
            "p_award_chest": chest_awarded,
        }).execute()
        if not finalized.data:
            raise RuntimeError("作業報酬を確定できませんでした。")
        return {
            "work_type": work_type,
            "exp": settings["exp"],
            "coins": coin_reward,
            "chest": chest_awarded,
            "old_level": old_level,
            "new_level": new_level,
            "new_exp": new_exp,
            "action": random.choice(WORK_FLAVORS.get(monster.get("element_type"), WORK_FLAVORS["無"])),
        }

    @app_commands.command(name="ddd_work", description="通常作業またはトレーニングへモンスターを派遣します")
    @app_commands.describe(work_type="派遣種別")
    @app_commands.choices(work_type=[
        app_commands.Choice(name="通常作業（5分・コイン、EXP、宝箱の可能性）", value="normal"),
        app_commands.Choice(name="トレーニング（1時間・EXP 500）", value="training"),
    ])
    async def ddd_work(self, interaction: discord.Interaction, work_type: str = "normal"):
        if work_type not in WORK_TYPES:
            await interaction.response.send_message("作業種別が不正です。", ephemeral=True)
            return
        user_id = str(interaction.user.id)
        await interaction.response.defer()
        sessions = await asyncio.to_thread(lambda: supabase.table("work_sessions").select("*, monsters(*)").eq("user_id", user_id).limit(1).execute())
        if sessions.data:
            session = sessions.data[0]
            monster = session.get("monsters")
            if not monster:
                await asyncio.to_thread(lambda: supabase.table("work_sessions").delete().eq("id", session["id"]).eq("user_id", user_id).execute())
                await interaction.followup.send("無効な派遣記録を整理しました。もう一度 `/ddd_work` を実行してください。", ephemeral=True)
                return
            finish_time = parse_datetime(session["finish_time"])
            now = datetime.now(timezone.utc)
            if now < finish_time:
                active_type = session.get("work_type") if session.get("work_type") in WORK_TYPES else "normal"
                embed = discord.Embed(
                    title=f"{WORK_TYPES[active_type]['label']}が進行中です",
                    description=f"**{monster['name']}** が派遣中です。通常作業とトレーニングは同時に実行できません。",
                    color=discord.Color.orange(),
                )
                if monster.get("image_url"):
                    embed.set_thumbnail(url=monster["image_url"])
                embed.add_field(name="完了予定", value=f"<t:{int(finish_time.timestamp())}:R>")
                await interaction.followup.send(embed=embed)
                return
            try:
                reward = await asyncio.to_thread(self.finish_work, session, monster)
            except Exception:
                logging.getLogger(__name__).exception("DDD work completion failed")
                await interaction.followup.send("報酬の確定に失敗しました。時間を置いて `/ddd_work` を再実行してください。", ephemeral=True)
                return
            embed = discord.Embed(title=f"{WORK_TYPES[reward['work_type']]['label']}の結果", color=discord.Color.green())
            if monster.get("image_url"):
                embed.set_thumbnail(url=monster["image_url"])
            embed.description = f"**{monster['name']}** が {reward['action']}。"
            if reward["coins"]:
                embed.add_field(name="獲得コイン", value=f"**+{reward['coins']:,}**", inline=True)
            level_text = f"**+{reward['exp']:,} EXP**"
            if reward["old_level"] != reward["new_level"]:
                level_text += f"\nLv.{reward['old_level']} → Lv.{reward['new_level']}"
            embed.add_field(name="獲得経験値", value=level_text, inline=True)
            if reward["chest"]:
                embed.add_field(name="宝箱", value="宝箱を1個獲得しました。`/ddd_open` で開封できます。", inline=False)
            await interaction.followup.send(embed=embed)
            return

        monsters = await asyncio.to_thread(lambda: supabase.table("monsters").select("*").eq("user_id", user_id).order("created_at", desc=True).limit(25).execute().data)
        if not monsters:
            await interaction.followup.send("派遣できるモンスターを所持していません。`/ddd_scout` でモンスターを迎えてください。")
            return
        settings = WORK_TYPES[work_type]
        description = "コイン・EXPを獲得し、25%の確率で宝箱も獲得します。" if work_type == "normal" else "コインと宝箱は獲得せず、EXPを500獲得します。"
        await interaction.followup.send(
            f"{settings['label']}を選択しました。所要時間は {int(settings['duration'].total_seconds() // 60)} 分です。{description}",
            view=MonsterWorkSelectView(self, user_id, monsters, work_type),
        )


async def setup(bot):
    await bot.add_cog(WorkCog(bot))
