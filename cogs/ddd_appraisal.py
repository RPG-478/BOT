import io
import json
import random
import os
import uuid
import discord
from discord import app_commands
from discord.ext import commands
import google.generativeai as genai
from supabase import create_client, Client

SUPABASE_URL = os.getenv("SUPABASE_URL")
# Storage.objects のRLSをバイパスするため、BotではService Role Keyを優先する。
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
genai.configure(api_key=GEMINI_API_KEY)

APPRAISAL_COST = 500  # 基本鑑定コスト
VALID_ELEMENTS = ["虚", "実", "正", "負", "無"]

class AppraisalCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # --- DB・プロファイル管理 ---
    def get_user_profile(self, user_id: str) -> dict:
        res = supabase.table("users").select("*").eq("user_id", user_id).execute()
        if res.data:
            return res.data[0]
        
        # 初回利用時の新規プロファイル登録
        new_user = {
            "user_id": user_id,
            "balance": 0,
            "max_box_slots": 20,
            "unlocked_palettes": ["8x8"]
        }
        inserted = supabase.table("users").insert(new_user).execute()
        return inserted.data[0]

    def check_box_capacity(self, user_id: str, max_slots: int) -> tuple[bool, int]:
        count_res = supabase.table("monsters").select("id", count="exact").eq("user_id", user_id).execute()
        current_count = count_res.count if count_res.count is not None else 0
        return current_count < max_slots, current_count

    # --- トランザクション処理 (ago coin) ---
    def deduct_coins_transaction(self, user_id: str, amount: int, reason: str) -> bool:
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
            print(f"[Transaction Error] {e}")
            return False

    def refund_coins(self, user_id: str, amount: int, reason: str):
        """エラー時の自動返金処理"""
        try:
            user_res = supabase.table("users").select("balance").eq("user_id", user_id).execute()
            if user_res.data:
                new_bal = user_res.data[0]["balance"] + amount
                supabase.table("users").update({"balance": new_bal}).eq("user_id", user_id).execute()
                supabase.table("transaction_history").insert({
                    "sender_id": "SYSTEM_REFUND",
                    "receiver_id": user_id,
                    "amount": amount,
                    "reason": reason
                }).execute()
        except Exception as e:
            print(f"[Refund Error] {e}")

    # --- AI・ステータス精密補正ロジック ---
    def normalize_stats(self, stats: dict, target_talent: int) -> dict:
        """AIが出力したステータスの合計値を才能ダイス（target_talent）と厳密に一致させる"""
        keys = ["hp", "attack", "defense", "sp_atk", "sp_def", "speed"]
        cleaned = {k: max(10, int(stats.get(k, 20))) for k in keys}
        
        current_sum = sum(cleaned.values())
        if current_sum == target_talent:
            return cleaned

        # 比率を崩さず再割り振り
        scaled = {k: max(10, int(round((cleaned[k] / current_sum) * target_talent))) for k in keys}
        
        # 端数調整（余りを最も大きいステータスに加算）
        diff = target_talent - sum(scaled.values())
        if diff != 0:
            max_k = max(scaled, key=scaled.get)
            scaled[max_k] = max(10, scaled[max_k] + diff)

        return scaled

    async def generate_ai_monster(self, image_bytes: bytes, dice: dict) -> dict:
        model = genai.GenerativeModel("gemini-3.5-flash-lite")
        
        prompt = f"""
あなたはゲーム「DDD (dot discord)」の鑑定AIです。
添付されたドット絵画像の特徴を分析し、条件に基づきJSONフォーマットのみで出力してください。

【ダイスパラメータ】
- 初期Lv: {dice['level']}
- 才能ダイス (Lv.30最高個体値合計): {dice['talent']}
- AIダイス: {dice['ai']} (100に近いほど意図を汲んだ理想的なステータス配分)
- 能力ダイス: {dice['ability']} (100に近いほど技・特性が強力)

【厳格ルール】
1. 属性(element_type)は以下から【最も適した1つ】のみ選択: ["虚", "実", "正", "負", "無"]
2. 技(moves)は**必ず3つ**。categoryは "physical", "special", "status" のいずれか。技の順序をスロット1〜3として保存する。

【出力フォーマット (JSON)】
{{
  "name": "名前(8文字以内)",
  "element_type": "属性",
  "characteristic": "特性名：効果の簡潔な説明",
  "description": "図鑑説明文(40文字以内)",
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
        
        raw_text = response.text.strip().replace("```json", "").replace("```", "")
        data = json.loads(raw_text)

        # 属性バリデーション
        if data.get("element_type") not in VALID_ELEMENTS:
            data["element_type"] = "無"

        # ステータス合計の補正
        data["max_stats"] = self.normalize_stats(data.get("max_stats", {}), dice["talent"])

        # 技データの整形（必ず3枠）
        fallback_moves = [
            {"name": "たいあたり", "type": "無", "category": "physical", "power": 40, "accuracy": 100, "description": "体当たり攻撃"},
            {"name": "まもる", "type": "無", "category": "status", "power": 0, "accuracy": 100, "description": "身を守る"},
            {"name": "でんこうせっか", "type": "無", "category": "physical", "power": 40, "accuracy": 100, "description": "素早い攻撃"},
        ]
        source_moves = data.get("moves", []) if isinstance(data.get("moves", []), list) else []
        valid_moves = []
        for idx in range(3):
            m = source_moves[idx] if idx < len(source_moves) and isinstance(source_moves[idx], dict) else fallback_moves[idx]
            category = m.get("category") if m.get("category") in ["physical", "special", "status"] else fallback_moves[idx]["category"]
            try:
                power = int(m.get("power", 40)) if category != "status" else 0
            except (TypeError, ValueError):
                power = 40 if category != "status" else 0
            try:
                accuracy = max(1, min(100, int(m.get("accuracy", 100))))
            except (TypeError, ValueError):
                accuracy = 100
            valid_moves.append({
                "name": str(m.get("name", fallback_moves[idx]["name"]))[:10],
                "type": m.get("type") if m.get("type") in VALID_ELEMENTS else data["element_type"],
                "category": category,
                "power": power,
                "accuracy": accuracy,
                "description": str(m.get("description", fallback_moves[idx]["description"]))[:30]
            })

        data["moves"] = valid_moves
        return data

    # --- Slash Command ---
    @app_commands.command(name="appraise", description="ドット絵画像を鑑定してAIモンスターを生成します（要500ago）")
    @app_commands.describe(attachment="鑑定するドット絵画像", canvas_size="使用したパレットサイズ")
    @app_commands.choices(canvas_size=[
        app_commands.Choice(name="8x8", value="8x8"),
        app_commands.Choice(name="16x16", value="16x16"),
        app_commands.Choice(name="64x64", value="64x64"),
        app_commands.Choice(name="128x128", value="128x128")
    ])
    async def appraise(self, interaction: discord.Interaction, attachment: discord.Attachment, canvas_size: str = "8x8"):
        user_id = str(interaction.user.id)
        await interaction.response.defer()

        # 1. パレット解放の確認
        profile = self.get_user_profile(user_id)
        unlocked_palettes = profile.get("unlocked_palettes", ["8x8"])
        if canvas_size not in unlocked_palettes:
            await interaction.followup.send(
                f"🔒 **{canvas_size}** パレットは解放されていません！（所持パレット: {', '.join(unlocked_palettes)}）",
                ephemeral=True
            )
            return

        # 2. ボックス容量確認
        can_add, current_cnt = self.check_box_capacity(user_id, profile["max_box_slots"])
        if not can_add:
            await interaction.followup.send(f"❌ **ボックスが満杯です！**（現在: {current_cnt}/{profile['max_box_slots']}匹）\n`/expand_box` で枠を拡張してください。")
            return

        # 3. コイン決済
        if not self.deduct_coins_transaction(user_id, APPRAISAL_COST, reason="monster_appraisal"):
            await interaction.followup.send(f"❌ **コインが不足しています！**（所持金: {profile['balance']} ago / 必要: {APPRAISAL_COST} ago）")
            return

        # 4. 厳選ダイスロール
        dice = {
            "level": random.randint(1, 20),
            "talent": random.randint(100, 600),
            "ai": random.randint(1, 100),
            "ability": random.randint(1, 100)
        }

        # 5. AI解析（エラー時は全額返金）
        image_bytes = await attachment.read()
        try:
            ai_data = await self.generate_ai_monster(image_bytes, dice)
        except Exception as e:
            self.refund_coins(user_id, APPRAISAL_COST, reason="appraisal_failed_refund")
            await interaction.followup.send(f"⚠️ **AI鑑定に失敗したためコインを返還しました。**\n詳細: `{e}`")
            return

        # 6. 画像保存（エラー時は全額返金）
        # 同一ユーザーが同じ秒に複数回鑑定しても画像が衝突しないようUUIDを付与する。
        file_ext = ".png"
        allowed_content_types = {"image/png", "image/jpeg", "image/webp", "image/gif"}
        content_type = attachment.content_type if attachment.content_type in allowed_content_types else "image/png"
        if content_type != "image/png":
            file_ext = "." + content_type.split("/", 1)[1]
        file_path = f"monsters/{user_id}/{uuid.uuid4().hex}{file_ext}"
        try:
            supabase.storage.from_("dot_images").upload(file_path, image_bytes, {"content-type": content_type, "upsert": "false"})
            public_url = supabase.storage.from_("dot_images").get_public_url(file_path)
        except Exception as e:
            self.refund_coins(user_id, APPRAISAL_COST, reason="upload_failed_refund")
            await interaction.followup.send(f"⚠️ **画像保存に失敗したためコインを返還しました。**\n詳細: `{e}`")
            return

        # 7. DB追加
        stats = ai_data["max_stats"]
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
            "max_hp": stats["hp"],
            "max_attack": stats["attack"],
            "max_defense": stats["defense"],
            "max_sp_atk": stats["sp_atk"],
            "max_sp_def": stats["sp_def"],
            "max_speed": stats["speed"],
            "moves": ai_data["moves"]
        }
        res = supabase.table("monsters").insert(record).execute()
        monster = res.data[0]

        # 8. 結果Embedの表示
        embed = discord.Embed(
            title=f"✨ 鑑定完了：【{monster['element_type']}】{monster['name']}",
            description=ai_data["description"],
            color=discord.Color.gold()
        )
        embed.set_image(url=public_url)
        embed.add_field(
            name="🎲 厳選ダイス結果",
            value=f"初期Lv: **{dice['level']}** / 30 | 才能(Lv30最高個体値): **{dice['talent']}**\nAI判定: **{dice['ai']}** | 能力補正: **{dice['ability']}**",
            inline=False
        )
        embed.add_field(
            name="📊 最高個体値 (Lv.30時)",
            value=f"**HP**: {stats['hp']} | **攻撃**: {stats['attack']} | **防御**: {stats['defense']}\n**特攻**: {stats['sp_atk']} | **特防**: {stats['sp_def']} | **素早さ**: {stats['speed']}",
            inline=False
        )
        embed.add_field(name="🌟 特性", value=monster["characteristic"], inline=False)
        
        moves_text = "\n".join([
            f"・**{m['name']}** [{m['type']}] ({'物理' if m['category']=='physical' else '特殊' if m['category']=='special' else '変化'} / 威力:{m['power'] if m['power']>0 else '-'})"
            for m in monster["moves"]
        ])
        embed.add_field(name="⚔️ 修得技", value=moves_text, inline=False)
        embed.set_footer(text=f"消費: {APPRAISAL_COST} ago | パレット: {canvas_size} | ボックス: {current_cnt + 1}/{profile['max_box_slots']}")

        await interaction.followup.send(embed=embed)

async def setup(bot):
    await bot.add_cog(AppraisalCog(bot))
