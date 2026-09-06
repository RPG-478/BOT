import asyncio
import json
import logging
import random
from datetime import datetime, timedelta, timezone

import discord
from discord import app_commands
from discord.ext import commands
from supabase import Client, create_client

from .ddd_battle import SAFE_TRAITS, TYPE_CHART, add_experience, experience_required, experience_space, normalize_moves
from .ddd_inventory import (
    ELEMENTS,
    MOVE_RESET_TICKET,
    ORB_CODES,
    STAT_KEYS,
    TRADE_TICKET,
    UPRAISE_CRYSTAL,
    add_item,
    consume_item,
    item_counts,
    item_label,
    restore_item,
    roll_chest_reward,
)

SUPABASE_URL = __import__("os").getenv("SUPABASE_URL")
SUPABASE_KEY = __import__("os").getenv("SUPABASE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

EXPAND_BOX_COST = 1000
RENAME_MONSTER_COST = 300
RENAME_MOVE_COST = 200
RENAME_ABILITY_COST = 250
MOVE_REROLL_COST = 2000
COINS_PER_EXP = 50
TRADE_COST = 5000
MAX_RENAME_LENGTH = 20
MAX_ABILITY_LENGTH = 60
ELEMENT_COLORS = {"虚": 0xA185F7, "実": 0x45E1AD, "正": 0xF7BE3E, "負": 0xF677A4, "無": 0x52A7FF}

TECHNIQUES = {
    "攻撃": {"category": "physical", "power": 45, "accuracy": 100, "description": "物理 / 威力45 / 命中100。安定した攻撃。"},
    "強攻撃": {"category": "physical", "power": 75, "accuracy": 80, "description": "物理 / 威力75 / 命中80。高威力だが外れやすい。"},
    "特殊": {"category": "special", "power": 45, "accuracy": 100, "description": "特殊 / 威力45 / 命中100。安定した特殊攻撃。"},
    "強特殊": {"category": "special", "power": 75, "accuracy": 80, "description": "特殊 / 威力75 / 命中80。高威力だが外れやすい。"},
    "回復": {"category": "status", "effect": "heal", "description": "変化 / HPを25%回復。1戦3回まで。"},
    "毒": {"category": "status", "effect": "poison", "accuracy": 85, "description": "変化 / 命中85。相手に3回の毒ダメージ。"},
    "特殊攻撃1": {"category": "special", "power": 30, "accuracy": 90, "effect_after": "attack_up", "description": "特殊 / 威力30 / 命中90。攻撃後に攻撃+1。"},
    "ヒール強化": {"category": "status", "effect": "heal_big", "description": "変化 / HPを50%回復。1戦3回まで。"},
    "強攻撃1": {"category": "physical", "power": 140, "accuracy": 80, "effect_after": "stun", "description": "物理 / 威力140 / 命中80。攻撃後に1ターン動けない。"},
    "特殊攻撃2": {"category": "special", "power": 25, "accuracy": 100, "effect_after": "random_switch", "description": "特殊 / 威力25 / 命中100。攻撃後にランダム交代。"},
    "特殊攻撃3": {"category": "special", "power": 40, "accuracy": 90, "effect_after": "drain", "description": "特殊 / 威力40 / 命中90。与えたダメージ分回復。"},
    "特殊1": {"category": "status", "effect": "entry_hazard", "description": "変化 / 登場した相手に最大HPの1/8ダメージ。"},
    "特殊2": {"category": "status", "effect": "revenge_bomb", "description": "変化 / 戦闘不能時に相手へ最大HP50%ダメージ。"},
    "絡みつき": {"category": "status", "effect": "bind", "accuracy": 85, "description": "変化 / 命中85。相手を3ターン拘束する。"},
    "締め付け": {"category": "status", "effect": "bind", "accuracy": 80, "description": "変化 / 命中80。相手を4ターン拘束する。"},
    "くさむすび": {"category": "special", "power": 55, "accuracy": 90, "description": "特殊 / 威力55 / 命中90。蔦を絡めて攻撃。"},
    "まきつく": {"category": "physical", "power": 35, "accuracy": 95, "description": "物理 / 威力35 / 命中95。絡みついて追撃する。"},
    "攻撃強化": {"category": "status", "effect": "attack_up", "description": "変化 / 攻撃を1段階上昇。最大6段階。"},
    "特殊強化": {"category": "status", "effect": "sp_atk_up", "description": "変化 / 特攻を1段階上昇。最大6段階。"},
    "防御強化": {"category": "status", "effect": "defense_up", "description": "変化 / 防御を1段階上昇。交代で解除。"},
    "特殊防御": {"category": "status", "effect": "sp_def_up", "description": "変化 / 特防を1段階上昇。交代で解除。"},
}


def required_breakthrough(level: int, stage: int) -> tuple[int, int] | None:
    """突破可能なレベルなら、必要突破段階とオーブ数を返す。"""
    if stage == 0 and level >= 30:
        return 30, 1
    if stage == 30 and level >= 40:
        return 40, 10
    return None


def strength_evaluation(monster: dict) -> tuple[int, str]:
    """能力値を重視した、従来より少し厳しい評価値。"""
    total = sum(int(monster.get(f"max_{key}") or 10) for key in STAT_KEYS)
    talent = int(monster.get("dice_talent") or 0)
    ai = int(monster.get("dice_ai") or 0)
    ability = int(monster.get("dice_ability") or 0)
    score = round(min(100, total / 650 * 45 + talent / 650 * 25 + ai / 100 * 15 + ability / 100 * 15))
    rank = "S" if score >= 93 else "A" if score >= 80 else "B" if score >= 64 else "C" if score >= 45 else "D"
    return score, rank


def monster_embed(monster: dict):
    element = monster.get("element_type", "無")
    level = int(monster.get("current_level") or 1)
    stage = int(monster.get("breakthrough_stage") or 0)
    embed = discord.Embed(
        title=f"{monster['name']} | Lv.{level} [{element}]"[:256],
        description=str(monster.get("characteristic") or "個性豊かなモンスター")[:500],
        color=ELEMENT_COLORS.get(element, 0x52A7FF),
    )
    if monster.get("image_url"):
        embed.set_image(url=monster["image_url"])
    if level >= 50:
        growth = "MAX LEVEL"
    elif required_breakthrough(level, stage):
        next_stage, amount = required_breakthrough(level, stage)
        growth = f"突破待ち（{element}のオーブ {amount}個）"
    else:
        growth = f"EXP {int(monster.get('current_exp') or 0)} / 次Lv {experience_required(level)}"
    embed.add_field(name="成長", value=f"{growth}\n才能 {monster.get('dice_talent', '-')} / 突破 {stage}", inline=False)
    stats = [(name, monster.get(f"max_{key}", 10)) for name, key in [("HP", "hp"), ("攻撃", "attack"), ("防御", "defense"), ("特攻", "sp_atk"), ("特防", "sp_def"), ("素早さ", "speed")]]
    embed.add_field(name="能力値", value="\n".join(f"**{name}** {value}" for name, value in stats), inline=True)
    score, rank = strength_evaluation(monster)
    bar = "█" * (score // 10) + "░" * (10 - score // 10)
    embed.add_field(name="強さ評価", value=f"**ランク {rank} / 100点**\n`{bar}` {score}", inline=True)
    trait_id = monster.get("trait_id") if monster.get("trait_id") in SAFE_TRAITS else "none"
    trait = SAFE_TRAITS[trait_id]
    embed.add_field(name=f"特性 | {trait['name']}", value=trait["description"], inline=False)
    weaknesses = [etype for etype, match in TYPE_CHART.items() if match.get(element, 1) > 1]
    embed.add_field(name="属性", value=f"弱点: {'・'.join(weaknesses) or 'なし'}\n同属性の攻撃技は威力1.5倍。", inline=True)
    for index, move in enumerate(normalize_moves(monster.get("moves")), 1):
        category = {"physical": "物理", "special": "特殊", "status": "変化"}[move["category"]]
        embed.add_field(name=f"{index}. {move['name']} [{move['type']}]", value=f"{category} / 威力 {move['power']} / 命中 {move['accuracy']}\n{str(move.get('description') or '効果説明なし')[:160]}", inline=False)
    embed.add_field(name="モンスターID", value=f"`{monster['id']}`", inline=True)
    embed.add_field(name="操作", value="`/ddd_upgrade` で育成・突破。`/ddd_random_match` で報酬対戦。`/ddd_loadout` で技を変更。", inline=False)
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
        text = f"{self.monster['name']} とお別れしました。" if result.data else "このモンスターはすでにボックスにいません。"
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
        options = [discord.SelectOption(label=f"{monster['name']} (Lv.{monster['current_level']})"[:100], description=f"属性:{monster['element_type']} | ID:{monster['id']}"[:100], value=str(monster["id"])) for monster in rows]
        if options:
            select = discord.ui.Select(placeholder=f"モンスターを選択 | {self.page + 1}/{max(1, (len(self.monsters) + 24) // 25)}ページ", options=options)
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
        await interaction.response.defer()
        result = await asyncio.to_thread(lambda: supabase.table("monsters").select("*").eq("id", selected_id).eq("user_id", self.user_id).execute())
        if not result.data:
            await interaction.followup.send("モンスターが見つかりません。ボックスを開き直してください。", ephemeral=True)
            return
        monster = result.data[0]
        if self.release:
            await interaction.followup.send(content=f"**{monster['name']}** とお別れしますか？削除は取り消せません。", view=ReleaseConfirm(self.user_id, monster), ephemeral=True)
        else:
            await interaction.followup.send(embed=monster_embed(monster))


class TradePartnerCardView(discord.ui.View):
    def __init__(self, cog, trade_id: str, proposer_id: str, partner_id: str, monsters: list):
        super().__init__(timeout=600)
        self.cog, self.trade_id, self.proposer_id, self.partner_id = cog, trade_id, proposer_id, partner_id
        options = [discord.SelectOption(label=f"{monster['name']} (Lv.{monster['current_level']})"[:100], description=f"属性: {monster['element_type']} | ID:{monster['id']}"[:100], value=str(monster["id"])) for monster in monsters[:25]]
        select = discord.ui.Select(placeholder="交換に出すカードを選択", options=options)
        select.callback = self.select_callback
        self.add_item(select)

    async def interaction_check(self, interaction):
        if str(interaction.user.id) != self.partner_id:
            await interaction.response.send_message("交換相手だけがカードを選べます。", ephemeral=True)
            return False
        return True

    async def select_callback(self, interaction):
        card_id = interaction.data["values"][0]
        await interaction.response.defer()
        try:
            trade = await asyncio.to_thread(self.cog.select_trade_partner_card, self.trade_id, self.partner_id, card_id)
        except ValueError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            return
        self.stop()
        view = TradeApprovalView(self.cog, trade)
        await interaction.edit_original_response(content=f"<@{self.proposer_id}> と <@{self.partner_id}> は内容を確認し、双方が承認してください。", embed=self.cog.trade_embed(trade), view=view, allowed_mentions=discord.AllowedMentions(users=[]))
        view.message = interaction.message

    async def on_timeout(self):
        await asyncio.to_thread(self.cog.close_trade_if_active, self.trade_id, "expired")


class TradeOfferSelectView(discord.ui.View):
    def __init__(self, cog, proposer_id: str, partner: discord.User, monsters: list):
        super().__init__(timeout=180)
        self.cog, self.proposer_id, self.partner = cog, proposer_id, partner
        options = [discord.SelectOption(label=f"{monster['name']} (Lv.{monster['current_level']})"[:100], description=f"属性: {monster['element_type']} | ID:{monster['id']}"[:100], value=str(monster["id"])) for monster in monsters[:25]]
        select = discord.ui.Select(placeholder="交換に出すカードを選択", options=options)
        select.callback = self.select_callback
        self.add_item(select)

    async def interaction_check(self, interaction):
        if str(interaction.user.id) != self.proposer_id:
            await interaction.response.send_message("この選択画面は操作できません。", ephemeral=True)
            return False
        return True

    async def select_callback(self, interaction):
        card_id = interaction.data["values"][0]
        await interaction.response.defer()
        try:
            trade, partner_cards = await asyncio.to_thread(self.cog.create_trade, self.proposer_id, str(self.partner.id), card_id)
        except ValueError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            return
        except Exception:
            logging.getLogger(__name__).exception("DDD trade creation failed")
            await interaction.followup.send("トレードを開始できませんでした。", ephemeral=True)
            return
        self.stop()
        if not partner_cards:
            await asyncio.to_thread(self.cog.close_trade_if_active, trade["id"], "cancelled")
            await interaction.edit_original_response(content="相手が交換に出せるカードを持っていないため、トレードを取り消しました。", view=None)
            return
        view = TradePartnerCardView(self.cog, trade["id"], self.proposer_id, str(self.partner.id), partner_cards)
        await interaction.edit_original_response(content=f"<@{self.partner.id}> は交換に出すカードを選んでください。", view=view, allowed_mentions=discord.AllowedMentions(users=[self.partner]))
        view.message = interaction.message


class TradeApprovalView(discord.ui.View):
    def __init__(self, cog, trade: dict):
        super().__init__(timeout=max(30, int((datetime.fromisoformat(str(trade["expires_at"]).replace("Z", "+00:00")) - datetime.now(timezone.utc)).total_seconds())))
        self.cog = cog
        self.trade_id = str(trade["id"])
        self.proposer_id = str(trade["proposer_id"])
        self.partner_id = str(trade["partner_id"])
        self.lock = asyncio.Lock()
        self.message = None

    async def interaction_check(self, interaction):
        if str(interaction.user.id) not in (self.proposer_id, self.partner_id):
            await interaction.response.send_message("トレード参加者だけが操作できます。", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="承認", style=discord.ButtonStyle.success)
    async def approve(self, interaction, button):
        await interaction.response.defer()
        async with self.lock:
            try:
                result = await asyncio.to_thread(self.cog.approve_trade, self.trade_id, str(interaction.user.id))
            except ValueError as exc:
                await interaction.followup.send(str(exc), ephemeral=True)
                return
            except Exception:
                logging.getLogger(__name__).exception("DDD trade approval failed")
                await interaction.followup.send("承認処理に失敗しました。", ephemeral=True)
                return
            if result["completed"]:
                self.stop()
                await interaction.edit_original_response(content="トレードが成立しました。", embed=None, view=None)
            else:
                await interaction.edit_original_response(embed=self.cog.trade_embed(result["trade"]), view=self)

    @discord.ui.button(label="キャンセル", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction, button):
        await interaction.response.defer()
        await asyncio.to_thread(self.cog.close_trade_if_active, self.trade_id, "cancelled")
        self.stop()
        await interaction.edit_original_response(content="トレードをキャンセルしました。", embed=None, view=None)

    async def on_timeout(self):
        await asyncio.to_thread(self.cog.close_trade_if_active, self.trade_id, "expired")
        for child in self.children:
            child.disabled = True
        if self.message:
            try:
                await self.message.edit(content="トレードの承認期限が切れました。", embed=None, view=None)
            except discord.HTTPException:
                pass


class SystemCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def get_user_profile(self, user_id: str) -> dict:
        result = supabase.table("users").select("*").eq("user_id", user_id).execute()
        if result.data:
            return result.data[0]
        created = supabase.table("users").insert({"user_id": user_id, "balance": 0, "max_box_slots": 20}).execute()
        return created.data[0]

    def deduct_coins(self, user_id: str, amount: int, reason: str) -> bool:
        try:
            profile = supabase.table("users").select("balance").eq("user_id", user_id).execute()
            if not profile.data:
                self.get_user_profile(user_id)
                profile = supabase.table("users").select("balance").eq("user_id", user_id).execute()
            balance = int(profile.data[0].get("balance") or 0)
            if balance < amount:
                return False
            changed = (supabase.table("users").update({"balance": balance - amount}).eq("user_id", user_id)
                       .eq("balance", balance).gte("balance", amount).execute())
            if not changed.data:
                return False
            supabase.table("transaction_history").insert({"sender_id": user_id, "receiver_id": "SYSTEM_DDD", "amount": amount, "reason": reason}).execute()
            return True
        except Exception:
            logging.getLogger(__name__).exception("DDD debit failed")
            return False

    def refund_coins(self, user_id: str, amount: int, reason: str) -> bool:
        try:
            profile = self.get_user_profile(user_id)
            balance = int(profile.get("balance") or 0)
            changed = supabase.table("users").update({"balance": balance + amount}).eq("user_id", user_id).eq("balance", balance).execute()
            if not changed.data:
                return False
            supabase.table("transaction_history").insert({"sender_id": "SYSTEM_REFUND", "receiver_id": user_id, "amount": amount, "reason": reason}).execute()
            return True
        except Exception:
            logging.getLogger(__name__).exception("DDD refund failed")
            return False

    def credit_coins(self, user_id: str, amount: int, reason: str) -> bool:
        try:
            profile = self.get_user_profile(user_id)
            balance = int(profile.get("balance") or 0)
            changed = supabase.table("users").update({"balance": balance + amount}).eq("user_id", user_id).eq("balance", balance).execute()
            if not changed.data:
                return False
            supabase.table("transaction_history").insert({"sender_id": "SYSTEM_DDD", "receiver_id": user_id, "amount": amount, "reason": reason}).execute()
            return True
        except Exception:
            logging.getLogger(__name__).exception("DDD credit failed")
            return False

    def trade_embed(self, trade: dict):
        proposer_card = trade.get("proposer_card") or {}
        partner_card = trade.get("partner_card") or {}
        payment = "トレードチケット使用" if trade.get("payment_kind") == "ticket" else f"{TRADE_COST}コイン使用"
        proposer_state = "承認済み" if trade.get("proposer_approved_at") else "未承認"
        partner_state = "承認済み" if trade.get("partner_approved_at") else "未承認"
        embed = discord.Embed(title="DDD トレード確認", description=f"費用: {payment}", color=discord.Color.blurple())
        embed.add_field(name=f"<@{trade['proposer_id']}> が渡すカード", value=f"{proposer_card.get('name', '不明')}\n状態: {proposer_state}", inline=True)
        embed.add_field(name=f"<@{trade['partner_id']}> が渡すカード", value=f"{partner_card.get('name', '不明')}\n状態: {partner_state}", inline=True)
        embed.set_footer(text="双方が承認するとカードを交換します。")
        return embed

    def active_trade_exists(self, user_id: str) -> bool:
        records = (supabase.table("ddd_trades").select("id").in_("status", ["selecting_partner", "awaiting_approval"])
                   .or_(f"proposer_id.eq.{user_id},partner_id.eq.{user_id}").limit(1).execute())
        return bool(records.data)

    def create_trade(self, proposer_id: str, partner_id: str, proposer_card_id: str) -> tuple[dict, list]:
        if self.active_trade_exists(proposer_id) or self.active_trade_exists(partner_id):
            raise ValueError("どちらかがすでに進行中のトレードを持っています。")
        card = supabase.table("monsters").select("id").eq("id", proposer_card_id).eq("user_id", proposer_id).execute()
        if not card.data:
            raise ValueError("交換に出すカードが見つかりません。")
        partner_cards = supabase.table("monsters").select("*").eq("user_id", partner_id).order("created_at", desc=True).limit(25).execute().data
        if not partner_cards:
            raise ValueError("相手が交換に出せるカードを持っていません。")
        payment_kind = "ticket" if item_counts(supabase, proposer_id).get(TRADE_TICKET, 0) else "coin"
        if payment_kind == "coin":
            profile = self.get_user_profile(proposer_id)
            if int(profile.get("balance") or 0) < TRADE_COST:
                raise ValueError(f"トレードには {TRADE_COST} コインまたはトレードチケットが必要です。")
        record = {
            "proposer_id": proposer_id,
            "partner_id": partner_id,
            "proposer_monster_id": proposer_card_id,
            "payment_kind": payment_kind,
            "status": "selecting_partner",
            "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat(),
        }
        created = supabase.table("ddd_trades").insert(record).execute()
        if not created.data:
            raise RuntimeError("トレード記録を作成できませんでした。")
        return created.data[0], partner_cards

    def select_trade_partner_card(self, trade_id: str, partner_id: str, card_id: str) -> dict:
        trade_result = supabase.table("ddd_trades").select("*").eq("id", trade_id).eq("partner_id", partner_id).eq("status", "selecting_partner").execute()
        if not trade_result.data:
            raise ValueError("このトレードは無効または期限切れです。")
        trade = trade_result.data[0]
        if datetime.fromisoformat(str(trade["expires_at"]).replace("Z", "+00:00")) <= datetime.now(timezone.utc):
            self.close_trade_if_active(trade_id, "expired")
            raise ValueError("トレードの選択期限が切れました。")
        card = supabase.table("monsters").select("*").eq("id", card_id).eq("user_id", partner_id).execute()
        if not card.data:
            raise ValueError("交換に出すカードが見つかりません。")
        updated = (supabase.table("ddd_trades").update({"partner_monster_id": card_id, "status": "awaiting_approval"})
                   .eq("id", trade_id).eq("status", "selecting_partner").execute())
        if not updated.data:
            raise ValueError("カード選択が競合しました。最初からやり直してください。")
        prepared = updated.data[0]
        proposer_card = supabase.table("monsters").select("*").eq("id", prepared["proposer_monster_id"]).execute().data
        prepared["proposer_card"] = proposer_card[0] if proposer_card else {}
        prepared["partner_card"] = card.data[0]
        return prepared

    def approve_trade(self, trade_id: str, user_id: str) -> dict:
        trade_result = supabase.table("ddd_trades").select("*").eq("id", trade_id).eq("status", "awaiting_approval").execute()
        if not trade_result.data:
            raise ValueError("このトレードはすでに終了しています。")
        trade = trade_result.data[0]
        if user_id not in (str(trade["proposer_id"]), str(trade["partner_id"])):
            raise ValueError("トレード参加者ではありません。")
        if datetime.fromisoformat(str(trade["expires_at"]).replace("Z", "+00:00")) <= datetime.now(timezone.utc):
            self.close_trade_if_active(trade_id, "expired")
            raise ValueError("トレードの承認期限が切れました。")
        field = "proposer_approved_at" if user_id == str(trade["proposer_id"]) else "partner_approved_at"
        if not trade.get(field):
            updated = supabase.table("ddd_trades").update({field: datetime.now(timezone.utc).isoformat()}).eq("id", trade_id).eq("status", "awaiting_approval").execute()
            if not updated.data:
                raise ValueError("承認が競合しました。もう一度確認してください。")
            trade = updated.data[0]
        if trade.get("proposer_approved_at") and trade.get("partner_approved_at"):
            try:
                finalized = supabase.rpc("ddd_finalize_trade", {"p_trade_id": trade_id}).execute()
            except Exception as exc:
                message = str(exc)
                if "trade_insufficient_coin" in message:
                    raise ValueError(f"トレード成立には提案者のコインが {TRADE_COST} 必要です。") from exc
                if "trade_ticket_missing" in message:
                    raise ValueError("トレードチケットが見つかりません。新しいトレードを開始してください。") from exc
                if "trade_card_owner_changed" in message:
                    raise ValueError("交換対象のカード所有者が変わったため、トレードを中止しました。") from exc
                raise
            if not finalized.data:
                raise RuntimeError("トレード確定に失敗しました。")
            return {"completed": True, "result": finalized.data}
        proposer_card = supabase.table("monsters").select("*").eq("id", trade["proposer_monster_id"]).execute().data
        partner_card = supabase.table("monsters").select("*").eq("id", trade["partner_monster_id"]).execute().data
        trade["proposer_card"] = proposer_card[0] if proposer_card else {}
        trade["partner_card"] = partner_card[0] if partner_card else {}
        return {"completed": False, "trade": trade}

    def close_trade_if_active(self, trade_id: str, status: str) -> None:
        supabase.table("ddd_trades").update({"status": status, "cancelled_at": datetime.now(timezone.utc).isoformat()}).eq("id", trade_id).in_("status", ["selecting_partner", "awaiting_approval"]).execute()

    def apply_upgrade(self, user_id: str, monster_id: str, action: str, amount: int = 0) -> dict:
        found = supabase.table("monsters").select("*").eq("id", monster_id).eq("user_id", user_id).execute()
        if not found.data:
            raise ValueError("指定したモンスターが見つかりません。")
        monster = found.data[0]
        level = int(monster.get("current_level") or 1)
        experience = int(monster.get("current_exp") or 0)
        stage = int(monster.get("breakthrough_stage") or 0)
        if action == "coin_to_exp":
            if amount <= 0:
                raise ValueError("交換するEXPを1以上で指定してください。")
            maximum = experience_space(level, experience, stage)
            if maximum <= 0:
                raise ValueError("このモンスターは現在EXPを受け取れません。")
            if amount > maximum:
                raise ValueError(f"現在交換できるEXPは最大 {maximum} です。")
            required = amount * COINS_PER_EXP
            if not self.deduct_coins(user_id, required, "ddd_upgrade_coin_to_exp"):
                raise ValueError(f"コインが不足しています（必要: {required}）。")
            try:
                new_level, new_exp = add_experience(level, experience, amount, stage)
                updated = (supabase.table("monsters").update({"current_level": new_level, "current_exp": new_exp})
                           .eq("id", monster_id).eq("user_id", user_id).eq("current_level", level).eq("current_exp", experience).execute())
                if not updated.data:
                    raise RuntimeError("モンスター情報が変化しました。")
            except Exception:
                self.refund_coins(user_id, required, "ddd_upgrade_coin_to_exp_refund")
                raise
            return {"action": action, "name": monster["name"], "cost": required, "level": new_level, "exp": new_exp}
        if action == "breakthrough":
            needed = required_breakthrough(level, stage)
            if not needed:
                raise ValueError("現在は突破できません。Lv.30またはLv.40に到達してから実行してください。")
            next_stage, orb_count = needed
            orb_code = ORB_CODES.get(monster.get("element_type"), ORB_CODES["無"])
            consumed = []
            for _ in range(orb_count):
                item = consume_item(supabase, user_id, orb_code)
                if not item:
                    for restored in consumed:
                        restore_item(supabase, restored)
                    raise ValueError(f"{item_label(orb_code)} が {orb_count}個必要です。")
                consumed.append(item)
            next_level = 31 if next_stage == 30 else 41
            try:
                updated = (supabase.table("monsters").update({"breakthrough_stage": next_stage, "current_level": next_level, "current_exp": 0})
                           .eq("id", monster_id).eq("user_id", user_id).eq("current_level", level).eq("breakthrough_stage", stage).execute())
                if not updated.data:
                    raise RuntimeError("モンスター情報が変化しました。")
            except Exception:
                for restored in consumed:
                    restore_item(supabase, restored)
                raise
            return {"action": action, "name": monster["name"], "orb": item_label(orb_code), "count": orb_count, "level": next_level}
        if action == "crystal":
            item = consume_item(supabase, user_id, UPRAISE_CRYSTAL)
            if not item:
                raise ValueError("アップレイズクリスタルを所持していません。")
            boosts = (item.get("metadata") or {}).get("boosts", [])
            if not isinstance(boosts, list) or len(boosts) != 2:
                restore_item(supabase, item)
                raise ValueError("このアップレイズクリスタルの内容が不正です。")
            values = {f"max_{key}": int(monster.get(f"max_{key}") or 10) for key in STAT_KEYS}
            try:
                for boost in boosts:
                    key, increment = boost.get("stat"), int(boost.get("amount"))
                    if key not in STAT_KEYS or not 1 <= increment <= 10:
                        raise ValueError("このアップレイズクリスタルの内容が不正です。")
                    values[f"max_{key}"] += increment
                updated = supabase.table("monsters").update(values).eq("id", monster_id).eq("user_id", user_id).execute()
                if not updated.data:
                    raise RuntimeError("能力値更新に失敗しました。")
            except Exception:
                restore_item(supabase, item)
                raise
            return {"action": action, "name": monster["name"], "crystal": item_label(UPRAISE_CRYSTAL, item.get("metadata"))}
        raise ValueError("育成内容が不正です。")

    @app_commands.command(name="ddd_box", description="所持モンスター一覧を確認します")
    @app_commands.describe(search="名前の部分一致", element="属性で絞り込む", order="並び順")
    @app_commands.choices(element=[app_commands.Choice(name=element, value=element) for element in TYPE_CHART], order=[app_commands.Choice(name="新しい順", value="created_at"), app_commands.Choice(name="レベル順", value="current_level"), app_commands.Choice(name="才能順", value="dice_talent")])
    async def show_box(self, interaction: discord.Interaction, search: str = "", element: str = "", order: str = "created_at"):
        user_id = str(interaction.user.id)
        await interaction.response.defer()
        profile = await asyncio.to_thread(self.get_user_profile, user_id)
        result = await asyncio.to_thread(lambda: supabase.table("monsters").select("*").eq("user_id", user_id).order(order, desc=True).execute())
        all_monsters = result.data or []
        monsters = [monster for monster in all_monsters if search.casefold() in monster["name"].casefold() and (not element or monster["element_type"] == element)]
        embed = discord.Embed(title=f"DDD COLLECTION | {len(all_monsters)}/{profile['max_box_slots']}", color=0x45E1AD, description=f"表示 {len(monsters)}匹。モンスターを選んで詳細を確認できます。")
        if not monsters:
            embed.description = "条件に合うモンスターがいません。`/ddd_scout` で新しいモンスターを迎えてください。"
            await interaction.followup.send(embed=embed)
            return
        if monsters[0].get("image_url"):
            embed.set_thumbnail(url=monsters[0]["image_url"])
        embed.add_field(name="コレクションの属性", value=" / ".join(f"{etype}: {sum(monster['element_type'] == etype for monster in all_monsters)}" for etype in TYPE_CHART), inline=False)
        await interaction.followup.send(embed=embed, view=MonsterSelectView(user_id, monsters))

    @app_commands.command(name="ddd_expand_box", description="1000コインでボックス容量を5枠拡張します")
    async def expand_box(self, interaction: discord.Interaction):
        user_id = str(interaction.user.id)
        await interaction.response.defer()
        profile = await asyncio.to_thread(self.get_user_profile, user_id)
        if not await asyncio.to_thread(self.deduct_coins, user_id, EXPAND_BOX_COST, "box_expansion"):
            await interaction.followup.send(f"コインが不足しています（所持: {profile['balance']} / 必要: {EXPAND_BOX_COST}）。")
            return
        new_slots = int(profile["max_box_slots"]) + 5
        updated = await asyncio.to_thread(lambda: supabase.table("users").update({"max_box_slots": new_slots}).eq("user_id", user_id).eq("max_box_slots", profile["max_box_slots"]).execute())
        if not updated.data:
            await asyncio.to_thread(self.refund_coins, user_id, EXPAND_BOX_COST, "box_expansion_refund")
            await interaction.followup.send("ボックス容量の更新に失敗したため、コインを返却しました。", ephemeral=True)
            return
        await interaction.followup.send(f"ボックス容量を {profile['max_box_slots']} → {new_slots} 匹へ拡張しました。")

    @app_commands.command(name="ddd_profile", description="所持コイン、宝箱、アイテムを確認します")
    async def profile(self, interaction: discord.Interaction):
        user_id = str(interaction.user.id)
        await interaction.response.defer()
        profile = await asyncio.to_thread(self.get_user_profile, user_id)
        count_result = await asyncio.to_thread(lambda: supabase.table("monsters").select("id", count="exact").eq("user_id", user_id).execute())
        chest_result = await asyncio.to_thread(lambda: supabase.table("ddd_chests").select("id", count="exact").eq("user_id", user_id).is_("opened_at", "null").execute())
        counts = await asyncio.to_thread(item_counts, supabase, user_id)
        item_lines = [f"{item_label(code)}: {count}" for code, count in counts.items()]
        embed = discord.Embed(title=f"{interaction.user.display_name} のプレイヤーデータ", color=discord.Color.purple())
        embed.set_thumbnail(url=interaction.user.display_avatar.url)
        embed.add_field(name="所持コイン", value=str(profile.get("balance") or 0), inline=True)
        embed.add_field(name="ボックス使用量", value=f"{count_result.count if count_result.count is not None else 0} / {profile['max_box_slots']}匹", inline=True)
        embed.add_field(name="未開封の宝箱", value=str(chest_result.count if chest_result.count is not None else 0), inline=True)
        embed.add_field(name="アイテム", value="\n".join(item_lines) if item_lines else "なし", inline=False)
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="ddd_open", description="所持している宝箱をすべて開封します")
    async def open_chests(self, interaction: discord.Interaction):
        user_id = str(interaction.user.id)
        await interaction.response.defer()
        chests = await asyncio.to_thread(lambda: supabase.table("ddd_chests").select("*").eq("user_id", user_id).is_("opened_at", "null").order("created_at").execute().data)
        if not chests:
            await interaction.followup.send("開封できる宝箱はありません。")
            return
        total_coins = 0
        items: list[str] = []
        opened = 0
        for chest in chests:
            reward = roll_chest_reward()
            marked = await asyncio.to_thread(lambda chest_id=chest["id"]: supabase.table("ddd_chests").update({"opened_at": datetime.now(timezone.utc).isoformat()}).eq("id", chest_id).eq("user_id", user_id).is_("opened_at", "null").execute())
            if not marked.data:
                continue
            opened += 1
            if reward["kind"] == "coin":
                total_coins += reward["amount"]
            else:
                item = await asyncio.to_thread(add_item, supabase, user_id, reward["item_code"], reward.get("metadata"))
                items.append(item_label(item["item_code"], item.get("metadata")))
        if total_coins:
            credited = await asyncio.to_thread(self.credit_coins, user_id, total_coins, "ddd_chest_open_coin")
            if not credited:
                await interaction.followup.send("宝箱は開封されましたが、コインの加算に失敗しました。管理者へ連絡してください。", ephemeral=True)
                return
        summary = [f"開封数: {opened}"]
        if total_coins:
            summary.append(f"コイン: +{total_coins}")
        if items:
            counts: dict[str, int] = {}
            for label in items:
                counts[label] = counts.get(label, 0) + 1
            summary.append("アイテム:\n" + "\n".join(f"{label} ×{count}" for label, count in counts.items()))
        await interaction.followup.send("\n".join(summary))

    @app_commands.command(name="ddd_upgrade", description="コインからEXPへの交換、突破、クリスタル使用を行います")
    @app_commands.describe(monster_id="ボックス詳細のモンスターID", action="育成内容", amount="コインからEXPへの交換量。ほかの操作では省略")
    @app_commands.choices(action=[
        app_commands.Choice(name="コインからEXPへ交換（1EXP=50コイン）", value="coin_to_exp"),
        app_commands.Choice(name="属性オーブで突破", value="breakthrough"),
        app_commands.Choice(name="アップレイズクリスタルを使用", value="crystal"),
    ])
    async def upgrade(self, interaction: discord.Interaction, monster_id: str, action: str, amount: int = 0):
        await interaction.response.defer(ephemeral=True)
        try:
            result = await asyncio.to_thread(self.apply_upgrade, str(interaction.user.id), monster_id, action, amount)
        except (ValueError, RuntimeError) as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            return
        if result["action"] == "coin_to_exp":
            message = f"**{result['name']}** にEXPを交換しました。\n消費コイン: {result['cost']}\n現在: Lv.{result['level']} / EXP {result['exp']}"
        elif result["action"] == "breakthrough":
            message = f"**{result['name']}** を突破しました。{result['orb']}を{result['count']}個使用し、Lv.{result['level']}から再開します。"
        else:
            message = f"**{result['name']}** に {result['crystal']} を使用しました。"
        await interaction.followup.send(message, ephemeral=True)

    @app_commands.command(name="ddd_release_monster", description="モンスターとお別れします。確認後に削除します")
    async def release_monster(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        user_id = str(interaction.user.id)
        monsters = await asyncio.to_thread(lambda: supabase.table("monsters").select("id,name,element_type,current_level").eq("user_id", user_id).order("created_at", desc=True).execute().data)
        if not monsters:
            await interaction.followup.send("お別れできるモンスターはいません。", ephemeral=True)
            return
        await interaction.followup.send("モンスターを選ぶと確認画面が開きます。削除は取り消せません。", view=MonsterSelectView(user_id, monsters, release=True), ephemeral=True)

    @app_commands.command(name="ddd_rename_monster", description="300コインでモンスター名を変更します")
    @app_commands.describe(monster_id="ボックス詳細のモンスターID", new_name="新しい名前（1〜20文字）")
    async def rename_monster(self, interaction: discord.Interaction, monster_id: str, new_name: str):
        new_name = new_name.strip()
        if not 1 <= len(new_name) <= MAX_RENAME_LENGTH:
            await interaction.response.send_message(f"名前は1〜{MAX_RENAME_LENGTH}文字で入力してください。", ephemeral=True)
            return
        user_id = str(interaction.user.id)
        await interaction.response.defer(ephemeral=True)
        found = await asyncio.to_thread(lambda: supabase.table("monsters").select("id,name").eq("id", monster_id).eq("user_id", user_id).execute())
        if not found.data:
            await interaction.followup.send("指定したモンスターが見つかりません。", ephemeral=True)
            return
        old_name = found.data[0]["name"]
        if old_name == new_name:
            await interaction.followup.send("現在と同じ名前です。", ephemeral=True)
            return
        if not await asyncio.to_thread(self.deduct_coins, user_id, RENAME_MONSTER_COST, "rename_monster"):
            await interaction.followup.send(f"コインが不足しています（必要: {RENAME_MONSTER_COST}）。", ephemeral=True)
            return
        updated = await asyncio.to_thread(lambda: supabase.table("monsters").update({"name": new_name}).eq("id", monster_id).eq("user_id", user_id).eq("name", old_name).execute())
        if not updated.data:
            await asyncio.to_thread(self.refund_coins, user_id, RENAME_MONSTER_COST, "rename_monster_refund")
            await interaction.followup.send("名前変更に失敗したため、コインを返却しました。", ephemeral=True)
            return
        await interaction.followup.send(f"**{old_name}** を **{new_name}** に変更しました。", ephemeral=True)

    @app_commands.command(name="ddd_rename_move", description="200コインで技名を変更します")
    @app_commands.describe(monster_id="ボックス詳細のモンスターID", move_slot="変更する技スロット", new_name="新しい技名（1〜20文字）")
    @app_commands.choices(move_slot=[app_commands.Choice(name=f"技{i}", value=i) for i in (1, 2, 3)])
    async def rename_move(self, interaction: discord.Interaction, monster_id: str, move_slot: int, new_name: str):
        new_name = new_name.strip()
        if move_slot not in (1, 2, 3) or not 1 <= len(new_name) <= MAX_RENAME_LENGTH:
            await interaction.response.send_message("技スロットは1〜3、名前は1〜20文字で指定してください。", ephemeral=True)
            return
        user_id = str(interaction.user.id)
        await interaction.response.defer(ephemeral=True)
        found = await asyncio.to_thread(lambda: supabase.table("monsters").select("name,moves").eq("id", monster_id).eq("user_id", user_id).execute())
        if not found.data:
            await interaction.followup.send("指定したモンスターが見つかりません。", ephemeral=True)
            return
        monster = found.data[0]
        old_moves = monster.get("moves") or []
        moves = normalize_moves(old_moves)
        old_name = moves[move_slot - 1]["name"]
        if old_name == new_name:
            await interaction.followup.send("現在と同じ技名です。", ephemeral=True)
            return
        if not await asyncio.to_thread(self.deduct_coins, user_id, RENAME_MOVE_COST, f"rename_move_{move_slot}"):
            await interaction.followup.send(f"コインが不足しています（必要: {RENAME_MOVE_COST}）。", ephemeral=True)
            return
        moves[move_slot - 1]["name"] = new_name
        updated = await asyncio.to_thread(lambda: supabase.table("monsters").update({"moves": moves}).eq("id", monster_id).eq("user_id", user_id).execute())
        if not updated.data:
            await asyncio.to_thread(self.refund_coins, user_id, RENAME_MOVE_COST, "rename_move_refund")
            await interaction.followup.send("技名変更に失敗したため、コインを返却しました。", ephemeral=True)
            return
        await interaction.followup.send(f"**{monster['name']}** の技{move_slot}を **{new_name}** に変更しました。", ephemeral=True)

    @app_commands.command(name="ddd_rename_ability", description="250コインで特性の表示名・説明を変更します")
    @app_commands.describe(monster_id="ボックス詳細のモンスターID", new_ability="新しい特性名・説明（1〜60文字）")
    async def rename_ability(self, interaction: discord.Interaction, monster_id: str, new_ability: str):
        new_ability = new_ability.strip()
        if not 1 <= len(new_ability) <= MAX_ABILITY_LENGTH:
            await interaction.response.send_message(f"特性名・説明は1〜{MAX_ABILITY_LENGTH}文字で入力してください。", ephemeral=True)
            return
        user_id = str(interaction.user.id)
        await interaction.response.defer(ephemeral=True)
        found = await asyncio.to_thread(lambda: supabase.table("monsters").select("name,characteristic").eq("id", monster_id).eq("user_id", user_id).execute())
        if not found.data:
            await interaction.followup.send("指定したモンスターが見つかりません。", ephemeral=True)
            return
        monster = found.data[0]
        if monster.get("characteristic") == new_ability:
            await interaction.followup.send("現在と同じ特性名・説明です。", ephemeral=True)
            return
        if not await asyncio.to_thread(self.deduct_coins, user_id, RENAME_ABILITY_COST, "rename_ability"):
            await interaction.followup.send(f"コインが不足しています（必要: {RENAME_ABILITY_COST}）。", ephemeral=True)
            return
        updated = await asyncio.to_thread(lambda: supabase.table("monsters").update({"characteristic": new_ability}).eq("id", monster_id).eq("user_id", user_id).execute())
        if not updated.data:
            await asyncio.to_thread(self.refund_coins, user_id, RENAME_ABILITY_COST, "rename_ability_refund")
            await interaction.followup.send("特性変更に失敗したため、コインを返却しました。", ephemeral=True)
            return
        await interaction.followup.send(f"**{monster['name']}** の特性表示を変更しました。", ephemeral=True)

    @app_commands.command(name="ddd_reroll_move", description="技の威力・命中を振り直します")
    @app_commands.describe(monster_id="ボックス詳細のモンスターID", move_slot="振り直す技スロット")
    @app_commands.choices(move_slot=[app_commands.Choice(name=f"技{i}", value=i) for i in (1, 2, 3)])
    async def reroll_move(self, interaction: discord.Interaction, monster_id: str, move_slot: int):
        if move_slot not in (1, 2, 3):
            await interaction.response.send_message("技スロットは1〜3で指定してください。", ephemeral=True)
            return
        user_id = str(interaction.user.id)
        await interaction.response.defer(ephemeral=True)
        found = await asyncio.to_thread(lambda: supabase.table("monsters").select("*").eq("id", monster_id).eq("user_id", user_id).execute())
        if not found.data:
            await interaction.followup.send("指定したモンスターが見つかりません。", ephemeral=True)
            return
        monster = found.data[0]
        moves = normalize_moves(monster.get("moves"))
        move = dict(moves[move_slot - 1])
        if move.get("category") == "status":
            await interaction.followup.send("変化技には振り直しを適用できません。攻撃技を選んでください。", ephemeral=True)
            return
        ticket = await asyncio.to_thread(consume_item, supabase, user_id, MOVE_RESET_TICKET)
        charged = False
        if not ticket:
            charged = await asyncio.to_thread(self.deduct_coins, user_id, MOVE_REROLL_COST, f"reroll_move_{move_slot}")
            if not charged:
                await interaction.followup.send(f"コインが不足しています（必要: {MOVE_REROLL_COST}）。", ephemeral=True)
                return
        move["power"] = random.randint(60, 110)
        move["accuracy"] = random.randint(50, 100)
        moves[move_slot - 1] = move
        try:
            updated = await asyncio.to_thread(lambda: supabase.table("monsters").update({"moves": moves}).eq("id", monster_id).eq("user_id", user_id).execute())
            if not updated.data:
                raise RuntimeError("技データの保存に失敗しました。")
        except Exception:
            if ticket:
                await asyncio.to_thread(restore_item, supabase, ticket)
            elif charged:
                await asyncio.to_thread(self.refund_coins, user_id, MOVE_REROLL_COST, "reroll_move_refund")
            await interaction.followup.send("振り直しに失敗したため、消費分を返却しました。", ephemeral=True)
            return
        payment = "技リセットチケットを使用" if ticket else f"{MOVE_REROLL_COST}コイン使用"
        await interaction.followup.send(f"**{monster['name']}** の技{move_slot}を振り直しました。\n威力 {move['power']} / 命中 {move['accuracy']}\n{payment}", ephemeral=True)

    @app_commands.command(name="ddd_loadout", description="モンスターの技1枠を変更します")
    @app_commands.describe(monster_id="ボックス詳細のモンスターID", slot="変更する技枠", technique="覚える技")
    @app_commands.choices(slot=[app_commands.Choice(name=f"技{i}", value=i) for i in (1, 2, 3)], technique=[app_commands.Choice(name=f"{name}：{data['description']}"[:100], value=name) for name, data in TECHNIQUES.items()])
    async def loadout(self, interaction: discord.Interaction, monster_id: str, slot: int, technique: str):
        if slot not in (1, 2, 3) or technique not in TECHNIQUES:
            await interaction.response.send_message("技枠と技を選択してください。", ephemeral=True)
            return
        user_id = str(interaction.user.id)
        await interaction.response.defer()
        found = await asyncio.to_thread(lambda: supabase.table("monsters").select("*").eq("id", monster_id).eq("user_id", user_id).execute())
        if not found.data:
            await interaction.followup.send("モンスターが見つかりません。", ephemeral=True)
            return
        monster = found.data[0]
        moves = normalize_moves(monster.get("moves"))
        moves[slot - 1] = {"name": technique, "type": monster["element_type"], "power": 0, "accuracy": 100, **TECHNIQUES[technique]}
        updated = await asyncio.to_thread(lambda: supabase.table("monsters").update({"moves": moves}).eq("id", monster_id).eq("user_id", user_id).execute())
        if not updated.data:
            await interaction.followup.send("技の変更に失敗しました。", ephemeral=True)
            return
        monster["moves"] = moves
        await interaction.followup.send(content="技を変更しました。進行中の対戦には反映されず、次の対戦から有効です。", embed=monster_embed(monster))

    @app_commands.command(name="ddd_trade", description="5000コインまたはチケットでカードをプレイヤー同士で交換します")
    @app_commands.describe(opponent="トレードする相手")
    async def trade(self, interaction: discord.Interaction, opponent: discord.User):
        user_id = str(interaction.user.id)
        if opponent.bot or str(opponent.id) == user_id:
            await interaction.response.send_message("自分またはBotとはトレードできません。", ephemeral=True)
            return
        await interaction.response.defer()
        if await asyncio.to_thread(self.active_trade_exists, user_id) or await asyncio.to_thread(self.active_trade_exists, str(opponent.id)):
            await interaction.followup.send("どちらかがすでに進行中のトレードを持っています。", ephemeral=True)
            return
        monsters = await asyncio.to_thread(lambda: supabase.table("monsters").select("*").eq("user_id", user_id).order("created_at", desc=True).limit(25).execute().data)
        if not monsters:
            await interaction.followup.send("トレードに出せるモンスターを持っていません。", ephemeral=True)
            return
        await interaction.followup.send(f"<@{opponent.id}> へ渡すカードを選んでください。トレードチケットを所持している場合は、成立時に自動使用します。", view=TradeOfferSelectView(self, user_id, opponent, monsters), allowed_mentions=discord.AllowedMentions(users=[]))

    @app_commands.command(name="ddd_guide", description="DDDの遊び方を確認します")
    async def guide(self, interaction: discord.Interaction):
        embed = discord.Embed(title="DDD ガイド", description="画像からモンスターをスカウトし、育成・対戦・交換を楽しむゲームです。", color=0x45E1AD)
        embed.add_field(name="モンスターを迎える", value="`/ddd_scout` は通常またはウルトラスカウトを選べます。`/ddd_legend_scout` は高品質な個体を狙うスカウトです。", inline=False)
        embed.add_field(name="育成と宝箱", value="`/ddd_work` の通常作業ではコインとEXPを獲得し、25%の確率で宝箱を入手します。トレーニングは1時間でEXP 500を獲得します。`/ddd_open` で宝箱をすべて開封できます。", inline=False)
        embed.add_field(name="突破とアイテム", value="Lv.30では対応属性のオーブ1個、Lv.40では10個を使い、`/ddd_upgrade` で突破します。突破後はそれぞれLv.31・Lv.41から成長を再開します。", inline=False)
        embed.add_field(name="対戦とトレード", value="`/ddd_battle` で3対3の対人戦、`/ddd_random_match` で報酬対戦ができます。`/ddd_trade` は双方のカード選択と承認で交換します。", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot):
    await bot.add_cog(SystemCog(bot))
