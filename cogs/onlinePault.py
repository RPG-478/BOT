# ~/BOT/cogs/OnlinePault.py
# -*- coding: utf-8 -*-
# ※ このファイルは変更なし。play.py から OnlineEntryView(interaction.user) で直接呼び出せます。
import discord
from discord.ext import commands
from discord import app_commands
import random

# --- 定数・スタッツ定義 ---
BATTLE_STATS = {
    "ソルジャー": [1, 0], "アサシン": [3, 0], "ナイト": [2, 1],
    "シールド": [1, 2], "ランナー": [1, 0], "イーター": [2, 0],
    "アーチャー": [1, 0], "バーサーカー": [1, 1], "盾士": [1, 0]
}

# カード出現重み (ソルジャーを多めに、盾士を少なめに)
CARD_WEIGHTS = {
    "ソルジャー": 30, "アサシン": 10, "ナイト": 10, "シールド": 10,
    "ランナー": 10, "イーター": 10, "アーチャー": 10, "バーサーカー": 5, "盾士": 5
}

def get_options_from_list(items, filter_type=None):
    options = []
    for i, card in enumerate(items):
        if filter_type is None or card.get("type") == filter_type:
            label = f"{card['name']} [{card.get('type', '不明')}]"
            options.append(discord.SelectOption(label=label, value=str(i)))
    return options

def make_online_embed(game):
    p1, p2 = game.p1, game.p2
    embed = discord.Embed(title=f"Online Pault: {p1['name']} vs {p2['name']}", color=0x5865F2)
    current = game.current_player
    embed.add_field(name="ターン", value=f"第 {game.turn_count} ターン / **{current['name']}** の番", inline=False)
    embed.add_field(name="ログ", value=f"```\n{game.logs}\n```", inline=False)
    
    def format_card(card):
        if not card: return "【 陥落 】"
        state = " (防)" if card.get("face_down") else ""
        return f"[{card['name']}{state}]"

    def get_top(cards):
        return format_card(cards[-1]) if cards else "[ --- ]"

    # P2 (上側) - 視覚的に正面に見えるよう配置
    p2_board = f"{get_top(p2['left'])} {format_card(p2['main'])} {get_top(p2['right'])}"
    embed.add_field(name=f"▼ {p2['name']} (L | C | R)", value=f"```\n{p2_board}\n```", inline=False)
    embed.add_field(name="VS", value="-----------", inline=False)
    # P1 (下側)
    p1_board = f"{get_top(p1['left'])} {format_card(p1['main'])} {get_top(p1['right'])}"
    embed.add_field(name=f"▲ {p1['name']} (L | C | R)", value=f"```\n{p1_board}\n```", inline=False)
    
    embed.set_footer(text=f"山札: {len(game.deck)}枚 | 手札: {p1['name']}={len(p1['hand'])}枚 / {p2['name']}={len(p2['hand'])}枚")
    return embed

class OnlinePaultGame:
    def __init__(self, p1_user, p2_user):
        self.turn_count = 1
        self.deck = self.create_deck()
        self.p1 = {"id": p1_user.id, "name": p1_user.display_name, "main": None, "left": [], "right": [], "hand": [], "ready": False}
        self.p2 = {"id": p2_user.id, "name": p2_user.display_name, "main": None, "left": [], "right": [], "hand": [], "ready": False}
        self.current_player = self.p1
        self.opponent_player = self.p2
        self.logs = "準備中"
        self.initial_draw(self.p1)
        self.initial_draw(self.p2)

    def create_deck(self):
        deck = []
        names = list(CARD_WEIGHTS.keys())
        weights = list(CARD_WEIGHTS.values())
        for _ in range(60):
            t = random.choices(["戦闘", "サポート"], weights=[70, 30])[0]
            name = random.choices(names, weights=weights)[0] if t == "戦闘" else random.choice(["ドロー", "サブ破壊", "裏返し"])
            deck.append({"name": name, "type": t, "face_down": False})
        random.shuffle(deck)
        return deck

    def apply_passive(self, card):
        if card and card["name"] == "盾士": card["face_down"] = True
        return card

    def initial_draw(self, player):
        battles = [c for c in self.deck if c["type"] == "戦闘"]
        for _ in range(3):
            if battles:
                c = battles.pop(0); player["hand"].append(c); self.deck.remove(c)
        for _ in range(2):
            if self.deck: player["hand"].append(self.deck.pop(0))

    def switch_turn(self):
        self.current_player, self.opponent_player = self.opponent_player, self.current_player
        if self.current_player == self.p1: self.turn_count += 1
        if self.deck: self.current_player["hand"].append(self.deck.pop(0))

    def check_victory(self):
        if self.p1["main"] is None: return self.p2["name"]
        if self.p2["main"] is None: return self.p1["name"]
        return None

