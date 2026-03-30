# -*- coding: utf-8 -*-
import discord
from discord.ext import commands
from discord import app_commands
import random
import asyncio

# 自作モジュールのインポート
import config
import defining as df

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
        self.logs = "準備フェーズ：まずは「城」にするカードを選んでください。"
        # 初期ドロー実行
        self.initial_draw()

    def create_deck(self):
        deck = []
        for _ in range(40):
            t = random.choices(["戦闘", "サポート"], weights=[80, 20])[0]
            name = random.choice(list(BATTLE_STATS.keys()) if t == "戦闘" else ["ドロー", "サブ破壊"])
            deck.append({"name": name, "type": t, "def_broken": False})
        random.shuffle(deck)
        return deck

    def initial_draw(self):
        """戦闘カード3枚 + ランダム2枚を配る"""
        p1 = self.players["p1"]
        # デッキから戦闘カードとそれ以外を分ける
        battles = [c for c in self.deck if c["type"] == "戦闘"]
        others = [c for c in self.deck if c["type"] != "戦闘"]
        
        # 戦闘3枚確定
        for _ in range(3):
            if battles:
                card = battles.pop(0)
                p1["hand"].append(card)
                self.deck.remove(card)
        
        # 残り2枚を補充
        for _ in range(2):
            if self.deck:
                p1["hand"].append(self.deck.pop(0))

    def check_victory(self):
        if self.players["cpu"]["main"] is None: return "p1"
        if self.players["p1"]["main"] is None: return "cpu"
        return None

# --- ヘルパー関数 ---
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
    def get_list(cards): return ", ".join([c["name"] for c in cards]) if cards else "空"
    
    embed.add_field(name="相手(CPU)の城", value=get_name(c["main"]), inline=True)
    embed.add_field(name="あなたの城", value=get_name(p["main"]), inline=True)
    embed.add_field(name="あなたの布陣", value=f"L: [{get_list(p['left'])}]\nR: [{get_list(p['right'])}]", inline=False)
    return embed

# --- 準備フェーズUI ---

class SetupMainSelect(discord.ui.Select):
    def __init__(self, game):
        self.game = game
        options = [
            discord.SelectOption(label=c["name"], value=str(i))
            for i, c in enumerate(game.players["p1"]["hand"]) if c["type"] == "戦闘"
        ]
        super().__init__(placeholder="城(Main)にするカードを選択...", options=options)

    async def callback(self, i: discord.Interaction):
        idx = int(self.values[0])
        p1 = self.game.players["p1"]
        p1["main"] = p1["hand"].pop(idx)
        await i.response.edit_message(content="🏰 城を配置しました。次に **レフト** に置くカードを選んでください（複数可）", view=SetupLeftView(self.game))

class SetupLeftView(discord.ui.View):
    def __init__(self, game):
        super().__init__()
        options = [
            discord.SelectOption(label=c["name"], value=str(i))
            for i, c in enumerate(game.players["p1"]["hand"]) if c["type"] == "戦闘"
        ]
        if options:
            self.add_item(SetupLeftSelect(game, options))
        else:
            self.add_item(SkipButton(game, "left"))

class SetupLeftSelect(discord.ui.Select):
    def __init__(self, game, options):
        self.game = game
        super().__init__(placeholder="レフト配置を選択...", min_values=1, max_values=len(options), options=options)

    async def callback(self, i: discord.Interaction):
        p1 = self.game.players["p1"]
        indices = sorted([int(v) for v in self.values], reverse=True)
        for idx in indices:
            p1["left"].append(p1["hand"].pop(idx))
        await i.response.edit_message(content="✅ レフト配置完了。最後に **ライト** を選んでください（複数可）", view=SetupRightView(self.game))

class SetupRightView(discord.ui.View):
    def __init__(self, game):
        super().__init__()
        options = [
            discord.SelectOption(label=c["name"], value=str(i))
            for i, c in enumerate(game.players["p1"]["hand"]) if c["type"] == "戦闘"
        ]
        if options:
            self.add_item(SetupRightSelect(game, options))
        else:
            self.add_item(SkipButton(game, "right"))

