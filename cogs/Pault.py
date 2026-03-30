# -*- coding: utf-8 -*-
import discord
from discord.ext import commands
from discord import app_commands
import random
import asyncio

# 自作モジュールのインポート
import config
import df_module as df  # defining.py を df_module としてインポート（名前は環境に合わせてください）

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
            deck.append({"name": name, "type": t, "def_broken": False})
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
        if self.players["cpu"]["main"] is None: return "p1"
        if self.players["p1"]["main"] is None: return "cpu"
        return None

# --- ロジック関数 ---
def execute_attack(attacker_card, defender_card):
    atk = BATTLE_STATS.get(attacker_card["name"], [0, 0])[0]
    dfn = BATTLE_STATS.get(defender_card["name"], [0, 0])[1]
    if atk > dfn: return True, "破壊成功！"
    return False, "防御力が高い…破壊失敗。"

def make_embed(game):
    p = game.players["p1"]
    c = game.players["cpu"]
    embed = discord.Embed(title="🏰 Pault 盤面", color=0x2f3136)
    embed.add_field(name="ターン", value=game.turn, inline=True)
    embed.add_field(name="ログ", value=game.logs, inline=False)
    
    def get_n(c): return c["name"] if c else "空"
    def get_l(cards): return "/".join([c["name"] for c in cards]) if cards else "空"
    
    embed.add_field(name="相手(CPU)の城", value=get_n(c["main"]), inline=True)
    embed.add_field(name="あなたの城", value=get_n(p["main"]), inline=True)
    embed.add_field(name="あなたの布陣", value=f"L: [{get_l(p['left'])}]\nR: [{get_l(p['right'])}]", inline=False)
    embed.add_field(name="手札枚数", value=f"{len(p['hand'])}枚", inline=True)
    return embed

# --- アクション View ---

class MainMenuView(discord.ui.View):
    def __init__(self, game):
        super().__init__(timeout=None)
        self.game = game

    @discord.ui.button(label="攻撃", style=discord.ButtonStyle.danger)
    async def attack(self, i: discord.Interaction, b: discord.ui.Button):
        if self.game.turn <= 2: return await i.response.send_message("準備期間中は攻撃禁止です", ephemeral=True)
        view = discord.ui.View()
        view.add_item(AtkPosButton(self.game, "left"))
        view.add_item(AtkPosButton(self.game, "right"))
        await i.response.edit_message(content="どのスポンから攻撃しますか？", view=view)

    @discord.ui.button(label="ドロー", style=discord.ButtonStyle.primary)
    async def draw(self, i: discord.Interaction, b: discord.ui.Button):
        if not self.game.deck: return await i.response.send_message("山札がありません", ephemeral=True)
        card = self.game.deck.pop(0)
        view = DrawResultView(self.game, card)
        await i.response.edit_message(content=f"🎴 引いたカード: **{card['name']}**\nどうしますか？", embed=None, view=view)

    @discord.ui.button(label="配置", style=discord.ButtonStyle.secondary)
    async def deploy(self, i: discord.Interaction, b: discord.ui.Button):
        view = discord.ui.View()
        for side in ["main", "left", "right"]:
            view.add_item(DeployPosButton(self.game, side))
        await i.response.edit_message(content="どこに配置しますか？", view=view)

    @discord.ui.button(label="サポート", style=discord.ButtonStyle.success)
    async def support(self, i: discord.Interaction, b: discord.ui.Button):
        options = df.get_options_from_list(self.game.players["p1"]["hand"], filter_type="サポート")
        if not options: return await i.response.send_message("サポートカードがありません", ephemeral=True)
        
        async def support_logic(interaction, indices):
            card = self.game.players["p1"]["hand"].pop(indices[0])
            self.game.logs = f"サポート【{card['name']}】を発動しました！（効果未実装）"
            await interaction.response.edit_message(content=self.game.logs, embed=make_embed(self.game), view=MainMenuView(self.game))

        view = df.GenericPickerView(options, 1, 1, "発動するサポートを選択", support_logic)
        await i.response.edit_message(content="サポートカードを選択してください", view=view)

    @discord.ui.button(label="降参", style=discord.ButtonStyle.grey)
    async def surrender(self, i: discord.Interaction, b: discord.ui.Button):
        await i.response.edit_message(content="🏳️ 降参しました。ゲームを終了します。", embed=None, view=None)

