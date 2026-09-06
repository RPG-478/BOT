import os
import asyncio
from .ddd_battle import calc_stat, normalize_moves, TYPE_CHART, add_experience
import discord
from discord import app_commands
from discord.ext import commands
from supabase import create_client, Client

SUPABASE_URL = os.getenv("SUPABASE_URL")
# Botは公開可能なSupabaseキーのみを使用する。サービスロールキーは使用しない。
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# 定数設定
EXPAND_BOX_COST = 1000  # ボックス5枠拡張のコスト
PALETTE_COSTS = {       # パレット開放コスト
    "16x16": 1000,
    "64x64": 5000,
    "128x128": 20000
}
RENAME_MONSTER_COST = 300  # dot名変更
RENAME_MOVE_COST = 200     # 技名変更
RENAME_ABILITY_COST = 250  # 特性名・説明変更
MAX_RENAME_LENGTH = 20
MAX_ABILITY_LENGTH = 60
COINS_PER_EXP = 50

ELEMENT_COLORS = {"虚": 0xA185F7, "実": 0x45E1AD, "正": 0xF7BE3E, "負": 0xF677A4, "無": 0x52A7FF}
TECHNIQUES = {
    "ストライク": {"category": "physical", "power": 45, "accuracy": 100, "description": "安定した物理攻撃"},
    "ブレイク": {"category": "physical", "power": 75, "accuracy": 80, "description": "命中を犠牲に威力を高める"},
    "パルス": {"category": "special", "power": 45, "accuracy": 100, "description": "特攻で放つ安定した光弾"},
    "ノヴァ": {"category": "special", "power": 75, "accuracy": 80, "description": "高威力の特殊攻撃"},
    "リペア": {"category": "status", "effect": "heal", "description": "HP25%回復。1戦3回まで"},
    "バリア": {"category": "status", "effect": "guard", "description": "次の被ダメージ半減"},
    "ポイズン": {"category": "status", "effect": "poison", "accuracy": 85, "description": "相手の行動後3回、最大HPの1/8ダメージ"},
    "パワーチャージ": {"category": "status", "effect": "attack_up", "description": "攻撃1段階上昇。最大6段階"},
    "マインドチャージ": {"category": "status", "effect": "sp_atk_up", "description": "特攻1段階上昇。最大6段階"},
    "アーマー": {"category": "status", "effect": "defense_up", "description": "防御1段階上昇。交代で解除"},
    "マジックアーマー": {"category": "status", "effect": "sp_def_up", "description": "特防1段階上昇。交代で解除"},
}


def exchange_values(amount: int, direction: str, level: int, exp: int, balance: int) -> tuple[int, int, int]:
    """既存モンスターEXPとago coinの交換結果を計算する。"""
    amount = int(amount)
    level = max(1, min(30, int(level or 1)))
    exp = max(0, int(exp or 0))
    balance = max(0, int(balance or 0))
    if amount <= 0:
        raise ValueError("交換量は1以上の整数で指定してください。")
    if direction == "exp_to_coin":
        if exp < amount:
            raise ValueError(f"モンスターEXPが不足しています（現在: {exp} EXP）。")
        return level, exp - amount, balance + amount * COINS_PER_EXP
    if direction == "coin_to_exp":
        if level >= 30:
            raise ValueError("Lv.30のモンスターには追加EXPを交換できません。")
        required = amount * COINS_PER_EXP
        if balance < required:
            raise ValueError(f"ago coinが不足しています（所持: {balance} / 必要: {required}）。")
        new_level, new_exp = add_experience(level, exp, amount)
        return new_level, new_exp, balance - required
    raise ValueError("交換方向が不正です。")


