import os
import random
import discord
from discord import app_commands
from discord.ext import commands
from supabase import create_client, Client

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# 5属性の相性表
TYPE_CHART = {
    "虚": {"実": 2.0, "虚": 0.5},
    "実": {"虚": 2.0, "実": 0.5},
    "正": {"負": 2.0, "正": 0.5},
    "負": {"正": 2.0, "負": 0.5},
    "無": {}
}

def calc_stat(max_stat: int, level: int) -> int:
    """Lv.30での最高個体値から現在Lvのステータスを計算"""
    return max(1, int(max_stat * (0.2 + 0.8 * (level / 30.0))))

def get_type_multiplier(atk_type: str, def_type: str) -> float:
    return TYPE_CHART.get(atk_type, {}).get(def_type, 1.0)

def calculate_damage(attacker: dict, defender: dict, move: dict) -> tuple[int, float]:
    """ポケモン準拠のダメージ計算"""
    atk_lv = attacker["current_level"]
    is_special = move.get("category") == "special"
    
    atk_val = calc_stat(attacker["max_sp_atk" if is_special else "max_attack"], atk_lv)
    def_val = calc_stat(defender["max_sp_def" if is_special else "max_defense"], defender["current_level"])
    
    power = move.get("power", 40)
    type_mult = get_type_multiplier(move.get("type", "無"), defender["element_type"])
    random_mult = random.uniform(0.85, 1.0)
    
    base_dmg = (((atk_lv * 2 / 5 + 2) * power * (atk_val / def_val)) / 50) + 2
    final_dmg = int(base_dmg * type_mult * random_mult)
    return max(1, final_dmg), type_mult

class BattleView(discord.ui.View):
    def __init__(self, battle_id: str, turn_user_id: str, p1_id: str, p2_id: str):
        super().__init__(timeout=180)
        self.battle_id = battle_id
        self.turn_user_id = turn_user_id
        self.p1_id = p1_id
        self.p2_id = p2_id

    async def execute_turn(self, interaction: discord.Interaction, move_idx: int):
        if str(interaction.user.id) != self.turn_user_id:
            await interaction.response.send_message("あなたのターンではありません。", ephemeral=True)
            return

        await interaction.response.defer()

        # 最新のバトル状態を取得
        res = supabase.table("battles").select("*").eq("id", self.battle_id).execute()
        battle = res.data[0]
        state = battle["battle_state"]

        is_p1 = str(interaction.user.id) == self.p1_id
        atk_key, def_key = ("p1", "p2") if is_p1 else ("p2", "p1")
        next_turn_id = self.p2_id if is_p1 else self.p1_id

        attacker_party = state[atk_key]["party"]
        defender_party = state[def_key]["party"]

        atk_idx = state[atk_key]["active_idx"]
        def_idx = state[def_key]["active_idx"]

        attacker = attacker_party[atk_idx]
        defender = defender_party[def_idx]

        move = attacker["moves"][move_idx]
        damage, mult = calculate_damage(attacker, defender, move)
        defender["current_hp"] = max(0, defender["current_hp"] - damage)

        # ログメッセージ
        log = f"⚔️ **{attacker['name']}** の {move['name']}！ **{defender['name']}** に {damage} ダメージ！"
        if mult > 1.0: log += " (効果はばつぐんだ！)"
        elif mult < 1.0 and mult > 0: log += " (効果はいまひとつのようだ...)"
        state["logs"].append(log)

        # ひんし判定・交代処理
        is_finished = False
        if defender["current_hp"] == 0:
            state["logs"].append(f"💀 **{defender['name']}** は倒れた！")
            
            # 生きている次のモンスターを検索
            next_def_idx = next((i for i, m in enumerate(defender_party) if m["current_hp"] > 0), None)
            if next_def_idx is not None:
                state[def_key]["active_idx"] = next_def_idx
                state["logs"].append(f"➡️ **{defender_party[next_def_idx]['name']}** がバトル場に出た！")
            else:
                is_finished = True
                state["logs"].append(f"🏆 <@{interaction.user.id}> の勝利！")
                self.award_exp(attacker["id"])

        # DB更新
        supabase.table("battles").update({
            "battle_state": state,
            "turn_user_id": next_turn_id,
            "is_finished": is_finished
        }).eq("id", self.battle_id).execute()

        # Embed構築・送信
        embed = self.build_embed(state)
        if is_finished:
            await interaction.followup.send(content="🎊 **対戦終了！**", embed=embed)
        else:
            next_view = BattleView(self.battle_id, next_turn_id, self.p1_id, self.p2_id)
            next_view.setup_buttons(state[def_key if is_p1 else atk_key]["party"][state[def_key if is_p1 else atk_key]["active_idx"]]["moves"])
            await interaction.followup.send(content=f"<@{next_turn_id}> のターンです。", embed=embed, view=next_view)

    def award_exp(self, monster_id: str):
        """勝利モンスターへの経験値付与＆レベルアップ（最大Lv.30）"""
        m_res = supabase.table("monsters").select("current_level, current_exp").eq("id", monster_id).execute()
        if not m_res.data: return
        
        m = m_res.data[0]
        if m["current_level"] >= 30: return
        
        new_exp = m["current_exp"] + 50
        new_lv = m["current_level"]
        if new_exp >= 100:
            new_lv = min(30, new_lv + 1)
            new_exp = 0

        supabase.table("monsters").update({"current_level": new_lv, "current_exp": new_exp}).eq("id", monster_id).execute()

    def setup_buttons(self, moves: list):
        self.clear_items()
        for idx, move in enumerate(moves):
            btn = discord.ui.Button(
                label=f"{move['name']} ({move['type']}/威:{move.get('power', 0)})",
                style=discord.ButtonStyle.primary,
                custom_id=f"move_{idx}"
            )
            btn.callback = self.create_callback(idx)
            self.add_item(btn)

    def create_callback(self, move_idx: int):
        async def callback(interaction: discord.Interaction):
            await self.execute_turn(interaction, move_idx)
        return callback

    def build_embed(self, state: dict) -> discord.Embed:
        p1_active = state["p1"]["party"][state["p1"]["active_idx"]]
        p2_active = state["p2"]["party"][state["p2"]["active_idx"]]
        
        embed = discord.Embed(title="⚔️ DDD コマンドバトル", description="\n".join(state["logs"][-4:]))
        embed.add_field(
            name=f"P1: {p1_active['name']} (Lv.{p1_active['current_level']})",
            value=f"HP: {p1_active['current_hp']} / {calc_stat(p1_active['max_hp'], p1_active['current_level'])}"
        )
        embed.add_field(
            name=f"P2: {p2_active['name']} (Lv.{p2_active['current_level']})",
            value=f"HP: {p2_active['current_hp']} / {calc_stat(p2_active['max_hp'], p2_active['current_level'])}"
        )
        return embed

class BattleCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="ddd_battle", description="他のプレイヤーと3v3の対戦を行います")
    async def battle(self, interaction: discord.Interaction, opponent: discord.User):
        await interaction.response.defer()

        p1_id, p2_id = str(interaction.user.id), str(opponent.id)
        p1_res = supabase.table("monsters").select("*").eq("user_id", p1_id).order("created_at", desc=True).limit(3).execute()
        p2_res = supabase.table("monsters").select("*").eq("user_id", p2_id).order("created_at", desc=True).limit(3).execute()

        if len(p1_res.data) < 3 or len(p2_res.data) < 3:
            await interaction.followup.send("対戦を行うには両プレイヤーが手持ちモンスターを【3匹以上】所有している必要があります。")
            return

        def prep_party(party):
            for m in party:
                m["current_hp"] = calc_stat(m["max_hp"], m["current_level"])
            return party

        p1_party, p2_party = prep_party(p1_res.data), prep_party(p2_res.data)
        
        # 先攻判定
        p1_spd = calc_stat(p1_party[0]["max_speed"], p1_party[0]["current_level"])
        p2_spd = calc_stat(p2_party[0]["max_speed"], p2_party[0]["current_level"])
        first_id = p1_id if p1_spd >= p2_spd else p2_id

        initial_state = {
            "p1": {"party": p1_party, "active_idx": 0},
            "p2": {"party": p2_party, "active_idx": 0},
            "logs": ["⚔️ 3v3 コマンドバトル開始！"]
        }

        b_res = supabase.table("battles").insert({
            "player1_id": p1_id,
            "player2_id": p2_id,
            "turn_user_id": first_id,
            "battle_state": initial_state
        }).execute()

        battle_id = b_res.data[0]["id"]
        
        first_party = p1_party if first_id == p1_id else p2_party
        view = BattleView(battle_id, first_id, p1_id, p2_id)
        view.setup_buttons(first_party[0]["moves"])

        embed = view.build_embed(initial_state)
        await interaction.followup.send(content=f"<@{first_id}> の先攻ターンです。", embed=embed, view=view)

async def setup(bot):
    await bot.add_cog(BattleCog(bot))
