import io
import asyncio
import logging
import struct
import zlib
from collections import defaultdict
import json
import random
import os
import uuid
import discord
from discord import app_commands
from discord.ext import commands
from supabase import create_client, Client
from .ddd_battle import SAFE_TRAITS

SUPABASE_URL = os.getenv("SUPABASE_URL")
# 既存環境ではSUPABASE_URLとSUPABASE_KEYを使用する。
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
GEMINI_API_KEY = "AQ.Ab8RN6LqsTEvK4h4ZW0u-Ni7qdxbytjUuXEJaZLDV3JG0Anygg"

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

APPRAISAL_COST = 500  # 基本鑑定コスト
ULTRA_SCOUT_COST = 10000  # 最低値保証付きウルトラスカウト
VALID_ELEMENTS = ["虚", "実", "正", "負", "無"]

# Free creator: deterministic, equal-budget characters; no AI requests or coin debit.
PIXEL_TEMPLATES = {
    "スライム": "00000000/00011000/00122100/01222210/01233210/01222210/00111100/00000000",
    "ナイト": "00111100/01222210/01233210/00122100/01122110/12122121/00111100/00100100",
    "ドラゴン": "01000010/01200210/01211210/00133100/01222210/12222221/00122100/01100110",
    "ゴースト": "00111100/01222210/12322321/12222221/12233221/12222221/12122121/01011010",
    "ロボット": "00011000/01111110/01222210/01322310/01111110/11222211/00111100/01100110",
    "白紙": "/".join(["00000000"] * 8),
}
PIXEL_COLORS = {
    "ミント": ((69, 225, 173), (216, 255, 244)),
    "サクラ": ((246, 119, 164), (255, 223, 234)),
    "アクア": ((82, 167, 255), (209, 238, 255)),
    "ゴールド": ((247, 190, 62), (255, 243, 197)),
    "ラベンダー": ((161, 133, 247), (239, 228, 255)),
}
# All archetypes total 360, so artistic complexity never grants a power advantage.
ARCHETYPES = {
    "バランス": (80, 60, 55, 60, 55, 50),
    "アタッカー": (70, 95, 45, 45, 40, 65),
    "ガーディアン": (100, 50, 85, 40, 60, 25),
    "メイジ": (65, 35, 40, 100, 65, 55),
    "スピード": (65, 65, 40, 65, 40, 85),
}


def normal_roll(minimum, maximum, rng=None):
    """中央付近が出やすい整数ロール。上下限外の値は範囲内に丸める。"""
    if minimum > maximum:
        raise ValueError("minimum must not exceed maximum")
    rng = rng or random
    mean = (minimum + maximum) / 2
    stddev = (maximum - minimum) / 6 or 1
    return max(minimum, min(maximum, round(rng.gauss(mean, stddev))))


def score_bar(value, maximum):
    score = max(0, min(100, round(value / maximum * 100)))
    return f"`{'█' * (score // 10)}{'░' * (10 - score // 10)}` {score}/100"


def parse_pixels(text):
    rows = text.strip().replace("/", "\n").splitlines()
    if len(rows) != 8 or any(len(row) != 8 or set(row) - set("0123") for row in rows):
        raise ValueError("0〜3だけで、各行8文字・全8行にしてください。0=透明、1=輪郭、2=本体、3=光。")
    return rows


def pixel_png(rows, color="ミント", scale=32):
    """Encode nearest-neighbour RGBA pixels with only Python's standard library."""
    rows = parse_pixels("\n".join(rows))
    if not 1 <= scale <= 64:
        raise ValueError("scale must be between 1 and 64")
    base, light = PIXEL_COLORS[color]
    palette = [(0, 0, 0, 0), (28, 31, 53, 255), (*base, 255), (*light, 255)]
    raw = b"".join((b"\0" + b"".join(bytes(palette[int(c)]) * scale for c in row)) * scale for row in rows)
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xffffffff)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 8 * scale, 8 * scale, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def creator_record(user_id, name, element, style, image_url):
    stats = ARCHETYPES[style]
    special = style == "メイジ"
    return {
        "user_id": user_id, "name": name, "image_url": image_url, "canvas_size": "8x8", "trait_id": "none",
        "element_type": element, "characteristic": "創作の魂：自分の手で生まれた唯一の相棒",
        "dice_level": 5, "dice_talent": 360, "dice_ai": 1, "dice_ability": 50,
        "current_level": 5, "current_exp": 0,
        **dict(zip(("max_hp", "max_attack", "max_defense", "max_sp_atk", "max_sp_def", "max_speed"), stats)),
        "moves": [
            {"name": "ドットバースト" if special else "ピクセルストライク", "type": element,
             "category": "special" if special else "physical", "power": 45, "accuracy": 100,
             "description": "自分の属性で安定した一撃"},
            {"name": "オーバードライブ", "type": element,
             "category": "special" if special else "physical", "power": 75, "accuracy": 80,
             "description": "命中80の大技"},
            {"name": "回復", "type": "無", "category": "status", "power": 0, "accuracy": 100,
             "effect": "heal", "description": "最大HPの25%を回復（3回まで）"},
        ],
    }


