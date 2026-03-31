# ~/BOT/cogs/OnlinePault.py
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

def make_online_embed(game):
    p1, p2 = game.p1, game.p2
    embed = discord.Embed(title=f"Online Pault: {p1['name']} vs {p2['name']}", color=0x5865F2)
    embed.add_field(name="ターン", value=f"第 {game.turn_count} ターン / {game.current_player['name']} の番", inline=False)
    embed.add_field(name="ログ", value=game.logs if game.logs else "対戦開始", inline=False)
    
    def format_card(card):
        if not card: return "【 陥落 】"
        state = " (防)" if card.get("face_down") else ""
        return f"[{card['name']}{state}]"

    def get_top(cards):
        return format_card(cards[-1]) if cards else "[ --- ]"

    # P2 (上側プレイヤー)
    p2_board = f"{get_top(p2['right'])} {format_card(p2['main'])} {get_top(p2['left'])}"
    embed.add_field(name=f"▼ {p2['name']} (R | C | L)", value=f"```\n{p2_board}\n```", inline=False)

    embed.add_field(name="VS", value="-----------", inline=False)

    # P1 (下側プレイヤー)
    p1_board = f"{get_top(p1['left'])} {format_card(p1['main'])} {get_top(p1['right'])}"
    embed.add_field(name=f"▲ {p1['name']} (L | C | R)", value=f"```\n{p1_board}\n```", inline=False)
    
    embed.set_footer(text=f"山札: {len(game.deck)}枚 | 手札: {p1['name']}={len(p1['hand'])}枚, {p2['name']}={len(p2['hand'])}枚")
    return embed

class OnlinePaultGame:
    def __init__(self, p1_user, p2_user):
        self.turn_count = 1
        self.deck = self.create_deck()
        self.p1 = {"id": p1_user.id, "name": p1_user.display_name, "main": None, "left": [], "right": [], "hand": []}
        self.p2 = {"id": p2_user.id, "name": p2_user.display_name, "main": None, "left": [], "right": [], "hand": []}
        self.current_player = self.p1
        self.opponent_player = self.p2
        self.logs = "準備フェーズ"
        self.initial_draw(self.p1)
        self.initial_draw(self.p2)

    def create_deck(self):
        deck = []
        for _ in range(60): # 2人用なので少し多めに
            t = random.choices(["戦闘", "サポート"], weights=[70, 30])[0]
            name = random.choice(list(BATTLE_STATS.keys())) if t == "戦闘" else random.choice(["ドロー", "サブ破壊", "裏返し"])
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
        if self.current_player == self.p1:
            self.current_player, self.opponent_player = self.p2, self.p1
        else:
            self.current_player, self.opponent_player = self.p1, self.p2
            self.turn_count += 1
        # ターン開始ドロー
        if self.deck:
            self.current_player["hand"].append(self.deck.pop(0))

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
            card["face_down"] = False
            logs.append(f"{card['name']}の(防)解除")
        else:
            dfn_val = BATTLE_STATS.get(card["name"], [0, 0])[1]
            if atk_val > dfn_val:
                if t_type == "sub": defender_list.remove(card)
                any_destroyed = True
                logs.append(f"{card['name']}撃破")
                if attacker_card["name"] == "イーター":
                    new_c = card.copy(); new_c["face_down"] = False; attacker_hand.append(new_c)
                    logs.append("捕食成功")
            else: logs.append(f"{card['name']}防御")

    if attacker_card["name"] == "アーチャー" and any_destroyed and defender_list:
        sc = defender_list[-1]
        if sc.get("face_down"):
            sc["face_down"] = False; logs.append(f"貫通:(防)解除")
        elif atk_val > BATTLE_STATS.get(sc["name"], [0, 0])[1]:
            defender_list.pop(); logs.append(f"貫通:撃破")
    return any_destroyed, logs

# --- View クラス群 ---

