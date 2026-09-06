import asyncio
import copy
import logging
import os
import random

import discord
from discord import app_commands
from discord.ext import commands
from supabase import create_client, Client

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
logger = logging.getLogger(__name__)

TYPE_CHART = {
    "虚": {"実": 2.0, "虚": 0.5}, "実": {"虚": 2.0, "実": 0.5},
    "正": {"負": 2.0, "正": 0.5}, "負": {"正": 2.0, "負": 0.5}, "無": {},
}
STAT_KEYS = ("hp", "attack", "defense", "sp_atk", "sp_def", "speed")
MAX_ACTIONS = 80


def integer(value, default=0, low=0, high=9999):
    try:
        return max(low, min(high, int(value)))
    except (ValueError, TypeError, OverflowError):
        return default


def calc_stat(max_stat: int, level: int) -> int:
    """Preserve the existing 20% base growth curve; clamp legacy data safely."""
    return max(1, int(integer(max_stat, 10, 1) * (0.2 + 0.8 * integer(level, 1, 1, 30) / 30)))


def get_type_multiplier(atk_type: str, def_type: str) -> float:
    return TYPE_CHART.get(atk_type, {}).get(def_type, 1.0)


def rank_multiplier(rank):
    rank = integer(rank, 0, -6, 6)
    return (2 + rank) / 2 if rank >= 0 else 2 / (2 - rank)


def normalize_moves(moves):
    source = moves if isinstance(moves, list) else []
    result = []
    for index in range(3):
        move = dict(source[index]) if index < len(source) and isinstance(source[index], dict) else {}
        category = move.get("category", "physical")
        if category not in ("physical", "special", "status"):
            category = "physical"
        result.append({**move, "name": str(move.get("name") or "たいあたり")[:20],
                       "type": move.get("type") if move.get("type") in TYPE_CHART else "無",
                       "category": category,
                       "power": 0 if category == "status" else integer(move.get("power", 40), 40, 1, 120),
                       "accuracy": integer(move.get("accuracy", 100), 100, 1, 100)})
    return result


def prepare_party(party):
    party = copy.deepcopy(party)
    for monster in party:
        monster["current_level"] = integer(monster.get("current_level"), 1, 1, 30)
        for key in STAT_KEYS:
            monster[f"max_{key}"] = integer(monster.get(f"max_{key}"), 10, 1)
        monster["moves"] = normalize_moves(monster.get("moves"))
        monster["current_hp"] = calc_stat(monster["max_hp"], monster["current_level"])
        monster.update(ranks={}, guarding=False, poison=0, heals=3)
    return party


def calculate_damage(attacker, defender, move, rng=None, critical=False):
    rng = rng or random
    mult = get_type_multiplier(move.get("type", "無"), defender["element_type"])
    if move.get("category") == "status":
        return 0, mult
    atk_key, def_key = ("sp_atk", "sp_def") if move.get("category") == "special" else ("attack", "defense")
    atk = calc_stat(attacker[f"max_{atk_key}"], attacker["current_level"]) * rank_multiplier(attacker.get("ranks", {}).get(atk_key, 0))
    defense = calc_stat(defender[f"max_{def_key}"], defender["current_level"]) * rank_multiplier(defender.get("ranks", {}).get(def_key, 0))
    power = integer(move.get("power", 40), 40, 1, 120)
    base = ((attacker["current_level"] * 2 / 5 + 2) * power * atk / max(1, defense)) / 50 + 2
    stab = 1.5 if move.get("type") == attacker["element_type"] else 1.0
    return max(1, int(base * mult * stab * rng.uniform(0.85, 1) * (1.5 if critical else 1) * (0.5 if defender.get("guarding") else 1))), mult


def add_experience(level, experience, amount):
    level = integer(level, 1, 1, 30)
    total = integer(experience) + max(0, amount)
    while total >= 100 and level < 30:
        level += 1
        total -= 100
    return level, 0 if level == 30 else total


def hp_bar(monster):
    maximum = calc_stat(monster["max_hp"], monster["current_level"])
    hp = integer(monster.get("current_hp"), maximum, 0, maximum)
    filled = max(1, round(hp / maximum * 12)) if hp else 0
    return f"`{'█' * filled}{'░' * (12 - filled)}` {hp}/{maximum}"