# --- サブUIコンポーネント ---

class DeployPosButton(discord.ui.Button):
    def __init__(self, game, side):
        super().__init__(label=f"{side.capitalize()}へ配置", style=discord.ButtonStyle.secondary)
        self.game, self.side = game, side

    async def callback(self, i: discord.Interaction):
        async def deploy_logic(interaction, indices):
            p1 = self.game.players["p1"]
            for idx in indices:
                card = p1["hand"].pop(idx)
                if self.side == "main": p1["main"] = card
                else: p1[self.side].append(card)
            self.game.logs = f"{self.side}への配置を完了しました。"
            await interaction.response.edit_message(content=self.game.logs, embed=make_embed(self.game), view=MainMenuView(self.game))

        options = df.get_options_from_list(self.game.players["p1"]["hand"], filter_type="戦闘")
        max_val = 1 if self.side == "main" else 5
        view = df.GenericPickerView(options, 1, max_val, f"{self.side}に置くカードを選択", deploy_logic)
        await i.response.edit_message(content="配置するカードを選んでください（複数可）", view=view)

class AtkPosButton(discord.ui.Button):
    def __init__(self, game, side):
        super().__init__(label=f"{side.capitalize()}から攻撃", style=discord.ButtonStyle.danger)
        self.game, self.side = game, side

    async def callback(self, i: discord.Interaction):
        p1, cpu = self.game.players["p1"], self.game.players["cpu"]
        if not p1[self.side]: return await i.response.send_message("カードがありません", ephemeral=True)
        
        atk_card = p1[self.side].pop() # 1番上を消費
        target_side = "right" if self.side == "left" else "left"
        
        # 簡易判定：相手のスポンがいればスポン破壊、いなければ城攻撃
        target = cpu["main"]
        success, res = execute_attack(atk_card, target)
        if success: cpu["main"] = None
        self.game.logs = f"{self.side}から攻撃！ {res}"
        
        await i.response.edit_message(content="CPUのターンへ...", view=None)
        await cpu_turn_logic(i, self.game)

class DrawResultView(discord.ui.View):
    def __init__(self, game, card):
        super().__init__()
        self.game, self.card = game, card

    @discord.ui.button(label="即座に配置", style=discord.ButtonStyle.success)
    async def deploy_now(self, i: discord.Interaction, b: discord.ui.Button):
        view = discord.ui.View()
        async def quick_deploy(interaction, side):
            if side == "main": self.game.players["p1"]["main"] = self.card
            else: self.game.players["p1"][side].append(self.card)
            await interaction.response.edit_message(content="配置完了。CPUのターンへ...", view=None)
            await cpu_turn_logic(interaction, self.game)
        
        for s in ["main", "left", "right"]:
            btn = discord.ui.Button(label=s)
            btn.callback = lambda it, side=s: quick_deploy(it, side)
            view.add_item(btn)
        await i.response.edit_message(content="どこに配置しますか？", view=view)

    @discord.ui.button(label="手札に保持", style=discord.ButtonStyle.secondary)
    async def keep(self, i: discord.Interaction, b: discord.ui.Button):
        self.game.players["p1"]["hand"].append(self.card)
        await i.response.edit_message(content="手札に加えました。CPUのターンへ...", view=None)
        await cpu_turn_logic(i, self.game)

