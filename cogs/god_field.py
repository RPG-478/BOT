import discord
from discord.ext import commands
import asyncio
import random

# --- カードクラス定義 ---
class Card:
    def __init__(self, name, category, attr, value, mp_cost=0, price=0, description=""):
        self.name = name
        self.category = category  # "ATTACK", "DEFENSE", "SPECIAL", "MAGIC"
        self.attr = attr          # "PHYSICAL", "FIRE", "WATER", "NONE"
        self.value = value        # 威力、防御力、回復量など
        self.mp_cost = mp_cost
        self.price = price        # 売却価格/価値
        self.description = description

# テスト用・検証用カードセット
TEST_CARDS = [
    Card("ファイアボール", "MAGIC", "FIRE", 15, mp_cost=5, price=10, description="火球を放つ初級魔法"),
    Card("木の棒", "ATTACK", "PHYSICAL", 5, price=1, description="ただの木の棒"),
    Card("革の盾", "DEFENSE", "PHYSICAL", 8, price=2, description="革製の粗末な盾"),
    Card("HP回復薬(仮)", "SPECIAL", "HEAL_HP", 15, price=5, description="HPを15回復する"),
    Card("MP回復薬(仮)", "SPECIAL", "HEAL_MP", 10, price=5, description="MPを10回復する"),
    Card("バチェット", "ATTACK", "NONE", 4, price=3, description="扱いやすい小型の斧")
]

# --- UI コンポーネント ---

