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

def get_options_from_list(items, filter_type=None):
    options = []
    for i, card in enumerate(items):
        if filter_type is None or card.get("type") == filter_type:
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
        state = " (防)" if card.get("face_down") else ""
        return f"[{card['name']}{state}]"

    def get_top(cards):
        return format_card(cards[-1]) if cards else "[ --- ]"

    # CPU盤面
    cpu_board = f"{get_top(c['right'])} {format_card(c['main'])} {get_top(c['left'])}"
    embed.add_field(name="▼ CPU (R | C | L)", value=f"```\n{cpu_board}\n```", inline=False)
    embed.add_field(name="VS", value="-----------", inline=False)
    # プレイヤー盤面
    p1_board = f"{get_top(p['left'])} {format_card(p['main'])} {get_top(p['right'])}"
    embed.add_field(name="▲ YOU (L | C | R)", value=f"```\n{p1_board}\n```", inline=False)
    
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
        self.logs = "準備完了"
        self.initial_draw()
        self.cpu_initial_setup()

    def create_deck(self):
        deck = []
        for _ in range(40):
            t = random.choices(["戦闘", "サポート"], weights=[70, 30])[0]
            name = random.choice(list(BATTLE_STATS.keys())) if t == "戦闘" else random.choice(["ドロー", "サブ破壊", "裏返し"])
            deck.append({"name": name, "type": t, "face_down": False})
        random.shuffle(deck)
        return deck

    def apply_passive(self, card):
        if card and card["name"] == "盾士": card["face_down"] = True
        return card

    def initial_draw(self):
        p1 = self.players["p1"]
        battles = [c for c in self.deck if c["type"] == "戦闘"]
        for _ in range(3):
            if battles:
                c = battles.pop(0); p1["hand"].append(c); self.deck.remove(c)
        for _ in range(2):
            if self.deck: p1["hand"].append(self.deck.pop(0))

    def cpu_initial_setup(self):
        cpu = self.players["cpu"]
        battles = [c for c in self.deck if c["type"] == "戦闘"][:5]
        for c in battles: self.deck.remove(c)
        cpu["main"] = self.apply_passive(battles[0])
        cpu["left"] = [self.apply_passive(battles[1]), self.apply_passive(battles[2])]
        cpu["right"] = [self.apply_passive(battles[3]), self.apply_passive(battles[4])]

    def check_victory(self):
        if self.players["cpu"]["main"] is None: return self.players["p1"]["name"]
        if self.players["p1"]["main"] is None: return "CPU"
        return None

def execute_attack(attacker_card, defender_list, is_main=False, main_card=None):
    """
    攻撃判定ロジック。
    defender_list: 列のリスト
    is_main: 城への直接攻撃か
    """
    logs = []
    atk_val = BATTLE_STATS.get(attacker_card["name"], [0, 0])[0]
    
    # ターゲット決定
    targets = []
    if is_main:
        if main_card: targets = [("main", main_card)]
    else:
        if defender_list:
            if attacker_card["name"] == "バーサーカー":
                # 範囲攻撃: 全員を対象
                targets = [("sub", c) for c in defender_list]
            else:
                # 通常/アーチャー: 1枚目が対象
                targets = [("sub", defender_list[-1])]

    if not targets:
        return True, ["直接攻撃成功！"]

    any_destroyed = False
    for t_type, card in targets:
        res_text = ""
        if card.get("face_down"):
            card["face_down"] = False
            res_text = f"{card['name']}の(防)を解除"
        else:
            dfn_val = BATTLE_STATS.get(card["name"], [0, 0])[1]
            if atk_val > dfn_val:
                if t_type == "sub": defender_list.remove(card)
                any_destroyed = True
                res_text = f"{card['name']}撃破"
            else:
                res_text = f"{card['name']}に防がれた"
        logs.append(res_text)

    # アーチャーの貫通判定 (1枚目を撃破し、まだ後ろにカードがある場合)
    if attacker_card["name"] == "アーチャー" and any_destroyed and defender_list:
        second_card = defender_list[-1]
        if second_card.get("face_down"):
            second_card["face_down"] = False
            logs.append(f"貫通: {second_card['name']}の(防)を解除")
        else:
            dfn_val2 = BATTLE_STATS.get(second_card["name"], [0, 0])[1]
            if atk_val > dfn_val2:
                defender_list.pop()
                logs.append(f"貫通: {second_card['name']}も撃破")
            else:
                logs.append(f"貫通: {second_card['name']}に停止")

    return any_destroyed, logs