# --- CPU ターン ---
async def cpu_turn_logic(i, game):
    cpu, p1 = game.players["cpu"], game.players["p1"]
    if game.deck: cpu["hand"].append(game.deck.pop(0))
    # CPU配置（簡易）
    for idx, c in enumerate(cpu["hand"]):
        if c["type"] == "戦闘":
            if not cpu["main"]: cpu["main"] = cpu["hand"].pop(idx); break
            if len(cpu["left"]) < 2: cpu["left"].append(cpu["hand"].pop(idx)); break
    
    cpu_log = "CPUはカードを引いて整理した。"
    if game.turn > 2 and cpu["left"] and p1["main"]:
        atk_card = cpu["left"].pop()
        success, res = execute_attack(atk_card, p1["main"])
        if success: p1["main"] = None; cpu_log = "CPUの攻撃！城が破壊された！"

    game.turn += 1
    vic = game.check_victory()
    if vic:
        await i.followup.send(f"🏁 **ゲーム終了！勝者：{vic}**")
    else:
        await i.followup.send(content=f"あなたのターンです\n【CPUログ】: {cpu_log}", embed=make_embed(game), view=MainMenuView(game))

# --- Cog 定義 ---
class Pault(commands.Cog):
    def __init__(self, bot): self.bot = bot

    @app_commands.command(name="pault", description="Pault対戦開始")
    async def pault(self, interaction: discord.Interaction):
        game = PaultGame(interaction.channel_id, interaction.user.id, interaction.user.display_name)
        
        async def initial_setup_main(i, indices):
            game.players["p1"]["main"] = game.players["p1"]["hand"].pop(indices[0])
            # 次にレフト
            options = df.get_options_from_list(game.players["p1"]["hand"], "戦闘")
            async def initial_left(i2, idx2):
                for idx in idx2: game.players["p1"]["left"].append(game.players["p1"]["hand"].pop(idx))
                # 次にライト
                options3 = df.get_options_from_list(game.players["p1"]["hand"], "戦闘")
                async def initial_right(i3, idx3):
                    for idx in idx3: game.players["p1"]["right"].append(game.players["p1"]["hand"].pop(idx))
                    await i3.response.edit_message(content="準備完了！", embed=make_embed(game), view=MainMenuView(game))
                await i2.response.edit_message(content="ライト配置を選択", view=df.GenericPickerView(options3, 1, 5, "ライト配置", initial_right))
            await i.response.edit_message(content="レフト配置を選択", view=df.GenericPickerView(options, 1, 5, "レフト配置", initial_left))

        options = df.get_options_from_list(game.players["p1"]["hand"], "戦闘")
        view = df.GenericPickerView(options, 1, 1, "城(Main)を選択", initial_setup_main)
        await interaction.response.send_message("🏰 **Pault 準備フェーズ**\n城となるカードを選んでください。", view=view)

async def setup(bot): await bot.add_cog(Pault(bot))


class GenericPickerView(discord.ui.View):
    """
    汎用的なカード選択ビュー。
    callback_func: 選択後に実行する関数。引数として (interaction, 選択されたインデックスのリスト) を取る。
    """
    def __init__(self, options, min_v, max_v, placeholder, callback_func):
        super().__init__(timeout=None)
        if not options:
            # 選択肢がない場合の処理（必要に応じてボタンを追加など）
            return
            
        self.add_item(GenericPickerSelect(options, min_v, max_v, placeholder, callback_func))

class GenericPickerSelect(discord.ui.Select):
    def __init__(self, options, min_v, max_v, placeholder, callback_func):
        # 実際の最大選択可能数はオプションの数を超えられないため調整
        actual_max = min(len(options), max_v)
        super().__init__(
            placeholder=placeholder,
            min_values=min_v,
            max_values=actual_max,
            options=options
        )
        self.callback_func = callback_func

    async def callback(self, interaction: discord.Interaction):
        # 選択されたインデックスを数値リストにして降順ソート（pop時のズレ防止）
        selected_indices = sorted([int(v) for v in self.values], reverse=True)
        # 外部で定義されたロジックを実行
        await self.callback_func(interaction, selected_indices)
