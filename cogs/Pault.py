# ~/BOT/cogs/Pault.py
# -*- coding: utf-8 -*-
import discord
from discord.ext import commands
from discord import app_commands
import random
import asyncio

# --- 定数・スタッツ定義 ---
BATTLE_STATS = {
    "ソルジャー": [1, 0], "アサシン": [3, 0], "ナイト": [2, 1],
    "シールド": [1, 2], "ランナー": [1, 0], "イーター": [2, 0],
    "アーチャー": [1, 0], "バーサーカー": [1, 1], "盾士": [1, 0]
}

def get_options_from_list(items, battle_stats, filter_type=None):
    """カードリストからセレクトメニューの選択肢を生成"""
    options = []
    for i, card in enumerate(items):
        if filter_type is None or card.get("type") == filter_type:
            if card.get("type") == "戦闘":
                s = battle_stats.get(card["name"], [0, 0])
                label = f"{card['name']} (ATK:{s[0]}/DFN:{s[1]})"
            else:
                label = f"{card['name']} [{card.get('type', '不明')}]"
            # インデックスをvalueとして保持
            options.append(discord.SelectOption(label=label, value=str(i)))
    return options

# --- 準備フェーズ用View ---
class InitialSetupView(discord.ui.View):
    def __init__(self, game):
        super().__init__(timeout=180)
        self.game = game
        self.step = "main"  # main -> left -> right
        self.update_select()

    def update_select(self):
        """現在のステップに合わせてセレクトメニューを更新"""
        self.clear_items()
        hand = self.game.players["p1"]["hand"]
        options = get_options_from_list(hand, BATTLE_STATS, filter_type="戦闘")

        if not options:
            # 万が一戦闘カードが足りない場合のフォールバック
            return

        if self.step == "main":
            placeholder, min_v, max_v = "城（メイン）を選択してください", 1, 1
        elif self.step == "left":
            placeholder, min_v, max_v = "レフトに配置するカード（最大3枚）", 1, min(3, len(options))
        else: # right
            placeholder, min_v, max_v = "ライトに配置するカード（最大3枚）", 1, min(3, len(options))

        select = discord.ui.Select(
            placeholder=placeholder,
            min_values=min_v,
            max_values=max_v,
            options=options
        )
        select.callback = self.handle_selection
        self.add_item(select)

    async def handle_selection(self, interaction: discord.Interaction):
        # 選択されたインデックスを数値リストに変換
        indices = sorted([int(v) for v in interaction.data['values']], reverse=True)
        hand = self.game.players["p1"]["hand"]
        
        # 選択されたカードを抽出
        selected_cards = []
        for idx in indices:
            selected_cards.append(hand.pop(idx))

        # ステップごとの反映処理
        if self.step == "main":
            self.game.players["p1"]["main"] = selected_cards[0]
            self.step = "left"
            self.update_select()
            await interaction.response.edit_message(content="🏰 **レフトスポーン**を選択してください（最大3枚）", view=self)
        
        elif self.step == "left":
            self.game.players["p1"]["left"].extend(selected_cards)
            self.step = "right"
            self.update_select()
            await interaction.response.edit_message(content="🏰 **ライトスポーン**を選択してください（最大3枚）", view=self)
        
        elif self.step == "right":
            self.game.players["p1"]["right"].extend(selected_cards)
            # 準備完了、メインメニューへ
            await interaction.response.edit_message(
                content="準備完了！対戦開始です。", 
                embed=make_embed(self.game), 
                view=MainMenuView(self.game)
            )

# --- ゲームロジック・盤面 ---
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
        # 最初は戦闘カードを3枚、その他を2枚
        battles = [c for c in self.deck if c["type"] == "戦闘"]
        for _ in range(3):
            if battles:
                card = battles.pop(0)
                p1["hand"].append(card)
                self.deck.remove(card)
        for _ in range(2):
            if self.deck: p1["hand"].append(self.deck.pop(0))

    def check_victory(self):
        if self.players["cpu"]["main"] is None: return self.players["p1"]["name"]
        if self.players["p1"]["main"] is None: return "CPU"
        return None

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
    
    def get_n(card): return f"🛡️ {card['name']}" if card else "❌ 陥落"
    def get_l(cards): return " | ".join([c["name"] for c in cards]) if cards else "なし"
    
    embed.add_field(name="相手(CPU)の城", value=get_n(c["main"]), inline=True)
    embed.add_field(name="あなたの城", value=get_n(p["main"]), inline=True)
    embed.add_field(name="相手の布陣", value=f"L: [{get_l(c['left'])}]\nR: [{get_l(c['right'])}]", inline=False)
    embed.add_field(name="あなたの布陣", value=f"L: [{get_l(p['left'])}]\nR: [{get_l(p['right'])}]", inline=False)
    embed.add_field(name="手札", value=f"{len(p['hand'])}枚", inline=True)
    return embed