async def cpu_turn_logic(i, game):
    cpu, p1 = game.players["cpu"], game.players["p1"]
    if game.deck: cpu["hand"].append(game.deck.pop(0))
    cpu_logs = []
    # CPU配置
    for idx, c in enumerate(cpu["hand"][:]):
        if c["type"] == "戦闘":
            card = game.apply_passive(cpu["hand"].pop(idx))
            if len(cpu["left"]) < 2: cpu["left"].append(card)
            elif len(cpu["right"]) < 2: cpu["right"].append(card)
    # CPU攻撃
    if game.turn >= 2:
        for side in ["left", "right"]:
            if cpu[side] and not cpu[side][0].get("face_down"):
                target_side = "right" if side == "left" else "left"
                atk_card = cpu[side].pop(0)
                if p1[target_side]:
                    _, res = execute_attack(atk_card, p1[target_side])
                    cpu_logs.append(f"CPU({side}): " + " & ".join(res))
                else:
                    win, _ = execute_attack(atk_card, [], True, p1["main"])
                    if win: p1["main"] = None
                    cpu_logs.append(f"CPU({side}): 城攻撃！")
                break
    
    game.logs += "\n" + ("\n".join(cpu_logs) if cpu_logs else "CPU待機")
    game.turn += 1
    vic = game.check_victory()
    if vic: await i.edit_original_response(content=f"勝者: {vic}", embed=make_embed(game), view=None)
    else: await i.edit_original_response(content="あなたの番", embed=make_embed(game), view=MainMenuView(game))

class MainMenuView(discord.ui.View):
    def __init__(self, game): super().__init__(timeout=None); self.game = game

    @discord.ui.button(label="攻撃", style=discord.ButtonStyle.danger)
    async def attack(self, i, b):
        if self.game.turn <= 2: return await i.response.send_message("準備期間中不可", ephemeral=True)
        view = discord.ui.View()
        for s in ["left", "right"]: view.add_item(AtkPosButton(self.game, s))
        view.add_item(CancelButton(self.game)); await i.response.edit_message(content="攻撃列選択", view=view)

    @discord.ui.button(label="ドロー", style=discord.ButtonStyle.primary)
    async def draw(self, i, b):
        if not self.game.deck: return await i.response.send_message("山札なし", ephemeral=True)
        card = self.game.deck.pop(0)
        await i.response.edit_message(content=f"【{card['name']}】入手", embed=make_embed(self.game), view=DrawResultView(self.game, card))

    @discord.ui.button(label="配置", style=discord.ButtonStyle.secondary)
    async def deploy(self, i, b):
        view = discord.ui.View()
        for side in ["main", "left", "right"]: view.add_item(DeployPosButton(self.game, side))
        view.add_item(CancelButton(self.game)); await i.response.edit_message(content="配置先選択", view=view)

    @discord.ui.button(label="サポート", style=discord.ButtonStyle.success)
    async def support(self, i, b):
        hand = self.game.players["p1"]["hand"]; opts = get_options_from_list(hand, "サポート")
        if not opts: return await i.response.send_message("なし", ephemeral=True)
        view = discord.ui.View(); select = discord.ui.Select(options=opts, placeholder="サポート選択")
        async def callback(it):
            card = hand.pop(int(it.data['values'][0])); await process_support_logic(it, self.game, card)
        select.callback = callback; view.add_item(select); view.add_item(CancelButton(self.game))
        await i.response.edit_message(content="サポート選択", view=view)

    @discord.ui.button(label="終了", style=discord.ButtonStyle.secondary)
    async def quit(self, i, b): await i.response.edit_message(content="終了", embed=None, view=None)

async def process_support_logic(interaction, game, card):
    if card["name"] == "ドロー":
        drawn = []
        for _ in range(2):
            if game.deck: drawn.append(game.deck.pop(0))
        game.players["p1"]["hand"].extend(drawn); game.logs = "サポート: 2枚ドロー"
    elif card["name"] == "サブ破壊":
        # 簡易的に相手のL/Rのトップを破壊する処理へ誘導
        game.logs = "サポート: サブ破壊発動"
    elif card["name"] == "裏返し":
        game.logs = "サポート: 裏返し発動"
    
    await interaction.response.defer()
    await cpu_turn_logic(interaction, game)

class AtkPosButton(discord.ui.Button):
    def __init__(self, game, side): super().__init__(label=f"{side.upper()}攻撃", style=discord.ButtonStyle.danger); self.game, self.side = game, side
    async def callback(self, i):
        p1, cpu = self.game.players["p1"], self.game.players["cpu"]
        if not p1[self.side]: return await i.response.send_message("不在", ephemeral=True)
        if p1[self.side][0].get("face_down"): return await i.response.send_message("(防)は行動不可", ephemeral=True)
        
        await i.response.defer()
        atk_card = p1[self.side].pop(0); target_side = "right" if self.side == "left" else "left"
        if cpu[target_side]:
            _, res = execute_attack(atk_card, cpu[target_side])
            self.game.logs = f"攻撃({self.side}): " + " & ".join(res)
        else:
            win, _ = execute_attack(atk_card, [], True, cpu["main"])
            if win: cpu["main"] = None
            self.game.logs = f"攻撃({self.side}): 城攻撃成功"
        
        await cpu_turn_logic(i, self.game)