class JoinView(discord.ui.View):
    """参加受付用ビュー"""
    def __init__(self, timeout):
        super().__init__(timeout=timeout)
        self.joined_users = []

    @discord.ui.button(label="参戦する", style=discord.ButtonStyle.green)
    async def join(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user not in [u.id for u in self.joined_users]:
            self.joined_users.append(interaction.user)
            await interaction.response.send_message(f"{interaction.user.display_name} が預言者として登録されました。", ephemeral=True)
        else:
            await interaction.response.send_message("既に登録されています。", ephemeral=True)

class HandActionView(discord.ui.View):
    """手札操作のメインView (エフェメラル)"""
    def __init__(self, player, game_state, channel):
        super().__init__(timeout=60)
        self.player = player
        self.game_state = game_state
        self.channel = channel

        # セレクトメニューを手動で追加
        self.add_item(ActionSelect(player, game_state, channel))

class ActionSelect(discord.ui.Select):
    """手札から行動を選択するセレクトメニュー"""
    def __init__(self, player, game_state, channel):
        self.player = player
        self.game_state = game_state
        self.channel = channel
        
        options = []
        for i, card in enumerate(player["hand"]):
            label = f"{card.name} (売:{card.price}円)"
            desc = f"[{card.category}] {card.description}"
            options.append(discord.SelectOption(label=label, value=str(i), description=desc))
        
        if not options:
            options.append(discord.SelectOption(label="祈る", value="pray", description="何も持たずに天に祈ります"))

        super().__init__(placeholder="使用するカードを選んでください", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        if self.values[0] == "pray":
            await interaction.response.send_message("天に祈りました。（何も起きなかった...）", ephemeral=True)
            return await self.game_state["cog"].process_turn_end(self.channel)

        card_idx = int(self.values[0])
        card = self.player["hand"][card_idx]

        # 1. 魔法カードのMPチェック
        if card.category == "MAGIC" and self.player["mp"] < card.mp_cost:
            return await interaction.response.send_message("MPが足りません！", ephemeral=True)

        # 2. 回復アイテムなどの特殊カード処理
        if card.category == "SPECIAL":
            self.player["hand"].pop(card_idx)
            self.player["hand"].append(random.choice(TEST_CARDS)) # 補充
            
            msg = ""
            if card.attr == "HEAL_HP":
                self.player["hp"] = min(40, self.player["hp"] + card.value)
                msg = f"{card.name}を使用！HPが{card.value}回復した！"
            elif card.attr == "HEAL_MP":
                self.player["mp"] += card.value
                msg = f"{card.name}を使用！MPが{card.value}回復した！"
            
            await interaction.response.send_message(msg, ephemeral=True)
            await self.channel.send(f"🧪 **{self.player['name']}** は {card.name} を使った。")
            return await self.game_state["cog"].process_turn_end(self.channel)

        # 3. 攻撃・魔法のターゲット選択
        if card.category in ["ATTACK", "MAGIC"]:
            view = TargetSelectView(self.player, card, card_idx, self.game_state, self.channel)
            await interaction.response.send_message(f"【{card.name}】の対象を選んでください：", view=view, ephemeral=True)
        else:
            await interaction.response.send_message("防御カードは相手のターンに使用します。", ephemeral=True)

class TargetSelectView(discord.ui.View):
    """攻撃対象を選択するビュー"""
    def __init__(self, attacker, card, card_idx, game_state, channel):
        super().__init__(timeout=60)
        self.attacker = attacker
        self.card = card
        self.card_idx = card_idx
        self.game_state = game_state
        self.channel = channel

        for p_id, p_data in game_state["players"].items():
            if p_id != attacker["id"] and p_data["hp"] > 0:
                btn = discord.ui.Button(label=f"{p_data['name']} (HP:{p_data['hp']})", style=discord.ButtonStyle.danger)
                btn.callback = self.make_callback(p_id)
                self.add_item(btn)

    def make_callback(self, target_id):
        async def callback(interaction: discord.Interaction):
            await interaction.response.send_message(f"{self.game_state['players'][target_id]['name']} への攻撃を確定しました。", ephemeral=True)
            # 手札から消費
            self.attacker["hand"].pop(self.card_idx)
            self.attacker["hand"].append(random.choice(TEST_CARDS))
            
            await self.game_state["cog"].trigger_defense_phase(self.channel, self.attacker, target_id, self.card)
        return callback

class TurnControlView(discord.ui.View):
    """メインパネルに表示される「行動ボタン」"""
    def __init__(self, current_p_id, player, game, channel):
        super().__init__(timeout=None)
        self.current_p_id = current_p_id
        self.player = player
        self.game = game
        self.channel = channel

    @discord.ui.button(label="自分の行動を選択", style=discord.ButtonStyle.primary, custom_id="gf_action_btn")
    async def action_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.current_p_id:
            return await interaction.response.send_message("あなたのターンではありません。", ephemeral=True)
        
        view = HandActionView(self.player, self.game, self.channel)
        await interaction.response.send_message("天啓を受けよ。手札を表示します：", view=view, ephemeral=True)

class DefensePromptView(discord.ui.View):
    """ターゲットに表示される防御開始ボタン"""
    def __init__(self, attacker, target_id, card, game_state, channel):
        super().__init__(timeout=30)
        self.attacker = attacker
        self.target_id = target_id
        self.card = card
        self.game_state = game_state
        self.channel = channel

    @discord.ui.button(label="防御カードを選択", style=discord.ButtonStyle.success)
    async def open_defense(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.target_id:
            return await interaction.response.send_message("あなたへの攻撃ではありません。", ephemeral=True)
        
        player = self.game_state["players"][self.target_id]
        options = [discord.SelectOption(label="無防備（何もしない）", value="none")]
        for i, c in enumerate(player["hand"]):
            if c.category == "DEFENSE":
                options.append(discord.SelectOption(label=f"{c.name} (防御:{c.value})", value=str(i)))
        
        view = discord.ui.View()
        select = discord.ui.Select(placeholder="防御カードを選択", options=options)

        async def select_callback(inter: discord.Interaction):
            def_card = None
            if select.values[0] != "none":
                idx = int(select.values[0])
                def_card = player["hand"][idx]
                player["hand"].pop(idx) # 消費
                player["hand"].append(random.choice(TEST_CARDS)) # 補充
            
            await inter.response.send_message("防御行動を決定しました。", ephemeral=True)
            await self.game_state["cog"].resolve_damage(self.channel, self.attacker, player, self.card, def_card)

        select.callback = select_callback
        view.add_item(select)
        await interaction.response.send_message("手札から防御カードを選んでください：", view=view, ephemeral=True)

    async def on_timeout(self):
        # タイムアウト時は無防備として処理
        player = self.game_state["players"][self.target_id]
        await self.game_state["cog"].resolve_damage(self.channel, self.attacker, player, self.card, None)

# --- Cog メインクラス ---

class GodField(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.games = {}

    @commands.hybrid_command(name="god_field")
    async def god_field(self, ctx, wait_time: int = 60):
        """ゴッドフィールドを開始する"""
        if ctx.channel.id in self.games:
            return await ctx.send("既にこのチャンネルでゲームが進行中です。")

        view = JoinView(timeout=wait_time)
        embed = discord.Embed(title="🙏 ゴッドフィールド：預言者集結", description=f"ボタンを押して参加してください。\n開始まで残り **{wait_time}** 秒...", color=0xffd700)
        await ctx.send(embed=embed, view=view)

        await asyncio.sleep(wait_time)

        if len(view.joined_users) < 2:
            return await ctx.send("預言者が足りません。2人以上の参加が必要です。")

        # ゲーム初期化
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
            "cog": self
        }

        await ctx.send("⚡ **戦いの火蓋が切って落とされた！**")
        await self.send_turn_panel(ctx.channel)

    async def send_turn_panel(self, channel):
        if channel.id not in self.games: return
        game = self.games[channel.id]
        p_id = game["turn_order"][game["current_index"]]
        player = game["players"][p_id]

        embed = discord.Embed(title=f"🔯 {player['name']} のターン", color=0x3498db)
        status_text = ""
        for pid, pdata in game["players"].items():
            icon = "💀" if pdata["hp"] <= 0 else "👤"
            status_text += f"{icon} **{pdata['name']}**: HP {pdata['hp']} / MP {pdata['mp']} / 💰 {pdata['money']}\n"
        
        embed.add_field(name="預言者たちの状態", value=status_text)
        embed.set_footer(text="下のボタンから手札を確認し、行動を選択してください。")
        
        view = TurnControlView(p_id, player, game, channel)
        await channel.send(embed=embed, view=view)

    async def trigger_defense_phase(self, channel, attacker, target_id, attack_card):
        game = self.games[channel.id]
        target_name = game["players"][target_id]["name"]
        
        # MP消費
        attacker["mp"] -= attack_card.mp_cost
        
        await channel.send(f"⚔️ **{attacker['name']}** が **{target_name}** に攻撃！\n使用カード: **{attack_card.name}** (威力:{attack_card.value})")
        
        view = DefensePromptView(attacker, target_id, attack_card, game, channel)
        await channel.send(f"🛡️ <@{target_id}> 防御してください！", view=view)

    async def resolve_damage(self, channel, attacker, target, atk_card, def_card):
        damage = atk_card.value
        def_text = "無防備だ！"
        
        if def_card:
            def_text = f"**{def_card.name}** で防御！"
            # 属性相性（簡易版：物理か同属性なら軽減）
            if def_card.attr == atk_card.attr or def_card.attr == "PHYSICAL" or atk_card.attr == "NONE":
                damage = max(0, damage - def_card.value)
        
        target["hp"] -= damage
        
        res_embed = discord.Embed(title="💥 攻撃結果", color=0xe74c3c)
        res_text = f"{target['name']} は {def_text}\n{damage} のダメージを受けた！ (残りHP: {max(0, target['hp'])})"
        
        if target["hp"] <= 0:
            res_text += f"\n💀 **{target['name']} は昇天した...**"
        
        res_embed.description = res_text
        await channel.send(embed=res_embed)
        
        await self.process_turn_end(channel)

    async def process_turn_end(self, channel):
        if channel.id not in self.games: return
        game = self.games[channel.id]
        
        # 生存チェック
        alive_ids = [pid for pid, pdata in game["players"].items() if pdata["hp"] > 0]
        if len(alive_ids) <= 1:
            winner_name = game["players"][alive_ids[0]]["name"] if alive_ids else "なし"
            await channel.send(f"🏆 **天界の戦いが終わった！**\n勝者: **{winner_name}**")
            del self.games[channel.id]
            return

        # 次の生存プレイヤーへ
        game["current_index"] = (game["current_index"] + 1) % len(game["turn_order"])
        while game["players"][game["turn_order"][game["current_index"]]]["hp"] <= 0:
            game["current_index"] = (game["current_index"] + 1) % len(game["turn_order"])
        
        await asyncio.sleep(2) # 少し間を置く
        await self.send_turn_panel(channel)

async def setup(bot):
    await bot.add_cog(GodField(bot))

