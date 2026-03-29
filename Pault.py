import discord
from discord import app_commands
import random
import asyncio

# --- 定数・スタッツ定義 ---
BATTLE_STATS = {
    "ソルジャー": [1, 0], "アサシン": [3, 0], "ナイト": [2, 1],
    "シールド": [1, 2], "ランナー": [1, 0], "イーター": [2, 0],
    "アーチャー": [1, 0], "バーサーカー": [1, 1], "盾士": [1, 0]
}

class PaultGame:
    def __init__(self, channel_id, user_id, user_name):
        self.channel_id = channel_id
        self.turn = 1
        self.deck = self.create_deck()
        self.players = {
            "p1": {"id": user_id, "name": user_name, "main": None, "left": [], "right": [], "hand": []},
            "cpu": {"id": "CPU", "name": "CPU", "main": None, "left": [], "right": [], "hand": []}
        }
        self.current_turn = "p1"
        self.logs = "準備フェーズ：最初の2周は攻撃禁止です。"

    def create_deck(self):
        deck = []
        for _ in range(40):
            t = random.choices(["戦闘", "サポート"], weights=[80, 20])[0]
            name = random.choice(list(BATTLE_STATS.keys()) if t == "戦闘" else ["ドロー", "サブ破壊"])
            deck.append({"name": name, "type": t, "def_broken": False})
        random.shuffle(deck)
        return deck

    def check_victory(self):
        """勝利判定：相手のメインが破壊されていたら終了"""
        if self.players["cpu"]["main"] is None: return "p1"
        if self.players["p1"]["main"] is None: return "cpu"
        return None

# --- 攻撃ロジック関数 ---
def execute_attack(attacker_card, defender_card):
    """攻撃力 vs 防御力の判定。破壊できればTrue"""
    atk = BATTLE_STATS.get(attacker_card["name"], [0, 0])[0]
    dfn = BATTLE_STATS.get(defender_card["name"], [0, 0])[1]
    
    # 防御状態（裏返し）の仕様：一度だけ防ぐ
    if defender_card.get("is_hidden", False):
        defender_card["is_hidden"] = False # 表に戻る
        return False, "防御状態により防がれた！"

    if atk > dfn:
        return True, "破壊成功！"
    return False, "防御力が高い…破壊失敗。"

# --- CPUの自動思考ロジック ---
async def cpu_logic(i, game):
    cpu = game.players["cpu"]
    p1 = game.players["p1"]
    
    # 1. ドロー
    if game.deck:
        card = game.deck.pop()
        # 城がなければ最優先で配置
        if not cpu["main"] and card["type"] == "戦闘":
            cpu["main"] = card
        else:
            cpu["hand"].append(card)

    # 2. 配置（手札に戦闘カードがあれば空きスロットへ）
    for idx, c in enumerate(cpu["hand"]):
        if c["type"] == "戦闘":
            if len(cpu["left"]) < 2: cpu["left"].append(cpu["hand"].pop(idx)); break
            if len(cpu["right"]) < 2: cpu["right"].append(cpu["hand"].pop(idx)); break

    # 3. 攻撃（戦闘期のみ）
    cpu_log = "CPUはカードを整理した。"
    if game.turn > 2:
        # 簡易的な攻撃：左スロットにカードがあればプレイヤーの右かメインを狙う
        if cpu["left"] and p1["main"]:
            atk_card = cpu["left"].pop() # カードを消費して攻撃
            success, res = execute_attack(atk_card, p1["main"])
            if success:
                p1["main"] = None
                cpu_log = f"CPUの攻撃！あなたの城が破壊された！"
            else:
                cpu_log = f"CPUの攻撃！{res}"

    game.turn += 1
    vic = game.check_victory()
    if vic:
        await i.followup.send(f"🏁 **ゲーム終了！勝者：{vic}**")
        return

    await i.followup.edit_message(message_id=i.message.id, content=f"あなたのターンです\n【ログ】{cpu_log}", embed=make_embed(game), view=MainView(game))

# --- UI: 攻撃ボタンView ---
class AttackView(discord.ui.View):
    def __init__(self, game):
        super().__init__()
        self.game = game

    @discord.ui.button(label="レフトから(右狙い)", style=discord.ButtonStyle.danger)
    async def atk_left(self, i: discord.Interaction, b: discord.ui.Button):
        await self.process_atk(i, "left", "right")

    @discord.ui.button(label="ライトから(左狙い)", style=discord.ButtonStyle.danger)
    async def atk_right(self, i: discord.Interaction, b: discord.ui.Button):
        await self.process_atk(i, "right", "left")

    async def process_atk(self, i, my_pos, target_pos):
        p = self.game.players["p1"]
        c = self.game.players["cpu"]
        
        if not p[my_pos]:
            return await i.response.send_message("その位置に攻撃可能なカードがありません。", ephemeral=True)
        
        atk_card = p[my_pos].pop() # 消費
        # ターゲット優先順位：メイン(城)を優先して狙う仕様
        target_card = c["main"]
        
        if target_card:
            success, res = execute_attack(atk_card, target_card)
            if success:
                c["main"] = None
                self.game.logs = f"城の破壊に成功！勝機です！"
            else:
                self.game.logs = f"攻撃失敗：{res}"
        
        await i.response.edit_message(content="攻撃終了。CPUの番です...", view=None)
        await cpu_logic(i, self.game)

# --- 既存Viewへの統合（カードを使用する内） ---
class ActionCategoryView(discord.ui.View):
    def __init__(self, game):
        super().__init__()
        self.game = game

    @discord.ui.button(label="攻撃", style=discord.ButtonStyle.danger)
    async def attack(self, i: discord.Interaction, b: discord.ui.Button):
        if self.game.turn <= 2:
            return await i.response.send_message("準備期間（2周）は攻撃できません！", ephemeral=True)
        await i.response.edit_message(content="攻撃位置を選んでください（カードを1枚消費します）", view=AttackView(self.game))

    @discord.ui.button(label="配置", style=discord.ButtonStyle.secondary)
    async def deploy(self, i: discord.Interaction, b: discord.ui.Button):
        # 以前のDeployViewを呼び出し
        pass

