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
        self.value = value        # 威力、防御力、特殊効果値
        self.mp_cost = mp_cost
        self.price = price        # 売却価格/購入価格
        self.description = description

# 更新されたカードセット
TEST_CARDS = [
    Card("ファイアボール", "MAGIC", "FIRE", 15, mp_cost=5, price=10, description="威力15/炎属性"),
    Card("銅の棍棒", "ATTACK", "NONE", 1, price=1, description="威力1/無属性"),
    Card("銀の棍棒", "ATTACK", "NONE", 1, price=10, description="威力1/無属性"),
    Card("乱弾武剣", "DEFENSE", "NONE", 5, price=10, description="防御5/無属性を弾く"),
    Card("革の盾", "DEFENSE", "PHYSICAL", 8, price=2, description="防御8/物理専用"),
    Card("買う", "SPECIAL", "BUY", 0, price=0, description="他人の神器を買う"),
    Card("売る", "SPECIAL", "SELL", 0, price=0, description="自分の神器を売る"),
    Card("両替", "SPECIAL", "EXCHANGE", 10, price=0, description="HP/MP/金を変換"),
    Card("バチェット", "ATTACK", "NONE", 4, price=3, description="威力4/無属性")
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

        # 特殊カード判定
        if card.category == "SPECIAL":
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

        # 両替は自分自身のみ
        if mode == "EXCHANGE":
            btn = discord.ui.Button(label="自分自身", style=discord.ButtonStyle.primary)
            btn.callback = self.make_callback(attacker["id"])
            self.add_item(btn)
        else:
            for p_id, p_data in game_state["players"].items():
                if p_id != attacker["id"] and p_data["hp"] > 0:
                    btn = discord.ui.Button(label=f"{p_data['name']}", style=discord.ButtonStyle.danger if mode=="ATTACK" else discord.ButtonStyle.secondary)
                    btn.callback = self.make_callback(p_id)
                    self.add_item(btn)

    def make_callback(self, target_id):
        async def callback(interaction: discord.Interaction):
            if self.game_state.get("active_interaction_id") != self.interaction_id:
                return await interaction.response.send_message("無効なアクションです。", ephemeral=True)
            
            self.game_state["active_interaction_id"] = None
            target = self.game_state["players"][target_id]
            
            if self.mode == "ATTACK":
                self.attacker["hand"].pop(self.card_idx)
                self.attacker["hand"].append(random.choice(TEST_CARDS))
                await interaction.response.edit_message(content=f"{target['name']}への攻撃確定。", view=None)
                await self.game_state["cog"].trigger_defense_phase(self.channel, self.attacker, target_id, self.card)
            
            elif self.mode == "BUY":
                # 相手の手札からランダムに提示
                item = random.choice(target["hand"])
                if self.attacker["money"] >= item.price:
                    self.attacker["money"] -= item.price
                    target["money"] += item.price
                    target["hand"].remove(item)
                    target["hand"].append(random.choice(TEST_CARDS))
                    self.attacker["hand"].pop(self.card_idx)
                    self.attacker["hand"].append(item)
                    await self.channel.send(f"{self.attacker['name']}が{target['name']}から{item.name}を{item.price}円で購入しました。")
                else:
                    await self.channel.send(f"{self.attacker['name']}は金が足りず、貧乏としてキャンセルされました。")
                await self.game_state["cog"].process_turn_end(self.channel)

            elif self.mode == "SELL":
                # 自分の手札から次に売るカードを選択させる必要があるが、ここでは簡易的に「売る」カード以外のランダムな1枚を売りつける
                sellable = [c for c in self.attacker["hand"] if c != self.card]
                if not sellable: return await self.game_state["cog"].process_turn_end(self.channel)
                item = random.choice(sellable)
                price = item.price
                
                # 徴収ロジック
                if target["money"] >= price:
                    target["money"] -= price
                    self.attacker["money"] += price
                elif (target["money"] + target["mp"]) >= price:
                    diff = price - target["money"]
                    target["money"] = 0
                    target["mp"] -= diff
                    self.attacker["money"] += price
                else:
                    diff = price - (target["money"] + target["mp"])
                    target["money"] = 0
                    target["mp"] = 0
                    target["hp"] -= diff
                    self.attacker["money"] += price

                self.attacker["hand"].remove(item)
                self.attacker["hand"].append(random.choice(TEST_CARDS))
                self.attacker["hand"].pop(self.attacker["hand"].index(self.card)) # 売るカード自身も消費
                self.attacker["hand"].append(random.choice(TEST_CARDS))
                target["hand"].append(item)
                
                await self.channel.send(f"{self.attacker['name']}が{target['name']}に{item.name}を売りつけました（{price}円徴収）。")
                await self.game_state["cog"].process_turn_end(self.channel)

            elif self.mode == "EXCHANGE":
                # HP -> MP (10単位)
                if self.attacker["hp"] > 10:
                    self.attacker["hp"] -= 10
                    self.attacker["mp"] += 10
                    await self.channel.send(f"{self.attacker['name']}が両替を行いました(HP-10/MP+10)。")
                self.attacker["hand"].pop(self.card_idx)
                self.attacker["hand"].append(random.choice(TEST_CARDS))
                await self.game_state["cog"].process_turn_end(self.channel)

        return callback

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
            await self.channel.send(f"{self.player['name']}タイムアウト。スキップします。")
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
                options.append(discord.SelectOption(label=f"{c.name}(防:{c.value}/{c.attr})", value=str(i)))
        
        view = discord.ui.View()
        # 複数選択可能に
        select = discord.ui.Select(placeholder="防御カード選択(複数可)", options=options, min_values=1, max_values=len(options))

        async def select_callback(inter: discord.Interaction):
            if self.resolved: return
            self.resolved = True
            self.stop()
            
            def_cards = []
            if "none" not in select.values:
                # 選択されたインデックスを降順でソートしてpop時のインデックスずれを防ぐ
                indices = sorted([int(v) for v in select.values], reverse=True)
                for idx in indices:
                    c = player["hand"].pop(idx)
                    def_cards.append(c)
                    player["hand"].append(random.choice(TEST_CARDS))
            
            await inter.response.send_message("防御確定。", ephemeral=True)
            await self.game_state["cog"].resolve_damage(self.channel, self.attacker, player, self.card, def_cards)

        select.callback = select_callback
        view.add_item(select)
        await interaction.response.send_message("防御カードを選択(複数可)。", view=view, ephemeral=True)

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
        if ctx.channel.id in self.games:
            return await ctx.send("進行中。")
        view = JoinView(timeout=wait_time)
        await ctx.send("ゴッドフィールド参加受付中...", view=view)
        await asyncio.sleep(wait_time)
        if len(view.joined_users) < 2:
            return await ctx.send("中止。")

        players = {}
        for user in view.joined_users:
            players[user.id] = {
                "id": user.id, "name": user.display_name,
                "hp": 40, "mp": 20, "hand": random.choices(TEST_CARDS, k=5),
                "money": 10, "guardian": None
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

    async def trigger_defense_phase(self, channel, attacker, target_id, attack_card):
        game = self.games[channel.id]
        attacker["mp"] -= attack_card.mp_cost
        await channel.send(f"{attacker['name']} -> {game['players'][target_id]['name']} : {attack_card.name}")
        await channel.send(content=f"<@{target_id}> 防御選択", view=DefensePromptView(attacker, target_id, attack_card, game, channel))

    async def resolve_damage(self, channel, attacker, target, atk_card, def_cards):
        damage = atk_card.value
        game = self.games[channel.id]
        
        # 弾く・跳ね返す判定
        for dc in def_cards:
            # 乱弾武剣による「弾く」(無属性または威力10以下を想定)
            if dc.name == "乱弾武剣" and (atk_card.attr == "NONE" or atk_card.attr == "PHYSICAL"):
                alive = [p for p in game["players"].values() if p["hp"] > 0]
                new_target = random.choice(alive)
                await channel.send(f"弾いた！攻撃は{new_target['name']}へ再抽選されます。")
                return await self.trigger_defense_phase(channel, attacker, new_target["id"], atk_card)
            
            # 跳ね返す(名前で判定)
            if "跳ね返す" in dc.description: # 特殊効果として
                await channel.send(f"跳ね返した！攻撃は{attacker['name']}へ戻ります。")
                return await self.trigger_defense_phase(channel, target, attacker["id"], atk_card)

        # 通常ダメージ計算
        total_def = 0
        for dc in def_cards:
            # 属性武器判定: 属性あり武器 vs 無属性防具(PHYSICAL)
            if atk_card.attr != "NONE" and dc.attr == "PHYSICAL":
                continue # 防御不可
            total_def += dc.value
        
        damage = max(0, damage - total_def)
        target["hp"] -= damage
        await channel.send(f"{target['name']}に{damage}ダメージ。(残HP:{max(0, target['hp'])})")
        
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