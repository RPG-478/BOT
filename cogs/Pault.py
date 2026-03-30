# -*- coding: utf-8 -*-
import discord
from discord.ext import commands
from discord import app_commands
import random
import asyncio

# 自作モジュールのインポート
import config
import df_module as df 

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
        self.logs = "準備フェーズ：城と布陣を決定してください。"
        self.initial_draw()

    def create_deck(self):
        deck = []
        for _ in range(40):
            t = random.choices(["戦闘", "サポート"], weights=[80, 20])[0]
            name = random.choice(list(BATTLE_STATS.keys()) if t == "戦闘" else ["ドロー", "サブ破壊"])
            deck.append({"name": name, "type": t})
        random.shuffle(deck)
        return deck

    def initial_draw(self):
        p1 = self.players["p1"]
        battles = [c for c in self.deck if c["type"] == "戦闘"]
        # 戦闘カード3枚を優先ドロー
        for _ in range(3):
            if battles:
                card = battles.pop(0)
                p1["hand"].append(card)
                self.deck.remove(card)
        # 残り2枚
        for _ in range(2):
            if self.deck: p1["hand"].append(self.deck.pop(0))

    def check_victory(self):
        if self.players["cpu"]["main"] is None: return self.players["p1"]["name"]
        if self.players["p1"]["main"] is None: return "CPU"
        return None

# --- ロジック関数 ---
def execute_attack(attacker_card, defender_card):
    if not defender_card: return True, "城を直接攻撃！"
    atk = BATTLE_STATS.get(attacker_card["name"], [0, 0])[0]
    dfn = BATTLE_STATS.get(defender_card["name"], [0, 0])[1]
    if atk > dfn: return True, f"{defender_card['name']}を撃破！"
    return False, f"{defender_card['name']}に防がれた…"

def make_embed(game):
    p, c = game.players["p1"], game.players["cpu"]
    embed = discord.Embed(title="🏰 Pault 盤面", color=0x2f3136)
    embed.add_field(name="ターン", value=game.turn, inline=True)
    embed.add_field(name="ログ", value=game.logs, inline=False)
    
    def get_n(card): return f"🛡️ {card['name']}" if card else "❌ 空"
    def get_l(cards): return " | ".join([c["name"] for c in cards]) if cards else "空野"
    
    embed.add_field(name="相手(CPU)の城", value=get_n(c["main"]), inline=True)
    embed.add_field(name="あなたの城", value=get_n(p["main"]), inline=True)
    embed.add_field(name="相手の布陣", value=f"L: [{get_l(c['left'])}]\nR: [{get_l(c['right'])}]", inline=False)
    embed.add_field(name="あなたの布陣", value=f"L: [{get_l(p['left'])}]\nR: [{get_l(p['right'])}]", inline=False)
    embed.add_field(name="手札", value=f"{len(p['hand'])}枚", inline=True)
    return embed

# --- UI Views ---

