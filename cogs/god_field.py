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
        self.attr = attr          # "PHYSICAL", "FIRE", "WATER", "NONE", "HEAL_HP", "HEAL_MP"
        self.value = value
        self.mp_cost = mp_cost
        self.price = price
        self.description = description

# テスト用カードセット
TEST_CARDS = [
    Card("ファイアボール", "MAGIC", "FIRE", 15, mp_cost=5, price=10, description="威力15/消費MP5"),
    Card("木の棒", "ATTACK", "PHYSICAL", 5, price=1, description="威力5"),
    Card("革の盾", "DEFENSE", "PHYSICAL", 8, price=2, description="防御8"),
    Card("HP回復薬(仮)", "SPECIAL", "HEAL_HP", 15, price=5, description="HP15回復"),
    Card("MP回復薬(仮)", "SPECIAL", "HEAL_MP", 10, price=5, description="MP10回復"),
    Card("バチェット", "ATTACK", "NONE", 4, price=3, description="威力4")
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
            desc = f"{card.description} (売:{card.price})"
            options.append(discord.SelectOption(label=label, value=str(i), description=desc))
        
        if not options:
            options.append(discord.SelectOption(label="祈る", value="pray"))

        super().__init__(placeholder="使用カード選択", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        if self.game_state.get("active_interaction_id") != self.interaction_id:
            return await interaction.response.send_message("無効なアクションです。", ephemeral=True)

        if self.values[0] == "pray":
            self.game_state["active_interaction_id"] = None
            await interaction.response.send_message("祈りました。", ephemeral=True)
            return await self.game_state["cog"].process_turn_end(self.channel)

        card_idx = int(self.values[0])
        card = self.player["hand"][card_idx]

        if card.category == "MAGIC" and self.player["mp"] < card.mp_cost:
            return await interaction.response.send_message("MP不足です。", ephemeral=True)

        if card.category == "SPECIAL":
            self.game_state["active_interaction_id"] = None
            self.player["hand"].pop(card_idx)
            self.player["hand"].append(random.choice(TEST_CARDS))
            
            msg = ""
            if card.attr == "HEAL_HP":
                self.player["hp"] = min(40, self.player["hp"] + card.value)
                msg = f"{card.name}を使用。HPが{card.value}回復しました。"
            elif card.attr == "HEAL_MP":
                self.player["mp"] += card.value
                msg = f"{card.name}を使用。MPが{card.value}回復しました。"
            
            await interaction.response.send_message(msg, ephemeral=True)
            await self.channel.send(f"{self.player['name']}が{card.name}を使用しました。")
            return await self.game_state["cog"].process_turn_end(self.channel)

        if card.category in ["ATTACK", "MAGIC"]:
            view = TargetSelectView(self.player, card, card_idx, self.game_state, self.channel, self.interaction_id)
            await interaction.response.edit_message(content=f"{card.name}の対象を選択してください。", view=view)
        else:
            await interaction.response.send_message("防御カードは攻撃された時に使用します。", ephemeral=True)

class TargetSelectView(discord.ui.View):
    def __init__(self, attacker, card, card_idx, game_state, channel, interaction_id):
        super().__init__(timeout=60)
        self.attacker = attacker
        self.card = card
        self.card_idx = card_idx
        self.game_state = game_state
        self.channel = channel
        self.interaction_id = interaction_id

        for p_id, p_data in game_state["players"].items():
            if p_id != attacker["id"] and p_data["hp"] > 0:
                btn = discord.ui.Button(label=f"{p_data['name']}", style=discord.ButtonStyle.danger)
                btn.callback = self.make_callback(p_id)
                self.add_item(btn)

    def make_callback(self, target_id):
        async def callback(interaction: discord.Interaction):
            if self.game_state.get("active_interaction_id") != self.interaction_id:
                return await interaction.response.send_message("無効なアクションです。", ephemeral=True)
            
            self.game_state["active_interaction_id"] = None
            await interaction.response.edit_message(content=f"{self.game_state['players'][target_id]['name']}への攻撃を確定しました。", view=None)
            
            self.attacker["hand"].pop(self.card_idx)
            self.attacker["hand"].append(random.choice(TEST_CARDS))
            
            await self.game_state["cog"].trigger_defense_phase(self.channel, self.attacker, target_id, self.card)
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
        await interaction.response.send_message("手札を表示します。", view=view, ephemeral=True)

    async def on_timeout(self):
        # 1分経過でスキップ
        if not self.resolved and self.game.get("active_interaction_id") == self.interaction_id:
            self.resolved = True
            self.game["active_interaction_id"] = None
            await self.channel.send(f"{self.player['name']}がタイムアウトしました。ターンを終了します。")
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
            return await interaction.response.send_message("対象ではありません。", ephemeral=True)
        
        if self.resolved:
            return await interaction.response.send_message("終了済みです。", ephemeral=True)
        
        player = self.game_state["players"][self.target_id]
        options = [discord.SelectOption(label="無防備", value="none")]
        for i, c in enumerate(player["hand"]):
            if c.category == "DEFENSE":
                options.append(discord.SelectOption(label=f"{c.name}({c.value})", value=str(i)))
        
        view = discord.ui.View()
        select = discord.ui.Select(placeholder="防御カード選択", options=options)

        async def select_callback(inter: discord.Interaction):
            if self.resolved: return
            self.resolved = True
            self.stop()
            
            def_card = None
            if select.values[0] != "none":
                idx = int(select.values[0])
                def_card = player["hand"][idx]
                player["hand"].pop(idx)
                player["hand"].append(random.choice(TEST_CARDS))
            
            await inter.response.send_message("防御を確定しました。", ephemeral=True)
            await self.game_state["cog"].resolve_damage(self.channel, self.attacker, player, self.card, def_card)

        select.callback = select_callback
        view.add_item(select)
        await interaction.response.send_message("防御カードを選択してください。", view=view, ephemeral=True)

    async def on_timeout(self):
        if not self.resolved:
            self.resolved = True
            player = self.game_state["players"][self.target_id]
            await self.game_state["cog"].resolve_damage(self.channel, self.attacker, player, self.card, None)

# --- Cog メインクラス ---

class GodField(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.games = {}

    @commands.hybrid_command(name="god_field")
    async def god_field(self, ctx, wait_time: int = 60):
        if ctx.channel.id in self.games:
            return await ctx.send("進行中のゲームがあります。")

        view = JoinView(timeout=wait_time)
        embed = discord.Embed(title="ゴッドフィールド開始", description=f"参加ボタンを押してください。\n開始まで残り {wait_time} 秒", color=0x333333)
        await ctx.send(embed=embed, view=view)

        await asyncio.sleep(wait_time)

        if len(view.joined_users) < 2:
            return await ctx.send("プレイヤー不足により中止します。")

        players = {}
        for user in view.joined_users:
            players[user.id] = {
                "id": user.id,
                "name": user.display_name,
                "hp": 40,
                "mp": 20,
                "hand": random.choices(TEST_CARDS, k=5),
                "money": 10,
                "guardian": None
            }

        self.games[ctx.channel.id] = {
            "players": players,
            "turn_order": list(players.keys()),
            "current_index": 0,
            "active_interaction_id": None,
            "cog": self
        }

        await ctx.send("対戦を開始します。")
        await self.send_turn_panel(ctx.channel)

    async def send_turn_panel(self, channel):
        if channel.id not in self.games: return
        game = self.games[channel.id]
        p_id = game["turn_order"][game["current_index"]]
        player = game["players"][p_id]

        new_id = str(uuid.uuid4())
        game["active_interaction_id"] = new_id

        embed = discord.Embed(title=f"{player['name']}のターン", color=0x777777)
        status_text = ""
        for pid, pdata in game["players"].items():
            icon = "RIP" if pdata["hp"] <= 0 else "LIVE"
            status_text += f"{icon} {pdata['name']}: HP {pdata['hp']} / MP {pdata['mp']} / {pdata['money']}\n"
        
        embed.add_field(name="ステータス", value=status_text)
        
        view = TurnControlView(p_id, player, game, channel, new_id)
        # メンションを付けてパネルを送信
        await channel.send(content=f"<@{p_id}> ターンが回ってきました。", embed=embed, view=view)

    async def trigger_defense_phase(self, channel, attacker, target_id, attack_card):
        game = self.games[channel.id]
        target_name = game["players"][target_id]["name"]
        
        attacker["mp"] -= attack_card.mp_cost
        
        await channel.send(f"{attacker['name']} -> {target_name} : {attack_card.name}(威力:{attack_card.value})")
        
        view = DefensePromptView(attacker, target_id, attack_card, game, channel)
        await channel.send(f"<@{target_id}> 防御選択してください。", view=view)

    async def resolve_damage(self, channel, attacker, target, atk_card, def_card):
        damage = atk_card.value
        def_msg = "無防備"
        
        if def_card:
            def_msg = f"{def_card.name}防御"
            if def_card.attr == atk_card.attr or def_card.attr == "PHYSICAL" or atk_card.attr == "NONE":
                damage = max(0, damage - def_card.value)
        
        target["hp"] -= damage
        
        msg = f"{target['name']} : {def_msg} -> {damage}ダメージを受けた (残HP: {max(0, target['hp'])})"
        if target["hp"] <= 0:
            msg += f"\n{target['name']}が昇天しました。"
        
        await channel.send(msg)
        await self.process_turn_end(channel)

    async def process_turn_end(self, channel):
        if channel.id not in self.games: return
        game = self.games[channel.id]
        
        alive_ids = [pid for pid, pdata in game["players"].items() if pdata["hp"] > 0]
        if len(alive_ids) <= 1:
            winner = game["players"][alive_ids[0]]["name"] if alive_ids else "なし"
            await channel.send(f"ゲーム終了。勝者: {winner}")
            del self.games[channel.id]
            return

        game["current_index"] = (game["current_index"] + 1) % len(game["turn_order"])
        while game["players"][game["turn_order"][game["current_index"]]]["hp"] <= 0:
            game["current_index"] = (game["current_index"] + 1) % len(game["turn_order"])
        
        await asyncio.sleep(1)
        await self.send_turn_panel(channel)

async def setup(bot):
    await bot.add_cog(GodField(bot))