class OnlineMainView(discord.ui.View):
    def __init__(self, game):
        super().__init__(timeout=None)
        self.game = game

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.game.current_player["id"]:
            await interaction.response.send_message("あなたの番ではありません", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="攻撃", style=discord.ButtonStyle.danger)
    async def attack(self, i, b):
        if self.game.turn_count <= 1: return await i.response.send_message("最初のターンは攻撃不可", ephemeral=True)
        v = discord.ui.View()
        for s in ["left", "right"]:
            btn = discord.ui.Button(label=f"{s.upper()}列で攻撃", style=discord.ButtonStyle.danger)
            async def mk_cb(side):
                async def _cb(it):
                    p = self.game.current_player; opp = self.game.opponent_player
                    if not p[side]: return await it.response.send_message("カードがありません", ephemeral=True)
                    if p[side][0].get("face_down"): return await it.response.send_message("(防)は行動不可", ephemeral=True)
                    
                    atk_card = p[side].pop(0)
                    opp_side = "right" if side == "left" else "left"
                    if opp[opp_side]:
                        _, res = execute_online_attack(atk_card, opp[opp_side], p["hand"])
                        self.game.logs = f"{p['name']}({side}): " + " & ".join(res)
                    else:
                        win, _ = execute_online_attack(atk_card, [], p["hand"], True, opp["main"])
                        if win: opp["main"] = None
                        self.game.logs = f"{p['name']}({side}): 城攻撃成功"
                    
                    if atk_card["name"] == "ランナー": p[side].append(atk_card)
                    
                    self.game.switch_turn()
                    await self.update_board(it)
                return _cb
            btn.callback = await mk_cb(s); v.add_item(btn)
        await i.response.edit_message(content="攻撃列を選択", view=v)

    @discord.ui.button(label="配置", style=discord.ButtonStyle.secondary)
    async def deploy(self, i, b):
        v = discord.ui.View()
        for s in ["main", "left", "right"]:
            btn = discord.ui.Button(label=f"{s.upper()}に配置", style=discord.ButtonStyle.secondary)
            async def mk_cb(side):
                async def _cb(it):
                    p = self.game.current_player
                    opts = get_options_from_list(p["hand"], "戦闘")
                    if not opts: return await it.response.send_message("配置できるカードがありません", ephemeral=True)
                    
                    sv = discord.ui.View()
                    sel = discord.ui.Select(options=opts, placeholder="カード選択")
                    async def sel_cb(it2):
                        c = self.game.apply_passive(p["hand"].pop(int(it2.data['values'][0])))
                        if side == "main": p["main"] = c
                        else: p[side].append(c)
                        self.game.logs = f"{p['name']}が{side.upper()}に配置"
                        self.game.switch_turn()
                        await self.update_board(it2)
                    sel.callback = sel_cb; sv.add_item(sel)
                    await it.response.edit_message(content=f"{side.upper()}に配置するカードを選択", view=sv)
                return _cb
            btn.callback = await mk_cb(s); v.add_item(btn)
        await i.response.edit_message(content="配置場所を選択", view=v)

    async def update_board(self, i):
        vic = self.game.check_victory()
        if vic:
            await i.response.edit_message(content=f"【決着】勝者: {vic}", embed=make_online_embed(self.game), view=None)
        else:
            await i.response.edit_message(content=None, embed=make_online_embed(self.game), view=OnlineMainView(self.game))

# --- 初期設定 View ---
class OnlineInitialSetupView(discord.ui.View):
    def __init__(self, game):
        super().__init__(timeout=None)
        self.game = game
        self.p1_ready = False
        self.p2_ready = False

    @discord.ui.button(label="自分の布陣を設定", style=discord.ButtonStyle.primary)
    async def setup(self, i, b):
        p = self.game.p1 if i.user.id == self.game.p1["id"] else self.game.p2 if i.user.id == self.game.p2["id"] else None
        if not p: return await i.response.send_message("対戦者ではありません", ephemeral=True)
        
        # 簡易設定（実際はSelectメニューを繋げますが、コード短縮のため自動で振り分けます）
        # 本来はPault.pyのInitialSetupViewと同様のステップが必要です
        if p["main"]: return await i.response.send_message("設定済みです", ephemeral=True)
        
        battles = [c for c in p["hand"] if c["type"] == "戦闘"]
        if len(battles) < 3: return await i.response.send_message("戦闘カードが足りません", ephemeral=True)
        
        p["main"] = self.game.apply_passive(battles[0]); p["hand"].remove(battles[0])
        p["left"].append(self.game.apply_passive(battles[1])); p["hand"].remove(battles[1])
        p["right"].append(self.game.apply_passive(battles[2])); p["hand"].remove(battles[2])
        
        if p["id"] == self.game.p1["id"]: self.p1_ready = True
        else: self.p2_ready = True
        
        await i.response.send_message("布陣を完了しました（自動配置）", ephemeral=True)
        if self.p1_ready and self.p2_ready:
            await i.message.edit(content="対戦開始！", embed=make_online_embed(self.game), view=OnlineMainView(self.game))

# --- エントリー View ---
class OnlineEntryView(discord.ui.View):
    def __init__(self, host_user):
        super().__init__(timeout=60)
        self.host = host_user
        self.p2 = None

    @discord.ui.button(label="参戦する", style=discord.ButtonStyle.green)
    async def join(self, i, b):
        if i.user.id == self.host.id: return await i.response.send_message("ホストは参戦できません", ephemeral=True)
        self.p2 = i.user
        game = OnlineInitialSetupView(OnlinePaultGame(self.host, self.p2))
        await i.response.edit_message(content=f"{self.host.display_name} vs {self.p2.display_name}\nそれぞれ布陣を設定してください。", view=game)
        self.stop()

class OnlinePault(commands.Cog):
    def __init__(self, bot): self.bot = bot
    @app_commands.command(name="online_pault", description="オンライン対戦を開始")
    async def online_pault(self, interaction: discord.Interaction):
        view = OnlineEntryView(interaction.user)
        await interaction.response.send_message(f"【Online Pault】{interaction.user.display_name}が挑戦者を待っています...", view=view)

async def setup(bot): await bot.add_cog(OnlinePault(bot))

