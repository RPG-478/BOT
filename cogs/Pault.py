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

def make_embed(game):
    p, c = game.players["p1"], game.players["cpu"]
    embed = discord.Embed(title="Pault 盤面", color=0x2f3136)
    embed.add_field(name="ターン", value=f"第 {game.turn} ターン", inline=True)
    embed.add_field(name="ログ", value=game.logs, inline=False)
    
    def format_card(card):
        if not card: return "【 陥落 】"
        s = BATTLE_STATS.get(card["name"], [0, 0])
        return f"[{card['name']} ({s[0]}/{s[1]})]"

    # サブスポンの1番上だけを取得するヘルパー
    def get_top(cards):
        return format_card(cards[-1]) if cards else "[ 空き ]"

    # CPU盤面 (右・城・左 の順でプレイヤー視点での反転を表現)
    cpu_board = f"{get_top(c['right'])} {format_card(c['main'])} {get_top(c['left'])}"
    embed.add_field(name="▼ 相手の布陣 (右翼 | 城 | 左翼)", value=f"```\n{cpu_board}\n```", inline=False)

    embed.add_field(name="VS", value="-----------", inline=False)

    # プレイヤー盤面 (左・城・右)
    p1_board = f"{get_top(p['left'])} {format_card(p['main'])} {get_top(p['right'])}"
    embed.add_field(name="▲ あなたの布陣 (左翼 | 城 | 右翼)", value=f"```\n{p1_board}\n```", inline=False)
    
    def get_hand(cards): return ", ".join([f"[{c['name']}]" for c in cards]) if cards else "なし"
    embed.add_field(name="手札", value=get_hand(p["hand"]), inline=False)
    embed.set_footer(text=f"山札: {len(game.deck)}枚")
    return embed

class PaultGame:
    def __init__(self, channel_id, user_id, user_name):
        self.channel_id = channel_id
        self.turn = 1
        self.deck = self.create_deck()
        self.players = {
            "p1": {"id": user_id, "name": user_name, "main": None, "left": [], "right": [], "hand": []},
            "cpu": {"id": "CPU", "name": "CPU", "main": None, "left": [], "right": [], "hand": []}
        }
        self.logs = "準備フェーズ"
        self.initial_draw()
        self.cpu_initial_setup()

    def create_deck(self):
        deck = []
        for _ in range(40):
            t = random.choices(["戦闘", "サポート"], weights=[75, 25])[0]
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

    def cpu_initial_setup(self):
        cpu = self.players["cpu"]
        battles = [c for c in self.deck if c["type"] == "戦闘"][:5]
        for c in battles: self.deck.remove(c)
        cpu["main"] = battles[0]; cpu["left"] = [battles[1], battles[2]]; cpu["right"] = [battles[3], battles[4]]

    def check_victory(self):
        if self.players["cpu"]["main"] is None: return self.players["p1"]["name"]
        if self.players["p1"]["main"] is None: return "CPU"
        return None

def execute_attack(attacker_card, defender_card):
    if not defender_card: return True, "直接攻撃！"
    atk = BATTLE_STATS.get(attacker_card["name"], [0, 0])[0]
    dfn = BATTLE_STATS.get(defender_card["name"], [0, 0])[1]
    if atk > dfn: return True, f"{defender_card['name']}を撃破"
    return False, f"{defender_card['name']}に防がれた"

async def cpu_turn_logic(i, game):
    cpu, p1 = game.players["cpu"], game.players["p1"]
    if game.deck: cpu["hand"].append(game.deck.pop(0))
    logs = []
    # CPU配置ロジック
    for idx, c in enumerate(cpu["hand"][:]):
        if c["type"] == "戦闘":
            if len(cpu["left"]) < 2: cpu["left"].append(cpu["hand"].pop(idx))
            elif len(cpu["right"]) < 2: cpu["right"].append(cpu["hand"].pop(idx))
    # CPU攻撃ロジック
    if game.turn >= 2:
        for side in ["left", "right"]:
            if cpu[side]:
                # CPUから見た対面への攻撃
                target_side = "right" if side == "left" else "left"
                atk_card = cpu[side].pop(0)
                if p1[target_side]:
                    target = p1[target_side][-1]
                    win, res = execute_attack(atk_card, target)
                    if win: p1[target_side].pop()
                    logs.append(f"CPU({side})攻撃: {res}")
                else:
                    win, res = execute_attack(atk_card, p1["main"])
                    if win: p1["main"] = None
                    logs.append(f"CPU({side})が城を攻撃！")
                break
    if not logs: logs.append("CPUは待機中")
    game.logs = "\n".join(logs); game.turn += 1
    vic = game.check_victory()
    if vic: await i.edit_original_response(content=f"勝者: {vic}", embed=make_embed(game), view=None)
    else: await i.edit_original_response(content="あなたの番です", embed=make_embed(game), view=MainMenuView(game))