def monster_embed(monster):
    element = monster.get("element_type", "無")
    level = monster.get("current_level", 1)
    embed = discord.Embed(title=f"{monster['name']} | Lv.{level} [{element}]"[:256],
                          description=str(monster.get("characteristic") or "自分だけのドットキャラクター")[:500],
                          color=ELEMENT_COLORS.get(element, 0x52A7FF))
    if monster.get("image_url"):
        embed.set_image(url=monster["image_url"])
    exp = max(0, min(100, monster.get("current_exp") or 0))
    progress = "MAX LEVEL" if level >= 30 else f"`{'█' * (exp // 10)}{'░' * (10 - exp // 10)}` {exp}/100 EXP"
    embed.add_field(name="成長", value=f"{progress}\nパレット {monster.get('canvas_size', '8x8')} / 才能 {monster.get('dice_talent', '-')}", inline=False)
    stats = [(name, monster.get(f"max_{key}", 10)) for name, key in [("HP", "hp"), ("攻撃", "attack"), ("防御", "defense"), ("特攻", "sp_atk"), ("特防", "sp_def"), ("素早さ", "speed")]]
    embed.add_field(name="現在の能力値 / Lv.30の上限", value="\n".join(f"**{name}** {calc_stat(value, level)} / {value}" for name, value in stats), inline=True)
    weaknesses = [element_type for element_type, match in TYPE_CHART.items() if match.get(element, 1) > 1]
    embed.add_field(name="属性メモ", value=f"弱点: {'・'.join(weaknesses) or 'なし'}\n自分と同じ属性の攻撃技は威力1.5倍。", inline=True)
    for index, move in enumerate(normalize_moves(monster.get("moves")), 1):
        category = {"physical": "物理", "special": "特殊", "status": "変化"}[move["category"]]
        embed.add_field(name=f"{index}. {move['name']} [{move['type']}]", value=f"{category} / 威力 {move['power']} / 命中 {move['accuracy']}\n{str(move.get('description') or '効果説明なし')[:160]}", inline=False)
    embed.add_field(name="この相棒で遊ぶ", value=f"`/ddd_practice monster_id:{monster['id']}`\n`/ddd_loadout` で技を選択。技名は `/ddd_rename_move`。", inline=False)
    embed.set_footer(text=f"モンスターID: {monster['id']}")
    return embed


class ReleaseConfirm(discord.ui.View):
    def __init__(self, user_id, monster):
        super().__init__(timeout=60)
        self.user_id, self.monster, self.used = user_id, monster, False

    async def interaction_check(self, interaction):
        if str(interaction.user.id) != self.user_id or self.used:
            await interaction.response.send_message("操作できない、または処理済みの確認画面です。", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="確認してお別れする", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction, button):
        self.used = True
        await interaction.response.defer()
        try:
            result = await asyncio.to_thread(lambda: supabase.table("monsters").delete().eq("id", self.monster["id"]).eq("user_id", self.user_id).execute())
        except Exception:
            self.used = False
            await interaction.followup.send("削除に失敗しました。時間を置いて再度確認してください。", ephemeral=True)
            return
        self.stop()
        text = f"{self.monster['name']} とお別れしました。" if result.data else "この相棒はすでにボックスにいません。"
        await interaction.edit_original_response(content=text, view=None)

    @discord.ui.button(label="キャンセル")
    async def cancel(self, interaction, button):
        self.used = True
        self.stop()
        await interaction.response.edit_message(content="お別れをキャンセルしました。", view=None)


