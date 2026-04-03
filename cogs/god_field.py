import discord
from discord.ext import commands
import asyncio
import random
import uuid

# --- カードクラス定義 ---
class Card:
    def __init__(self, name, category, attr, value, mp_cost=0, price=0, description=""):
        self.name = name
        self.category = category  # "ATTACK", "DEFENSE", "SPECIAL", "MAGIC"
        self.attr = attr          # "PHYSICAL", "FIRE", "EARTH", "NONE", "REFLECT", "HEAL_HP", "HEAL_MP", "BUY", "SELL", "EXCHANGE"
        self.value = value
        self.mp_cost = mp_cost
        self.price = price
        self.description = description

# アイテムセット (修正・追加分)
TEST_CARDS = [
    Card("銅の棍棒", "ATTACK", "NONE", 1, price=1, description="威力1/無属性"),
    Card("銀の棍棒", "ATTACK", "NONE", 1, price=10, description="威力1/無属性"),
    Card("金の棍棒", "ATTACK", "NONE", 1, price=25, description="威力1/無属性"),
    Card("神の剣", "ATTACK", "NONE", 30, price=25, description="威力30/無属性"),
    Card("乱弾武剣", "DEFENSE", "NONE", 5, price=10, description="防御5/弾く"),
    Card("スマイルのしずく", "SPECIAL", "HEAL_HP", 5, price=1, description="HP5回復"),
    Card("スマイルの花", "SPECIAL", "HEAL_MP", 5, price=1, description="MP5回復"),
    Card("買う", "SPECIAL", "BUY", 0, price=3, description="他人の神器を買う(3円)"),
    Card("売る", "SPECIAL", "SELL", 0, price=5, description="自分の神器を売る(5円)"),
    Card("両替", "SPECIAL", "EXCHANGE", 0, price=3, description="ステータス変換(3円)"),
    Card("バチェット", "ATTACK", "NONE", 4, price=3, description="威力4/無属性"),
    Card("ムチ", "ATTACK", "NONE", 2, price=1, description="威力2/無属性"),
    Card("セイバーロッド", "ATTACK", "NONE", 2, price=10, description="攻2/防6"),
    Card("パンチ", "ATTACK", "NONE", 3, price=1, description="威力3/無属性"),
    Card("革の帽子", "DEFENSE", "NONE", 1, price=1, description="防御1"),
    Card("革の服", "DEFENSE", "NONE", 2, price=2, description="防御2"),
    Card("アイアンガントレット", "DEFENSE", "NONE", 3, price=3, description="防御3"),
    Card("アイアンシールド", "DEFENSE", "NONE", 4, price=4, description="防御4"),
    Card("アイアンアーマー", "DEFENSE", "NONE", 5, price=5, description="防御5"),
    Card("神の盾", "DEFENSE", "NONE", 30, price=25, description="防御30"),
    Card("大木", "MAGIC", "EARTH", 6, mp_cost=3, price=5, description="威力6/土魔法(MP3)"),
    Card("たいまつ", "ATTACK", "FIRE", 1, price=1, description="威力1/炎属性"),
    Card("スーパーミラー", "DEFENSE", "REFLECT", 0, price=10, description="全てを跳ね返す"),
    Card("棘ベルト", "ATTACK", "NONE", 2, price=3, description="攻2/防4"),
    Card("鎖ガマ", "ATTACK", "NONE", 5, price=2, description="威力5"),
    Card("硬いつち", "ATTACK", "NONE", 6, price=3, description="威力6"),
    Card("打撃の鉄板", "ATTACK", "NONE", 5, price=3, description="攻5/防7"),
    Card("エルボーサック", "ATTACK", "NONE", 6, price=3, description="攻6/防3"),
    Card("なぎなたクラシック", "ATTACK", "NONE", 7, price=3, description="威力7"),
    Card("吹き矢", "ATTACK", "NONE", 1, price=1, description="追加ダメージ1"),
    Card("ゴーストソード", "ATTACK", "NONE", 7, price=10, description="威力7/HP吸収"),
    Card("鬼のくつ", "ATTACK", "NONE", 5, price=10, description="威力5/防3/攻撃時消耗"),
    Card("火の玉", "MAGIC", "FIRE", 2, mp_cost=2, price=3, description="威力2/炎魔法(MP2)")
]

# --- UI コンポーネント ---