class PixelModal(discord.ui.Modal, title="8×8 ドット絵を描く"):
    def __init__(self, editor):
        super().__init__()
        self.editor = editor
        self.revision = editor.revision
        self.art = discord.ui.TextInput(label="0=透明 / 1=輪郭 / 2=本体 / 3=光", style=discord.TextStyle.paragraph,
                                        default="\n".join(editor.rows), min_length=71, max_length=71)
        self.name_input = discord.ui.TextInput(label="相棒の名前", default=editor.name, max_length=20)
        self.add_item(self.art)
        self.add_item(self.name_input)

    async def on_submit(self, interaction):
        if not await self.editor.interaction_check(interaction):
            return
        if self.revision != self.editor.revision:
            await interaction.response.send_message("編集内容が更新されています。もう一度開いてください。", ephemeral=True)
            return
        try:
            rows = parse_pixels(str(self.art))
            name = str(self.name_input).strip()
            if not name:
                raise ValueError("名前を入力してください。")
        except ValueError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        self.editor.snapshot()
        self.editor.rows, self.editor.name = rows, name
        await self.editor.refresh(interaction)


class PixelStudio(discord.ui.View):
    def __init__(self, cog, user_id, name):
        super().__init__(timeout=900)
        self.cog, self.user_id, self.name = cog, user_id, name
        self.rows = parse_pixels(PIXEL_TEMPLATES["スライム"])
        self.element, self.style, self.color = "無", "バランス", "ミント"
        self.history, self.revision = [], 0
        self.saving = self.saved = False
        for row, (label, values, attribute) in enumerate([
            ("ベースを選ぶ（絵を置換）", PIXEL_TEMPLATES, "template"),
            ("属性を選ぶ", VALID_ELEMENTS, "element"),
            ("戦闘スタイル", ARCHETYPES, "style"),
            ("カラーパレット", PIXEL_COLORS, "color"),
        ]):
            select = discord.ui.Select(placeholder=label, options=[discord.SelectOption(label=v, value=v) for v in values], row=row)
            select.callback = self.selection(attribute)
            self.add_item(select)

    async def interaction_check(self, interaction):
        if str(interaction.user.id) != self.user_id:
            await interaction.response.send_message("自分の工房は /ddd_create で開けます。", ephemeral=True)
            return False
        if self.saved or self.saving or self.is_finished():
            await interaction.response.send_message("保存中・保存済み、または期限切れの工房です。", ephemeral=True)
            return False
        return True

    def snapshot(self):
        self.history.append((self.rows[:], self.name, self.element, self.style, self.color))
        self.history = self.history[-20:]
        self.revision += 1

    def selection(self, attribute):
        async def callback(interaction):
            self.snapshot()
            value = interaction.data["values"][0]
            if attribute == "template":
                self.rows = parse_pixels(PIXEL_TEMPLATES[value])
            else:
                setattr(self, attribute, value)
            await self.refresh(interaction)
        return callback

    def embed(self):
        stats = ARCHETYPES[self.style]
        embed = discord.Embed(title=f"DDD PIXEL STUDIO | {self.name}", color=0x45E1AD,
                              description="描く → 個性を選ぶ → 相棒として登録\nAI API・ago消費なし。画像は公開保存されます。")
        embed.set_image(url="attachment://dot.png")
        embed.add_field(name="キャラクターデザイン", value=f"属性 **{self.element}** / **{self.style}** / {self.color}", inline=False)
        embed.add_field(name="Lv.30 ポテンシャル / 合計360", value=" / ".join(f"{k} {v}" for k, v in zip(["HP", "攻", "防", "特攻", "特防", "速"], stats)), inline=False)
        embed.add_field(name="描き方", value="「描く・名前」で8行の数字を編集。0=透明、1=輪郭、2=本体、3=光。\nテンプレート・左右反転・20手まで戻す機能で、好きな形を作れます。", inline=False)
        embed.set_footer(text="Lv.5で誕生 / 技3枠 / 保存前なら何度でも編集可能 / 工房の操作期限15分")
        return embed

    def file(self):
        return discord.File(io.BytesIO(pixel_png(self.rows, self.color)), filename="dot.png")

    async def refresh(self, interaction):
        await interaction.response.edit_message(embed=self.embed(), attachments=[self.file()], view=self)

    @discord.ui.button(label="描く・名前", style=discord.ButtonStyle.primary, row=4)
    async def draw(self, interaction, button):
        await interaction.response.send_modal(PixelModal(self))

    @discord.ui.button(label="左右反転", row=4)
    async def mirror(self, interaction, button):
        self.snapshot()
        self.rows = [row[::-1] for row in self.rows]
        await self.refresh(interaction)

    @discord.ui.button(label="戻す", row=4)
    async def undo(self, interaction, button):
        if self.history:
            self.rows, self.name, self.element, self.style, self.color = self.history.pop()
            self.revision += 1
        await self.refresh(interaction)

    @discord.ui.button(label="相棒として登録", style=discord.ButtonStyle.success, row=4)
    async def publish(self, interaction, button):
        if not any(c != "0" for row in self.rows for c in row):
            await interaction.response.send_message("まず1ドット以上描いてください。", ephemeral=True)
            return
        self.saving = True
        await interaction.response.defer()
        try:
            async with self.cog.creation_locks[self.user_id]:
                monster = await asyncio.to_thread(self.cog.save_creation, self)
            self.saved = True
        except Exception:
            logging.getLogger(__name__).exception("DDD free creation failed")
            self.saving = False
            await interaction.followup.send("保存できませんでした。ボックス容量とStorage設定を確認してください。課金はありません。", ephemeral=True)
            return
        self.stop()
        embed = self.embed()
        embed.title = f"相棒誕生 | {self.name}"
        embed.description = "ボックスに保存しました。まずは /ddd_practice で腕試し！"
        embed.set_image(url=monster["image_url"])
        embed.add_field(name="モンスターID", value=str(monster["id"]), inline=False)
        await interaction.edit_original_response(embed=embed, attachments=[], view=None)