class MonsterSelectView(discord.ui.View):
    def __init__(self, user_id, monsters, release=False):
        super().__init__(timeout=180)
        self.user_id, self.monsters, self.release = user_id, monsters, release
        self.page = 0
        self.render()

    async def interaction_check(self, interaction):
        if str(interaction.user.id) != self.user_id:
            await interaction.response.send_message("自分のボックスは /ddd_box で開いてください。", ephemeral=True)
            return False
        return True

    def render(self):
        self.clear_items()
        rows = self.monsters[self.page * 25:(self.page + 1) * 25]
        options = [discord.SelectOption(label=f"{m['name']} (Lv.{m['current_level']})"[:100],
                   description=f"属性:{m['element_type']} | ID:{m['id']}"[:100], value=str(m["id"])) for m in rows]
        if options:
            select = discord.ui.Select(placeholder=f"相棒を選ぶ | {self.page + 1}/{max(1, (len(self.monsters) + 24) // 25)}ページ", options=options)
            select.callback = self.select_callback
            self.add_item(select)
        for label, delta, disabled in [("前の25匹", -1, self.page == 0), ("次の25匹", 1, (self.page + 1) * 25 >= len(self.monsters))]:
            button = discord.ui.Button(label=label, disabled=disabled, row=1)
            button.callback = self.page_callback(delta)
            self.add_item(button)

    def page_callback(self, delta):
        async def callback(interaction):
            self.page = max(0, min((len(self.monsters) - 1) // 25, self.page + delta))
            self.render()
            await interaction.response.edit_message(view=self)
        return callback

    async def select_callback(self, interaction):
        selected_id = interaction.data["values"][0]
        await interaction.response.defer(ephemeral=True)
        result = await asyncio.to_thread(lambda: supabase.table("monsters").select("*").eq("id", selected_id).eq("user_id", self.user_id).execute())
        if not result.data:
            await interaction.followup.send("相棒が見つかりません。ボックスを開き直してください。", ephemeral=True)
            return
        monster = result.data[0]
        if self.release:
            await interaction.followup.send(content=f"**{monster['name']}** とお別れしますか？削除は取り消せません。", view=ReleaseConfirm(self.user_id, monster), ephemeral=True)
        else:
            await interaction.followup.send(embed=monster_embed(monster), ephemeral=True)


class SystemCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # --- ヘルパーメソッド ---
    def get_user_profile(self, user_id: str) -> dict:
        res = supabase.table("users").select("*").eq("user_id", user_id).execute()
        if res.data:
            return res.data[0]
        
        new_user = {
            "user_id": user_id,
            "balance": 0,
            "max_box_slots": 20,
            "unlocked_palettes": ["8x8"]
        }
        inserted = supabase.table("users").insert(new_user).execute()
        return inserted.data[0]

    def deduct_coins(self, user_id: str, amount: int, reason: str) -> bool:
        try:
            user_res = supabase.table("users").select("balance").eq("user_id", user_id).execute()
            if not user_res.data or user_res.data[0]["balance"] < amount:
                return False

            new_bal = user_res.data[0]["balance"] - amount
            update_res = (
                supabase.table("users")
                .update({"balance": new_bal})
                .eq("user_id", user_id)
                .gte("balance", amount)
                .execute()
            )
            if not update_res.data:
                return False

            supabase.table("transaction_history").insert({
                "sender_id": user_id,
                "receiver_id": "SYSTEM_PURCHASE",
                "amount": amount,
                "reason": reason
            }).execute()
            return True
        except Exception as e:
            print(f"[Transaction Error] {e}")
            return False

    # --- Commands ---

    def exchange_monster(self, user_id: str, monster_id: str, direction: str, amount: int) -> dict:
        profile = supabase.table("users").select("balance").eq("user_id", user_id).execute()
        balance = int(profile.data[0].get("balance") or 0) if profile.data else 0
        monster_result = (supabase.table("monsters")
                          .select("id,name,current_level,current_exp")
                          .eq("id", monster_id).eq("user_id", user_id).execute())
        if not monster_result.data:
            raise ValueError("指定したモンスターが見つかりません。`/ddd_box`でIDを確認してください。")
        monster = monster_result.data[0]
        old_level = int(monster.get("current_level") or 1)
        old_exp = int(monster.get("current_exp") or 0)
        new_level, new_exp, new_balance = exchange_values(amount, direction, old_level, old_exp, balance)

        updated_monster = (supabase.table("monsters").update({"current_level": new_level, "current_exp": new_exp})
                           .eq("id", monster_id).eq("user_id", user_id)
                           .eq("current_level", old_level).eq("current_exp", old_exp).execute())
        if not updated_monster.data:
            raise RuntimeError("モンスター情報が変化したため、交換を中止しました。")
        updated_user = (supabase.table("users").update({"balance": new_balance})
                        .eq("user_id", user_id).eq("balance", balance).execute())
        if not updated_user.data:
            (supabase.table("monsters").update({"current_level": old_level, "current_exp": old_exp})
             .eq("id", monster_id).eq("user_id", user_id)
             .eq("current_level", new_level).eq("current_exp", new_exp).execute())
            raise RuntimeError("残高が変化したため、交換を中止しました。")

        coin_delta = new_balance - balance
        supabase.table("transaction_history").insert({
            "sender_id": user_id if coin_delta < 0 else "SYSTEM_DDD",
            "receiver_id": "SYSTEM_DDD" if coin_delta < 0 else user_id,
            "amount": abs(coin_delta),
            "reason": f"ddd_exchange_{direction}",
        }).execute()
        return {"name": monster["name"], "old_level": old_level, "old_exp": old_exp,
                "new_level": new_level, "new_exp": new_exp, "old_balance": balance,
                "new_balance": new_balance}

    @app_commands.command(name="ddd_exchange", description="指定モンスターのEXPとago coinを50:1で交換します")
    @app_commands.describe(monster_id="/ddd_boxに表示されるモンスターID", direction="交換方向", amount="EXPの数量")
    @app_commands.choices(direction=[
        app_commands.Choice(name="モンスターEXP → ago coin", value="exp_to_coin"),
        app_commands.Choice(name="ago coin → モンスターEXP", value="coin_to_exp"),
    ])
    async def exchange(self, interaction: discord.Interaction, monster_id: str, direction: str, amount: int):
        await interaction.response.defer(ephemeral=True)
        try:
            result = await asyncio.to_thread(self.exchange_monster, str(interaction.user.id), monster_id, direction, amount)
            level = f"Lv.{result['old_level']} → Lv.{result['new_level']}" if result["old_level"] != result["new_level"] else f"Lv.{result['new_level']}"
            await interaction.followup.send(
                f"**{result['name']}** の交換が完了しました。\\n"
                f"モンスターEXP: **{result['old_exp']} → {result['new_exp']}**（{level}）\\n"
                f"ago coin: **{result['old_balance']} → {result['new_balance']}**\\n"
                f"レート: **50 ago coin = 1 EXP**", ephemeral=True)
        except (ValueError, TypeError, RuntimeError) as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
        except Exception:
            await interaction.followup.send("交換に失敗しました。残高とモンスターIDを確認してください。", ephemeral=True)

    @app_commands.command(name="ddd_box", description="所持しているモンスター一覧を確認・詳細表示します")
    @app_commands.describe(search="名前の部分一致", element="属性で絞り込む", order="並び順")
    @app_commands.choices(element=[app_commands.Choice(name=e, value=e) for e in TYPE_CHART],
                          order=[app_commands.Choice(name="新しい順", value="created_at"), app_commands.Choice(name="レベル順", value="current_level"), app_commands.Choice(name="才能順", value="dice_talent")])
    async def show_box(self, interaction: discord.Interaction, search: str = "", element: str = "", order: str = "created_at"):
        user_id = str(interaction.user.id)
        await interaction.response.defer()

        profile = await asyncio.to_thread(self.get_user_profile, user_id)
        res = await asyncio.to_thread(lambda: supabase.table("monsters").select("*").eq("user_id", user_id).order(order, desc=True).execute())
        all_monsters = res.data
        monsters = [m for m in all_monsters if search.casefold() in m["name"].casefold() and (not element or m["element_type"] == element)]
        embed = discord.Embed(title=f"DDD COLLECTION | {len(all_monsters)}/{profile['max_box_slots']}", color=0x45E1AD,
                              description=f"表示 {len(monsters)}匹。相棒を選んで能力値・技・成長をチェック。\n`/ddd_create` 作成 → `/ddd_loadout` 技を選ぶ → `/ddd_practice` 腕試し")
        if not monsters:
            embed.description = "条件に合う相棒がいません。検索を変えるか /ddd_create で無料作成しましょう。"
            await interaction.followup.send(embed=embed)
            return
        embed.set_thumbnail(url=monsters[0].get("image_url") or interaction.user.display_avatar.url)
        embed.add_field(name="コレクションの属性", value=" / ".join(f"{e}: {sum(m['element_type'] == e for m in all_monsters)}" for e in TYPE_CHART), inline=False)
        await interaction.followup.send(embed=embed, view=MonsterSelectView(user_id, monsters))


    @app_commands.command(name="ddd_expand_box", description="1000 ago を消費してボックス容量を5枠拡張します")
    async def expand_box(self, interaction: discord.Interaction):
        user_id = str(interaction.user.id)
        await interaction.response.defer()

        profile = self.get_user_profile(user_id)

        if not self.deduct_coins(user_id, EXPAND_BOX_COST, reason="box_expansion"):
            await interaction.followup.send(f"❌ **コインが不足しています！**（所持: {profile['balance']} ago / 必要: {EXPAND_BOX_COST} ago）")
            return

        new_slots = profile["max_box_slots"] + 5
        supabase.table("users").update({"max_box_slots": new_slots}).eq("user_id", user_id).execute()

        await interaction.followup.send(f"🎉 **ボックスを拡張しました！**（最大容量: {profile['max_box_slots']} → **{new_slots}** 匹）")


    @app_commands.command(name="ddd_unlock_palette", description="コインを消費して新しい高解像度パレットを開放します")
    @app_commands.describe(size="開放するパレットサイズ")
    @app_commands.choices(size=[
        app_commands.Choice(name="16x16 (1,000 ago)", value="16x16"),
        app_commands.Choice(name="64x64 (5,000 ago)", value="64x64"),
        app_commands.Choice(name="128x128 (20,000 ago)", value="128x128")
    ])
    async def unlock_palette(self, interaction: discord.Interaction, size: str):
        user_id = str(interaction.user.id)
        await interaction.response.defer()

        profile = self.get_user_profile(user_id)
        unlocked = profile.get("unlocked_palettes", ["8x8"])

        if size in unlocked:
            await interaction.followup.send(f"⚠️ パレット **{size}** は既に開放されています。")
            return

        cost = PALETTE_COSTS.get(size, 1000)
        if not self.deduct_coins(user_id, cost, reason=f"unlock_palette_{size}"):
            await interaction.followup.send(f"❌ **コインが不足しています！**（所持: {profile['balance']} ago / 必要: {cost} ago）")
            return

        unlocked.append(size)
        supabase.table("users").update({"unlocked_palettes": unlocked}).eq("user_id", user_id).execute()

        await interaction.followup.send(f"🎨 **パレット 【{size}】 を解放しました！**\n`/ddd_appraise` の鑑定時に選択可能になります。")


    @app_commands.command(name="ddd_rename_monster", description="ago coinを消費して自分のモンスターのdot名を変更します")
    @app_commands.describe(monster_id="/boxの詳細画面に表示されるモンスターID", new_name="新しいdot名（1〜20文字）")
    async def rename_monster(self, interaction: discord.Interaction, monster_id: str, new_name: str):
        user_id = str(interaction.user.id)
        new_name = new_name.strip()
        if not new_name or len(new_name) > MAX_RENAME_LENGTH:
            await interaction.response.send_message(f"❌ 名前は1〜{MAX_RENAME_LENGTH}文字で入力してください。", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        res = supabase.table("monsters").select("id, name").eq("id", monster_id).eq("user_id", user_id).execute()
        if not res.data:
            await interaction.followup.send("❌ 指定したモンスターが見つからないか、あなたの所持個体ではありません。", ephemeral=True)
            return
        monster = res.data[0]
        if monster["name"] == new_name:
            await interaction.followup.send("⚠️ 現在と同じ名前です。", ephemeral=True)
            return
        profile = self.get_user_profile(user_id)
        if not self.deduct_coins(user_id, RENAME_MONSTER_COST, reason="rename_monster"):
            await interaction.followup.send(f"❌ ago coinが不足しています。（必要: {RENAME_MONSTER_COST} ago / 所持: {profile['balance']} ago）", ephemeral=True)
            return
        try:
            update = supabase.table("monsters").update({"name": new_name}).eq("id", monster_id).eq("user_id", user_id).execute()
            if not update.data:
                raise RuntimeError("monster update returned no rows")
        except Exception:
            # 決済後の更新失敗時は同額を返金する。
            self.refund_coins(user_id, RENAME_MONSTER_COST, reason="rename_monster_failed_refund")
            await interaction.followup.send("⚠️ 名前変更に失敗したため、ago coinを返金しました。", ephemeral=True)
            return
        await interaction.followup.send(f"✅ dot名を **{monster['name']}** から **{new_name}** に変更しました。（{RENAME_MONSTER_COST} ago）", ephemeral=True)


    @app_commands.command(name="ddd_rename_move", description="ago coinを消費して自分のモンスターの技名を変更します")
    @app_commands.describe(monster_id="/boxの詳細画面に表示されるモンスターID", move_slot="変更する技スロット", new_name="新しい技名（1〜20文字）")
    @app_commands.choices(move_slot=[
        app_commands.Choice(name="技1", value=1),
        app_commands.Choice(name="技2", value=2),
        app_commands.Choice(name="技3", value=3),
    ])
    async def rename_move(self, interaction: discord.Interaction, monster_id: str, move_slot: int, new_name: str):
        user_id = str(interaction.user.id)
        new_name = new_name.strip()
        if not new_name or len(new_name) > MAX_RENAME_LENGTH:
            await interaction.response.send_message(f"❌ 技名は1〜{MAX_RENAME_LENGTH}文字で入力してください。", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        res = supabase.table("monsters").select("id, name, moves").eq("id", monster_id).eq("user_id", user_id).execute()
        if not res.data:
            await interaction.followup.send("❌ 指定したモンスターが見つからないか、あなたの所持個体ではありません。", ephemeral=True)
            return
        monster = res.data[0]
        moves = monster.get("moves") or []
        if move_slot not in (1, 2, 3) or move_slot > len(moves):
            await interaction.followup.send("❌ 技スロットは1〜3で、存在する技を選択してください。", ephemeral=True)
            return
        move = dict(moves[move_slot - 1])
        old_name = str(move.get("name", "技"))
        if old_name == new_name:
            await interaction.followup.send("⚠️ 現在と同じ技名です。", ephemeral=True)
            return
        profile = self.get_user_profile(user_id)
        if not self.deduct_coins(user_id, RENAME_MOVE_COST, reason=f"rename_move_{move_slot}"):
            await interaction.followup.send(f"❌ ago coinが不足しています。（必要: {RENAME_MOVE_COST} ago / 所持: {profile['balance']} ago）", ephemeral=True)
            return
        move["name"] = new_name
        moves[move_slot - 1] = move
        try:
            update = supabase.table("monsters").update({"moves": moves}).eq("id", monster_id).eq("user_id", user_id).execute()
            if not update.data:
                raise RuntimeError("monster move update returned no rows")
        except Exception:
            self.refund_coins(user_id, RENAME_MOVE_COST, reason="rename_move_failed_refund")
            await interaction.followup.send("⚠️ 技名変更に失敗したため、ago coinを返金しました。", ephemeral=True)
            return
        await interaction.followup.send(f"✅ **{monster['name']}** の技{move_slot}を **{old_name}** から **{new_name}** に変更しました。（{RENAME_MOVE_COST} ago）", ephemeral=True)


    @app_commands.command(name="ddd_rename_ability", description="ago coinを消費して自分のモンスターの特性名・説明を変更します")
    @app_commands.describe(monster_id="/boxの詳細画面に表示されるモンスターID", new_ability="新しい特性名・説明（1〜60文字）")
    async def rename_ability(self, interaction: discord.Interaction, monster_id: str, new_ability: str):
        user_id = str(interaction.user.id)
        new_ability = new_ability.strip()
        if not new_ability or len(new_ability) > MAX_ABILITY_LENGTH:
            await interaction.response.send_message(f"❌ 特性名・説明は1〜{MAX_ABILITY_LENGTH}文字で入力してください。", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        res = supabase.table("monsters").select("id, name, characteristic").eq("id", monster_id).eq("user_id", user_id).execute()
        if not res.data:
            await interaction.followup.send("❌ 指定したモンスターが見つからないか、あなたの所持個体ではありません。", ephemeral=True)
            return
        monster = res.data[0]
        old_ability = str(monster.get("characteristic") or "未設定")
        if old_ability == new_ability:
            await interaction.followup.send("⚠️ 現在と同じ特性名・説明です。", ephemeral=True)
            return
        profile = self.get_user_profile(user_id)
        if not self.deduct_coins(user_id, RENAME_ABILITY_COST, reason="rename_ability"):
            await interaction.followup.send(f"❌ ago coinが不足しています。（必要: {RENAME_ABILITY_COST} ago / 所持: {profile['balance']} ago）", ephemeral=True)
            return
        try:
            update = supabase.table("monsters").update({"characteristic": new_ability}).eq("id", monster_id).eq("user_id", user_id).execute()
            if not update.data:
                raise RuntimeError("monster ability update returned no rows")
        except Exception:
            self.refund_coins(user_id, RENAME_ABILITY_COST, reason="rename_ability_failed_refund")
            await interaction.followup.send("⚠️ 特性名・説明の変更に失敗したため、ago coinを返金しました。", ephemeral=True)
            return
        await interaction.followup.send(f"✅ **{monster['name']}** の特性を **{new_ability}** に変更しました。（{RENAME_ABILITY_COST} ago）", ephemeral=True)


    @app_commands.command(name="ddd_profile", description="所持コイン、ボックス容量、解放済みパレットを確認します")
    async def profile(self, interaction: discord.Interaction):
        user_id = str(interaction.user.id)
        await interaction.response.defer()

        prof = self.get_user_profile(user_id)
        count_res = supabase.table("monsters").select("id", count="exact").eq("user_id", user_id).execute()
        current_monsters = count_res.count if count_res.count is not None else 0

        embed = discord.Embed(
            title=f"👤 {interaction.user.display_name} さんのプレイヤーデータ",
            color=discord.Color.purple()
        )
        embed.set_thumbnail(url=interaction.user.display_avatar.url)
        embed.add_field(name="💰 所持コイン", value=f"**{prof['balance']}** ago", inline=True)
        embed.add_field(name="📦 ボックス使用量", value=f"**{current_monsters}** / {prof['max_box_slots']} 匹", inline=True)
        embed.add_field(name="🎨 解放済みパレット", value=", ".join([f"`{p}`" for p in prof['unlocked_palettes']]), inline=False)

        await interaction.followup.send(embed=embed)


    @app_commands.command(name="ddd_release_monster", description="相棒とお別れ。確認後に削除します（ページ切替対応）")
    async def release_monster(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        uid = str(interaction.user.id)
        result = await asyncio.to_thread(lambda: supabase.table("monsters").select("id,name,element_type,current_level").eq("user_id", uid).order("created_at", desc=True).execute())
        if not result.data:
            await interaction.followup.send("お別れできる相棒はいません。", ephemeral=True)
            return
        await interaction.followup.send("相棒を選ぶと確認画面が開きます。削除は取り消せません。", view=MonsterSelectView(uid, result.data, release=True), ephemeral=True)

    @app_commands.command(name="ddd_loadout", description="相棒の技1枠を無料で変更。攻撃・回復・毒・強化を組み合わせよう")
    @app_commands.describe(monster_id="ボックス詳細のID", slot="変更する技枠", technique="覚える技。技名も選んだ技に置き換わります")
    @app_commands.choices(slot=[app_commands.Choice(name=f"技{i}", value=i) for i in (1, 2, 3)],
                          technique=[app_commands.Choice(name=f"{name}：{data['description']}"[:100], value=name) for name, data in TECHNIQUES.items()])
    async def loadout(self, interaction: discord.Interaction, monster_id: str, slot: int, technique: str):
        if slot not in (1, 2, 3) or technique not in TECHNIQUES:
            await interaction.response.send_message("技枠と技を選択してください。", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        uid = str(interaction.user.id)
        def update():
            result = supabase.table("monsters").select("*").eq("id", monster_id).eq("user_id", uid).execute()
            if not result.data:
                return None
            monster = result.data[0]
            old_moves = monster.get("moves")
            moves = normalize_moves(old_moves)
            moves[slot - 1] = {"name": technique, "type": monster["element_type"], "power": 0, "accuracy": 100, **TECHNIQUES[technique]}
            # Compare the old JSON array to avoid silently overwriting concurrent edits.
            query = supabase.table("monsters").update({"moves": moves}).eq("id", monster_id).eq("user_id", uid)
            if old_moves is None:
                query = query.is_("moves", "null")
            else:
                import json
                query = query.eq("moves", json.dumps(old_moves, ensure_ascii=False))
            updated = query.execute()
            return updated.data[0] if updated.data else None
        monster = await asyncio.to_thread(update)
        if not monster:
            await interaction.followup.send("相棒が見つからないか同時編集がありました。ボックスを確認して再操作してください。", ephemeral=True)
            return
        await interaction.followup.send(content="技を変更しました。進行中の対戦には反映されず、次の対戦から有効です。", embed=monster_embed(monster), ephemeral=True)

    @app_commands.command(name="ddd_guide", description="DDDの遊び方・属性相性・無料機能・バトルルールを確認")
    async def guide(self, interaction: discord.Interaction):
        embed = discord.Embed(title="DDD | 小さなドットから、自分だけの物語を。", color=0x45E1AD,
                              description="描いて、組み合わせて、戦わせる。Discordがあなたのドット絵工房になります。")
        embed.add_field(name="01 / 相棒を作る", value="`/ddd_create` で8×8の工房を開く。5つのキャラベースと白紙、5色、5属性、5スタイルからカスタム。数字の編集で全64ドットを描けます。", inline=False)
        embed.add_field(name="02 / 戦い方を決める", value="`/ddd_box` でIDを確認し `/ddd_loadout` で3枠の技を編成。物理・特殊・回復・毒・能力アップなど11種類。性能合計は無料作成で全員360です。", inline=False)
        embed.add_field(name="03 / ひとりで腕試し", value="`/ddd_practice` は1匹から遊べる無料のCPU戦。草原・遺跡・鏡の3コース。練習なので経験値・コインは変動しません。", inline=False)
        embed.add_field(name="04 / 友達と対戦・育成", value="`/ddd_battle` で招待。双方の直近3匹が出場し、速い先頭が先攻。勝利パーティ全員に50 EXP、100 EXPでレベルアップ（Lv.30まで）。期限切れは `/ddd_resume`。", inline=False)
        embed.add_field(name="戦術ノート", value="虚⇔実・正⇔負はお互いに2倍、同属性は半減（無を除く）。一致属性技は1.5倍。防御でダメージ半減、交代で能力ランク解除。回復は3回まで。80手で引き分け。", inline=False)
        embed.add_field(name="費用について", value="工房・技編成・練習にAI API・ago消費はありません。既存の `/ddd_appraise` は500 ago＋管理者側のGemini API利用、改名・ボックス拡張は従来どおりagoを使います。Discord・Supabase等の運用費は別です。", inline=False)
        embed.set_footer(text="ドット画像は公開Storageに保存されます。個人情報を描かないでください。")
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot):
    await bot.add_cog(SystemCog(bot))
