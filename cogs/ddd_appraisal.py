import asyncio
import json
import logging
import os
import random
import uuid

import discord
from discord import app_commands
from discord.ext import commands
from supabase import Client, create_client

from .ddd_battle import SAFE_TRAITS

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

# ローカル運用用。必要に応じてこのリストへキーを追加する。
# 既存の直書きキーは互換性のため残し、429時は後続キーを順に試す。
GEMINI_API_KEYS = [
    "AQ.Ab8RN6LqsTEvK4h4ZW0u-Ni7qdxbytjUuXEJaZLDV3JG0Anygg",
    # "2つ目のGemini APIキーをここへ追記",
    os.getenv("GEMINI_API_KEY", ""),
    os.getenv("GEMINI_API_KEY_2", ""),
    os.getenv("GEMINI_API_KEY_3", ""),
]

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

SCOUT_COST = 500
ULTRA_SCOUT_COST = 10_000
LEGEND_SCOUT_COST = 100_000
VALID_ELEMENTS = ["虚", "実", "正", "負", "無"]
STAT_KEYS = ("hp", "attack", "defense", "sp_atk", "sp_def", "speed")

SCOUT_TIERS = {
    "normal": {
        "label": "通常スカウト",
        "cost": SCOUT_COST,
        "talent": (100, 600),
        "ai": (1, 100),
        "ability": (1, 100),
        "talent_cap": 600,
        "guarantee": "",
    },
    "ultra": {
        "label": "ウルトラスカウト",
        "cost": ULTRA_SCOUT_COST,
        "talent": (400, 600),
        "ai": (50, 100),
        "ability": (50, 100),
        "talent_cap": 600,
        "guarantee": "才能値400以上・AI適合50以上・能力補正50以上",
    },
    "legend": {
        "label": "レジェンドスカウト",
        "cost": LEGEND_SCOUT_COST,
        "talent": (500, 650),
        "ai": (70, 100),
        "ability": (70, 100),
        "talent_cap": 650,
        "guarantee": "才能値500以上・AI適合70以上・能力補正70以上・才能値上限650",
    },
}


def normal_roll(minimum, maximum, rng=None):
    """中央付近が出やすい整数ロール。"""
    if minimum > maximum:
        raise ValueError("minimum must not exceed maximum")
    rng = rng or random
    mean = (minimum + maximum) / 2
    stddev = (maximum - minimum) / 6 or 1
    return max(minimum, min(maximum, round(rng.gauss(mean, stddev))))


def score_bar(value, maximum):
    score = max(0, min(100, round(value / maximum * 100)))
    return f"`{'█' * (score // 10)}{'░' * (10 - score // 10)}` {score}/100"


def unique_api_keys() -> list[str]:
    """空値と重複を除いたGeminiキーを定義順で返す。"""
    keys: list[str] = []
    for key in GEMINI_API_KEYS:
        key = str(key or "").strip()
        if key and key not in keys:
            keys.append(key)
    return keys


def is_rate_limited(error: Exception) -> bool:
    status = getattr(error, "status_code", None) or getattr(error, "code", None)
    text = str(error).lower()
    return status == 429 or "429" in text or "resource_exhausted" in text or "rate limit" in text


