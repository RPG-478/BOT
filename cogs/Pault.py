# ~/BOT/cogs/Pault.py
# -*- coding: utf-8 -*-
import discord
from discord.ext import commands
from discord import app_commands
import random
import asyncio
#a
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
    embed = discord.Embed(title="Pault 盤面", color=0xFFFFFF)
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
    def __init__(self, user_or_channel_id, user_id=None, user_name=None):
        if user_id is None:
            user = user_or_channel_id
            self.channel_id = 0
            uid = user.id
            uname = user.display_name
        else:
            self.channel_id = user_or_channel_id
            uid = user_id
            uname = user_name

        self.turn = 1
        self.deck = self.create_deck()
        self.players = {
            "p1": {"id": uid, "name": uname, "main": None, "left": [], "right": [], "hand": []},
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

def execute_attack(attacker_card, defender_list, attacker_hand, is_main=False, main_card=None):
    logs = []
    atk_val = BATTLE_STATS.get(attacker_card["name"], [0, 0])[0]
    
    targets = []
    if is_main:
        if main_card: targets = [("main", main_card)]
    else:
        if defender_list:
            if attacker_card["name"] == "バーサーカー":
                targets = [("sub", c) for c in defender_list]
            else:
                targets = [("sub", defender_list[-1])]

    if not targets:
        return True, ["直接攻撃！"]

    any_destroyed = False
    for t_type, card in targets:
        if card.get("face_down"):
            card["face_down"] = False
            logs.append(f"{card['name']}の(防)を解除")
        else:
            dfn_val = BATTLE_STATS.get(card["name"], [0, 0])[1]
            if atk_val > dfn_val:
                if t_type == "sub": defender_list.remove(card)
                any_destroyed = True
                logs.append(f"{card['name']}撃破")
                if attacker_card["name"] == "イーター":
                    new_card = card.copy()
                    new_card["face_down"] = False
                    attacker_hand.append(new_card)
                    logs.append("捕食成功！")
            else:
                logs.append(f"{card['name']}に防御された")

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
                logs.append(f"貫通: {second_card['name']}に阻まれた")

    return any_destroyed, logs

async def cpu_turn_logic(i, game):
    cpu, p1 = game.players["cpu"], game.players["p1"]
    if game.deck: cpu["hand"].append(game.deck.pop(0))
    cpu_logs = []
    
    for idx, c in enumerate(cpu["hand"][:]):
        if c["type"] == "戦闘":
            card = game.apply_passive(cpu["hand"].pop(idx))
            if len(cpu["left"]) < 2: cpu["left"].append(card)
            elif len(cpu["right"]) < 2: cpu["right"].append(card)
            
    if game.turn >= 2:
        for side in ["left", "right"]:
            if cpu[side] and not cpu[side][0].get("face_down"):
                target_side = "right" if side == "left" else "left"
                atk_card = cpu[side].pop(0)
                if p1[target_side]:
                    _, res = execute_attack(atk_card, p1[target_side], cpu["hand"])
                    cpu_logs.append(f"CPU({side}): " + " & ".join(res))
                else:
                    win, _ = execute_attack(atk_card, [], cpu["hand"], True, p1["main"])
                    if win: p1["main"] = None
                    cpu_logs.append(f"CPU({side}): 城攻撃成功")
                
                if atk_card["name"] == "ランナー":
                    cpu[side].append(atk_card)
                break
    
    game.logs += "\n" + ("\n".join(cpu_logs) if cpu_logs else "CPU待機")
    game.turn += 1
    vic = game.check_victory()
    if vic: await i.edit_original_response(content=f"勝者: {vic}", embed=make_embed(game), view=None)
    else: await i.edit_original_response(content="あなたの番", embed=make_embed(game), view=MainMenuView(game))

async def process_support_logic(interaction, game, card):
    if card["name"] == "ドロー":
        drawn = []
        for _ in range(2):
            if game.deck: drawn.append(game.deck.pop(0))
        game.players["p1"]["hand"].extend(drawn)
        game.logs = "サポート: 2枚ドロー"
        await interaction.response.defer()
        await cpu_turn_logic(interaction, game)
        
    elif card["name"] == "サブ破壊":
        view = discord.ui.View()
        for s in ["left", "right"]:
            btn = discord.ui.Button(label=f"相手{s.upper()}破壊", style=discord.ButtonStyle.danger)
            async def mk_cb(side):
                async def _cb(it):
                    if game.players["cpu"][side]:
                        target = game.players["cpu"][side].pop()
                        game.logs = f"サポート: 相手{side}の{target['name']}を破壊"
                    else: game.logs = "サポート: 破壊対象なし"
                    await it.response.defer(); await cpu_turn_logic(it, game)
                return _cb
            btn.callback = await mk_cb(s); view.add_item(btn)
        await interaction.response.edit_message(content="破壊列選択", view=view)

    elif card["name"] == "裏返し":
        view = discord.ui.View()
        targets = [("自分L", "p1", "left"), ("自分R", "p1", "right"), ("相手L", "cpu", "left"), ("相手R", "cpu", "right")]
        for label, pk, sk in targets:
            btn = discord.ui.Button(label=label, style=discord.ButtonStyle.primary)
            async def mk_flip(p_key, s_key):
                async def _cb(it):
                    if game.players[p_key][s_key]:
                        game.players[p_key][s_key][-1]["face_down"] = True
                        game.logs = f"サポート: {label}を(防)にした"
                    else: game.logs = "サポート: 対象不在で不発"
                    await it.response.defer(); await cpu_turn_logic(it, game)
                return _cb
            btn.callback = await mk_flip(pk, sk); view.add_item(btn)
        await interaction.response.edit_message(content="裏返し対象選択", view=view)

class AtkPosButton(discord.ui.Button):
    def __init__(self, game, side): super().__init__(label=f"{side.upper()}攻撃", style=discord.ButtonStyle.danger); self.game, self.side = game, side
    async def callback(self, i):
        p1, cpu = self.game.players["p1"], self.game.players["cpu"]
        if not p1[self.side]: return await i.response.send_message("不在", ephemeral=True)
        if p1[self.side][0].get("face_down"): return await i.response.send_message("(防)は行動不可", ephemeral=True)
        
        await i.response.defer()
        atk_card = p1[self.side].pop(0); target_side = "right" if self.side == "left" else "left"
        if cpu[target_side]:
            _, res = execute_attack(atk_card, cpu[target_side], p1["hand"])
            self.game.logs = f"攻撃({self.side}): " + " & ".join(res)
        else:
            win, _ = execute_attack(atk_card, [], p1["hand"], True, cpu["main"])
            if win: cpu["main"] = None
            self.game.logs = f"攻撃({self.side}): 城攻撃成功"
        
        if atk_card["name"] == "ランナー":
            p1[self.side].append(atk_card)
            
        await cpu_turn_logic(i, self.game)

class MainMenuView(discord.ui.View):
    def __init__(self, game): super().__init__(timeout=None); self.game = game
    @discord.ui.button(label="攻撃", style=discord.ButtonStyle.danger)
    async def attack(self, i, b):
        if self.game.turn <= 2: return await i.response.send_message("準備期間中不可", ephemeral=True)
        v = discord.ui.View(); [v.add_item(AtkPosButton(self.game, s)) for s in ["left", "right"]]
        v.add_item(CancelButton(self.game))
        await i.response.edit_message(content="攻撃列選択", view=v)

    @discord.ui.button(label="配置", style=discord.ButtonStyle.success)
    async def deploy(self, i, b):
        opts = get_options_from_list(self.game.players["p1"]["hand"], "戦闘")
        if not opts: return await i.response.send_message("戦闘カードなし", ephemeral=True)
        v = discord.ui.View(); s = discord.ui.Select(options=opts); s.callback = self.make_deploy_cb(s); v.add_item(s); v.add_item(CancelButton(self.game))
        await i.response.edit_message(content="配置カード選択", view=v)

    def make_deploy_cb(self, sel):
        async def _cb(it):
            idx = int(sel.values[0]); card = self.game.players["p1"]["hand"].pop(idx)
            v = discord.ui.View()
            for side in ["main", "left", "right"]:
                btn = discord.ui.Button(label=side.upper()); btn.callback = self.make_pos_cb(card, side); v.add_item(btn)
            v.add_item(CancelButton(self.game))
            await it.response.edit_message(content=f"{card['name']} の配置先", view=v)
        return _cb

    def make_pos_cb(self, card, pos):
        async def _cb(it):
            p1 = self.game.players["p1"]
            if pos == "main":
                if p1["main"]: p1["hand"].append(p1["main"])
                p1["main"] = self.game.apply_passive(card)
            else:
                if len(p1[pos]) >= 2: return await it.response.send_message("満員", ephemeral=True)
                p1[pos].append(self.game.apply_passive(card))
            self.game.logs = f"{card['name']}を{pos}に配置"
            await it.response.defer(); await cpu_turn_logic(it, self.game)
        return _cb

    @discord.ui.button(label="サポート", style=discord.ButtonStyle.primary)
    async def support(self, i, b):
        opts = get_options_from_list(self.game.players["p1"]["hand"], "サポート")
        if not opts: return await i.response.send_message("サポートカードなし", ephemeral=True)
        v = discord.ui.View(); s = discord.ui.Select(options=opts); s.callback = self.make_sup_cb(s); v.add_item(s); v.add_item(CancelButton(self.game))
        await i.response.edit_message(content="サポートカード選択", view=v)

    def make_sup_cb(self, sel):
        async def _cb(it):
            idx = int(sel.values[0]); card = self.game.players["p1"]["hand"].pop(idx)
            await process_support_logic(it, self.game, card)
        return _cb

    @discord.ui.button(label="パス", style=discord.ButtonStyle.secondary)
    async def skip(self, i, b):
        self.game.logs = "パスしました"
        await i.response.defer(); await cpu_turn_logic(i, self.game)

class CancelButton(discord.ui.Button):
    def __init__(self, game): super().__init__(label="キャンセル", style=discord.ButtonStyle.secondary); self.game = game
    async def callback(self, i): await i.response.edit_message(content="メニュー", view=MainMenuView(self.game))

class SetupView(discord.ui.View):
    def __init__(self, game): super().__init__(timeout=None); self.game = game
    @discord.ui.button(label="メイン配置", style=discord.ButtonStyle.primary)
    async def set_main(self, i, b):
        opts = get_options_from_list(self.game.players["p1"]["hand"], "戦闘")
        v = discord.ui.View(); s = discord.ui.Select(options=opts); s.callback = self.make_cb(s); v.add_item(s)
        await i.response.edit_message(content="メインカード選択", view=v)
    def make_cb(self, sel):
        async def _cb(it):
            idx = int(sel.values[0]); card = self.game.players["p1"]["hand"].pop(idx)
            self.game.players["p1"]["main"] = self.game.apply_passive(card)
            await it.response.edit_message(content="サブ(L)配置中...", view=SubSetupView(self.game, "left"))
        return _cb

class SubSetupView(discord.ui.View):
    def __init__(self, game, side): super().__init__(timeout=None); self.game, self.side = game, side
    @discord.ui.button(label="サブ配置(1枚目)", style=discord.ButtonStyle.primary)
    async def set_sub(self, i, b):
        opts = get_options_from_list(self.game.players["p1"]["hand"], "戦闘")
        v = discord.ui.View(); s = discord.ui.Select(options=opts); s.callback = self.make_cb(s); v.add_item(s)
        await i.response.edit_message(content=f"サブ({self.side}) 1枚目選択", view=v)
    def make_cb(self, sel):
        async def _cb(it):
            idx = int(sel.values[0]); card = self.game.players["p1"]["hand"].pop(idx)
            self.game.players["p1"][self.side].append(self.game.apply_passive(card))
            v = discord.ui.View(); opts = get_options_from_list(self.game.players["p1"]["hand"], "戦闘")
            s = discord.ui.Select(options=opts); s.callback = self.make_cb2(s); v.add_item(s)
            await it.response.edit_message(content=f"サブ({self.side}) 2枚目選択", view=v)
        return _cb
    def make_cb2(self, sel):
        async def _cb(it):
            idx = int(sel.values[0]); card = self.game.players["p1"]["hand"].pop(idx)
            self.game.players["p1"][self.side].append(self.game.apply_passive(card))
            if self.side == "left": await it.response.edit_message(content="サブ(R)配置中...", view=SubSetupView(self.game, "right"))
            else: await it.response.edit_message(content="ゲーム開始！", embed=make_embed(self.game), view=MainMenuView(self.game))
        return _cb