class JoinView(discord.ui.View):
    def __init__(self, timeout):
        super().__init__(timeout=timeout)
        self.joined_users = []

    @discord.ui.button(label="参加", style=discord.ButtonStyle.secondary)
    async def join(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id not in [u.id for u in self.joined_users]:
            self.joined_users.append(interaction.user)
            await interaction.response.send_message(f"{interaction.user.display_name}を登録しました。", ephemeral=True)
        else:
            await interaction.response.send_message("登録済みです。", ephemeral=True)

class HandActionView(discord.ui.View):
    def __init__(self, player, game_state, channel, interaction_id):
        super().__init__(timeout=60)
        self.player, self.game_state, self.channel, self.interaction_id = player, game_state, channel, interaction_id
        self.add_item(ActionSelect(player, game_state, channel, interaction_id))

class ActionSelect(discord.ui.Select):
    def __init__(self, player, game_state, channel, interaction_id):
        self.player, self.game_state, self.channel, self.interaction_id = player, game_state, channel, interaction_id
        options = []
        for i, card in enumerate(player["hand"]):
            tag = f"【{card.category}】"
            # 視認性向上のため詳細を表示
            desc = f"{card.description}"
            options.append(discord.SelectOption(label=f"{tag}{card.name}", value=str(i), description=desc))
        if not options: options.append(discord.SelectOption(label="祈る", value="pray"))
        super().__init__(placeholder="神器を選択してください", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        if self.game_state.get("active_interaction_id") != self.interaction_id: return
        if self.values[0] == "pray":
            self.game_state["active_interaction_id"] = None
            await interaction.response.send_message("祈りました。", ephemeral=True)
            return await self.game_state["cog"].process_turn_end(self.channel)

        idx = int(self.values[0]); card = self.player["hand"][idx]
        if card.category == "MAGIC" and self.player["mp"] < card.mp_cost:
            return await interaction.response.send_message("MPが足りません。", ephemeral=True)

        if card.category == "SPECIAL":
            if card.attr == "EXCHANGE":
                await interaction.response.edit_message(content="【両替】交換先を選択：", view=ExchangeView(self.player, idx, self.game_state, self.channel, self.interaction_id))
            elif card.attr == "SELL":
                await interaction.response.edit_message(content="【売る】相手に渡す自分の神器を選択：", view=SellSelectView(self.player, idx, self.game_state, self.channel, self.interaction_id))
            elif card.attr in ["HEAL_HP", "HEAL_MP"]:
                self.game_state["active_interaction_id"] = None
                self.player["hand"].pop(idx); self.player["hand"].append(random.choice(TEST_CARDS))
                if card.attr == "HEAL_HP": self.player["hp"] += card.value
                else: self.player["mp"] += card.value
                await interaction.response.send_message(f"{card.name}を使用しました。", ephemeral=True)
                await self.game_state["cog"].process_turn_end(self.channel)
            else:
                await interaction.response.edit_message(content=f"{card.name}の対象を選択：", view=TargetSelectView(self.player, card, idx, self.game_state, self.channel, self.interaction_id, mode=card.attr))
            return

        if card.category in ["ATTACK", "MAGIC"]:
            # 鬼のくつ等はATTACKカテゴリとして扱い、ここで対象選択へ
            await interaction.response.edit_message(content=f"{card.name}の攻撃対象を選択：", view=TargetSelectView(self.player, card, idx, self.game_state, self.channel, self.interaction_id, mode="ATTACK"))
        else:
            await interaction.response.send_message("防御神器は攻撃された時に使用します。", ephemeral=True)

class SellSelectView(discord.ui.View):
    def __init__(self, player, sell_card_idx, game_state, channel, interaction_id):
        super().__init__(timeout=60)
        self.player, self.sell_card_idx, self.game_state, self.channel, self.interaction_id = player, sell_card_idx, game_state, channel, interaction_id
        # 「売る」カード自体以外から選択
        options = [discord.SelectOption(label=f"{c.name}({c.price}円)", value=str(i)) for i, c in enumerate(player["hand"]) if i != sell_card_idx]
        if options:
            sel = discord.ui.Select(placeholder="売りつける神器を選択", options=options)
            sel.callback = self.select_callback
            self.add_item(sel)

    async def select_callback(self, interaction: discord.Interaction):
        item_idx = int(interaction.data['values'][0]); item = self.player["hand"][item_idx]
        await interaction.response.edit_message(content=f"{item.name}を誰に売りつけますか？", view=TargetSelectView(self.player, item, item_idx, self.game_state, self.channel, self.interaction_id, mode="SELL", sell_tool_idx=self.sell_card_idx))

class ExchangeView(discord.ui.View):
    def __init__(self, player, card_idx, game_state, channel, interaction_id):
        super().__init__(timeout=60)
        self.player, self.card_idx, self.game_state, self.channel, self.interaction_id = player, card_idx, game_state, channel, interaction_id

    async def do_exchange(self, interaction, f, t):
        if self.game_state.get("active_interaction_id") != self.interaction_id: return
        if self.player.get(f, 0) >= 10:
            self.player[f] -= 10; self.player[t] += 10
            self.player["hand"].pop(self.card_idx); self.player["hand"].append(random.choice(TEST_CARDS))
            self.game_state["active_interaction_id"] = None
            await self.game_state["cog"].log(self.channel, f"{self.player['name']}が両替({f}→{t})を行いました。")
            await self.game_state["cog"].process_turn_end(self.channel)
        else: await interaction.response.send_message("リソースが足りません。", ephemeral=True)

    @discord.ui.button(label="HP(10)→MP(10)", style=discord.ButtonStyle.secondary)
    async def hp_mp(self, i, b): await self.do_exchange(i, "hp", "mp")
    @discord.ui.button(label="MP(10)→金(10)", style=discord.ButtonStyle.secondary)
    async def mp_money(self, i, b): await self.do_exchange(i, "mp", "money")
    @discord.ui.button(label="金(10)→HP(10)", style=discord.ButtonStyle.secondary)
    async def money_hp(self, i, b): await self.do_exchange(i, "money", "hp")

class TargetSelectView(discord.ui.View):
    def __init__(self, attacker, card, card_idx, game_state, channel, interaction_id, mode="ATTACK", sell_tool_idx=None):
        super().__init__(timeout=60)
        self.attacker, self.card, self.card_idx, self.game_state, self.channel, self.interaction_id, self.mode, self.sell_tool_idx = attacker, card, card_idx, game_state, channel, interaction_id, mode, sell_tool_idx
        for p_id, p in game_state["players"].items():
            if p_id != attacker["id"] and p["hp"] > 0:
                btn = discord.ui.Button(label=f"{p['name']}", style=discord.ButtonStyle.danger if mode=="ATTACK" else discord.ButtonStyle.secondary)
                btn.callback = self.make_callback(p_id)
                self.add_item(btn)

    def make_callback(self, tid):
        async def callback(interaction: discord.Interaction):
            if self.game_state.get("active_interaction_id") != self.interaction_id: return
            target = self.game_state["players"][tid]
            if self.mode == "ATTACK":
                self.game_state["active_interaction_id"] = None
                # 魔法系(MAGIC)は一度使うと以後何度でも選択可能（手札から消えない）
                if self.card.category != "MAGIC":
                    self.attacker["hand"].pop(self.card_idx); self.attacker["hand"].append(random.choice(TEST_CARDS))
                await interaction.response.edit_message(content=f"{target['name']}への攻撃を確定しました。", view=None)
                await self.game_state["cog"].trigger_defense_phase(self.channel, self.attacker, tid, self.card)
            elif self.mode == "BUY":
                item = random.choice(target["hand"])
                await interaction.response.edit_message(content=f"{target['name']}から{item.name}({item.price}円)を買い取りますか？", view=BuyConfirmView(self.attacker, target, item, self.card_idx, self.game_state, self.channel, self.interaction_id))
            elif self.mode == "SELL":
                self.game_state["active_interaction_id"] = None
                p = self.card.price
                if target["money"] >= p: target["money"] -= p
                elif (target["money"] + target["mp"]) >= p: target["mp"] -= (p - target["money"]); target["money"] = 0
                else: target["hp"] -= (p - target["money"] - target["mp"]); target["money"] = target["mp"] = 0
                target["hp"] = max(0, target["hp"])
                self.attacker["money"] += p
                # 売った神器と、売るカード本体を消費
                self.attacker["hand"].pop(self.card_idx)
                actual_tool_idx = self.sell_tool_idx if self.sell_tool_idx < len(self.attacker["hand"]) else 0
                self.attacker["hand"].pop(actual_tool_idx)
                while len(self.attacker["hand"]) < 8: self.attacker["hand"].append(random.choice(TEST_CARDS))
                target["hand"].append(self.card)
                await self.game_state["cog"].log(self.channel, f"【売買】{self.attacker['name']}が{target['name']}に{self.card.name}を売りつけました。")
                await self.game_state["cog"].process_turn_end(self.channel)
        return callback

class BuyConfirmView(discord.ui.View):
    def __init__(self, b, s, i, cidx, gs, ch, iid):
        super().__init__(timeout=60)
        self.b, self.s, self.i, self.cidx, self.gs, self.ch, self.iid = b, s, i, cidx, gs, ch, iid
    @discord.ui.button(label="買う", style=discord.ButtonStyle.success)
    async def buy(self, i, btn):
        if self.b["money"] >= self.i.price:
            self.b["money"] -= self.i.price; self.s["money"] += self.i.price
            self.s["hand"].remove(self.i); self.s["hand"].append(random.choice(TEST_CARDS))
            self.b["hand"].pop(self.cidx); self.b["hand"].append(self.i)
            await self.gs["cog"].log(self.ch, f"【売買】{self.b['name']}が{self.i.name}を購入しました。")
        else: await self.gs["cog"].log(self.ch, f"【売買】{self.b['name']}はお金が足りませんでした。")
        self.gs["active_interaction_id"] = None
        await self.gs["cog"].process_turn_end(self.ch)
    @discord.ui.button(label="買わない", style=discord.ButtonStyle.danger)
    async def no(self, i, btn): self.gs["active_interaction_id"] = None; await self.gs["cog"].process_turn_end(self.ch)

class DefensePromptView(discord.ui.View):
    def __init__(self, a, tid, c, gs, ch):
        super().__init__(timeout=60)
        self.a, self.tid, self.c, self.gs, self.ch, self.resolved = a, tid, c, gs, ch, False
    @discord.ui.button(label="防御神器を選択", style=discord.ButtonStyle.success)
    async def open_def(self, i, btn):
        if i.user.id != self.tid or self.resolved: return
        p = self.gs["players"][self.tid]
        # 防御だけでなく武器でも防御可能。鬼のくつのようなATTACK属性でも防御値があれば選択可能。
        opts = [discord.SelectOption(label="無防備", value="none")] + [discord.SelectOption(label=f"【防御】{c.name}(防:{c.value if hasattr(c, 'value') else 0})", value=str(idx)) for idx, c in enumerate(p["hand"]) if c.category in ["DEFENSE", "ATTACK"]]
        v = discord.ui.View(); sel = discord.ui.Select(placeholder="複数選択可能", options=opts, min_values=1, max_values=len(opts))
        async def cb(inter: discord.Interaction):
            if self.resolved: return
            self.resolved = True
            dc = []
            if "none" not in sel.values:
                # 逆順にpopしてインデックスずれを防ぐ
                for idx in sorted([int(x) for x in sel.values], reverse=True):
                    card = p["hand"].pop(idx)
                    dc.append(card)
                    p["hand"].append(random.choice(TEST_CARDS))
            await inter.response.send_message("防御を確定しました。", ephemeral=True)
            await self.gs["cog"].resolve_damage(self.ch, self.a, p, self.c, dc)
        sel.callback = cb; v.add_item(sel)
        await i.response.send_message("防御神器を選択してください。", view=v, ephemeral=True)
    async def on_timeout(self):
        if not self.resolved: self.resolved = True; await self.gs["cog"].resolve_damage(self.ch, self.a, self.gs["players"][self.tid], self.c, [])

class TurnControlView(discord.ui.View):
    def __init__(self, pid, p, g, ch, iid):
        super().__init__(timeout=60)
        self.pid, self.p, self.g, self.ch, self.iid, self.resolved = pid, p, g, ch, iid, False
    @discord.ui.button(label="行動を開始", style=discord.ButtonStyle.primary)
    async def act(self, i, btn):
        if i.user.id != self.pid or self.g.get("active_interaction_id") != self.iid: return
        await i.response.send_message("手札を展開します。", view=HandActionView(self.p, self.g, self.ch, self.iid), ephemeral=True)
    async def on_timeout(self):
        if not self.resolved and self.g.get("active_interaction_id") == self.iid:
            self.resolved = True; self.g["active_interaction_id"] = None
            await self.ch.send(f"{self.p['name']}のターンがタイムアウトしました。"); await self.g["cog"].process_turn_end(self.ch)

# --- Cog メイン ---

class GodField(commands.Cog):
    def __init__(self, bot): self.bot, self.games = bot, {}

    async def log(self, ch, t):
        m = await ch.send(f"[{t}]")
        if ch.id in self.games: self.games[ch.id]["temp_msgs"].append(m)

    @commands.hybrid_command(name="god_field")
    async def god_field(self, ctx, wait_time: int = 60):
        if ctx.channel.id in self.games: return await ctx.send("現在対戦が進行中です。")
        v = JoinView(timeout=wait_time); await ctx.send("ゴッドフィールド：参加者募集中...", view=v)
        await asyncio.sleep(wait_time)
        if len(v.joined_users) < 2: return await ctx.send("人数不足のため中止します。")
        # 初期HPは40以上(40)に設定
        ps = {u.id: {"id": u.id, "name": u.display_name, "hp": 40, "mp": 20, "hand": random.choices(TEST_CARDS, k=8), "money": 10} for u in v.joined_users}
        self.games[ctx.channel.id] = {"players": ps, "turn_order": list(ps.keys()), "current_index": 0, "active_interaction_id": None, "cog": self, "temp_msgs": []}
        await self.send_turn_panel(ctx.channel)

    async def send_turn_panel(self, ch):
        if ch.id not in self.games: return
        g = self.games[ch.id]
        # 使用済みのパネルやログを削除
        for m in g["temp_msgs"]:
            try: await m.delete()
            except: pass
        g["temp_msgs"] = []
        pid = g["turn_order"][g["current_index"]]; p = g["players"][pid]
        iid = str(uuid.uuid4()); g["active_interaction_id"] = iid
        st = "\n".join([f"{'RIP' if x['hp']<=0 else 'LIVE'} {x['name']}: HP{x['hp']} MP{x['mp']} 💰{x['money']}" for x in g["players"].values()])
        e = discord.Embed(title=f"{p['name']}のターン", description=st, color=0x2f3136)
        m = await ch.send(content=f"<@{pid}> 行動を選択してください：", embed=e, view=TurnControlView(pid, p, g, ch, iid))
        g["temp_msgs"].append(m)

    async def trigger_defense_phase(self, ch, a, tid, c, skip=False):
        g = self.games[ch.id]
        if skip:
            await self.log(ch, f"{g['players'][tid]['name']}は防げません！")
            return await self.resolve_damage(ch, a, g["players"][tid], c, [])
        a["mp"] = max(0, a["mp"] - c.mp_cost)
        await self.log(ch, f"【攻撃】{a['name']} ➔ {g['players'][tid]['name']} ： {c.name}")
        m = await ch.send(content=f"<@{tid}> 防御神器を選択してください：", view=DefensePromptView(a, tid, c, g, ch))
        g["temp_msgs"].append(m)

    async def resolve_damage(self, ch, a, t, atk, dfs):
        dmg = atk.value; g = self.games[ch.id]
        for d in dfs:
            if d.name == "乱弾武剣" and atk.attr in ["NONE", "PHYSICAL"]:
                nt = random.choice([p for p in g["players"].values() if p["hp"] > 0])
                await self.log(ch, f"【防御】乱弾武剣で弾きました！ ➔ 次の標的：{nt['name']}")
                return await self.trigger_defense_phase(ch, a, nt["id"], atk, skip=(nt["id"]==t["id"]))
            if d.attr == "REFLECT" or d.name == "スーパーミラー":
                await self.log(ch, "【防御】神器を跳ね返しました！")
                return await self.trigger_defense_phase(ch, t, a["id"], atk)
        # 属性相性計算（簡易）
        td = sum([d.value for d in dfs if not (atk.attr != "NONE" and hasattr(d, 'attr') and d.attr == "PHYSICAL")])
        dmg = max(0, dmg - td)
        # 特殊アイテム：ゴーストソード
        if atk.name == "ゴーストソード": a["hp"] += dmg; await self.log(ch, f"【吸収】{dmg}回復しました。")
        t["hp"] = max(0, t["hp"] - dmg); await self.log(ch, f"【結果】{t['name']}に{dmg}ダメージを与えました。(HP:{t['hp']})")
        if t["hp"] <= 0: await self.log(ch, f"【昇天】{t['name']}が力尽きました。")
        await self.process_turn_end(ch)

    async def process_turn_end(self, ch):
        if ch.id not in self.games: return
        g = self.games[ch.id]
        al = [i for i, p in g["players"].items() if p["hp"] > 0]
        if len(al) <= 1:
            w = g["players"][al[0]]["name"] if al else "なし"; await ch.send(f"勝者：{w}。対戦を終了します。"); del self.games[ch.id]; return
        g["current_index"] = (g["current_index"] + 1) % len(g["turn_order"])
        while g["players"][g["turn_order"][g["current_index"]]]["hp"] <= 0: g["current_index"] = (g["current_index"] + 1) % len(g["turn_order"])
        await asyncio.sleep(2); await self.send_turn_panel(ch)

async def setup(bot): await bot.add_cog(GodField(bot))