def resolve_action(state, side, action, rng=None):
    rng = rng or random
    other = "p2" if side == "p1" else "p1"
    team, enemy = state[side], state[other]
    actor = team["party"][team["active_idx"]]
    target = enemy["party"][enemy["active_idx"]]
    if actor["current_hp"] <= 0:
        raise ValueError("倒れている相棒は行動できません。")
    if action.startswith("switch:"):
        index = integer(action.split(":", 1)[1], -1, -1, 99)
        if index < 0 or index >= len(team["party"]) or index == team["active_idx"] or team["party"][index]["current_hp"] <= 0:
            raise ValueError("その相棒には交代できません。")
    elif action not in ("guard", "surrender"):
        index = integer(action, -1, -1, 99)
        if index not in range(3):
            raise ValueError("技は1〜3から選んでください。")
    logs = state.setdefault("logs", [])
    actor["guarding"] = False
    if action == "surrender":
        logs.append(f"{side.upper()} が降参しました。")
        return other
    if action.startswith("switch:"):
        actor["ranks"] = {}
        team["active_idx"] = index
        logs.append(f"{actor['name']} → {team['party'][index]['name']} に交代！")
    elif action == "guard":
        actor["guarding"] = True
        logs.append(f"{actor['name']} は防御。次の被ダメージを半減！")
    else:
        move = actor["moves"][index]
        if rng.random() * 100 >= move["accuracy"]:
            logs.append(f"{actor['name']} の {move['name']} は外れた！")
        elif move["category"] == "status":
            effect = move.get("effect")
            if effect == "heal":
                maximum = calc_stat(actor["max_hp"], actor["current_level"])
                if actor["heals"] > 0:
                    recovered = min(maximum - actor["current_hp"], max(1, maximum // 4))
                    actor["current_hp"] += recovered
                    actor["heals"] -= 1
                    logs.append(f"{actor['name']} はHPを{recovered}回復！ 残り{actor['heals']}回")
                else:
                    logs.append(f"{move['name']} は回数切れ。回復できなかった。")
            elif effect in ("attack_up", "defense_up", "sp_atk_up", "sp_def_up"):
                key = effect[:-3]
                actor["ranks"][key] = min(6, actor["ranks"].get(key, 0) + 1)
                logs.append(f"{actor['name']} の {key} が1段階上昇！")
            elif effect == "poison":
                target["poison"] = 3
                logs.append(f"{target['name']} は毒状態に！ 行動後3回ダメージ。")
            elif effect == "guard":
                actor["guarding"] = True
                logs.append(f"{actor['name']} は {move['name']} で防御！")
            else:
                logs.append(f"{move['name']}：未対応の変化効果です（ダメージなし）。")
        else:
            critical = rng.random() < 1 / 16
            damage, mult = calculate_damage(actor, target, move, rng, critical)
            target["current_hp"] = max(0, target["current_hp"] - damage)
            target["guarding"] = False
            notes = (" 急所！" if critical else "") + (" 弱点！" if mult > 1 else " 耐性あり" if mult < 1 else "")
            logs.append(f"{actor['name']} の {move['name']} → {target['name']} に{damage}！{notes}")
    if actor.get("poison", 0) and actor["current_hp"] > 0:
        damage = max(1, calc_stat(actor["max_hp"], actor["current_level"]) // 8)
        actor["current_hp"] = max(0, actor["current_hp"] - damage)
        actor["poison"] -= 1
        logs.append(f"{actor['name']} に毒のダメージ {damage}")
    alive = {}
    for key in ("p1", "p2"):
        party = state[key]["party"]
        indices = [i for i, m in enumerate(party) if m["current_hp"] > 0]
        alive[key] = bool(indices)
        if indices and party[state[key]["active_idx"]]["current_hp"] <= 0:
            state[key]["active_idx"] = indices[0]
            logs.append(f"{party[indices[0]]['name']} が自動出場！")
    state["version"] = state.get("version", 0) + 1
    state["logs"] = logs[-12:]
    if not alive["p1"] and not alive["p2"]:
        return "draw"
    if not alive["p1"]:
        return "p2"
    if not alive["p2"]:
        return "p1"
    return "draw" if state["version"] >= MAX_ACTIONS else None


def battle_embed(state, practice=False):
    embed = discord.Embed(title=f"DDD {'PRACTICE' if practice else 'ARENA'} | TURN {state.get('version', 0) + 1}", color=0x8B7CF8,
                          description="\n".join(state["logs"][-5:])[:3000])
    for side in ("p1", "p2"):
        team = state[side]
        active = team["party"][team["active_idx"]]
        effects = (" / 防御" if active.get("guarding") else "") + (f" / 毒{active['poison']}" if active.get("poison") else "")
        reserve = "\n".join(f"{'>' if i == team['active_idx'] else '-'} {m['name']} {'戦闘不能' if m['current_hp'] <= 0 else str(m['current_hp']) + ' HP'}" for i, m in enumerate(team["party"]))
        embed.add_field(name=f"{side.upper()} | {active['name']} Lv.{active['current_level']} [{active['element_type']}]"[:256],
                        value=f"{hp_bar(active)}{effects}\n{reserve}"[:1024], inline=True)
    first = state["p1"]["party"][state["p1"]["active_idx"]]
    second = state["p2"]["party"][state["p2"]["active_idx"]]
    if first.get("image_url"):
        embed.set_image(url=first["image_url"])
    if second.get("image_url"):
        embed.set_thumbnail(url=second["image_url"])
    embed.set_footer(text="一致属性×1.5 / 虚⇔実・正⇔負が弱点 / 防御は半減 / 交代も1手 / 80手で引き分け")
    return embed


class BattleView(discord.ui.View):
    def __init__(self, cog, battle_id, state, turn_user_id, p1_id, p2_id, practice=False):
        super().__init__(timeout=180)
        self.cog, self.battle_id, self.state = cog, battle_id, state
        self.turn_user_id, self.p1_id, self.p2_id = turn_user_id, p1_id, p2_id
        self.practice, self.version = practice, state.get("version", 0)
        self.lock = asyncio.Lock()
        self.used = False
        self.message = None
        side = "p1" if turn_user_id == p1_id else "p2"
        team = state[side]
        for idx, move in enumerate(team["party"][team["active_idx"]]["moves"]):
            effect = move.get("effect", "変化") if move["category"] == "status" else f"威{move['power']}"
            button = discord.ui.Button(label=f"{move['name']} [{move['type']}] {effect} / 命{move['accuracy']}"[:80], style=discord.ButtonStyle.primary, row=0)
            button.callback = self.callback_for(str(idx))
            self.add_item(button)
        for label, action in (("防御", "guard"), ("降参", "surrender")):
            button = discord.ui.Button(label=label, style=discord.ButtonStyle.secondary, row=1)
            button.callback = self.callback_for(action)
            self.add_item(button)
        for index, monster in enumerate(team["party"]):
            if index != team["active_idx"] and monster["current_hp"] > 0:
                button = discord.ui.Button(label=f"交代: {monster['name']}"[:80], row=2)
                button.callback = self.callback_for(f"switch:{index}")
                self.add_item(button)

    def callback_for(self, action):
        async def callback(interaction):
            await self.execute_turn(interaction, action)
        return callback

    async def execute_turn(self, interaction, action):
        if str(interaction.user.id) != self.turn_user_id:
            await interaction.response.send_message("あなたのターンではありません。", ephemeral=True)
            return
        await interaction.response.defer()
        async with self.lock:
            if self.used or self.is_finished():
                await interaction.followup.send("このターンは処理済み、または期限切れです。", ephemeral=True)
                return
            state = copy.deepcopy(self.state)
            side = "p1" if self.turn_user_id == self.p1_id else "p2"
            try:
                winner = resolve_action(state, side, action)
                if self.practice and winner is None:
                    cpu = state["p2"]["party"][state["p2"]["active_idx"]]
                    healing = next((i for i, m in enumerate(cpu["moves"]) if m.get("effect") == "heal"), None)
                    hurt = cpu["current_hp"] < calc_stat(cpu["max_hp"], cpu["current_level"]) // 2
                    choice = healing if healing is not None and hurt and cpu["heals"] else random.choice([i for i, m in enumerate(cpu["moves"]) if m["category"] != "status"] or [0])
                    winner = resolve_action(state, "p2", str(choice))
                next_id = self.p1_id if self.practice or side == "p2" else self.p2_id
                if winner:
                    state["logs"].append("引き分け！" if winner == "draw" else f"{winner.upper()} の勝利！")
                    state["winner"] = winner
                if not self.practice:
                    updated = await asyncio.to_thread(self.save_turn, state, next_id, winner is not None)
                    if not updated:
                        self.used = True
                        await interaction.followup.send("古い操作です。最新の対戦画面か /ddd_resume を使用してください。", ephemeral=True)
                        return
            except ValueError as exc:
                await interaction.followup.send(str(exc), ephemeral=True)
                return
            except Exception:
                logger.exception("DDD battle update failed")
                await interaction.followup.send("対戦更新に失敗しました。/ddd_resume で最新状態を確認してください。", ephemeral=True)
                return
            self.used = True
            self.stop()
            if winner:
                if not self.practice:
                    self.cog.busy.difference_update((self.p1_id, self.p2_id))
                if not self.practice and winner != "draw":
                    try:
                        await asyncio.to_thread(self.award_exp, state[winner]["party"])
                        state["logs"].append("勝利パーティ全員に50 EXP。100 EXPでLv.UP（上限30）。")
                    except Exception:
                        logger.exception("DDD reward failed for battle %s", self.battle_id)
                        state["logs"].append("経験値の保存に失敗しました。管理者へ対戦IDを連絡してください。")
                view = None
            else:
                view = BattleView(self.cog, self.battle_id, state, next_id, self.p1_id, self.p2_id, self.practice)
            await interaction.edit_original_response(content="対戦終了" if winner else f"<@{next_id}> のターン", embed=battle_embed(state, self.practice), view=view,
                                                     allowed_mentions=discord.AllowedMentions.none())
            if view:
                view.message = interaction.message

    def save_turn(self, state, next_id, finished):
        query = supabase.table("battles").update({"battle_state": state, "turn_user_id": next_id, "is_finished": finished})
        return query.eq("id", self.battle_id).eq("is_finished", False).eq("turn_user_id", self.turn_user_id).eq("battle_state->>version", str(self.version)).execute().data

    def award_exp(self, party):
        for monster in party:
            result = supabase.table("monsters").select("current_level,current_exp").eq("id", monster["id"]).eq("user_id", monster["user_id"]).execute()
            if not result.data:
                continue
            old = result.data[0]
            level, exp = add_experience(old["current_level"], old.get("current_exp", 0), 50)
            updated = supabase.table("monsters").update({"current_level": level, "current_exp": exp}).eq("id", monster["id"]).eq("user_id", monster["user_id"]).eq("current_level", old["current_level"]).eq("current_exp", old.get("current_exp", 0)).execute()
            if not updated.data:
                raise RuntimeError("Concurrent EXP update; manual reconciliation needed")

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        if self.message:
            try:
                await self.message.edit(content="操作期限切れ。対人戦は /ddd_resume で再開できます。練習戦は /ddd_practice でやり直せます。", view=self)
            except discord.HTTPException:
                pass


# --- パーティ選出用コンポーネント ---

class PartyDropdown(discord.ui.Select):
    def __init__(self, monsters, parent_view, user_id):
        self.parent_view = parent_view
        self.user_id = user_id
        options = []
        for m in monsters[:25]:
            hp = calc_stat(m.get("max_hp", 10), m.get("current_level", 1))
            options.append(discord.SelectOption(
                label=f"{m['name']} Lv.{m.get('current_level', 1)}"[:100],
                value=str(m["id"]),
                description=f"属性:{m.get('element_type', '無')} / HP:{hp}"[:100]
            ))
        super().__init__(
            placeholder="対戦に出す3体（先発順）を選択...",
            min_values=3,
            max_values=3,
            options=options
        )

    async def callback(self, interaction: discord.Interaction):
        side = "p1" if self.user_id == self.parent_view.p1_id else "p2"
        await self.parent_view.set_selection(interaction, side, self.values)


class EphemeralSelectView(discord.ui.View):
    def __init__(self, monsters, parent_view, user_id):
        super().__init__(timeout=60)
        self.add_item(PartyDropdown(monsters, parent_view, user_id))


class PartySelectView(discord.ui.View):
    def __init__(self, cog, p1_id, p2_id, p1_monsters, p2_monsters):
        super().__init__(timeout=120)
        self.cog, self.p1_id, self.p2_id = cog, p1_id, p2_id
        self.p1_monsters, self.p2_monsters = p1_monsters, p2_monsters
        self.p1_selection = None
        self.p2_selection = None
        self.lock = asyncio.Lock()
        self.message = None

    @discord.ui.button(label="手持ちから3体選ぶ", style=discord.ButtonStyle.primary)
    async def select_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        uid = str(interaction.user.id)
        if uid not in (self.p1_id, self.p2_id):
            await interaction.response.send_message("対戦参加者のみ選出できます。", ephemeral=True)
            return

        if uid == self.p1_id and self.p1_selection:
            await interaction.response.send_message("あなたは既に3体選出済みです。", ephemeral=True)
            return
        if uid == self.p2_id and self.p2_selection:
            await interaction.response.send_message("あなたは既に3体選出済みです。", ephemeral=True)
            return

        monsters = self.p1_monsters if uid == self.p1_id else self.p2_monsters
        view = EphemeralSelectView(monsters, self, uid)
        await interaction.response.send_message("対戦に出す3体をドロップダウンから選択してください（選択順が先発順になります）:", view=view, ephemeral=True)

    async def set_selection(self, interaction: discord.Interaction, side: str, selected_ids: list):
        async with self.lock:
            if side == "p1":
                self.p1_selection = selected_ids
            else:
                self.p2_selection = selected_ids

            p1_status = "選出完了！" if self.p1_selection else "選出中..."
            p2_status = "選出完了！" if self.p2_selection else "選出中..."

            await interaction.response.send_message("3体の選出を完了しました！相手の完了を待っています...", ephemeral=True)

            embed = discord.Embed(
                title="DDD ARENA | パーティ選出フェーズ",
                description=f"下のボタンを押して手持ちから対戦に出す3体を選択してください。\n\n<@{self.p1_id}>: {p1_status}\n<@{self.p2_id}>: {p2_status}",
                color=0x8B7CF8
            )

            if self.p1_selection and self.p2_selection:
                self.stop()
                try:
                    record = await asyncio.to_thread(
                        self.cog.start_battle, self.p1_id, self.p2_id, self.p1_selection, self.p2_selection
                    )
                    battle_view = BattleView(self.cog, record["id"], record["battle_state"], str(record["turn_user_id"]), self.p1_id, self.p2_id)
                    battle_view.message = self.message
                    await self.message.edit(
                        content=f"<@{battle_view.turn_user_id}> の先攻です。",
                        embed=battle_embed(battle_view.state),
                        view=battle_view,
                        allowed_mentions=discord.AllowedMentions.none()
                    )
                except Exception:
                    logger.exception("DDD party select start battle failed")
                    self.cog.busy.difference_update((self.p1_id, self.p2_id))
                    await self.message.edit(content="対戦の開始に失敗しました。", embed=None, view=None)
            else:
                await self.message.edit(embed=embed, view=self)

    async def on_timeout(self):
        self.cog.busy.difference_update((self.p1_id, self.p2_id))
        if self.message:
            try:
                await self.message.edit(content="選出の制限時間が切れました。対戦をキャンセルします。", embed=None, view=None)
            except discord.HTTPException:
                pass


# --- 挑戦招待用コンポーネント ---

class ChallengeView(discord.ui.View):
    def __init__(self, cog, p1_id, p2_id):
        super().__init__(timeout=60)
        self.cog, self.p1_id, self.p2_id = cog, p1_id, p2_id
        self.claimed = False
        self.message = None

    async def interaction_check(self, interaction):
        if str(interaction.user.id) != self.p2_id:
            await interaction.response.send_message("招待されたプレイヤーだけが回答できます。", ephemeral=True)
            return False
        if self.claimed:
            await interaction.response.send_message("回答済みの招待です。", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="対戦を受ける", style=discord.ButtonStyle.success)
    async def accept(self, interaction, button):
        self.claimed = True
        self.stop()
        await interaction.response.defer()
        try:
            # 双方のモンスターを取得して選出準備
            p1_monsters = await asyncio.to_thread(lambda: supabase.table("monsters").select("*").eq("user_id", self.p1_id).order("created_at", desc=True).limit(25).execute().data)
            p2_monsters = await asyncio.to_thread(lambda: supabase.table("monsters").select("*").eq("user_id", self.p2_id).order("created_at", desc=True).limit(25).execute().data)

            if len(p1_monsters) < 3 or len(p2_monsters) < 3:
                self.cog.busy.difference_update((self.p1_id, self.p2_id))
                await interaction.edit_original_response(content="対戦を開始できませんでした。双方3匹以上の所持が必要です。", embed=None, view=None)
                return

            select_view = PartySelectView(self.cog, self.p1_id, self.p2_id, p1_monsters, p2_monsters)
            embed = discord.Embed(
                title="DDD ARENA | パーティ選出フェーズ",
                description=f"下のボタンを押して手持ちから対戦に出す3体を選択してください。\n\n<@{self.p1_id}>: 選出中...\n<@{self.p2_id}>: 選出中...",
                color=0x8B7CF8
            )
            await interaction.edit_original_response(content="【パーティ選出フェーズ】", embed=embed, view=select_view)
            select_view.message = interaction.message
        except Exception:
            logger.exception("DDD challenge accept failed")
            self.cog.busy.difference_update((self.p1_id, self.p2_id))
            await interaction.edit_original_response(content="開始処理中にエラーが発生しました。", embed=None, view=None)

    @discord.ui.button(label="今回はやめる", style=discord.ButtonStyle.secondary)
    async def decline(self, interaction, button):
        self.claimed = True
        self.stop()
        self.cog.busy.difference_update((self.p1_id, self.p2_id))
        await interaction.response.edit_message(content="招待を取り消しました。", embed=None, view=None)

    async def on_timeout(self):
        self.cog.busy.difference_update((self.p1_id, self.p2_id))
        if self.message:
            try:
                await self.message.edit(content="対戦招待の期限が切れました。", embed=None, view=None)
            except discord.HTTPException:
                pass


class BattleCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.busy = set()

    def active_battle(self, user_id):
        return supabase.table("battles").select("*").eq("is_finished", False).or_(f"player1_id.eq.{user_id},player2_id.eq.{user_id}").limit(1).execute().data

    def start_battle(self, p1_id, p2_id, p1_monster_ids=None, p2_monster_ids=None):
        if self.active_battle(p1_id) or self.active_battle(p2_id):
            raise ValueError("active battle")

        def fetch_party(uid, m_ids):
            if m_ids:
                res = supabase.table("monsters").select("*").in_("id", m_ids).eq("user_id", uid).execute().data
                m_map = {str(m["id"]): m for m in res}
                party = [m_map[mid] for mid in m_ids if mid in m_map]
                if len(party) == 3:
                    return party
            return supabase.table("monsters").select("*").eq("user_id", uid).order("created_at", desc=True).limit(3).execute().data

        p1_data = fetch_party(p1_id, p1_monster_ids)
        p2_data = fetch_party(p2_id, p2_monster_ids)

        if len(p1_data) < 3 or len(p2_data) < 3:
            raise ValueError("three monsters required")

        p1, p2 = prepare_party(p1_data), prepare_party(p2_data)
        first_id = p1_id if calc_stat(p1[0]["max_speed"], p1[0]["current_level"]) >= calc_stat(p2[0]["max_speed"], p2[0]["current_level"]) else p2_id
        state = {"p1": {"party": p1, "active_idx": 0}, "p2": {"party": p2, "active_idx": 0}, "version": 0,
                 "logs": ["3対3の対戦開始！ 技・防御・交代から行動を選ぼう。"]}
        record = supabase.table("battles").insert({"player1_id": p1_id, "player2_id": p2_id, "turn_user_id": first_id,
                                                  "battle_state": state, "is_finished": False}).execute().data[0]
        return record

    @app_commands.command(name="ddd_battle", description="相手に招待を送り、手持ちから選抜した3体でドットバトル")
    async def battle(self, interaction: discord.Interaction, opponent: discord.User):
        p1_id, p2_id = str(interaction.user.id), str(opponent.id)
        if p1_id == p2_id or opponent.bot:
            await interaction.response.send_message("自分やBotには挑戦できません。一人なら /ddd_practice！", ephemeral=True)
            return
        if p1_id in self.busy or p2_id in self.busy:
            await interaction.response.send_message("どちらかが対戦中・招待中です。未完了戦は /ddd_resume。", ephemeral=True)
            return
        self.busy.update((p1_id, p2_id))
        view = ChallengeView(self, p1_id, p2_id)
        try:
            await interaction.response.send_message(
                content=f"<@{p2_id}>、ドットバトルへの招待です。",
                embed=discord.Embed(title="DDD ARENA | 挑戦状", description="手持ちから選抜した3体で対戦を行います。\n勝利パーティに50 EXP。\n60秒以内に回答してください。", color=0x8B7CF8),
                view=view,
                allowed_mentions=discord.AllowedMentions(users=[opponent])
            )
            view.message = await interaction.original_response()
        except Exception:
            self.busy.difference_update((p1_id, p2_id))
            raise

    @app_commands.command(name="ddd_resume", description="未完了の対人戦を再表示。再起動やボタン期限切れから復帰")
    async def resume(self, interaction: discord.Interaction):
        await interaction.response.defer()
        records = await asyncio.to_thread(self.active_battle, str(interaction.user.id))
        if not records:
            await interaction.followup.send("未完了の対戦はありません。", ephemeral=True)
            return
        record = records[0]
        state = record["battle_state"]
        if "version" not in state:
            await asyncio.to_thread(lambda: supabase.table("battles").update({"is_finished": True}).eq("id", record["id"]).execute())
            self.busy.difference_update((str(record["player1_id"]), str(record["player2_id"])))
            await interaction.followup.send("旧バージョンの未完了戦を報酬なしで終了しました。新しく対戦できます。", ephemeral=True)
            return
        view = BattleView(self, record["id"], state, str(record["turn_user_id"]), str(record["player1_id"]), str(record["player2_id"]))
        view.message = await interaction.followup.send(content=f"<@{view.turn_user_id}> のターン", embed=battle_embed(state), view=view, ephemeral=False, wait=True,
                                                       allowed_mentions=discord.AllowedMentions.none())

    @app_commands.command(name="ddd_practice", description="自分の相棒でCPUと無料の練習戦。経験値・コイン変動なし")
    @app_commands.describe(monster_id="ボックス詳細のID。省略時は最新の相棒", course="相手の戦い方")
    @app_commands.choices(course=[app_commands.Choice(name=n, value=n) for n in ["草原のスライム", "遺跡のガーディアン", "鏡のライバル"]])
    async def practice(self, interaction: discord.Interaction, monster_id: str = "", course: str = "草原のスライム"):
        await interaction.response.defer(ephemeral=True)
        def load():
            query = supabase.table("monsters").select("*").eq("user_id", str(interaction.user.id))
            if monster_id:
                query = query.eq("id", monster_id)
            return query.order("created_at", desc=True).limit(1).execute().data
        monsters = await asyncio.to_thread(load)
        if not monsters:
            await interaction.followup.send("相棒が見つかりません。/ddd_create で無料作成しましょう！", ephemeral=True)
            return
        player = prepare_party(monsters)
        enemy = copy.deepcopy(player)
        enemy[0]["name"] = course
        enemy[0]["image_url"] = ""
        if course == "草原のスライム":
            enemy[0]["element_type"] = "無"
            enemy[0]["max_attack"] = max(1, enemy[0]["max_attack"] * 2 // 3)
            enemy[0]["max_sp_atk"] = max(1, enemy[0]["max_sp_atk"] * 2 // 3)
        elif course == "遺跡のガーディアン":
            enemy[0]["max_defense"] = min(9999, enemy[0]["max_defense"] * 3 // 2)
            enemy[0]["max_sp_def"] = min(9999, enemy[0]["max_sp_def"] * 3 // 2)
        enemy = prepare_party(enemy)
        state = {"p1": {"party": player, "active_idx": 0}, "p2": {"party": enemy, "active_idx": 0}, "version": 0,
                 "logs": [f"{course}に挑戦！ HP・経験値・コインは練習後に持ち越しません。"]}
        uid = str(interaction.user.id)
        view = BattleView(self, None, state, uid, uid, "CPU", practice=True)
        view.message = await interaction.followup.send(embed=battle_embed(state, True), view=view, ephemeral=True, wait=True)


async def setup(bot):
    await bot.add_cog(BattleCog(bot))