class DeployPosButton(discord.ui.Button):
    def __init__(self, game, side): super().__init__(label=f"{side.upper()}配置", style=discord.ButtonStyle.secondary); self.game, self.side = game, side
    async def callback(self, i):
        hand = self.game.players["p1"]["hand"]; opts = get_options_from_list(hand, "戦闘")
        if not opts: return await i.response.send_message("なし", ephemeral=True)
        view = discord.ui.View(); select = discord.ui.Select(options=opts)
        async def cb(it):
            card = self.game.apply_passive(hand.pop(int(it.data['values'][0])))
            if self.side == "main": self.game.players["p1"]["main"] = card
            else: self.game.players["p1"][self.side].append(card)
            self.game.logs = f"{self.side.upper()}に配置"
            await it.response.defer(); await cpu_turn_logic(it, self.game)
        select.callback = cb; view.add_item(select); view.add_item(CancelButton(self.game))
        await i.response.edit_message(content="配置選択", view=view)

class DrawResultView(discord.ui.View):
    def __init__(self, game, card):
        super().__init__(); self.game, self.card = game, card
        if card["type"] == "戦闘":
            btn = discord.ui.Button(label="即配置", style=discord.ButtonStyle.success); btn.callback = self.deploy_flow; self.add_item(btn)
        else:
            btn = discord.ui.Button(label="即使用", style=discord.ButtonStyle.success); btn.callback = self.use_immediately; self.add_item(btn)
        keep = discord.ui.Button(label="手札へ", style=discord.ButtonStyle.secondary); keep.callback = self.keep_flow; self.add_item(keep)
    async def deploy_flow(self, i):
        v = discord.ui.View()
        for s in ["main", "left", "right"]:
            b = discord.ui.Button(label=s.upper())
            def mk(side):
                async def _c(it):
                    c = self.game.apply_passive(self.card)
                    if side == "main": self.game.players["p1"]["main"] = c
                    else: self.game.players["p1"][side].append(c)
                    self.game.logs = f"ドロー後{side.upper()}配置"
                    await it.response.defer(); await cpu_turn_logic(it, self.game)
                return _c
            b.callback = mk(s); v.add_item(b)
        await i.response.edit_message(content="配置先", view=v)
    async def use_immediately(self, i): await process_support_logic(i, self.game, self.card)
    async def keep_flow(self, i): 
        self.game.players["p1"]["hand"].append(self.card); self.game.logs = "ドローカードを手札へ"
        await i.response.defer(); await cpu_turn_logic(i, self.game)

class InitialSetupView(discord.ui.View):
    def __init__(self, game): super().__init__(timeout=180); self.game, self.step = game, "main"; self.update_select()
    def update_select(self):
        self.clear_items(); hand = self.game.players["p1"]["hand"]; opts = get_options_from_list(hand, "戦闘")
        conf = {"main": ("城", 1, 1), "left": ("L(最大3)", 1, min(3, len(opts))), "right": ("R(最大3)", 1, min(3, len(opts)))}
        p, mi, ma = conf[self.step]; sel = discord.ui.Select(placeholder=p, min_values=mi, max_values=ma, options=opts)
        sel.callback = self.handle_selection; self.add_item(sel)
    async def handle_selection(self, i):
        idxs = sorted([int(v) for v in i.data['values']], reverse=True); hand = self.game.players["p1"]["hand"]
        sld = [self.game.apply_passive(hand.pop(x)) for x in idxs]
        if self.step == "main": self.game.players["p1"]["main"] = sld[0]; self.step = "left"
        elif self.step == "left": self.game.players["p1"]["left"].extend(sld); self.step = "right"
        else:
            self.game.players["p1"]["right"].extend(sld)
            self.game.logs = "ゲーム開始"
            await i.response.edit_message(content="対戦開始", embed=make_embed(self.game), view=MainMenuView(self.game)); return
        self.update_select(); await i.response.edit_message(embed=make_embed(self.game), view=self)

class CancelButton(discord.ui.Button):
    def __init__(self, game): super().__init__(label="戻る", style=discord.ButtonStyle.gray); self.game = game
    async def callback(self, i): await i.response.edit_message(content="メニュー", embed=make_embed(self.game), view=MainMenuView(self.game))

class Pault(commands.Cog):
    def __init__(self, bot): self.bot = bot
    @app_commands.command(name="pault", description="ゲーム開始")
    async def pault(self, interaction: discord.Interaction):
        game = PaultGame(interaction.channel_id, interaction.user.id, interaction.user.display_name)
        await interaction.response.send_message(embed=make_embed(game), view=InitialSetupView(game))

async def setup(bot): await bot.add_cog(Pault(bot))