def execute_online_attack(attacker_card, defender_list, attacker_hand, is_main=False, main_card=None):
    logs = []
    atk_val = BATTLE_STATS.get(attacker_card["name"], [0, 0])[0]
    targets = []
    if is_main:
        if main_card: targets = [("main", main_card)]
    else:
        if defender_list:
            if attacker_card["name"] == "バーサーカー": targets = [("sub", c) for c in defender_list]
            else: targets = [("sub", defender_list[-1])]
    if not targets: return True, ["直接攻撃！"]

    any_destroyed = False
    for t_type, card in targets:
        if card.get("face_down"):
            card["face_down"] = False; logs.append(f"{card['name']}(防)解除")
        else:
            dfn_val = BATTLE_STATS.get(card["name"], [0, 0])[1]
            if atk_val > dfn_val:
                if t_type == "sub": defender_list.remove(card)
                any_destroyed = True; logs.append(f"{card['name']}撃破")
                if attacker_card["name"] == "イーター":
                    new_c = card.copy(); new_c["face_down"] = False; attacker_hand.append(new_c)
                    logs.append("捕食成功")
            else: logs.append(f"{card['name']}防御")
    
    if attacker_card["name"] == "アーチャー" and any_destroyed and defender_list:
        sc = defender_list[-1]
        if sc.get("face_down"): sc["face_down"] = False; logs.append("貫通:(防)解除")
        elif atk_val > BATTLE_STATS.get(sc["name"], [0, 0])[1]:
            defender_list.pop(); logs.append("貫通:撃破")
    return any_destroyed, logs

# --- View クラス ---

class OnlineMainView(discord.ui.View):
    def __init__(self, game):
        super().__init__(timeout=None)
        self.game = game

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.game.current_player["id"]:
            await interaction.response.send_message(f"今は {self.game.current_player['name']} の番です", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="攻撃", style=discord.ButtonStyle.danger)
    async def attack(self, i, b):
        if self.game.turn_count <= 1 and self.game.current_player == self.game.p1:
            return await i.response.send_message("先攻第1ターンは攻撃不可", ephemeral=True)
        v = discord.ui.View()
        for s in ["left", "right"]:
            btn = discord.ui.Button(label=f"{s.upper()}列で攻撃", style=discord.ButtonStyle.danger)
            async def mk_cb(side):
                async def _cb(it):
                    p, opp = self.game.current_player, self.game.opponent_player
                    if not p[side]: return await it.response.send_message("不在", ephemeral=True)
                    if p[side][0].get("face_down"): return await it.response.send_message("(防)は不可", ephemeral=True)
                    
                    atk_c = p[side].pop(0)
                    # 攻撃先：自分の左列は相手の左列(正面)へ
                    if opp[side]:
                        _, res = execute_online_attack(atk_c, opp[side], p["hand"])
                        self.game.logs = f"{p['name']}({side}): " + " & ".join(res)
                    else:
                        win, _ = execute_online_attack(atk_c, [], p["hand"], True, opp["main"])
                        if win: opp["main"] = None
                        self.game.logs = f"{p['name']}({side}): 城攻撃成功"
                    
                    if atk_c["name"] == "ランナー": p[side].append(atk_c)
                    self.game.switch_turn(); await self.update_board(it)
                return _cb
            btn.callback = await mk_cb(s); v.add_item(btn)
        v.add_item(OnlineCancelButton(self.game)); await i.response.edit_message(content="攻撃列選択", view=v)

    @discord.ui.button(label="ドロー", style=discord.ButtonStyle.primary)
    async def draw(self, i, b):
        if not self.game.deck: return await i.response.send_message("山札切れ", ephemeral=True)
        c = self.game.deck.pop(0)
        await i.response.edit_message(content=f"【{c['name']}】を引きました", view=OnlineDrawResultView(self.game, c))

    @discord.ui.button(label="配置", style=discord.ButtonStyle.secondary)
    async def deploy(self, i, b):
        v = discord.ui.View()
        for s in ["main", "left", "right"]:
            btn = discord.ui.Button(label=f"{s.upper()}配置", style=discord.ButtonStyle.secondary)
            async def mk_cb(side):
                async def _cb(it):
                    p = self.game.current_player; opts = get_options_from_list(p["hand"], "戦闘")
                    if not opts: return await it.response.send_message("手札に戦闘カードがありません", ephemeral=True)
                    sv = discord.ui.View(); sel = discord.ui.Select(options=opts)
                    async def sel_cb(it2):
                        c = self.game.apply_passive(p["hand"].pop(int(it2.data['values'][0])))
                        if side == "main": p["main"] = c
                        else: p[side].append(c)
                        self.game.logs = f"{p['name']}が{side.upper()}に配置"; self.game.switch_turn(); await self.update_board(it2)
                    sel.callback = sel_cb; sv.add_item(sel); sv.add_item(OnlineCancelButton(self.game))
                    await it.response.edit_message(content="カード選択", view=sv)
                return _cb
            btn.callback = await mk_cb(s); v.add_item(btn)
        v.add_item(OnlineCancelButton(self.game)); await i.response.edit_message(content="配置先選択", view=v)

    @discord.ui.button(label="サポート", style=discord.ButtonStyle.success)
    async def support(self, i, b):
        p = self.game.current_player; opts = get_options_from_list(p["hand"], "サポート")
        if not opts: return await i.response.send_message("なし", ephemeral=True)
        v = discord.ui.View(); sel = discord.ui.Select(options=opts)
        async def cb(it): await process_online_support(it, self.game, p["hand"].pop(int(it.data['values'][0])))
        sel.callback = cb; v.add_item(sel); v.add_item(OnlineCancelButton(self.game)); await i.response.edit_message(content="サポート選択", view=v)

    @discord.ui.button(label="手札確認", style=discord.ButtonStyle.gray)
    async def check_hand(self, i, b):
        p = self.game.p1 if i.user.id == self.game.p1["id"] else self.game.p2
        hand_str = ", ".join([f"**{c['name']}**" for c in p["hand"]]) if p["hand"] else "なし"
        await i.response.send_message(f"あなたの手札: {hand_str}", ephemeral=True)

    async def update_board(self, i):
        vic = self.game.check_victory()
        if vic: await i.response.edit_message(content=f"【決着】勝者: {vic}", embed=make_online_embed(self.game), view=None)
        else: await i.response.edit_message(content=None, embed=make_online_embed(self.game), view=OnlineMainView(self.game))

