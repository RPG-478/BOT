# ~/BOT/cogs/Pault.py
# -*- coding: utf-8 -*-
import discord
from discord.ext import commands
from discord import app_commands
import random
import asyncio
import config
import defining as df 

# --- 定数・スタッツ定義 ---
BATTLE_STATS = {
    "ソルジャー": [1, 0], "アサシン": [3, 0], "ナイト": [2, 1],
    "シールド": [1, 2], "ランナー": [1, 0], "イーター": [2, 0],
    "アーチャー": [1, 0], "バーサーカー": [1, 1], "盾士": [1, 0]
}
def get_options_from_list(items, battle_stats, filter_type=None):
    """
    カードリストからセレクトメニューの選択肢を生成します。
    battle_statsを引数に取ることで、循環参照を回避しています。
    """
    options = []
    for i, card in enumerate(items):
        if filter_type is None or card.get("type") == filter_type:
            if card.get("type") == "戦闘":
                s = battle_stats.get(card["name"], [0, 0])
                label = f"{card['name']} (ATK:{s[0]}/DFN:{s[1]})"
            else:
                label = f"{card['name']} [{card.get('type', '不明')}]"
                
            options.append(discord.SelectOption(label=label, value=str(i)))
    return options

class GenericPickerView(discord.ui.View):
    """汎用的なカード選択用Viewクラスです。"""
    def __init__(self, options, min_v, max_v, placeholder, callback_func):
        super().__init__(timeout=None)
        select = discord.ui.Select(
            placeholder=placeholder,
            min_values=min_v,
            max_values=max_v,
            options=options
        )
        async def internal_callback(interaction):
            indices = [int(v) for v in select.values]
            await callback_func(interaction, indices)
        select.callback = internal_callback
        self.add_item(select)
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
    
    def get_n(card): return f"🛡️ {card['name']}" if card else "❌ 空"
    def get_l(cards): return " | ".join([c["name"] for c in cards]) if cards else "空野"
    
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
                if success: p1["main"] = None; cpu_log = f"CPUの攻撃で城が破壊された！"
                break

    game.turn += 1
    vic = game.check_victory()
    if vic:
        await i.followup.send(f"🏁 **ゲーム終了！ 勝者: {vic}**")
    else:
        await i.edit_original_response(content=f"あなたの番です。\n【CPU】: {cpu_log}", embed=make_embed(game), view=MainMenuView(game))

class MainMenuView(discord.ui.View):
    def __init__(self, game):
        super().__init__(timeout=None)
        self.game = game

    @discord.ui.button(label="攻撃", style=discord.ButtonStyle.danger)
    async def attack(self, i: discord.Interaction, b: discord.ui.Button):
        if self.game.turn <= 2: 
            return await i.response.send_message("準備期間は攻撃禁止です", ephemeral=True)
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
        options = df.get_options_from_list(hand, BATTLE_STATS, filter_type="サポート")
        if not options: return await i.response.send_message("使用可能なサポートがありません", ephemeral=True)
        
        async def support_logic(interaction, indices):
            await interaction.response.defer()
            card = hand.pop(indices[0])
            self.game.logs = f"サポート【{card['name']}】発動！"
            await interaction.edit_original_response(content=self.game.logs, embed=make_embed(self.game), view=MainMenuView(self.game))

        await i.response.edit_message(content="サポートカードを選択：", view=df.GenericPickerView(options, 1, 1, "発動するカード", support_logic))

class DeployPosButton(discord.ui.Button):
    def __init__(self, game, side):
        super().__init__(label=f"{side.upper()}に配置", style=discord.ButtonStyle.secondary)
        self.game, self.side = game, side

    async def callback(self, i: discord.Interaction):
        hand = self.game.players["p1"]["hand"]
        options = df.get_options_from_list(hand, BATTLE_STATS, filter_type="戦闘")
        if not options: return await i.response.send_message("戦闘カードがありません", ephemeral=True)

        async def deploy_logic(interaction, indices):
            await interaction.response.defer()
            for idx in sorted(indices, reverse=True):
                card = hand.pop(idx)
                if self.side == "main": self.game.players["p1"]["main"] = card
                else: self.game.players["p1"][self.side].append(card)
            await interaction.edit_original_response(content="配置しました", embed=make_embed(self.game), view=MainMenuView(self.game))

        await i.response.edit_message(content="カードを選んでください", view=df.GenericPickerView(options, 1, 1, "選択", deploy_logic))

class AtkPosButton(discord.ui.Button):
    def __init__(self, game, side):
        super().__init__(label=f"{side.upper()}から攻撃", style=discord.ButtonStyle.danger)
        self.game, self.side = game, side

    async def callback(self, i: discord.Interaction):
        await i.response.defer()
        p1, cpu = self.game.players["p1"], self.game.players["cpu"]
        if not p1[self.side]: return await i.followup.send("カードがいません", ephemeral=True)
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
                await it.response.defer()
                if side == "main": self.game.players["p1"]["main"] = self.card
                else: self.game.players["p1"][side].append(self.card)
                await cpu_turn_logic(it, self.game)
            btn.callback = q_dep
            v.add_item(btn)
        await i.response.edit_message(content="どこに配置しますか？", view=v)

    @discord.ui.button(label="手札保持", style=discord.ButtonStyle.secondary)
    async def keep(self, i: discord.Interaction, b: discord.ui.Button):
        await i.response.defer()
        self.game.players["p1"]["hand"].append(self.card)
        await cpu_turn_logic(i, self.game)

class Pault(commands.Cog):
    def __init__(self, bot): self.bot = bot

    @app_commands.command(name="pault", description="Pault対戦を開始")
    async def pault(self, interaction: discord.Interaction):
        await interaction.response.defer()
        game = PaultGame(interaction.channel_id, interaction.user.id, interaction.user.display_name)
        hand = game.players["p1"]["hand"]

        async def step3_right(i3, idx3):
            await i3.response.defer()
            for idx in sorted(idx3, reverse=True): 
                game.players["p1"]["right"].append(hand.pop(idx))
            await i3.edit_original_response(content="準備完了！", embed=make_embed(game), view=MainMenuView(game))

        async def step2_left(i2, idx2):
            await i2.response.defer()
            for idx in sorted(idx2, reverse=True): 
                game.players["p1"]["left"].append(hand.pop(idx))
            opt_r = df.get_options_from_list(hand, BATTLE_STATS, "戦闘")
            await i2.edit_original_response(content="ライトスポーンを選択してください（最大3枚）", view=df.GenericPickerView(opt_r, 1, 3, "ライト配置", step3_right))

        async def step1_main(i1, idx1):
            await i1.response.defer()
            game.players["p1"]["main"] = hand.pop(idx1[0])
            opt_l = df.get_options_from_list(hand, BATTLE_STATS, "戦闘")
            await i1.edit_original_response(content="レフトスポーンを選択してください（最大3枚）", view=df.GenericPickerView(opt_l, 1, 3, "レフト配置", step2_left))

        opt_m = df.get_options_from_list(hand, BATTLE_STATS, "戦闘")
        await interaction.followup.send("🏰 **Pault 準備フェーズ**\n城を選んでください。", view=df.GenericPickerView(opt_m, 1, 1, "城選択", step1_main))

async def setup(bot): await bot.add_cog(Pault(bot))