class MainMenuView(discord.ui.View):
    def __init__(self, game):
        super().__init__(timeout=None)
        self.game = game

    @discord.ui.button(label="攻撃", style=discord.ButtonStyle.danger)
    async def attack(self, i: discord.Interaction, b: discord.ui.Button):
        if self.game.turn <= 2: 
            return await i.response.send_message("準備期間（2ターン目まで）は攻撃禁止です", ephemeral=True)
        view = discord.ui.View()
        view.add_item(AtkPosButton(self.game, "left"))
        view.add_item(AtkPosButton(self.game, "right"))
        await i.response.edit_message(content="どの位置から攻撃しますか？", view=view)

    @discord.ui.button(label="ドロー", style=discord.ButtonStyle.primary)
    async def draw(self, i: discord.Interaction, b: discord.ui.Button):
        if not self.game.deck: return await i.response.send_message("山札切れ！", ephemeral=True)
        card = self.game.deck.pop(0)
        await i.response.edit_message(content=f"🎴 **{card['name']}** を引きました。", view=DrawResultView(self.game, card))

    @discord.ui.button(label="配置", style=discord.ButtonStyle.secondary)
    async def deploy(self, i: discord.Interaction, b: discord.ui.Button):
        view = discord.ui.View()
        for side in ["main", "left", "right"]:
            view.add_item(DeployPosButton(self.game, side))
        await i.response.edit_message(content="配置先を選んでください：", view=view)

    @discord.ui.button(label="サポート", style=discord.ButtonStyle.success)
    async def support(self, i: discord.Interaction, b: discord.ui.Button):
        hand = self.game.players["p1"]["hand"]
        options = df.get_options_from_list(hand, filter_type="サポート")
        if not options: return await i.response.send_message("使用可能なサポートがありません", ephemeral=True)
        
        async def support_logic(interaction, indices):
            card = hand.pop(indices[0])
            self.game.logs = f"サポート【{card['name']}】発動！ (効果は順次実装)"
            await interaction.response.edit_message(content=self.game.logs, embed=make_embed(self.game), view=MainMenuView(self.game))

        await i.response.edit_message(content="サポートカードを選択：", view=df.GenericPickerView(options, 1, 1, "発動するカード", support_logic))

    @discord.ui.button(label="降参", style=discord.ButtonStyle.grey)
    async def surrender(self, i: discord.Interaction, b: discord.ui.Button):
        await i.response.edit_message(content="🏳️ 降参しました。ゲーム終了。", embed=None, view=None)

# --- 補助コンポーネント ---

class DeployPosButton(discord.ui.Button):
    def __init__(self, game, side):
        super().__init__(label=f"{side.upper()}に配置", style=discord.ButtonStyle.secondary)
        self.game, self.side = game, side

    async def callback(self, i: discord.Interaction):
        hand = self.game.players["p1"]["hand"]
        options = df.get_options_from_list(hand, filter_type="戦闘")
        if not options: return await i.response.send_message("配置できる戦闘カードがありません", ephemeral=True)

        async def deploy_logic(interaction, indices):
            for idx in indices:
                card = hand.pop(idx)
                if self.side == "main": self.game.players["p1"]["main"] = card
                else: self.game.players["p1"][self.side].append(card)
            self.game.logs = f"{self.side}にカードを配置しました。"
            await interaction.response.edit_message(content=self.game.logs, embed=make_embed(self.game), view=MainMenuView(self.game))

        max_v = 1 if self.side == "main" else 5
        await i.response.edit_message(content=f"{self.side}に置くカードを選んでください", view=df.GenericPickerView(options, 1, max_v, "カード選択", deploy_logic))

class AtkPosButton(discord.ui.Button):
    def __init__(self, game, side):
        super().__init__(label=f"{side.upper()}から攻撃", style=discord.ButtonStyle.danger)
        self.game, self.side = game, side

    async def callback(self, i: discord.Interaction):
        p1, cpu = self.game.players["p1"], self.game.players["cpu"]
        if not p1[self.side]: return await i.response.send_message("攻撃できるカードがいません", ephemeral=True)
        
        atk_card = p1[self.side].pop()
        # 相手の対面スポンを狙う（Leftなら相手のRight、Rightなら相手のLeft）
        target_side = "right" if self.side == "left" else "left"
        
        if cpu[target_side]:
            target_card = cpu[target_side][-1] # 一番上のカード
            success, res = execute_attack(atk_card, target_card)
            if success: cpu[target_side].pop()
        else:
            success, res = execute_attack(atk_card, cpu["main"])
            if success: cpu["main"] = None
            
        self.game.logs = f"{self.side}からの攻撃：{res}"
        await i.response.edit_message(content="CPUのターンへ...", view=None)
        await cpu_turn_logic(i, self.game)