# --- サポート・初期化 View 略（前回分を調整して統合） ---

class OnlineInitialSetupView(discord.ui.View):
    def __init__(self, game, message):
        super().__init__(timeout=None); self.game = game; self.message = message
    @discord.ui.button(label="布陣を設定", style=discord.ButtonStyle.primary)
    async def setup(self, i, b):
        p = self.game.p1 if i.user.id == self.game.p1["id"] else self.game.p2 if i.user.id == self.game.p2["id"] else None
        if not p: return await i.response.send_message("不可", ephemeral=True)
        if p["ready"]: return await i.response.send_message("済", ephemeral=True)
        await self.start_flow(i, p)

    async def start_flow(self, interaction, p):
        opts = get_options_from_list(p["hand"], "戦闘")
        v = discord.ui.View(); sel = discord.ui.Select(placeholder="城を選択", options=opts)
        async def main_cb(it):
            p["main"] = self.game.apply_passive(p["hand"].pop(int(it.data['values'][0])))
            await self.setup_sub(it, p, "left")
        sel.callback = main_cb; v.add_item(sel); await interaction.response.send_message("城を選択", view=v, ephemeral=True)

    async def setup_sub(self, interaction, p, side):
        opts = get_options_from_list(p["hand"], "戦闘")
        max_v = min(3, len(opts))
        if max_v == 0: p["ready"] = True; await self.check_start(interaction); return
        v = discord.ui.View(); sel = discord.ui.Select(placeholder=f"{side.upper()}選択(1~{max_v}枚)", min_values=1, max_values=max_v, options=opts)
        async def sub_cb(it):
            idxs = sorted([int(v) for v in it.data['values']], reverse=True)
            for x in idxs: p[side].append(self.game.apply_passive(p["hand"].pop(x)))
            if side == "left": await self.setup_sub(it, p, "right")
            else: p["ready"] = True; await it.response.edit_message(content="待機中...", view=None); await self.check_start(it)
        sel.callback = sub_cb; v.add_item(sel); await interaction.response.edit_message(content=f"{side.upper()}選択", view=v)

    async def check_start(self, it):
        if self.game.p1["ready"] and self.game.p2["ready"]:
            self.game.logs = "対戦開始！ P1のターン"
            await self.message.edit(content=None, embed=make_online_embed(self.game), view=OnlineMainView(self.game))