class ScoutDecisionView(discord.ui.View):
    """スカウト結果をボックスへ登録・見送り・再抽選する画面。"""

    def __init__(self, cog, user_id, record, file_path, dice, stats, tier, attachment, box_text):
        super().__init__(timeout=180)
        self.cog = cog
        self.user_id = user_id
        self.record = record
        self.file_path = file_path
        self.dice = dice
        self.stats = stats
        self.tier = tier
        self.attachment = attachment
        self.box_text = box_text
        self.done = False

    @property
    def tier_data(self):
        return SCOUT_TIERS[self.tier]

    def preview_embed(self):
        talent_cap = self.tier_data["talent_cap"]
        embed = discord.Embed(
            title=f"DDD {self.tier_data['label']} | 【{self.record['element_type']}】{self.record['name']}",
            description="個体をボックスへ迎え入れるか、見送るか、再抽選するかを選んでください。",
            color=discord.Color.gold(),
        )
        embed.set_image(url=self.record["image_url"])
        embed.add_field(
            name="個体ポテンシャル",
            value=(f"初期レベル **{self.dice['level']} / 20**  {score_bar(self.dice['level'], 20)}\n"
                   f"才能値 **{self.dice['talent']} / {talent_cap}**  {score_bar(self.dice['talent'], talent_cap)}\n"
                   f"AI適合 **{self.dice['ai']} / 100**  {score_bar(self.dice['ai'], 100)}\n"
                   f"能力補正 **{self.dice['ability']} / 100**  {score_bar(self.dice['ability'], 100)}"),
            inline=False,
        )
        embed.add_field(
            name="能力配分",
            value=(f"**HP**: {self.stats['hp']} | **攻撃**: {self.stats['attack']} | **防御**: {self.stats['defense']}\n"
                   f"**特攻**: {self.stats['sp_atk']} | **特防**: {self.stats['sp_def']} | **素早さ**: {self.stats['speed']}"),
            inline=False,
        )
        embed.add_field(name="特性", value=self.record["characteristic"], inline=False)
        moves_text = "\n".join(
            f"・**{m['name']}** [{m['type']}] ({'物理' if m['category'] == 'physical' else '特殊' if m['category'] == 'special' else '変化'} / 威力:{m['power'] if m['power'] > 0 else '-'})"
            for m in self.record["moves"]
        )
        embed.add_field(name="修得技", value=moves_text, inline=False)
        embed.set_footer(text=f"必要コイン: {self.tier_data['cost']} | ボックス: {self.box_text}")
        return embed

    async def interaction_check(self, interaction):
        if str(interaction.user.id) != self.user_id or self.done:
            await interaction.response.send_message("このスカウト結果は操作済み、またはあなたのものではありません。", ephemeral=True)
            return False
        return True

    async def cleanup_file(self):
        try:
            await asyncio.to_thread(lambda: supabase.storage.from_("dot_images").remove([self.file_path]))
        except Exception:
            logging.getLogger(__name__).warning("Could not clean up unselected DDD image", exc_info=True)

    @discord.ui.button(label="スカウトしてボックスへ", style=discord.ButtonStyle.success)
    async def scout(self, interaction, button):
        self.done = True
        await interaction.response.defer()
        try:
            result = await asyncio.to_thread(lambda: supabase.table("monsters").insert(self.record).execute())
            if not result.data:
                raise RuntimeError("登録結果が空です")
            monster = result.data[0]
        except Exception:
            self.done = False
            await interaction.followup.send("ボックスへの登録に失敗しました。", ephemeral=True)
            return
        self.stop()
        embed = self.preview_embed()
        embed.description = "ボックスへ迎え入れました。"
        embed.set_footer(text=f"ボックス登録済み | モンスターID: {monster['id']}")
        await interaction.edit_original_response(embed=embed, view=None)

    @discord.ui.button(label="再抽選", style=discord.ButtonStyle.primary)
    async def reload(self, interaction, button):
        self.done = True
        self.stop()
        await interaction.response.defer()
        await self.cleanup_file()
        await interaction.edit_original_response(content="再抽選中です。", embed=None, view=None)
        await self.cog._run_scout(interaction, self.attachment, self.tier, already_deferred=True)

    @discord.ui.button(label="今回は見送る", style=discord.ButtonStyle.secondary)
    async def decline(self, interaction, button):
        self.done = True
        await interaction.response.defer()
        await self.cleanup_file()
        self.stop()
        embed = self.preview_embed()
        embed.description = "スカウトを見送りました。個体はボックスへ登録されません。"
        await interaction.edit_original_response(embed=embed, view=None)

    async def on_timeout(self):
        if self.done:
            return
        self.done = True
        await self.cleanup_file()
        for child in self.children:
            child.disabled = True


class AppraisalCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def get_user_profile(self, user_id: str) -> dict:
        res = supabase.table("users").select("*").eq("user_id", user_id).execute()
        if res.data:
            return res.data[0]
        new_user = {"user_id": user_id, "balance": 0, "max_box_slots": 20}
        inserted = supabase.table("users").insert(new_user).execute()
        return inserted.data[0]

    def check_box_capacity(self, user_id: str, max_slots: int) -> tuple[bool, int]:
        count_res = supabase.table("monsters").select("id", count="exact").eq("user_id", user_id).execute()
        current_count = count_res.count if count_res.count is not None else 0
        return current_count < max_slots, current_count

    def deduct_coins_transaction(self, user_id: str, amount: int, reason: str) -> bool:
        try:
            user_res = supabase.table("users").select("balance").eq("user_id", user_id).execute()
            if not user_res.data or int(user_res.data[0].get("balance") or 0) < amount:
                return False
            balance = int(user_res.data[0].get("balance") or 0)
            updated = (supabase.table("users").update({"balance": balance - amount}).eq("user_id", user_id)
                       .eq("balance", balance).gte("balance", amount).execute())
            if not updated.data:
                return False
            supabase.table("transaction_history").insert({
                "sender_id": user_id, "receiver_id": "SYSTEM_SCOUT", "amount": amount, "reason": reason
            }).execute()
            return True
        except Exception:
            logging.getLogger(__name__).exception("DDD scout debit failed")
            return False

    def refund_coins(self, user_id: str, amount: int, reason: str):
        try:
            user_res = supabase.table("users").select("balance").eq("user_id", user_id).execute()
            if not user_res.data:
                return
            balance = int(user_res.data[0].get("balance") or 0)
            updated = (supabase.table("users").update({"balance": balance + amount}).eq("user_id", user_id)
                       .eq("balance", balance).execute())
            if updated.data:
                supabase.table("transaction_history").insert({
                    "sender_id": "SYSTEM_REFUND", "receiver_id": user_id, "amount": amount, "reason": reason
                }).execute()
        except Exception:
            logging.getLogger(__name__).exception("DDD scout refund failed")

    def normalize_stats(self, stats: dict, target_talent: int, talent_cap: int = 600) -> dict:
        """個体値合計をターゲットと厳密に一致させる。"""
        target_talent = max(60, min(talent_cap, int(target_talent)))
        cleaned = {}
        for key in STAT_KEYS:
            try:
                cleaned[key] = max(10, int(stats.get(key, 20)))
            except (TypeError, ValueError):
                cleaned[key] = 20
        cleaned["hp"] = min(220, cleaned["hp"])
        current_sum = sum(cleaned.values())
        scaled = {key: max(10, int(round(cleaned[key] / current_sum * target_talent))) for key in STAT_KEYS}
        scaled["hp"] = min(220, scaled["hp"])
        difference = target_talent - sum(scaled.values())
        if difference > 0:
            hp_add = min(difference, 220 - scaled["hp"])
            scaled["hp"] += hp_add
            difference -= hp_add
            if difference:
                scaled[max(STAT_KEYS, key=scaled.get)] += difference
        else:
            remaining = -difference
            while remaining:
                candidates = [key for key in STAT_KEYS if scaled[key] > 10]
                if not candidates:
                    break
                key = max(candidates, key=scaled.get)
                amount = min(remaining, scaled[key] - 10)
                scaled[key] -= amount
                remaining -= amount
        return scaled

    async def generate_ai_monster(self, image_bytes: bytes, dice: dict, talent_cap: int) -> dict:
        keys = unique_api_keys()
        if not keys:
            raise RuntimeError("鑑定を現在利用できません。")
        from google import genai
        from google.genai import types

        prompt = f"""
あなたはゲーム「DDD」のモンスター鑑定士です。
添付画像を読み取り、以下の条件に従ってJSONだけを出力してください。

【個体条件】
- 初期Lv: {dice['level']}
- 才能値: {dice['talent']}（6能力の合計）
- AI適合: {dice['ai']}
- 能力補正: {dice['ability']}

【厳格ルール】
1. element_typeは「虚」「実」「正」「負」「無」から最も適した1つだけ選ぶ。
2. movesは必ず3つ。categoryは「physical」「special」「status」のいずれか。
3. characteristicは図鑑に表示する短い文章だけを書く。

【JSON形式】
{{
  "name": "名前(8文字以内)",
  "element_type": "属性",
  "characteristic": "特性名：効果の簡潔な説明",
  "max_stats": {{"hp": 0, "attack": 0, "defense": 0, "sp_atk": 0, "sp_def": 0, "speed": 0}},
  "moves": [{{"name": "技名", "type": "属性", "category": "physical", "power": 40, "accuracy": 100, "description": "説明"}}]
}}
"""
        rate_errors = []
        for api_key in keys:
            try:
                async with genai.Client(api_key=api_key).aio as client:
                    response = await client.models.generate_content(
                        model=os.getenv("DDD_GEMINI_MODEL", "gemini-2.5-flash"),
                        contents=[prompt, types.Part.from_bytes(data=image_bytes, mime_type="image/png")],
                    )
                raw_text = response.text.strip().replace("```json", "").replace("```", "")
                data = json.loads(raw_text)
                break
            except Exception as exc:
                if is_rate_limited(exc):
                    rate_errors.append(exc)
                    continue
                raise
        else:
            raise RuntimeError("すべての鑑定キーがレート制限中です。少し時間を置いて再試行してください。") from (rate_errors[-1] if rate_errors else None)

        if data.get("element_type") not in VALID_ELEMENTS:
            data["element_type"] = "無"
        data["name"] = str(data.get("name") or "無名の相棒")[:20]
        data["characteristic"] = str(data.get("characteristic") or "標準")[:60]
        data["max_stats"] = self.normalize_stats(data.get("max_stats", {}), dice["talent"], talent_cap)

        fallback_moves = [
            {"name": "たいあたり", "type": "無", "category": "physical", "power": 40, "accuracy": 100, "description": "体当たり攻撃"},
            {"name": "かげうち", "type": "無", "category": "physical", "power": 40, "accuracy": 100, "description": "素早い攻撃"},
            {"name": "回復", "type": "無", "category": "status", "power": 0, "accuracy": 100, "effect": "heal", "description": "HPを回復"},
        ]
        source_moves = data.get("moves") if isinstance(data.get("moves"), list) else []
        valid_moves = []
        for index in range(3):
            move = source_moves[index] if index < len(source_moves) and isinstance(source_moves[index], dict) else fallback_moves[index]
            category = move.get("category") if move.get("category") in ("physical", "special", "status") else fallback_moves[index]["category"]
            try:
                power = int(move.get("power", 40)) if category != "status" else 0
            except (TypeError, ValueError):
                power = 40 if category != "status" else 0
            try:
                accuracy = max(50, min(100, int(move.get("accuracy", 100))))
            except (TypeError, ValueError):
                accuracy = 100
            valid_moves.append({
                "name": str(move.get("name") or fallback_moves[index]["name"])[:10],
                "type": move.get("type") if move.get("type") in VALID_ELEMENTS else data["element_type"],
                "category": category,
                "power": max(0, min(140, power)),
                "accuracy": accuracy,
                "description": str(move.get("description") or fallback_moves[index]["description"])[:30],
                **({"effect": "heal"} if category == "status" and str(move.get("name")) == "回復" else {}),
            })
        data["moves"] = valid_moves
        trait_ids = tuple(SAFE_TRAITS)
        data["trait_id"] = trait_ids[dice["ability"] % len(trait_ids)]
        return data

    @staticmethod
    def make_dice(tier: str) -> dict:
        data = SCOUT_TIERS[tier]
        return {
            "level": normal_roll(1, 20),
            "talent": normal_roll(*data["talent"]),
            "ai": normal_roll(*data["ai"]),
            "ability": normal_roll(*data["ability"]),
        }

    async def _run_scout(self, interaction: discord.Interaction, attachment: discord.Attachment, tier: str, already_deferred: bool = False):
        if tier not in SCOUT_TIERS:
            if not already_deferred:
                await interaction.response.send_message("スカウト種別が不正です。", ephemeral=True)
            else:
                await interaction.followup.send("スカウト種別が不正です。", ephemeral=True)
            return
        if not already_deferred:
            await interaction.response.defer()
        user_id = str(interaction.user.id)
        tier_data = SCOUT_TIERS[tier]
        profile = await asyncio.to_thread(self.get_user_profile, user_id)
        can_add, current_count = await asyncio.to_thread(self.check_box_capacity, user_id, int(profile["max_box_slots"]))
        if not can_add:
            await interaction.followup.send(f"ボックスが満杯です（現在: {current_count}/{profile['max_box_slots']}匹）。")
            return
        if not await asyncio.to_thread(self.deduct_coins_transaction, user_id, tier_data["cost"], f"ddd_scout_{tier}"):
            await interaction.followup.send(f"コインが不足しています（所持: {profile.get('balance', 0)} / 必要: {tier_data['cost']}）。")
            return

        try:
            image_bytes = await attachment.read()
            dice = self.make_dice(tier)
            ai_data = await self.generate_ai_monster(image_bytes, dice, tier_data["talent_cap"])
        except Exception:
            await asyncio.to_thread(self.refund_coins, user_id, tier_data["cost"], f"ddd_scout_{tier}_failed_refund")
            logging.getLogger(__name__).exception("DDD scout failed")
            await interaction.followup.send("スカウトに失敗したため、コインを返還しました。")
            return

        allowed_content_types = {"image/png", "image/jpeg", "image/webp", "image/gif"}
        content_type = attachment.content_type if attachment.content_type in allowed_content_types else "image/png"
        extension = "." + content_type.split("/", 1)[1]
        file_path = f"monsters/{user_id}/{uuid.uuid4().hex}{extension}"
        try:
            await asyncio.to_thread(lambda: supabase.storage.from_("dot_images").upload(
                file_path, image_bytes, {"content-type": content_type, "upsert": "false"}
            ))
            public_url = await asyncio.to_thread(lambda: supabase.storage.from_("dot_images").get_public_url(file_path))
        except Exception:
            await asyncio.to_thread(self.refund_coins, user_id, tier_data["cost"], f"ddd_scout_{tier}_upload_failed_refund")
            logging.getLogger(__name__).exception("DDD scout image upload failed")
            await interaction.followup.send("画像を保存できなかったため、コインを返還しました。")
            return

        stats = ai_data["max_stats"]
        record = {
            "user_id": user_id,
            "name": ai_data["name"],
            "image_url": public_url,
            "element_type": ai_data["element_type"],
            "characteristic": ai_data["characteristic"],
            "trait_id": ai_data["trait_id"],
            "dice_level": dice["level"],
            "dice_talent": dice["talent"],
            "dice_ai": dice["ai"],
            "dice_ability": dice["ability"],
            "current_level": dice["level"],
            "current_exp": 0,
            "breakthrough_stage": 0,
            "max_hp": stats["hp"],
            "max_attack": stats["attack"],
            "max_defense": stats["defense"],
            "max_sp_atk": stats["sp_atk"],
            "max_sp_def": stats["sp_def"],
            "max_speed": stats["speed"],
            "moves": ai_data["moves"],
        }
        view = ScoutDecisionView(
            self, user_id, record, file_path, dice, stats, tier, attachment,
            f"未登録（{current_count}/{profile['max_box_slots']}）",
        )
        embed = view.preview_embed()
        if tier_data["guarantee"]:
            embed.description = f"{tier_data['guarantee']}。個体をボックスへ迎え入れるか、見送るか、再抽選するかを選んでください。"
        await interaction.followup.send(embed=embed, view=view)

    @app_commands.command(name="ddd_scout", description="画像からモンスターをスカウトします")
    @app_commands.describe(attachment="スカウトする画像", scout_type="通常またはウルトラ")
    @app_commands.choices(scout_type=[
        app_commands.Choice(name="通常スカウト（500コイン）", value="normal"),
        app_commands.Choice(name="ウルトラスカウト（10000コイン）", value="ultra"),
    ])
    async def scout(self, interaction: discord.Interaction, attachment: discord.Attachment, scout_type: str = "normal"):
        await self._run_scout(interaction, attachment, scout_type)

    @app_commands.command(name="ddd_legend_scout", description="100000コインで高品質なモンスターをスカウトします")
    @app_commands.describe(attachment="スカウトする画像")
    async def legend_scout(self, interaction: discord.Interaction, attachment: discord.Attachment):
        await self._run_scout(interaction, attachment, "legend")


async def setup(bot):
    await bot.add_cog(AppraisalCog(bot))