class DrawResultView(discord.ui.View):
    def __init__(self, game, card):
        super().__init__()
        self.game, self.card = game, card

    @discord.ui.button(label="即座に配置", style=discord.ButtonStyle.success)
    async def deploy(self, i: discord.Interaction, b: discord.ui.Button):
        v = discord.ui.View()
        for s in ["main", "left", "right"]:
            btn = discord.ui.Button(label=s.upper())
            async def q_dep(it, side=s):
                if side == "main": self.game.players["p1"]["main"] = self.card
                else: self.game.players["p1"][side].append(self.card)
                await it.response.edit_message(content="配置完了。CPUターンへ", view=None)
                await cpu_turn_logic(it, self.game)
            btn.callback = q_dep
            v.add_item(btn)
        await i.response.edit_message(content="どこに配置しますか？", view=v)

    @discord.ui.button(label="手札に保持", style=discord.ButtonStyle.secondary)
    async def keep(self, i: discord.Interaction, b: discord.ui.Button):
        self.game.players["p1"]["hand"].append(self.card)
        await i.response.edit_message(content="手札に加えました。", view=None)
        await cpu_turn_logic(i, self.game)

# --- CPU Logic ---
async def cpu_turn_logic(i, game):
    cpu, p1 = game.players["cpu"], game.players["p1"]
    if game.deck: cpu["hand"].append(game.deck.pop(0))
    
    # 簡易AI: 戦闘カードがあれば城＞左＞右の順で埋める
    for idx, c in enumerate(cpu["hand"][:]):
        if c["type"] == "戦闘":
            if not cpu["main"]: cpu["main"] = cpu["hand"].pop(idx)
            elif len(cpu["left"]) < 2: cpu["left"].append(cpu["hand"].pop(idx))
            elif len(cpu["right"]) < 2: cpu["right"].append(cpu["hand"].pop(idx))

    cpu_log = "CPUは防衛を固めた。"
    if game.turn > 2:
        # 左から優先攻撃
        for side in ["left", "right"]:
            if cpu[side] and p1["main"]:
                atk_card = cpu[side].pop()
                success, _ = execute_attack(atk_card, p1["main"])
                if success: p1["main"] = None; cpu_log = f"CPUの{side}攻撃で城が破壊された！"
                break

    game.turn += 1
    vic = game.check_victory()
    if vic:
        await i.followup.send(f"🏁 **ゲーム終了！ 勝者: {vic}**")
    else:
        await i.followup.send(content=f"あなたの番です。\n【CPU】: {cpu_log}", embed=make_embed(game), view=MainMenuView(game))

# --- Cog ---
class Pault(commands.Cog):
    def __init__(self, bot): self.bot = bot

    @app_commands.command(name="pault", description="Pault対戦を開始")
    async def pault(self, interaction: discord.Interaction):
        game = PaultGame(interaction.channel_id, interaction.user.id, interaction.user.display_name)
        hand = game.players["p1"]["hand"]

        # 準備フェーズ連鎖
        async def step3_right(i3, idx3):
            for idx in idx3: game.players["p1"]["right"].append(hand.pop(idx))
            await i3.response.edit_message(content="準備完了！対戦開始です。", embed=make_embed(game), view=MainMenuView(game))

        async def step2_left(i2, idx2):
            for idx in idx2: game.players["p1"]["left"].append(hand.pop(idx))
            opt_r = df.get_options_from_list(hand, "戦闘")
            await i2.response.edit_message(content="次は **ライトスポーン** を選択してください", view=df.GenericPickerView(opt_r, 1, 5, "ライト配置", step3_right))

        async def step1_main(i1, idx1):
            game.players["p1"]["main"] = hand.pop(idx1[0])
            opt_l = df.get_options_from_list(hand, "戦闘")
            await i1.response.edit_message(content="次は **レフトスポーン** を選択してください", view=df.GenericPickerView(opt_l, 1, 5, "レフト配置", step2_left))

        opt_m = df.get_options_from_list(hand, "戦闘")
        await interaction.response.send_message("🏰 **Pault 準備フェーズ**\n城(Main)となるカードを選んでください。", view=df.GenericPickerView(opt_m, 1, 1, "城を選択", step1_main))

async def setup(bot): await bot.add_cog(Pault(bot))