async def process_online_support(interaction, game, card):
    p, opp = game.current_player, game.opponent_player
    if card["name"] == "ドロー":
        for _ in range(2): 
            if game.deck: p["hand"].append(game.deck.pop(0))
        game.logs = f"{p['name']}: ドロー×2"
    elif card["name"] == "サブ破壊":
        v = discord.ui.View()
        for s in ["left", "right"]:
            btn = discord.ui.Button(label=f"相手{s.upper()}破壊", style=discord.ButtonStyle.danger)
            async def mk(side):
                async def _c(it):
                    if opp[side]: t = opp[side].pop(); game.logs = f"{p['name']}: 相手の{t['name']}破壊"
                    else: game.logs = "不発"
                    game.switch_turn(); await it.response.edit_message(content=None, embed=make_online_embed(game), view=OnlineMainView(game))
                return _c
            btn.callback = await mk(s); v.add_item(btn)
        return await interaction.response.edit_message(content="対象選択", view=v)
    elif card["name"] == "裏返し":
        v = discord.ui.View()
        targets = [("自分L", p, "left"), ("自分R", p, "right"), ("相手L", opp, "left"), ("相手R", opp, "right")]
        for label, tp, sk in targets:
            btn = discord.ui.Button(label=label, style=discord.ButtonStyle.primary)
            async def mk_f(target_p, s_key, lbl):
                async def _c(it):
                    if target_p[s_key]: target_p[s_key][-1]["face_down"] = True; game.logs = f"{p['name']}: {lbl}を(防)化"
                    else: game.logs = "不発"
                    game.switch_turn(); await it.response.edit_message(content=None, embed=make_online_embed(game), view=OnlineMainView(game))
                return _c
            btn.callback = await mk_f(tp, sk, label); v.add_item(btn)
        return await interaction.response.edit_message(content="対象選択", view=v)
    
    game.switch_turn(); await interaction.response.edit_message(content=None, embed=make_online_embed(game), view=OnlineMainView(game))

class OnlineDrawResultView(discord.ui.View):
    def __init__(self, game, card): super().__init__(); self.game, self.card = game, card
    @discord.ui.button(label="即配置(戦闘のみ)", style=discord.ButtonStyle.success)
    async def deploy_now(self, i, b):
        if self.card["type"] != "戦闘": return await i.response.send_message("不可", ephemeral=True)
        v = discord.ui.View()
        for s in ["main", "left", "right"]:
            btn = discord.ui.Button(label=s.upper())
            async def mk_cb(side):
                async def _cb(it):
                    c = self.game.apply_passive(self.card); p = self.game.current_player
                    if side == "main": p["main"] = c
                    else: p[side].append(c)
                    self.game.logs = f"ドロー即配置({side})"; self.game.switch_turn(); await it.response.edit_message(content=None, embed=make_online_embed(self.game), view=OnlineMainView(self.game))
                return _cb
            btn.callback = await mk_cb(s); v.add_item(btn)
        await i.response.edit_message(content="配置先", view=v)
    @discord.ui.button(label="手札へ", style=discord.ButtonStyle.secondary)
    async def keep(self, i, b):
        self.game.current_player["hand"].append(self.card); self.game.logs = "ドローを手札へ"; self.game.switch_turn()
        await i.response.edit_message(content=None, embed=make_online_embed(self.game), view=OnlineMainView(self.game))

class OnlineCancelButton(discord.ui.Button):
    def __init__(self, game): super().__init__(label="戻る", style=discord.ButtonStyle.gray); self.game = game
    async def callback(self, i): await i.response.edit_message(content=None, embed=make_online_embed(self.game), view=OnlineMainView(self.game))

class OnlineEntryView(discord.ui.View):
    def __init__(self, host): super().__init__(timeout=60); self.host = host
    @discord.ui.button(label="参戦する", style=discord.ButtonStyle.green)
    async def join(self, i, b):
        if i.user.id == self.host.id: return await i.response.send_message("不可", ephemeral=True)
        game = OnlinePaultGame(self.host, i.user)
        await i.response.edit_message(content="対戦成立。布陣を設定してください。", view=OnlineInitialSetupView(game, i.message))

class OnlinePault(commands.Cog):
    def __init__(self, bot): self.bot = bot
    async def online_pault(self, interaction: discord.Interaction):
        await interaction.response.send_message(f"【Online Pault】{interaction.user.display_name}が挑戦者を待っています...", view=OnlineEntryView(interaction.user))

async def setup(bot): await bot.add_cog(OnlinePault(bot))