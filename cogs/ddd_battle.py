import asyncio
import copy
import logging
import os
import random

import discord
from discord import app_commands
from discord.ext import commands
from supabase import create_client, Client

from .ddd_inventory import HERB, consume_item, restore_item

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
logger = logging.getLogger(__name__)

TYPE_CHART = {
    # 虚→実→正→負→虚。攻撃側が有利なら1.5倍、逆側は0.5倍。
    "虚": {"実": 1.5, "負": 0.5},
    "実": {"正": 1.5, "虚": 0.5},
    "正": {"負": 1.5, "実": 0.5},
    "負": {"虚": 1.5, "正": 0.5},
    "無": {},
}
STAT_KEYS = ("hp", "attack", "defense", "sp_atk", "sp_def", "speed")
MAX_ACTIONS = 80
SAFE_TRAITS = {
    "none": {"name": "標準", "description": "追加効果なし。"},
    "regen": {"name": "再生", "description": "自分の行動開始時、HPが最大値の1/12回復。"},
    "guard": {"name": "堅守", "description": "受けるダメージを15%軽減。"},
    "valor": {"name": "闘志", "description": "HP半分以下のとき、与えるダメージを10%上昇。"},
    "focus": {"name": "集中", "description": "技の命中率を5上昇。100を超えない。"},
}


def integer(value, default=0, low=0, high=9999):
    try:
        return max(low, min(high, int(value)))
    except (ValueError, TypeError, OverflowError):
        return default


def calc_stat(max_stat: int, level: int) -> int:
    """Lv.30を基準に、Lv.40で1.2倍、Lv.50でLv.40の1.2倍へ伸ばす。"""
    level = integer(level, 1, 1, 50)
    if level <= 30:
        multiplier = 0.2 + 0.8 * level / 30
    elif level <= 40:
        multiplier = 1.0 + 0.2 * (level - 30) / 10
    else:
        multiplier = 1.2 + 0.24 * (level - 40) / 10
    return max(1, int(integer(max_stat, 10, 1) * multiplier))


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
                       "power": 0 if category == "status" else integer(move.get("power", 40), 40, 1, 140),
                       "accuracy": integer(move.get("accuracy", 100), 100, 1, 100)})
    return result


def prepare_party(party):
    party = copy.deepcopy(party)
    for monster in party:
        monster["current_level"] = integer(monster.get("current_level"), 1, 1, 50)
        for key in STAT_KEYS:
            monster[f"max_{key}"] = integer(monster.get(f"max_{key}"), 10, 1)
        monster["moves"] = normalize_moves(monster.get("moves"))
        monster["trait_id"] = monster.get("trait_id") if monster.get("trait_id") in SAFE_TRAITS else "none"
        monster["current_hp"] = calc_stat(monster["max_hp"], monster["current_level"])
        monster.update(ranks={}, guarding=False, poison=0, heals=3, stunned=0, bound=0,
                       entry_hazard=False, revenge_bomb=False)
    return party


def calculate_damage(attacker, defender, move, rng=None, critical=False):
    rng = rng or random
    mult = get_type_multiplier(move.get("type", "無"), defender["element_type"])
    if move.get("category") == "status":
        return 0, mult
    atk_key, def_key = ("sp_atk", "sp_def") if move.get("category") == "special" else ("attack", "defense")
    atk = calc_stat(attacker[f"max_{atk_key}"], attacker["current_level"]) * rank_multiplier(attacker.get("ranks", {}).get(atk_key, 0))
    defense = calc_stat(defender[f"max_{def_key}"], defender["current_level"]) * rank_multiplier(defender.get("ranks", {}).get(def_key, 0))
    power = integer(move.get("power", 40), 40, 1, 140)
    base = ((attacker["current_level"] * 2 / 5 + 2) * power * atk / max(1, defense)) / 50 + 2
    stab = 1.5 if move.get("type") == attacker["element_type"] else 1.0
    trait_multiplier = 1.1 if attacker.get("trait_id") == "valor" and attacker.get("current_hp", 0) <= calc_stat(attacker["max_hp"], attacker["current_level"]) // 2 else 1.0
    trait_multiplier *= 0.85 if defender.get("trait_id") == "guard" else 1.0
    return max(1, int(base * mult * stab * rng.uniform(0.85, 1) * (1.5 if critical else 1) * (0.5 if defender.get("guarding") else 1) * trait_multiplier)), mult


def experience_required(level):
    """次レベルまでの必要EXP。Lv.30までは100、31〜40は1000、41〜50は10000。"""
    level = integer(level, 1, 1, 50)
    return 100 if level < 30 else 1000 if level < 40 else 10000