class MainMenuView(discord.ui.View):
    def __init__(self, game):
        super().__init__(timeout=None); self.game = game

    @discord.ui.button(label="攻撃", style=discord.ButtonStyle.danger)
    async def attack(self, i: discord.Interaction, b: discord.ui.Button):
        if self.game.turn <= 2: return await i.response.send_message("準備期間中不可", ephemeral=True)
        view = discord.ui.View()
        for s in ["left", "right"]: view.add_item(AtkPosButton(self.game, s))
        view.add_item(CancelButton(self.game)); await i.response.edit_message(content="攻撃列を選択", view=view)

    @discord.ui.button(label="ドロー", style=discord.ButtonStyle.primary)
    async def draw(self, i: discord.Interaction, b: discord.ui.Button):
        if not self.game.deck: return await i.response.send_message("山札なし", ephemeral=True)
        card = self.game.deck.pop(0); await i.response.edit_message(content=f"【{card['name']}】を引きました", embed=make_embed(self.game), view=DrawResultView(self.game, card))

    @discord.ui.button(label="配置", style=discord.ButtonStyle.secondary)
    async def deploy(self, i: discord.Interaction, b: discord.ui.Button):
        view = discord.ui.View()
        for side in ["main", "left", "right"]: view.add_item(DeployPosButton(self.game, side))
        view.add_item(CancelButton(self.game)); await i.response.edit_message(content="配置先を選択", view=view)

    @discord.ui.button(label="サポート", style=discord.ButtonStyle.success)
    async def support(self, i: discord.Interaction, b: discord.ui.Button):
        hand = self.game.players["p1"]["hand"]; opts = get_options_from_list(hand, BATTLE_STATS, "サポート")
        if not opts: return await i.response.send_message("サポートカードを持っていません", ephemeral=True)
        view = discord.ui.View(); select = discord.ui.Select(options=opts, placeholder="使用するサポートを選択")
        async def callback(it):
            card = hand.pop(int(it.data['values'][0])); await process_support_logic(it, self.game, card)
        select.callback = callback; view.add_item(select); view.add_item(CancelButton(self.game))
        await i.response.edit_message(content="サポート選択", view=view)

    @discord.ui.button(label="終了", style=discord.ButtonStyle.secondary)
    async def quit(self, i: discord.Interaction, b: discord.ui.Button):
        await i.response.edit_message(content="ゲームを終了しました", embed=None, view=None)

async def process_support_logic(interaction, game, card):
    if card["name"] == "ドロー":
        drawn = []
        for _ in range(2):
            if game.deck: drawn.append(game.deck.pop(0))
        game.players["p1"]["hand"].extend(drawn); game.logs = f"サポート発動: 2枚ドローしました"
        await interaction.response.defer(); await cpu_turn_logic(interaction, game)
    elif card["name"] == "サブ破壊":
        view = discord.ui.View()
        for s in ["left", "right"]:
            btn = discord.ui.Button(label=f"相手の{s.upper()}を1枚破壊", style=discord.ButtonStyle.danger)
            async def make_cb(side):
                async def _cb(it):
                    if game.players["cpu"][side]:
                        destroyed = game.players["cpu"][side].pop(0)
                        game.logs = f"サポート発動: 相手の{side}の{destroyed['name']}を破壊しました"
                    else: game.logs = f"相手の{side}にはカードがありませんでした"
                    await it.response.defer(); await cpu_turn_logic(it, game)
                return _cb
            btn.callback = await make_cb(s); view.add_item(btn)
        await interaction.response.edit_message(content="破壊する列を選択", view=view)

class CancelButton(discord.ui.Button):
    def __init__(self, game): super().__init__(label="キャンセル", style=discord.ButtonStyle.gray); self.game = game
    async def callback(self, i: discord.Interaction): await i.response.edit_message(content="メニューに戻りました", embed=make_embed(self.game), view=MainMenuView(self.game))

class AtkPosButton(discord.ui.Button):
    def __init__(self, game, side): super().__init__(label=f"{side.upper()}攻撃", style=discord.ButtonStyle.danger); self.game, self.side = game, side
    async def callback(self, i: discord.Interaction):
        p1, cpu = self.game.players["p1"], self.game.players["cpu"]
        if not p1[self.side]: return await i.response.send_message("カードなし", ephemeral=True)
        await i.response.defer(); atk_card = p1[self.side].pop(0); target_side = "right" if self.side == "left" else "left"
        if cpu[target_side]:
            win, res = execute_attack(atk_card, cpu[target_side][-1])
            if win: cpu[target_side].pop()
            self.game.logs = f"攻撃({self.side}): {res}"
        else:
            win, res = execute_attack(atk_card, cpu["main"])
            if win: cpu["main"] = None
            self.game.logs = f"攻撃({self.side}): 城を攻撃しました"
        await cpu_turn_logic(i, self.game)