class ScoutDecisionView(discord.ui.View):
    """鑑定済み個体をボックスへ迎えるか、見送るかを選ぶ確認画面。"""
    def __init__(self, cog, user_id, record, file_path, dice, stats, canvas_size, box_text, cost=APPRAISAL_COST):
        super().__init__(timeout=180)
        self.cog = cog
        self.user_id = user_id
        self.record = record
        self.file_path = file_path
        self.dice = dice
        self.stats = stats
        self.canvas_size = canvas_size
        self.box_text = box_text
        self.cost = cost
        self.done = False

    def preview_embed(self):
        embed = discord.Embed(
            title=f"DDD 鑑定記録 | 【{self.record['element_type']}】{self.record['name']}",
            description="**鑑定完了**\nこの個体をボックスへ迎え入れますか？見送っても鑑定費用は返金されません。",
            color=discord.Color.gold(),
        )
        embed.set_image(url=self.record["image_url"])
        embed.add_field(
            name="厳選結果 | 個体ポテンシャル",
            value=(f"初期レベル **{self.dice['level']} / 20**  {score_bar(self.dice['level'], 20)}\n"
                   f"才能値 **{self.dice['talent']} / 600**  {score_bar(self.dice['talent'], 600)}\n"
                   f"AI適合 **{self.dice['ai']} / 100**  {score_bar(self.dice['ai'], 100)}\n"
                   f"能力補正 **{self.dice['ability']} / 100**  {score_bar(self.dice['ability'], 100)}"),
            inline=False,
        )
        embed.add_field(
            name="能力配分 | Lv.30到達時",
            value=(f"**HP**: {self.stats['hp']} | **攻撃**: {self.stats['attack']} | **防御**: {self.stats['defense']}\n"
                   f"**特攻**: {self.stats['sp_atk']} | **特防**: {self.stats['sp_def']} | **素早さ**: {self.stats['speed']}"),
            inline=False,
        )
        embed.add_field(name="特性 | 個体の特徴", value=self.record["characteristic"], inline=False)
        moves_text = "\n".join(
            f"・**{m['name']}** [{m['type']}] ({'物理' if m['category']=='physical' else '特殊' if m['category']=='special' else '変化'} / 威力:{m['power'] if m['power'] > 0 else '-'})"
            for m in self.record["moves"]
        )
        embed.add_field(name="修得技 | バトル構成", value=moves_text, inline=False)
        embed.set_footer(text=f"鑑定費用: {self.cost} ago | パレット: {self.canvas_size} | ボックス: {self.box_text}")
        return embed

    async def interaction_check(self, interaction):
        if str(interaction.user.id) != self.user_id or self.done:
            await interaction.response.send_message("この鑑定結果は操作済み、またはあなたのものではありません。", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="スカウトしてボックスへ", style=discord.ButtonStyle.success)
    async def scout(self, interaction, button):
        self.done = True
        await interaction.response.defer()
        try:
            result = await asyncio.to_thread(lambda: supabase.table("monsters").insert(self.record).execute())
            if not result.data:
                raise RuntimeError("登録結果が空でした")
            monster = result.data[0]
        except Exception:
            self.done = False
            await interaction.followup.send("ボックスへの登録に失敗しました。鑑定費用は返金されません。", ephemeral=True)
            return
        self.stop()
        embed = self.preview_embed()
        embed.description = "**スカウト成功**\nこの個体をボックスへ迎え入れました。"
        embed.set_footer(text=f"鑑定費用: {APPRAISAL_COST} ago | ボックス登録済み | モンスターID: {monster['id']}")
        await interaction.edit_original_response(embed=embed, view=None)

    @discord.ui.button(label="今回は見送る", style=discord.ButtonStyle.secondary)
    async def decline(self, interaction, button):
        self.done = True
        await interaction.response.defer()
        try:
            await asyncio.to_thread(lambda: supabase.storage.from_("dot_images").remove([self.file_path]))
        except Exception:
            pass
        self.stop()
        embed = self.preview_embed()
        embed.description = "**スカウトを見送りました。**\n個体はボックスへ登録されず、鑑定費用も返金されません。"
        await interaction.edit_original_response(embed=embed, view=None)

    async def on_timeout(self):
        if self.done:
            return
        self.done = True
        try:
            await asyncio.to_thread(lambda: supabase.storage.from_("dot_images").remove([self.file_path]))
        except Exception:
            pass
        for child in self.children:
            child.disabled = True


class AppraisalCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.creation_locks = defaultdict(asyncio.Lock)

    @app_commands.command(name="ddd_create", description="無料のドット絵工房。自分だけの相棒を描いて育てよう（AI不使用）")
    @app_commands.describe(name="相棒の名前（1〜20文字）")
    @app_commands.checks.cooldown(1, 15, key=lambda i: i.user.id)
    async def create(self, interaction: discord.Interaction, name: str = "はじめてのドット"):
        name = name.strip()
        if not 1 <= len(name) <= 20:
            await interaction.response.send_message("名前は1〜20文字で指定してください。", ephemeral=True)
            return
        view = PixelStudio(self, str(interaction.user.id), name)
        await interaction.response.send_message(embed=view.embed(), file=view.file(), view=view, ephemeral=True)

    def save_creation(self, editor):
        profile = self.get_user_profile(editor.user_id)
        available, _ = self.check_box_capacity(editor.user_id, profile["max_box_slots"])
        if not available:
            raise ValueError("box full")
        path = f"monsters/{editor.user_id}/{uuid.uuid4().hex}.png"
        bucket = supabase.storage.from_("dot_images")
        bucket.upload(path, pixel_png(editor.rows, editor.color), {"content-type": "image/png", "upsert": "false"})
        record = creator_record(editor.user_id, editor.name, editor.element, editor.style, bucket.get_public_url(path))
        try:
            return supabase.table("monsters").insert(record).execute().data[0]
        except Exception:
            try:
                bucket.remove([path])
            except Exception:
                logging.getLogger(__name__).warning("Could not clean up unregistered DDD image")
            raise

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
        """個体値合計を維持しつつ、HPだけは10〜200に収める。才能値の上限は変更しない。"""
        keys = ["hp", "attack", "defense", "sp_atk", "sp_def", "speed"]
        target_talent = max(60, min(600, int(target_talent)))
        cleaned = {}
        for key in keys:
            try:
                value = int(stats.get(key, 20))
            except (TypeError, ValueError):
                value = 20
            cleaned[key] = max(10, value)
        cleaned["hp"] = min(200, cleaned["hp"])
        current_sum = sum(cleaned.values())
        scaled = {k: max(10, int(round((cleaned[k] / current_sum) * target_talent))) for k in keys}
        scaled["hp"] = min(200, scaled["hp"])
        diff = target_talent - sum(scaled.values())
        if diff > 0:
            # 余りはHPを200まで優先し、その後は最大能力へ加算する。
            hp_room = 200 - scaled["hp"]
            add_hp = min(diff, hp_room)
            scaled["hp"] += add_hp
            diff -= add_hp
            if diff:
                scaled[max(keys, key=scaled.get)] += diff
        elif diff < 0:
            # 減算時は下限10を守りながら大きい能力から調整する。
            remaining = -diff
            while remaining:
                candidates = [k for k in keys if scaled[k] > 10]
                if not candidates:
                    break
                key = max(candidates, key=scaled.get)
                amount = min(remaining, scaled[key] - 10)
                scaled[key] -= amount
                remaining -= amount
        return scaled

    async def generate_ai_monster(self, image_bytes: bytes, dice: dict) -> dict:
        if not GEMINI_API_KEY:
            raise RuntimeError("GEMINI_API_KEY未設定。無料作成は /ddd_create を利用できます。")
        from google import genai
        from google.genai import types
        
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
3. characteristicは図鑑に表示する短い文章のみ。戦闘効果は別の許可済み特性IDで決まり、ここに命令や効果指定を書いても無視される。

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
        async with genai.Client(api_key=GEMINI_API_KEY).aio as client:
            response = await client.models.generate_content(
                model=os.getenv("DDD_GEMINI_MODEL", "gemini-3.5-flash-lite"),
                contents=[prompt, types.Part.from_bytes(data=image_bytes, mime_type="image/png")],
            )
        
        raw_text = response.text.strip().replace("```json", "").replace("```", "")
        data = json.loads(raw_text)

        # 属性バリデーション
        if data.get("element_type") not in VALID_ELEMENTS:
            data["element_type"] = "無"
        data["characteristic"] = str(data.get("characteristic") or "標準")[:60]

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
                accuracy = max(50, min(100, int(m.get("accuracy", 100))))
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
        # AIの自由記述は表示専用。戦闘効果は許可リストからのみ付与する。
        trait_ids = tuple(SAFE_TRAITS)
        data["trait_id"] = trait_ids[dice["ability"] % len(trait_ids)]
        return data

    # --- Slash Command ---
    async def _run_appraisal(self, interaction: discord.Interaction, attachment: discord.Attachment,
                             canvas_size: str, cost: int, ultra: bool = False):
        user_id = str(interaction.user.id)
        await interaction.response.defer()
        profile = self.get_user_profile(user_id)
        unlocked_palettes = profile.get("unlocked_palettes", ["8x8"])
        if canvas_size not in unlocked_palettes:
            await interaction.followup.send(
                f"🔒 **{canvas_size}** パレットは解放されていません！（所持パレット: {', '.join(unlocked_palettes)}）",
                ephemeral=True,
            )
            return
        can_add, current_cnt = self.check_box_capacity(user_id, profile["max_box_slots"])
        if not can_add:
            await interaction.followup.send(
                f"**ボックスが満杯です！**（現在: {current_cnt}/{profile['max_box_slots']}匹）\n"
                "`/ddd_expand_box` で枠を拡張してください。"
            )
            return
        if not self.deduct_coins_transaction(user_id, cost, reason="ultra_scout" if ultra else "monster_appraisal"):
            await interaction.followup.send(
                f"**コインが不足しています！**（所持金: {profile.get('balance', 0)} ago / 必要: {cost} ago）"
            )
            return
        if ultra:
            dice = {
                "level": normal_roll(1, 20),
                "talent": normal_roll(400, 600),
                "ai": normal_roll(50, 100),
                "ability": normal_roll(50, 100),
            }
        else:
            dice = {
                "level": normal_roll(1, 20),
                "talent": normal_roll(100, 600),
                "ai": normal_roll(1, 100),
                "ability": normal_roll(1, 100),
            }
        try:
            image_bytes = await attachment.read()
            ai_data = await self.generate_ai_monster(image_bytes, dice)
        except Exception as exc:
            self.refund_coins(user_id, cost, reason="ultra_scout_failed_refund" if ultra else "appraisal_failed_refund")
            await interaction.followup.send(f"**AI鑑定に失敗したためコインを返還しました。**\n詳細: `{exc}`")
            return
        file_ext = ".png"
        allowed_content_types = {"image/png", "image/jpeg", "image/webp", "image/gif"}
        content_type = attachment.content_type if attachment.content_type in allowed_content_types else "image/png"
        if content_type != "image/png":
            file_ext = "." + content_type.split("/", 1)[1]
        file_path = f"monsters/{user_id}/{uuid.uuid4().hex}{file_ext}"
        try:
            supabase.storage.from_("dot_images").upload(file_path, image_bytes, {"content-type": content_type, "upsert": "false"})
            public_url = supabase.storage.from_("dot_images").get_public_url(file_path)
        except Exception as exc:
            self.refund_coins(user_id, cost, reason="ultra_scout_upload_failed_refund" if ultra else "upload_failed_refund")
            await interaction.followup.send(f"**画像保存に失敗したためコインを返還しました。**\n詳細: `{exc}`")
            return
        stats = ai_data["max_stats"]
        record = {
            "user_id": user_id, "name": ai_data["name"], "image_url": public_url,
            "canvas_size": canvas_size, "element_type": ai_data["element_type"],
            "characteristic": ai_data["characteristic"], "trait_id": ai_data["trait_id"],
            "dice_level": dice["level"], "dice_talent": dice["talent"],
            "dice_ai": dice["ai"], "dice_ability": dice["ability"],
            "current_level": dice["level"], "current_exp": 0,
            "max_hp": stats["hp"], "max_attack": stats["attack"],
            "max_defense": stats["defense"], "max_sp_atk": stats["sp_atk"],
            "max_sp_def": stats["sp_def"], "max_speed": stats["speed"],
            "moves": ai_data["moves"],
        }
        guarantee = "最低保証: 才能値400 / AI適合50 / 能力補正50" if ultra else "通常鑑定"
        view = ScoutDecisionView(
            self, user_id, record, file_path, dice, stats, canvas_size,
            f"未登録（{current_cnt}/{profile['max_box_slots']}）", cost=cost,
        )
        embed = view.preview_embed()
        embed.description = ("**ウルトラスカウト鑑定完了**\nこの個体をボックスへ迎え入れますか？\n"
                             f"{guarantee}\n見送っても鑑定費用は返金されません。") if ultra else embed.description
        await interaction.followup.send(embed=embed, view=view)

    @app_commands.command(name="ddd_appraise", description="ドット絵画像を鑑定してAIモンスターを生成します（要500ago）")
    @app_commands.describe(attachment="鑑定するドット絵画像", canvas_size="使用したパレットサイズ")
    @app_commands.choices(canvas_size=[
        app_commands.Choice(name="8x8", value="8x8"),
        app_commands.Choice(name="16x16", value="16x16"),
        app_commands.Choice(name="64x64", value="64x64"),
        app_commands.Choice(name="128x128", value="128x128")
    ])
    async def appraise(self, interaction: discord.Interaction, attachment: discord.Attachment, canvas_size: str = "8x8"):
        await self._run_appraisal(interaction, attachment, canvas_size, APPRAISAL_COST)

    @app_commands.command(name="ddd_ultra_scout", description="1万ago coinで最低値保証のウルトラスカウト")
    @app_commands.describe(attachment="スカウトするドット絵画像", canvas_size="使用したパレットサイズ")
    @app_commands.choices(canvas_size=[
        app_commands.Choice(name="8x8", value="8x8"),
        app_commands.Choice(name="16x16", value="16x16"),
        app_commands.Choice(name="64x64", value="64x64"),
        app_commands.Choice(name="128x128", value="128x128")
    ])
    async def ultra_scout(self, interaction: discord.Interaction, attachment: discord.Attachment, canvas_size: str = "8x8"):
        await self._run_appraisal(interaction, attachment, canvas_size, ULTRA_SCOUT_COST, ultra=True)


async def setup(bot):
    await bot.add_cog(AppraisalCog(bot))