def add_experience(level, experience, amount, breakthrough_stage=0):
    """EXPを加算する。Lv.30・40では対応する突破までレベル上昇を停止する。"""
    level = integer(level, 1, 1, 50)
    total = max(0, integer(experience)) + max(0, int(amount))
    stage = integer(breakthrough_stage, 0, 0, 40)
    while level < 50 and total >= experience_required(level):
        if (level == 30 and stage < 30) or (level == 40 and stage < 40):
            return level, experience_required(level)
        total -= experience_required(level)
        level += 1
    return level, 0 if level == 50 else total


def experience_space(level, experience, breakthrough_stage=0):
    """現在の突破状況で無駄なく追加できるEXPの上限を返す。"""
    level = integer(level, 1, 1, 50)
    current_exp = max(0, integer(experience))
    stage = integer(breakthrough_stage, 0, 0, 40)
    space = 0
    while level < 50:
        needed = experience_required(level)
        if (level == 30 and stage < 30) or (level == 40 and stage < 40):
            return space + max(0, needed - current_exp)
        space += max(0, needed - current_exp)
        level += 1
        current_exp = 0
    return space


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
    elif action not in ("herb", "surrender"):
        index = integer(action, -1, -1, 99)
        if index not in range(3):
            raise ValueError("技は1〜3から選んでください。")
    logs = state.setdefault("logs", [])
    actor["guarding"] = False
    was_stunned = actor.get("stunned", 0) > 0 and action != "surrender"
    if was_stunned:
        actor["stunned"] = 0
        logs.append(f"{actor['name']} は動けない！")
        action = "herb"
    if actor.get("trait_id") == "regen":
        maximum = calc_stat(actor["max_hp"], actor["current_level"])
        recovered = min(maximum - actor["current_hp"], max(1, maximum // 12))
        if recovered:
            actor["current_hp"] += recovered
            logs.append(f"{actor['name']} の特性『再生』でHPが{recovered}回復。")
    if action == "surrender":
        logs.append(f"{side.upper()} が降参しました。")
        return other
    if action.startswith("switch:"):
        actor["ranks"] = {}
        team["active_idx"] = index
        entrant = team["party"][index]
        if team.get("entry_hazard"):
            hazard = max(1, calc_stat(entrant["max_hp"], entrant["current_level"]) // 8)
            entrant["current_hp"] = max(0, entrant["current_hp"] - hazard)
            logs.append(f"{entrant['name']}は登場時に罠のダメージ {hazard}！")
        logs.append(f"{actor['name']} → {entrant['name']} に交代！")
    elif action == "herb":
        maximum = calc_stat(actor["max_hp"], actor["current_level"])
        recovered = maximum - actor["current_hp"]
        actor["current_hp"] = maximum
        if recovered:
            logs.append(f"{actor['name']} は薬草でHPを{recovered}回復！")
        else:
            logs.append(f"{actor['name']} は薬草を使ったが、HPは満タンだった。")
    else:
        move = actor["moves"][index]
        accuracy = min(100, move["accuracy"] + (5 if actor.get("trait_id") == "focus" else 0))
        if rng.random() * 100 >= accuracy:
            logs.append(f"{actor['name']} の {move['name']} は外れた！")
        elif move["category"] == "status":
            effect = move.get("effect")
            if effect in ("heal", "heal_big"):
                maximum = calc_stat(actor["max_hp"], actor["current_level"])
                if actor["heals"] > 0:
                    heal_fraction = 2 if effect == "heal_big" else 4
                    recovered = min(maximum - actor["current_hp"], max(1, maximum // heal_fraction))
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
            elif effect == "bind":
                duration = 4 if move.get("name") == "締め付け" else 3
                target["bound"] = max(target.get("bound", 0), duration)
                logs.append(f"{target['name']} は {move['name']} に絡め取られた！ {duration}ターン拘束。")
            elif effect == "entry_hazard":
                enemy["entry_hazard"] = True
                logs.append(f"{target['name']}の陣地に特殊な罠を設置した！")
            elif effect == "revenge_bomb":
                actor["revenge_bomb"] = True
                logs.append(f"{actor['name']}は戦闘不能時の反撃を準備した！")
            elif effect == "guard":
                logs.append(f"{move['name']} は現在使用できません。")
            else:
                logs.append(f"{move['name']}：未対応の変化効果です（ダメージなし）。")
        else:
            critical = rng.random() < 1 / 16
            damage, mult = calculate_damage(actor, target, move, rng, critical)
            target["current_hp"] = max(0, target["current_hp"] - damage)
            target["guarding"] = False
            if target["current_hp"] > 0 and move.get("effect_after") == "attack_up":
                actor["ranks"]["attack"] = min(6, actor["ranks"].get("attack", 0) + 1)
                logs.append(f"{actor['name']} の攻撃が1段階上昇！")
            if target["current_hp"] > 0 and move.get("effect_after") == "drain":
                maximum = calc_stat(actor["max_hp"], actor["current_level"])
                recovered = min(maximum - actor["current_hp"], damage)
                actor["current_hp"] += recovered
                logs.append(f"{actor['name']} は与えたダメージ分のHPを回復！")
            if target["current_hp"] > 0 and move.get("effect_after") == "stun":
                actor["stunned"] = 1
                logs.append(f"{actor['name']} は反動で1ターン動けない！")
            if target["current_hp"] > 0 and move.get("effect_after") == "random_switch":
                choices = [i for i, m in enumerate(team["party"]) if i != team["active_idx"] and m["current_hp"] > 0]
                if choices:
                    team["active_idx"] = rng.choice(choices)
                    team["party"][team["active_idx"]]["ranks"] = {}
                    logs.append(f"{actor['name']} は攻撃後に交代！")
            notes = (" 急所！" if critical else "") + (" 弱点！" if mult > 1 else " 耐性あり" if mult < 1 else "")
            logs.append(f"{actor['name']} の {move['name']} → {target['name']} に{damage}！{notes}")
    if actor.get("poison", 0) and actor["current_hp"] > 0:
        damage = max(1, calc_stat(actor["max_hp"], actor["current_level"]) // 8)
        actor["current_hp"] = max(0, actor["current_hp"] - damage)
        actor["poison"] -= 1
        logs.append(f"{actor['name']} に毒のダメージ {damage}")
    for key in ("p1", "p2"):
        fallen = state[key]["party"]
        enemy_team = state["p2" if key == "p1" else "p1"]
        for fallen_monster in fallen:
            if fallen_monster.get("revenge_bomb") and fallen_monster["current_hp"] <= 0:
                target_monster = enemy_team["party"][enemy_team["active_idx"]]
                damage = max(1, calc_stat(fallen_monster["max_hp"], fallen_monster["current_level"]) // 2)
                target_monster["current_hp"] = max(0, target_monster["current_hp"] - damage)
                fallen_monster["revenge_bomb"] = False
                logs.append(f"{fallen_monster['name']}の反撃で{target_monster['name']}に{damage}ダメージ！")
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
    embed = discord.Embed(title=f"DDD {'PRACTICE' if practice else 'ARENA'} | TURN {state.get('version', 0) + 1}", color=0xFFFFFF,
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
    embed.set_footer(text="一致属性×1.5 / 虚⇔実・正⇔負が弱点 / 交代も1手 / 80手で引き分け")
    return embed


class BattleView(discord.ui.View):
    def __init__(self, cog, battle_id, state, turn_user_id, p1_id, p2_id, practice=False, mode="battle", match_type="normal"):
        super().__init__(timeout=180)
        self.cog, self.battle_id, self.state = cog, battle_id, state
        self.turn_user_id, self.p1_id, self.p2_id = turn_user_id, p1_id, p2_id
        self.practice, self.mode, self.match_type, self.version = practice, mode, match_type, state.get("version", 0)
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
        if self.mode == "random":
            button = discord.ui.Button(label="薬草（HP全回復）", style=discord.ButtonStyle.success, row=1)
            button.callback = self.callback_for("herb")
            self.add_item(button)
        button = discord.ui.Button(label="降参", style=discord.ButtonStyle.secondary, row=1)
        button.callback = self.callback_for("surrender")
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
            herb_item = None
            try:
                if action == "herb":
                    if self.mode != "random":
                        raise ValueError("薬草はランダムマッチでのみ使用できます。")
                    herb_item = await asyncio.to_thread(consume_item, supabase, self.turn_user_id, HERB)
                    if not herb_item:
                        raise ValueError("薬草を所持していません。")
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
                        if herb_item:
                            await asyncio.to_thread(restore_item, supabase, herb_item)
                        self.used = True
                        await interaction.followup.send("古い操作です。最新の対戦画面か /ddd_resume を使用してください。", ephemeral=True)
                        return
            except ValueError as exc:
                if herb_item:
                    await asyncio.to_thread(restore_item, supabase, herb_item)
                await interaction.followup.send(str(exc), ephemeral=True)
                return
            except Exception:
                if herb_item:
                    await asyncio.to_thread(restore_item, supabase, herb_item)
                logger.exception("DDD battle update failed")
                await interaction.followup.send("対戦更新に失敗しました。/ddd_resume で最新状態を確認してください。", ephemeral=True)
                return
            self.used = True
            self.stop()
            if winner:
                if not self.practice:
                    self.cog.busy.difference_update((self.p1_id, self.p2_id))
                if not self.practice and self.mode == "battle" and winner != "draw":
                    try:
                        await asyncio.to_thread(self.award_exp, state[winner]["party"])
                        state["logs"].append("勝利パーティ全員に50 EXPを獲得しました。")
                    except Exception:
                        logger.exception("DDD reward failed for battle %s", self.battle_id)
                        state["logs"].append("経験値の保存に失敗しました。管理者へ対戦IDを連絡してください。")
                elif self.mode == "random" and winner == "p1":
                    try:
                        await asyncio.to_thread(self.award_random_match, state["p1"]["party"][0])
                        reward = {"normal": (10, 50), "elite": (30, 300), "boss": (100, 1000)}[self.match_type]
                        state["logs"].append(f"勝利報酬としてEXP {reward[0]}、コイン{reward[1]}を獲得しました。")
                    except Exception:
                        logger.exception("DDD random match reward failed")
                        state["logs"].append("勝利しましたが、報酬の保存に失敗しました。")
                view = None
            else:
                view = BattleView(self.cog, self.battle_id, state, next_id, self.p1_id, self.p2_id, self.practice, self.mode, self.match_type)
            await interaction.edit_original_response(content="対戦終了" if winner else f"<@{next_id}> のターン", embed=battle_embed(state, self.practice), view=view,
                                                     allowed_mentions=discord.AllowedMentions.none())
            if view:
                view.message = interaction.message

    def save_turn(self, state, next_id, finished):
        query = supabase.table("battles").update({"battle_state": state, "turn_user_id": next_id, "is_finished": finished})
        return query.eq("id", self.battle_id).eq("is_finished", False).eq("turn_user_id", self.turn_user_id).eq("battle_state->>version", str(self.version)).execute().data

    def award_exp(self, party):
        for monster in party:
            result = supabase.table("monsters").select("current_level,current_exp,breakthrough_stage").eq("id", monster["id"]).eq("user_id", monster["user_id"]).execute()
            if not result.data:
                continue
            old = result.data[0]
            level, exp = add_experience(old["current_level"], old.get("current_exp", 0), 50, old.get("breakthrough_stage", 0))
            updated = supabase.table("monsters").update({"current_level": level, "current_exp": exp}).eq("id", monster["id"]).eq("user_id", monster["user_id"]).eq("current_level", old["current_level"]).eq("current_exp", old.get("current_exp", 0)).execute()
            if not updated.data:
                raise RuntimeError("Concurrent EXP update; manual reconciliation needed")

    def award_random_match(self, monster):
        result = supabase.table("monsters").select("current_level,current_exp,breakthrough_stage").eq("id", monster["id"]).eq("user_id", self.p1_id).execute()
        if not result.data:
            raise RuntimeError("Selected monster no longer exists")
        old = result.data[0]
        exp_reward, coin_reward = {"normal": (10, 50), "elite": (30, 300), "boss": (100, 1000)}[self.match_type]
        level, exp = add_experience(old["current_level"], old.get("current_exp", 0), exp_reward, old.get("breakthrough_stage", 0))
        updated = supabase.table("monsters").update({"current_level": level, "current_exp": exp}).eq("id", monster["id"]).eq("user_id", self.p1_id).eq("current_level", old["current_level"]).eq("current_exp", old.get("current_exp", 0)).execute()
        if not updated.data:
            raise RuntimeError("Concurrent EXP update; manual reconciliation needed")
        profile = supabase.table("users").select("balance").eq("user_id", self.p1_id).execute()
        balance = int(profile.data[0].get("balance") or 0) if profile.data else 0
        updated_user = supabase.table("users").update({"balance": balance + coin_reward}).eq("user_id", self.p1_id).eq("balance", balance).execute()
        if not updated_user.data:
            raise RuntimeError("Concurrent balance update; manual reconciliation needed")

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        if self.message:
            try:
                await self.message.edit(content="操作期限切れ。対人戦は /ddd_resume で再開できます。ランダムマッチは再挑戦してください。", view=self)
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
                color=0xFFFFFF
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
                color=0xFFFFFF
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
                 "logs": ["3対3の対戦開始！ 技・交代・降参から行動を選ぼう。"]}
        record = supabase.table("battles").insert({"player1_id": p1_id, "player2_id": p2_id, "turn_user_id": first_id,
                                                  "battle_state": state, "is_finished": False}).execute().data[0]
        return record

    @app_commands.command(name="ddd_battle", description="相手に招待を送り、手持ちから選抜した3体でドットバトル")
    async def battle(self, interaction: discord.Interaction, opponent: discord.User):
        p1_id, p2_id = str(interaction.user.id), str(opponent.id)
        if p1_id == p2_id or opponent.bot:
            await interaction.response.send_message("自分やBotには挑戦できません。", ephemeral=True)
            return
        if p1_id in self.busy or p2_id in self.busy:
            await interaction.response.send_message("どちらかが対戦中・招待中です。未完了戦は /ddd_resume。", ephemeral=True)
            return
        self.busy.update((p1_id, p2_id))
        view = ChallengeView(self, p1_id, p2_id)
        try:
            await interaction.response.send_message(
                content=f"<@{p2_id}>、ドットバトルへの招待です。",
                embed=discord.Embed(title="DDD ARENA | 挑戦状", description="手持ちから選抜した3体で対戦を行います。\n勝利パーティに50 EXP。\n60秒以内に回答してください。", color=0xFFFFFF),
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

    @app_commands.command(name="ddd_random_match", description="通常・エリート・ボスの3種から選ぶ報酬ランダムマッチ")
    @app_commands.describe(monster_id="使用する相棒のID", match_type="挑戦するマッチ種別")
    @app_commands.choices(match_type=[
        app_commands.Choice(name="通常マッチ（Lv.30以下）", value="normal"),
        app_commands.Choice(name="エリートマッチ（Lv.30以上）", value="elite"),
        app_commands.Choice(name="ボスマッチ（Lv.30以上）", value="boss"),
    ])
    async def random_match(self, interaction: discord.Interaction, monster_id: str, match_type: str = "normal"):
        await interaction.response.defer()
        uid = str(interaction.user.id)
        def load():
            own = supabase.table("monsters").select("*").eq("id", monster_id).eq("user_id", uid).execute().data
            all_monsters = supabase.table("monsters").select("*").execute().data
            return own, all_monsters
        own, all_monsters = await asyncio.to_thread(load)
        if not own:
            await interaction.followup.send("指定した相棒が見つかりません。/ddd_boxでIDを確認してください。", ephemeral=True)
            return
        if match_type not in ("normal", "elite", "boss"):
            await interaction.followup.send("マッチ種別が不正です。", ephemeral=True)
            return
        player_level = int(own[0].get("current_level") or 1)
        if match_type == "normal" and player_level > 30:
            await interaction.followup.send("通常マッチはLv.30以下の相棒専用です。", ephemeral=True)
            return
        if match_type in ("elite", "boss") and player_level < 30:
            await interaction.followup.send("エリート・ボスマッチはLv.30以上の相棒専用です。", ephemeral=True)
            return
        if not all_monsters:
            await interaction.followup.send("対戦相手になるキャラがまだいません。", ephemeral=True)
            return
        candidates = [m for m in all_monsters if (int(m.get("current_level") or 1) <= 30 if match_type == "normal" else int(m.get("current_level") or 1) >= 30)]
        opponent = random.choice(candidates or all_monsters)
        player = prepare_party([own[0]])
        enemy = prepare_party([copy.deepcopy(opponent)])
        reward = {"normal": (10, 50), "elite": (30, 300), "boss": (100, 1000)}[match_type]
        if match_type == "boss":
            boss_hp_multiplier = random.randint(3, 5)
            boss = enemy[0]
            boss["max_hp"] = min(9999, boss["max_hp"] * boss_hp_multiplier)
            for key in ("attack", "defense", "sp_atk", "sp_def", "speed"):
                boss[f"max_{key}"] = min(9999, int(boss[f"max_{key}"] * 1.5))
            boss["current_hp"] = calc_stat(boss["max_hp"], boss["current_level"])
            boss_label = f" HP{boss_hp_multiplier}倍 / その他能力1.5倍"
        else:
            boss_label = ""
        labels = {"normal": "通常マッチ", "elite": "エリートマッチ", "boss": "ボスマッチ"}
        state = {
            "p1": {"party": player, "active_idx": 0}, "p2": {"party": enemy, "active_idx": 0},
            "version": 0, "match_type": match_type,
            "logs": [f"{labels[match_type]}開始。{opponent['name']}が対戦相手に選ばれました。{boss_label} 勝利報酬: EXP {reward[0]} / コイン{reward[1]}。"],
        }
        view = BattleView(self, None, state, uid, uid, "RANDOM_CPU", practice=True, mode="random", match_type=match_type)
        view.message = await interaction.followup.send(embed=battle_embed(state, True), view=view, wait=True)

async def setup(bot):
    await bot.add_cog(BattleCog(bot))
