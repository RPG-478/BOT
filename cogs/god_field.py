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
        self.attr = attr          # "PHYSICAL", "FIRE", "WATER", "NONE"
        self.value = value
        self.mp_cost = mp_cost
        self.price = price
        self.description = description

# 更新されたカードセット
TEST_CARDS = [
    Card("銅の棍棒", "ATTACK", "NONE", 1, price=1, description="威力1/無属性"),
    Card("銀の棍棒", "ATTACK", "NONE", 1, price=10, description="威力1/無属性"),
    Card("乱弾武剣", "DEFENSE", "NONE", 5, price=10, description="防御5/無属性を弾く"),
    Card("スマイルのしずく", "SPECIAL", "HEAL_HP", 5, price=1, description="HP5回復"),
    Card("スマイルの花", "SPECIAL", "HEAL_MP", 5, price=1, description="MP5回復"),
    Card("買う", "SPECIAL", "BUY", 0, price=0, description="他人の神器を買う"),
    Card("売る", "SPECIAL", "SELL", 0, price=0, description="自分の神器を売る"),
    Card("両替", "SPECIAL", "EXCHANGE", 0, price=0, description="ステータス変換"),
    Card("バチェット", "ATTACK", "NONE", 4, price=3, description="威力4/無属性"),
    Card("ムチ", "ATTACK", "NONE", 2, price=1, description="威力2/無属性"),
    Card("セイバーロッド", "ATTACK", "NONE", 2, price=10, description="威力2/防御6/無属性"),
    Card("パンチ", "ATTACK", "NONE", 3, price=1, description="威力3/無属性"),
    Card("革の帽子", "DEFENSE", "NONE", 1, price=1, description="防御1/無属性"),
    Card("革の服", "DEFENSE", "NONE", 2, price=2, description="防御2/無属性"),
    Card("アイアンガントレット", "DEFENSE", "NONE", 3, price=3, description="防御3/無属性"),
    Card("アイアンシールド", "DEFENCE", "NONE", 4, price=4, description="防御4/無属性"),
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
        self.player = player
        self.game_state = game_state
        self.channel = channel
        self.interaction_id = interaction_id
        self.add_item(ActionSelect(player, game_state, channel, interaction_id))

class ActionSelect(discord.ui.Select):
    def __init__(self, player, game_state, channel, interaction_id):
        self.player = player
        self.game_state = game_state
        self.channel = channel
        self.interaction_id = interaction_id
        
        options = []
        for i, card in enumerate(player["hand"]):
            label = f"{card.name}"
            desc = f"{card.description} (価値:{card.price})"
            options.append(discord.SelectOption(label=label, value=str(i), description=desc))
        
        if not options:
            options.append(discord.SelectOption(label="祈る", value="pray"))

        super().__init__(placeholder="カード選択", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        if self.game_state.get("active_interaction_id") != self.interaction_id:
            return await interaction.response.send_message("無効なアクションです。", ephemeral=True)

        if self.values[0] == "pray":
            self.game_state["active_interaction_id"] = None
            await interaction.response.send_message("祈りました。", ephemeral=True)
            return await self.game_state["cog"].process_turn_end(self.channel)

        card_idx = int(self.values[0])
        card = self.player["hand"][card_idx]

        if card.category == "SPECIAL":
            if card.attr == "EXCHANGE":
                view = ExchangeView(self.player, card_idx, self.game_state, self.channel, self.interaction_id)
                await interaction.response.edit_message(content="交換する項目を選択してください。", view=view)
            elif card.attr in ["HEAL_HP", "HEAL_MP"]:
                self.game_state["active_interaction_id"] = None
                self.player["hand"].pop(card_idx)
                self.player["hand"].append(random.choice(TEST_CARDS))
                if card.attr == "HEAL_HP":
                    self.player["hp"] = min(40, self.player["hp"] + card.value)
                else:
                    self.player["mp"] += card.value
                await interaction.response.send_message(f"{card.name}を使用しました。", ephemeral=True)
                await self.channel.send(f"{self.player['name']}が{card.name}を使用しました。")
                await self.game_state["cog"].process_turn_end(self.channel)
            else:
                view = TargetSelectView(self.player, card, card_idx, self.game_state, self.channel, self.interaction_id, mode=card.attr)
                await interaction.response.edit_message(content=f"{card.name}の対象を選択してください。", view=view)
            return

        if card.category == "MAGIC" and self.player["mp"] < card.mp_cost:
            return await interaction.response.send_message("MP不足です。", ephemeral=True)

        if card.category in ["ATTACK", "MAGIC"]:
            view = TargetSelectView(self.player, card, card_idx, self.game_state, self.channel, self.interaction_id, mode="ATTACK")
            await interaction.response.edit_message(content=f"{card.name}の対象を選択してください。", view=view)
        else:
            await interaction.response.send_message("防御カードは攻撃された時に使用します。", ephemeral=True)

class ExchangeView(discord.ui.View):
    def __init__(self, player, card_idx, game_state, channel, interaction_id):
        super().__init__(timeout=60)
        self.player = player
        self.card_idx = card_idx
        self.game_state = game_state
        self.channel = channel
        self.interaction_id = interaction_id

    async def do_exchange(self, interaction, from_attr, to_attr):
        if self.game_state.get("active_interaction_id") != self.interaction_id: return
        val = 10
        if self.player.get(from_attr, 0) >= val:
            self.player[from_attr] -= val
            self.player[to_attr] += val
            self.player["hand"].pop(self.card_idx)
            self.player["hand"].append(random.choice(TEST_CARDS))
            self.game_state["active_interaction_id"] = None
            await self.channel.send(f"{self.player['name']}が両替({from_attr}→{to_attr})を行いました。")
            await self.game_state["cog"].process_turn_end(self.channel)
        else:
            await interaction.response.send_message("リソースが足りません。", ephemeral=True)

    @discord.ui.button(label="HP(10)→MP(10)", style=discord.ButtonStyle.secondary)
    async def hp_mp(self, interaction, button): await self.do_exchange(interaction, "hp", "mp")
    @discord.ui.button(label="MP(10)→金(10)", style=discord.ButtonStyle.secondary)
    async def mp_money(self, interaction, button): await self.do_exchange(interaction, "mp", "money")
    @discord.ui.button(label="金(10)→HP(10)", style=discord.ButtonStyle.secondary)
    async def money_hp(self, interaction, button): await self.do_exchange(interaction, "money", "hp")

class TargetSelectView(discord.ui.View):
    def __init__(self, attacker, card, card_idx, game_state, channel, interaction_id, mode="ATTACK"):
        super().__init__(timeout=60)
        self.attacker = attacker
        self.card = card
        self.card_idx = card_idx
        self.game_state = game_state
        self.channel = channel
        self.interaction_id = interaction_id
        self.mode = mode

        for p_id, p_data in game_state["players"].items():
            if p_id != attacker["id"] and p_data["hp"] > 0:
                btn = discord.ui.Button(label=f"{p_data['name']}", style=discord.ButtonStyle.danger if mode=="ATTACK" else discord.ButtonStyle.secondary)
                btn.callback = self.make_callback(p_id)
                self.add_item(btn)

    def make_callback(self, target_id):
        async def callback(interaction: discord.Interaction):
            if self.game_state.get("active_interaction_id") != self.interaction_id:
                return await interaction.response.send_message("無効なアクションです。", ephemeral=True)
            
            target = self.game_state["players"][target_id]
            
            if self.mode == "ATTACK":
                self.game_state["active_interaction_id"] = None
                self.attacker["hand"].pop(self.card_idx)
                self.attacker["hand"].append(random.choice(TEST_CARDS))
                await interaction.response.edit_message(content=f"{target['name']}への攻撃確定。", view=None)
                await self.game_state["cog"].trigger_defense_phase(self.channel, self.attacker, target_id, self.card)
            
            elif self.mode == "BUY":
                item = random.choice(target["hand"])
                view = BuyConfirmView(self.attacker, target, item, self.card_idx, self.game_state, self.channel, self.interaction_id)
                await interaction.response.edit_message(content=f"{target['name']}から{item.name}を{item.price}円で買いますか？", view=view)

            elif self.mode == "SELL":
                self.game_state["active_interaction_id"] = None
                sellable = [c for i, c in enumerate(self.attacker["hand"]) if i != self.card_idx]
                if not sellable: return await self.game_state["cog"].process_turn_end(self.channel)
                item = random.choice(sellable)
                price = item.price
                
                if target["money"] >= price:
                    target["money"] -= price
                    self.attacker["money"] += price
                elif (target["money"] + target["mp"]) >= price:
                    diff = price - target["money"]
                    target["money"] = 0
                    target["mp"] = max(0, target["mp"] - diff)
                    self.attacker["money"] += price
                else:
                    diff = price - (target["money"] + target["mp"])
                    target["money"] = 0
                    target["mp"] = 0
                    target["hp"] = max(0, target["hp"] - diff)
                    self.attacker["money"] += price

                self.attacker["hand"].remove(item)
                self.attacker["hand"].append(random.choice(TEST_CARDS))
                self.attacker["hand"].pop(self.attacker["hand"].index(self.card))
                self.attacker["hand"].append(random.choice(TEST_CARDS))
                target["hand"].append(item)
                await self.channel.send(f"{self.attacker['name']}が{target['name']}に{item.name}を売りつけました。")
                await self.game_state["cog"].process_turn_end(self.channel)
        return callback

class BuyConfirmView(discord.ui.View):
    def __init__(self, buyer, seller, item, card_idx, game_state, channel, interaction_id):
        super().__init__(timeout=60)
        self.buyer = buyer
        self.seller = seller
        self.item = item
        self.card_idx = card_idx
        self.game_state = game_state
        self.channel = channel
        self.interaction_id = interaction_id

    @discord.ui.button(label="買う", style=discord.ButtonStyle.success)
    async def buy(self, interaction, button):
        if self.buyer["money"] >= self.item.price:
            self.buyer["money"] -= self.item.price
            self.seller["money"] += self.item.price
            self.seller["hand"].remove(self.item)
            self.seller["hand"].append(random.choice(TEST_CARDS))
            self.buyer["hand"].pop(self.card_idx)
            self.buyer["hand"].append(self.item)
            await self.channel.send(f"{self.buyer['name']}が{self.item.name}を購入しました。")
        else:
            await self.channel.send(f"{self.buyer['name']}は金が足りませんでした。")
        self.game_state["active_interaction_id"] = None
        await self.game_state["cog"].process_turn_end(self.channel)

    @discord.ui.button(label="買わない", style=discord.ButtonStyle.danger)
    async def cancel(self, interaction, button):
        await self.channel.send(f"{self.buyer['name']}は購入を見送りました。")
        self.game_state["active_interaction_id"] = None
        await self.game_state["cog"].process_turn_end(self.channel)

class TurnControlView(discord.ui.View):
    def __init__(self, current_p_id, player, game, channel, interaction_id):
        super().__init__(timeout=60)
        self.current_p_id = current_p_id
        self.player = player
        self.game = game
        self.channel = channel
        self.interaction_id = interaction_id
        self.resolved = False

    @discord.ui.button(label="行動を選択", style=discord.ButtonStyle.primary)
    async def action_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.current_p_id:
            return await interaction.response.send_message("あなたのターンではありません。", ephemeral=True)
        if self.game.get("active_interaction_id") != self.interaction_id or self.resolved:
            return await interaction.response.send_message("無効なアクションです。", ephemeral=True)
        view = HandActionView(self.player, self.game, self.channel, self.interaction_id)
        await interaction.response.send_message("手札選択", view=view, ephemeral=True)

    async def on_timeout(self):
        if not self.resolved and self.game.get("active_interaction_id") == self.interaction_id:
            self.resolved = True
            self.game["active_interaction_id"] = None
            await self.channel.send(f"{self.player['name']}タイムアウト。")
            await self.game["cog"].process_turn_end(self.channel)

class DefensePromptView(discord.ui.View):
    def __init__(self, attacker, target_id, card, game_state, channel):
        super().__init__(timeout=60)
        self.attacker = attacker
        self.target_id = target_id
        self.card = card
        self.game_state = game_state
        self.channel = channel
        self.resolved = False

    @discord.ui.button(label="防御選択", style=discord.ButtonStyle.success)
    async def open_defense(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.target_id:
            return await interaction.response.send_message("対象外です。", ephemeral=True)
        if self.resolved:
            return await interaction.response.send_message("終了済み。", ephemeral=True)
        
        player = self.game_state["players"][self.target_id]
        options = [discord.SelectOption(label="無防備", value="none")]
        for i, c in enumerate(player["hand"]):
            if c.category == "DEFENSE":
                options.append(discord.SelectOption(label=f"{c.name}(防:{c.value})", value=str(i)))
        
        view = discord.ui.View()
        select = discord.ui.Select(placeholder="防御カード選択(複数可)", options=options, min_values=1, max_values=len(options))

        async def select_callback(inter: discord.Interaction):
            if self.resolved: return
            self.resolved = True
            self.stop()
            def_cards = []
            if "none" not in select.values:
                indices = sorted([int(v) for v in select.values], reverse=True)
                for idx in indices:
                    c = player["hand"].pop(idx)
                    def_cards.append(c)
                    player["hand"].append(random.choice(TEST_CARDS))
            await inter.response.send_message("防御確定。", ephemeral=True)
            await self.game_state["cog"].resolve_damage(self.channel, self.attacker, player, self.card, def_cards)

        select.callback = select_callback
        view.add_item(select)
        await interaction.response.send_message("防御選択。", view=view, ephemeral=True)

    async def on_timeout(self):
        if not self.resolved:
            self.resolved = True
            player = self.game_state["players"][self.target_id]
            await self.game_state["cog"].resolve_damage(self.channel, self.attacker, player, self.card, [])

# --- Cog メインクラス ---

class GodField(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.games = {}

    @commands.hybrid_command(name="god_field")
    async def god_field(self, ctx, wait_time: int = 60):
        if ctx.channel.id in self.games: return await ctx.send("進行中。")
        view = JoinView(timeout=wait_time)
        await ctx.send("参加受付中...", view=view)
        await asyncio.sleep(wait_time)
        if len(view.joined_users) < 2: return await ctx.send("中止。")

        players = {}
        for user in view.joined_users:
            players[user.id] = {
                "id": user.id, "name": user.display_name,
                "hp": 40, "mp": 20, "hand": random.choices(TEST_CARDS, k=5),
                "money": 10
            }
        self.games[ctx.channel.id] = {
            "players": players, "turn_order": list(players.keys()),
            "current_index": 0, "active_interaction_id": None, "cog": self
        }
        await ctx.send("開始。")
        await self.send_turn_panel(ctx.channel)

    async def send_turn_panel(self, channel):
        if channel.id not in self.games: return
        game = self.games[channel.id]
        p_id = game["turn_order"][game["current_index"]]
        player = game["players"][p_id]
        new_id = str(uuid.uuid4())
        game["active_interaction_id"] = new_id

        status = "\n".join([f"{'RIP' if p['hp']<=0 else 'LIVE'} {p['name']}: HP{p['hp']} MP{p['mp']} 💰{p['money']}" for p in game["players"].values()])
        embed = discord.Embed(title=f"{player['name']}のターン", description=status, color=0x333333)
        await channel.send(content=f"<@{p_id}>", embed=embed, view=TurnControlView(p_id, player, game, channel, new_id))

    async def trigger_defense_phase(self, channel, attacker, target_id, attack_card, skip_defense=False):
        game = self.games[channel.id]
        if skip_defense:
            await channel.send(f"自分に当たった！防御できません。")
            await self.resolve_damage(channel, attacker, game["players"][target_id], attack_card, [])
            return

        attacker["mp"] = max(0, attacker["mp"] - attack_card.mp_cost)
        await channel.send(f"{attacker['name']} -> {game['players'][target_id]['name']} : {attack_card.name}")
        await channel.send(content=f"<@{target_id}> 防御選択", view=DefensePromptView(attacker, target_id, attack_card, game, channel))

    async def resolve_damage(self, channel, attacker, target, atk_card, def_cards):
        damage = atk_card.value
        game = self.games[channel.id]
        
        for dc in def_cards:
            if dc.name == "乱弾武剣" and (atk_card.attr == "NONE" or atk_card.attr == "PHYSICAL"):
                alive = [p for p in game["players"].values() if p["hp"] > 0]
                new_target = random.choice(alive)
                # 自分に返った場合は防御不可フラグ
                is_self = (new_target["id"] == target["id"])
                await channel.send(f"弾いた！次は{new_target['name']}です。")
                return await self.trigger_defense_phase(channel, attacker, new_target["id"], atk_card, skip_defense=is_self)
            
            if "跳ね返す" in dc.description:
                await channel.send(f"跳ね返した！")
                return await self.trigger_defense_phase(channel, target, attacker["id"], atk_card)

        total_def = sum([dc.value for dc in def_cards if not (atk_card.attr != "NONE" and dc.attr == "PHYSICAL")])
        damage = max(0, damage - total_def)
        target["hp"] = max(0, target["hp"] - damage)
        await channel.send(f"{target['name']}に{damage}ダメージ。(残HP:{target['hp']})")
        if target["hp"] <= 0: await channel.send(f"{target['name']}昇天。")
        await self.process_turn_end(channel)

    async def process_turn_end(self, channel):
        if channel.id not in self.games: return
        game = self.games[channel.id]
        alive = [pid for pid, p in game["players"].items() if p["hp"] > 0]
        if len(alive) <= 1:
            winner = game["players"][alive[0]]["name"] if alive else "なし"
            await channel.send(f"終了。勝者: {winner}")
            del self.games[channel.id]
            return
        game["current_index"] = (game["current_index"] + 1) % len(game["turn_order"])
        while game["players"][game["turn_order"][game["current_index"]]]["hp"] <= 0:
            game["current_index"] = (game["current_index"] + 1) % len(game["turn_order"])
        await asyncio.sleep(1)
        await self.send_turn_panel(channel)

async def setup(bot):
    await bot.add_cog(GodField(bot))

