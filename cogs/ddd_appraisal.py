import io
import json
import random
import os
import discord
from discord import app_commands
from discord.ext import commands
import google.generativeai as genai
from supabase import create_client, Client

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
genai.configure(api_key=GEMINI_API_KEY)

APPRAISAL_COST = 500

class AppraisalCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def check_box_capacity(self, user_id: str) -> tuple[bool, int, int]:
        user_res = supabase.table("users").select("max_box_slots").eq("user_id", user_id).execute()
        max_slots = user_res.data[0]["max_box_slots"] if user_res.data else 20
        
        count_res = supabase.table("monsters").select("id", count="exact").eq("user_id", user_id).execute()
        current_count = count_res.count if count_res.count is not None else 0
        
        return current_count < max_slots, current_count, max_slots

    def deduct_coins(self, user_id: str, amount: int, reason: str) -> bool:
        try:
            user_res = supabase.table("users").select("balance").eq("user_id", user_id).execute()
            if not user_res.data or user_res.data[0]["balance"] < amount:
                return False

            new_balance = user_res.data[0]["balance"] - amount
            update_res = (
                supabase.table("users")
                .update({"balance": new_balance})
                .eq("user_id", user_id)
                .gte("balance", amount)
                .execute()
            )
            if not update_res.data:
                return False

            supabase.table("transaction_history").insert({
                "sender_id": user_id,
                "receiver_id": "SYSTEM_APPRAISAL",
                "amount": amount,
                "reason": reason
            }).execute()
            return True
        except Exception as e:
            print(f"Transaction Error: {e}")
            return False

    async def generate_ai_monster(self, image_bytes: bytes, dice: dict) -> dict:
        model = genai.GenerativeModel("gemini-1.5-flash")
        prompt = f"""
あなたはゲーム「DDD (dot discord)」の鑑定AIです。
添付のドット絵を分析し、以下の条件・ダイス値に基づきJSON形式で出力してください。

【ダイス値】
- 初期Lv: {dice['level']}
- 才能ダイス(Lv.30最高個体値合計): {dice['talent']} (HP, attack, defense, sp_atk, sp_def, speed の6値の合計が【必ず {dice['talent']}】になるよう配分)
- AIダイス: {dice['ai']} (100に近いほど画像意図を汲んだ理想的なステータス配分)
- 能力ダイス: {dice['ability']} (100に近いほど技・特性が強力)

【ルール】
- 属性(element_type)は【"虚", "実", "正", "負", "無"】の5つから画像に最も合うものを1つ選択してください。
- 技は最大4つ。カテゴリーは physical / special / status から選択。

【出力形式(JSONのみ)】
{{
  "name": "名前(8文字以内)",
  "element_type": "属性",
  "characteristic": "特性名と効果説明",
  "description": "図鑑説明",
  "max_stats": {{
    "hp": 0, "attack": 0, "defense": 0, "sp_atk": 0, "sp_def": 0, "speed": 0
  }},
  "moves": [
    {{"name": "技名", "type": "属性", "category": "physical", "power": 40, "accuracy": 100, "description": "説明"}}
  ]
}}
"""
        image_part = {"mime_type": "image/png", "data": image_bytes}
        response = await model.generate_content_async([prompt, image_part])
        clean_json = response.text.strip().replace("```json", "").replace("```", "")
        return json.loads(clean_json)

    @app_commands.command(name="appraise", description="ドット絵画像を鑑定してAIモンスターを生成します（要500ago）")
    async def appraise(self, interaction: discord.Interaction, attachment: discord.Attachment, canvas_size: str = "8x8"):
        user_id = str(interaction.user.id)
        await interaction.response.defer()

        # ボックス容量確認
        can_add, current_cnt, max_slots = self.check_box_capacity(user_id)
        if not can_add:
            await interaction.followup.send(f"❌ ボックスが満杯です！（現在: {current_cnt}/{max_slots}匹）\n`/expand_box` で枠を拡張してください。")
            return

        # コイン消費
        if not self.deduct_coins(user_id, APPRAISAL_COST, "monster_appraisal"):
            await interaction.followup.send(f"❌ コインが不足しているか処理に失敗しました。（必要: {APPRAISAL_COST} ago）")
            return

        # ダイスロール
        dice = {
            "level": random.randint(1, 20),
            "talent": random.randint(100, 600),
            "ai": random.randint(1, 100),
            "ability": random.randint(1, 100)
        }

        image_bytes = await attachment.read()
        try:
            ai_data = await self.generate_ai_monster(image_bytes, dice)
        except Exception as e:
            await interaction.followup.send(f"⚠️ AI解析エラー: {e}")
            return

        # Storage保存
        file_path = f"monsters/{user_id}_{int(interaction.created_at.timestamp())}.png"
        supabase.storage.from_("dot_images").upload(file_path, image_bytes, {"content-type": "image/png"})
        public_url = supabase.storage.from_("dot_images").get_public_url(file_path)

        # DB追加
        record = {
            "user_id": user_id,
            "name": ai_data["name"],
            "image_url": public_url,
            "canvas_size": canvas_size,
            "element_type": ai_data["element_type"],
            "characteristic": ai_data["characteristic"],
            "dice_level": dice["level"],
            "dice_talent": dice["talent"],
            "dice_ai": dice["ai"],
            "dice_ability": dice["ability"],
            "current_level": dice["level"],
            "current_exp": 0,
            "max_hp": ai_data["max_stats"]["hp"],
            "max_attack": ai_data["max_stats"]["attack"],
            "max_defense": ai_data["max_stats"]["defense"],
            "max_sp_atk": ai_data["max_stats"]["sp_atk"],
            "max_sp_def": ai_data["max_stats"]["sp_def"],
            "max_speed": ai_data["max_stats"]["speed"],
            "moves": ai_data["moves"]
        }
        res = supabase.table("monsters").insert(record).execute()
        monster = res.data[0]

        # 結果送信
        embed = discord.Embed(title=f"✨ 鑑定完了：【{monster['element_type']}】{monster['name']}", description=ai_data["description"])
        embed.set_image(url=public_url)
        embed.add_field(name="🎲 ダイス結果", value=f"初期Lv: **{dice['level']}** | 最高個体値(Lv30): **{dice['talent']}**\nAI: **{dice['ai']}** | 能力: **{dice['ability']}**", inline=False)
        embed.add_field(name="📊 最高個体値(Lv.30)", value=f"HP:{monster['max_hp']} A:{monster['max_attack']} D:{monster['max_defense']} C:{monster['max_sp_atk']} S:{monster['max_sp_def']} SPD:{monster['max_speed']}", inline=False)
        embed.add_field(name="🌟 特性", value=monster["characteristic"], inline=False)
        await interaction.followup.send(embed=embed)

async def setup(bot):
    await bot.add_cog(AppraisalCog(bot))
