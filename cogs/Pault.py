import discord
from discord.ext import commands
from discord import app_commands
import random
import asyncio

# --- 定数・スタッツ定義 (提供通り) ---
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
        if self.players["cpu"]["main"] is None: return "p1"
        if self.players["p1"]["main"] is None: return "cpu"
        return None

# --- 提供されたロジック関数 (そのまま) ---
def execute_attack(attacker_card, defender_card):
    atk = BATTLE_STATS.get(attacker_card["name"], [0, 0])[0]
    dfn = BATTLE_STATS.get(defender_card["name"], [0, 0])[1]
    
    if defender_card.get("is_hidden", False):
        defender_card["is_hidden"] = False 
        return False, "防御状態により防がれた！"
    if atk > dfn:
        return True, "破壊成功！"
    return False, "防御力が高い…破壊失敗。"

def make_embed(game):
    p = game.players["p1"]
    c = game.players["cpu"]
    embed = discord.Embed(title="🏰 Pault 盤面", color=0x2f3136)
    embed.add_field(name="ターン", value=game.turn, inline=True)
    embed.add_field(name="ログ", value=game.logs, inline=False)
    
    def get_name(card): return card["name"] if card else "空"
    
    embed.add_field(name="相手(CPU)の城", value=get_name(c["main"]), inline=True)
    embed.add_field(name="あなたの城", value=get_name(p["main"]), inline=True)
    return embed

# --- 提供されたUIクラス (そのまま) ---
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
        
        atk_card = p[my_pos].pop()
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
        await i.response.send_message("配置機能は準備中です。", ephemeral=True)

# --- CPUロジック (そのまま) ---
async def cpu_logic(i, game):
    cpu = game.players["cpu"]
    p1 = game.players["p1"]
    if game.deck:
        card = game.deck.pop()
        if not cpu["main"] and card["type"] == "戦闘":
            cpu["main"] = card
        else:
            cpu["hand"].append(card)
    for idx, c in enumerate(cpu["hand"]):
        if c["type"] == "戦闘":
            if len(cpu["left"]) < 2: cpu["left"].append(cpu["hand"].pop(idx)); break
            if len(cpu["right"]) < 2: cpu["right"].append(cpu["hand"].pop(idx)); break
    cpu_log = "CPUはカードを整理した。"
    if game.turn > 2:
        if cpu["left"] and p1["main"]:
            atk_card = cpu["left"].pop()
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
    await i.followup.send(content=f"あなたのターンです\n【ログ】{cpu_log}", embed=make_embed(game), view=ActionCategoryView(game))

# --- Cog定義 ---
class Pault(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.games = {}

    @app_commands.command(name="pault", description="Pault対戦を開始します")
    async def pault(self, interaction: discord.Interaction):
        game = PaultGame(interaction.channel_id, interaction.user.id, interaction.user.display_name)
        # 初期配置
        for _ in range(5):
            if game.deck:
                c = game.deck.pop()
                if not game.players["p1"]["main"] and c["type"] == "戦闘":
                    game.players["p1"]["main"] = c
                else:
                    game.players["p1"]["hand"].append(c)
        
        self.games[interaction.user.id] = game
        await interaction.response.send_message(embed=make_embed(game), view=ActionCategoryView(game))

async def setup(bot):
    await bot.add_cog(Pault(bot))