class SetupRightSelect(discord.ui.Select):
    def __init__(self, game, options):
        self.game = game
        super().__init__(placeholder="ライト配置を選択...", min_values=1, max_values=len(options), options=options)

    async def callback(self, i: discord.Interaction):
        p1 = self.game.players["p1"]
        indices = sorted([int(v) for v in self.values], reverse=True)
        for idx in indices:
            p1["right"].append(p1["hand"].pop(idx))
        
        # CPUも初期配置（簡易版）
        await cpu_initial_setup(self.game)
        
        self.game.logs = "準備完了！ゲームスタート！"
        await i.response.edit_message(content="⚔️ 全ての配置が完了しました。", embed=make_embed(self.game), view=ActionCategoryView(self.game))

class SkipButton(discord.ui.Button):
    def __init__(self, game, side):
        super().__init__(label=f"{side}をスキップ", style=discord.ButtonStyle.secondary)
        self.game = game
        self.side = side
    async def callback(self, i: discord.Interaction):
        if self.side == "left":
            await i.response.edit_message(content="レフトをスキップ。ライトを選んでください。", view=SetupRightView(self.game))
        else:
            await cpu_initial_setup(self.game)
            await i.response.edit_message(content="配置完了！", embed=make_embed(self.game), view=ActionCategoryView(self.game))

# --- 通常ターンUI ---

class ActionCategoryView(discord.ui.View):
    def __init__(self, game):
        super().__init__()
        self.game = game

    @discord.ui.button(label="攻撃", style=discord.ButtonStyle.danger)
    async def attack(self, i: discord.Interaction, b: discord.ui.Button):
        if self.game.turn <= 2:
            return await i.response.send_message("準備期間（2周）は攻撃禁止です！", ephemeral=True)
        await i.response.edit_message(content="攻撃位置を選択：", view=AttackView(self.game))

    @discord.ui.button(label="配置（未実装）", style=discord.ButtonStyle.secondary, disabled=True)
    async def deploy(self, i: discord.Interaction, b: discord.ui.Button):
        pass

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
            return await i.response.send_message("攻撃できるカードがありません。", ephemeral=True)
        
        atk_card = p[my_pos].pop()
        target_card = c["main"]
        if target_card:
            success, res = execute_attack(atk_card, target_card)
            if success:
                c["main"] = None
                self.game.logs = f"城の破壊に成功！"
            else:
                self.game.logs = f"攻撃失敗：{res}"
        
        await i.response.edit_message(content="CPUのターンへ...", view=None)
        await cpu_logic(i, self.game)

# --- ロジック ---

async def cpu_initial_setup(game):
    """CPUの初期配置ロジック"""
    cpu = game.players["cpu"]
    # CPUも戦闘3枚確保
    battles = [c for c in game.deck if c["type"] == "戦闘"]
    for _ in range(3):
        if battles:
            card = battles.pop(0)
            game.deck.remove(card)
            if not cpu["main"]: cpu["main"] = card
            elif len(cpu["left"]) < 1: cpu["left"].append(card)
            else: cpu["right"].append(card)

async def cpu_logic(i, game):
    cpu = game.players["cpu"]
    p1 = game.players["p1"]
    # ドロー
    if game.deck:
        cpu["hand"].append(game.deck.pop(0))
            
    cpu_log = "CPUは態勢を整えている。"
    if game.turn > 2:
        if cpu["left"] and p1["main"]:
            atk_card = cpu["left"].pop()
            success, res = execute_attack(atk_card, p1["main"])
            if success:
                p1["main"] = None
                cpu_log = f"CPUの攻撃！城が壊された！"
            else:
                cpu_log = f"CPUの攻撃失敗。"
                
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
        print(df.format_log(f"Game started by {interaction.user.display_name}"))
        game = PaultGame(interaction.channel_id, interaction.user.id, interaction.user.display_name)
        self.games[interaction.user.id] = game
        
        # 準備フェーズ：城選択Viewから開始
        view = discord.ui.View()
        view.add_item(SetupMainSelect(game))
        await interaction.response.send_message("🏰 **準備フェーズ開始**\n手札から「城」にするカードを選んでください。", view=view)

async def setup(bot):
    await bot.add_cog(Pault(bot))