class DeployPosButton(discord.ui.Button):
    def __init__(self, game, side): super().__init__(label=f"{side.upper()}配置", style=discord.ButtonStyle.secondary); self.game, self.side = game, side
    async def callback(self, i: discord.Interaction):
        hand = self.game.players["p1"]["hand"]; opts = get_options_from_list(hand, BATTLE_STATS, "戦闘")
        if not opts: return await i.response.send_message("戦闘カードを持っていません", ephemeral=True)
        view = discord.ui.View(); select = discord.ui.Select(options=opts)
        async def cb(it):
            card = hand.pop(int(it.data['values'][0]))
            if self.side == "main": self.game.players["p1"]["main"] = card
            else: self.game.players["p1"][self.side].append(card)
            await it.response.edit_message(content="配置完了", embed=make_embed(self.game), view=MainMenuView(self.game))
        select.callback = cb; view.add_item(select); view.add_item(CancelButton(self.game))
        await i.response.edit_message(content="配置カードを選択", view=view)

class DrawResultView(discord.ui.View):
    def __init__(self, game, card):
        super().__init__()
        self.game = game
        self.card = card
        if card["type"] == "戦闘":
            btn = discord.ui.Button(label="即座に配置", style=discord.ButtonStyle.success)
            btn.callback = self.deploy_flow
            self.add_item(btn)
        else:
            btn = discord.ui.Button(label="即座に使用", style=discord.ButtonStyle.success)
            btn.callback = self.use_immediately
            self.add_item(btn)
        keep = discord.ui.Button(label="手札へ", style=discord.ButtonStyle.secondary)
        keep.callback = self.keep_flow
        self.add_item(keep)

    async def deploy_flow(self, i):
        v = discord.ui.View()
        for s in ["main", "left", "right"]:
            b = discord.ui.Button(label=s.upper())
            def mk(side):
                async def _c(it):
                    if side == "main": self.game.players["p1"]["main"] = self.card
                    else: self.game.players["p1"][side].append(self.card)
                    await it.response.defer(); await cpu_turn_logic(it, self.game)
                return _c
            b.callback = mk(s); v.add_item(b)
        await i.response.edit_message(content="配置先を選択", view=v)

    async def use_immediately(self, i): await process_support_logic(i, self.game, self.card)

    async def keep_flow(self, i):
        self.game.players["p1"]["hand"].append(self.card); await i.response.defer(); await cpu_turn_logic(i, self.game)

class InitialSetupView(discord.ui.View):
    def __init__(self, game): super().__init__(timeout=180); self.game, self.step = game, "main"; self.update_select()
    def update_select(self):
        self.clear_items(); hand = self.game.players["p1"]["hand"]; opts = get_options_from_list(hand, BATTLE_STATS, "戦闘")
        conf = {"main": ("城を選択", 1, 1), "left": ("レフト配置(最大3枚)", 1, min(3, len(opts))), "right": ("ライト配置(最大3枚)", 1, min(3, len(opts)))}
        p, mi, ma = conf[self.step]; sel = discord.ui.Select(placeholder=p, min_values=mi, max_values=ma, options=opts)
        sel.callback = self.handle_selection; self.add_item(sel)
    async def handle_selection(self, i):
        idxs = sorted([int(v) for v in i.data['values']], reverse=True); hand = self.game.players["p1"]["hand"]; sld = [hand.pop(x) for x in idxs]
        if self.step == "main": self.game.players["p1"]["main"] = sld[0]; self.step = "left"
        elif self.step == "left": self.game.players["p1"]["left"].extend(sld); self.step = "right"
        else: self.game.players["p1"]["right"].extend(sld); await i.response.edit_message(content="開始", embed=make_embed(self.game), view=MainMenuView(self.game)); return
        self.update_select(); await i.response.edit_message(embed=make_embed(self.game), view=self)

class Pault(commands.Cog):
    def __init__(self, bot): self.bot = bot
    @app_commands.command(name="pault", description="対戦開始")
    async def pault(self, interaction: discord.Interaction):
        game = PaultGame(interaction.channel_id, interaction.user.id, interaction.user.display_name)
        await interaction.response.send_message(embed=make_embed(game), view=InitialSetupView(game))

async def setup(bot): await bot.add_cog(Pault(bot))