async def cpu_turn_logic(i, game):
    cpu, p1 = game.players["cpu"], game.players["p1"]
    if game.deck: cpu["hand"].append(game.deck.pop(0))
    for idx, c in enumerate(cpu["hand"][:]):
        if c["type"] == "戦闘":
            if not cpu["main"]: cpu["main"] = cpu["hand"].pop(idx)
            elif len(cpu["left"]) < 2: cpu["left"].append(cpu["hand"].pop(idx))
            elif len(cpu["right"]) < 2: cpu["right"].append(cpu["hand"].pop(idx))

    cpu_log = "CPUは布陣を整えた。"
    if game.turn > 2:
        for side in ["left", "right"]:
            if cpu[side] and p1["main"]:
                atk_card = cpu[side].pop()
                success, _ = execute_attack(atk_card, p1["main"])
                if success: 
                    p1["main"] = None
                    cpu_log = f"CPUの攻撃であなたの城が破壊された！"
                break

    game.turn += 1
    vic = game.check_victory()
    if vic:
        await i.followup.send(f"🏁 **ゲーム終了！ 勝者: {vic}**")
    else:
        # CPUターンの結果を表示し、ユーザーのターンへ
        await i.edit_original_response(content=f"あなたの番です。\n【CPU】: {cpu_log}", embed=make_embed(game), view=MainMenuView(game))

# --- メインメニュー用View ---
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

class DeployPosButton(discord.ui.Button):
    def __init__(self, game, side):
        super().__init__(label=f"{side.upper()}に配置", style=discord.ButtonStyle.secondary)
        self.game, self.side = game, side

    async def callback(self, i: discord.Interaction):
        hand = self.game.players["p1"]["hand"]
        options = get_options_from_list(hand, BATTLE_STATS, filter_type="戦闘")
        if not options: return await i.response.send_message("配置できる戦闘カードがありません", ephemeral=True)

        # 選択用セレクトメニューを表示（ここでは簡易的に1枚選択）
        select = discord.ui.Select(options=options, placeholder="配置するカードを選択")
        
        async def deploy_callback(it: discord.Interaction):
            idx = int(it.data['values'][0])
            card = hand.pop(idx)
            if self.side == "main": self.game.players["p1"]["main"] = card
            else: self.game.players["p1"][self.side].append(card)
            await it.response.edit_message(content="配置しました", embed=make_embed(self.game), view=MainMenuView(self.game))
        
        select.callback = deploy_callback
        view = discord.ui.View(); view.add_item(select)
        await i.response.edit_message(content="カードを選んでください", view=view)

class AtkPosButton(discord.ui.Button):
    def __init__(self, game, side):
        super().__init__(label=f"{side.upper()}から攻撃", style=discord.ButtonStyle.danger)
        self.game, self.side = game, side

    async def callback(self, i: discord.Interaction):
        p1, cpu = self.game.players["p1"], self.game.players["cpu"]
        if not p1[self.side]: return await i.response.send_message("その列にカードがいません", ephemeral=True)
        
        await i.response.defer()
        atk_card = p1[self.side].pop()
        target_side = "right" if self.side == "left" else "left"
        
        if cpu[target_side]:
            target_card = cpu[target_side][-1]
            success, res = execute_attack(atk_card, target_card)
            if success: cpu[target_side].pop()
        else:
            success, res = execute_attack(atk_card, cpu["main"])
            if success: cpu["main"] = None
        
        await i.edit_original_response(content="CPUのターン...", view=None)
        await asyncio.sleep(1)
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
            async def make_callback(side):
                async def q_dep(it: discord.Interaction):
                    await it.response.defer()
                    if side == "main": self.game.players["p1"]["main"] = self.card
                    else: self.game.players["p1"][side].append(self.card)
                    await cpu_turn_logic(it, self.game)
                return q_dep
            btn.callback = await make_callback(s)
            v.add_item(btn)
        await i.response.edit_message(content="どこに配置しますか？", view=v)

    @discord.ui.button(label="手札保持", style=discord.ButtonStyle.secondary)
    async def keep(self, i: discord.Interaction, b: discord.ui.Button):
        await i.response.defer()
        self.game.players["p1"]["hand"].append(self.card)
        await cpu_turn_logic(i, self.game)

# --- Cog定義 ---
class Pault(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="pault", description="Pault対戦を開始")
    async def pault(self, interaction: discord.Interaction):
        game = PaultGame(interaction.channel_id, interaction.user.id, interaction.user.display_name)
        # 修正された準備用Viewを呼び出し
        view = InitialSetupView(game)
        await interaction.response.send_message(
            "🏰 **Pault 準備フェーズ**\nまずは**城（メイン）**を選んでください。", 
            view=view
        )

async def setup(bot):
    await bot.add_cog(Pault(bot))