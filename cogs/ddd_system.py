import os
import discord
from discord import app_commands
from discord.ext import commands
from supabase import create_client, Client

SUPABASE_URL = os.getenv("SUPABASE_URL")
# BotのStorage・DB操作ではService Role Keyを優先する。
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_KEY")
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

# --- UI コンポーネント (ボックス一覧・詳細・お別れ) ---
class MonsterSelectView(discord.ui.View):
    def __init__(self, user_id: str, monsters: list):
        super().__init__(timeout=180)
        self.user_id = user_id
        self.monsters = monsters

        # ドロップダウンメニューの作成
        options = []
        for idx, m in enumerate(monsters[:25]):  # Select Menuの上限は25件
            options.append(
                discord.SelectOption(
                    label=f"{m['name']} (Lv.{m['current_level']})",
                    description=f"属性:{m['element_type']} | 才能:{m['dice_talent']}",
                    value=str(m["id"]),
                    emoji="👾"
                )
            )

        select = discord.ui.Select(
            placeholder="詳細を確認するモンスターを選択...",
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
            await interaction.response.send_message("指定されたモンスターが見つかりませんでした。", ephemeral=True)
            return

        # モンスター詳細 Embed の生成
        embed = discord.Embed(
            title=f"【{monster['element_type']}】{monster['name']} (Lv.{monster['current_level']})",
            description=f"特性: **{monster['characteristic']}**\nパレット: `{monster['canvas_size']}`",
            color=discord.Color.green()
        )
        embed.set_image(url=monster["image_url"])
        embed.add_field(
            name="🎲 厳選ログ",
            value=f"初期Lv: {monster['dice_level']} | 才能: {monster['dice_talent']} | AI: {monster['dice_ai']} | 能力: {monster['dice_ability']}",
            inline=False
        )
        embed.add_field(
            name="📊 最高個体値 (Lv.30)",
            value=f"HP: {monster['max_hp']} | 攻: {monster['max_attack']} | 防: {monster['max_defense']}\n特攻: {monster['max_sp_atk']} | 特防: {monster['max_sp_def']} | 素早さ: {monster['max_speed']}",
            inline=False
        )

        moves_text = "\n".join([f"・**{m['name']}** [{m['type']}] (威力:{m.get('power', '-')})" for m in monster["moves"]])
        embed.add_field(name="⚔️ 技構成", value=moves_text, inline=False)
        embed.set_footer(text=f"モンスターID: {monster['id']} | 名前変更: /ddd_rename_monster | 技名変更: /ddd_rename_move")

        await interaction.response.send_message(embed=embed, ephemeral=True)


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

    @app_commands.command(name="ddd_box", description="所持しているモンスター一覧を確認・詳細表示します")
    async def show_box(self, interaction: discord.Interaction):
        user_id = str(interaction.user.id)
        await interaction.response.defer()

        profile = self.get_user_profile(user_id)
        res = supabase.table("monsters").select("*").eq("user_id", user_id).order("created_at", desc=True).execute()
        monsters = res.data

        embed = discord.Embed(
            title=f"📦 モンスターボックス ({len(monsters)}/{profile['max_box_slots']}匹)",
            color=discord.Color.blue()
        )

        if not monsters:
            embed.description = "モンスターを所持していません。`/ddd_appraise` で鑑定を行いましょう！"
            await interaction.followup.send(embed=embed)
            return

        view = MonsterSelectView(user_id, monsters)
        embed.description = "下のドロップダウンメニューから選択して個体の詳細ステータスを確認できます。"
        await interaction.followup.send(embed=embed, view=view)


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


    @app_commands.command(name="ddd_release_monster", description="ボックスのモンスターとお別れ（削除）して枠を空けます")
    async def release_monster(self, interaction: discord.Interaction):
        user_id = str(interaction.user.id)
        await interaction.response.defer()

        res = supabase.table("monsters").select("id, name, element_type, current_level").eq("user_id", user_id).order("created_at", desc=True).execute()
        monsters = res.data

        if not monsters:
            await interaction.followup.send("お別れできるモンスターがいません。")
            return

        options = [
            discord.SelectOption(
                label=f"{m['name']} (Lv.{m['current_level']})",
                description=f"属性: {m['element_type']}",
                value=str(m["id"])
            )
            for m in monsters[:25]
        ]

        select = discord.ui.Select(placeholder="お別れするモンスターを選択...", options=options)

        async def select_callback(select_interaction: discord.Interaction):
            if str(select_interaction.user.id) != user_id:
                await select_interaction.response.send_message("他のプレイヤーの操作です。", ephemeral=True)
                return

            target_id = select.values[0]
            target_monster = next((m for m in monsters if str(m["id"]) == target_id), None)

            # DBから削除
            supabase.table("monsters").delete().eq("id", target_id).execute()

            await select_interaction.response.send_message(
                f"👋 **{target_monster['name']}** とお別れしました。（ボックス枠が1つ空きました）"
            )

        select.callback = select_callback
        view = discord.ui.View()
        view.add_item(select)

        await interaction.followup.send("⚠️ **削除したモンスターは復元できません。** お別れする個体を選択してください:", view=view)


async def setup(bot):
    await bot.add_cog(SystemCog(bot))
