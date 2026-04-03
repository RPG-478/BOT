import discord
from discord.ext import commands
import asyncio
import random
import uuid

# --- カード定義 ---
class Card:
    def __init__(self, name, category, attr, value, mp_cost=0):
        self.name = name
        self.category = category  # "ATTACK", "DEFENSE", "SPECIAL", "MAGIC"
        self.attr = attr          # "PHYSICAL", "FIRE", "WATER", etc.
        self.value = value
        self.mp_cost = mp_cost

# テスト用カードセット
TEST_CARDS = [
    Card("ファイアボール", "MAGIC", "FIRE", 15, mp_cost=5),
    Card("木の棒", "ATTACK", "PHYSICAL", 5),
    Card("革の盾", "DEFENSE", "PHYSICAL", 8)
]

# --- UI コンポーネント ---

class JoinView(discord.ui.View):
    """参加受付用ビュー"""
    def __init__(self, timeout):
        super().__init__(timeout=timeout)
        self.joined_users = []

    @discord.ui.button(label="参戦する", style=discord.ButtonStyle.green)
    async def join(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user not in self.joined_users:
            self.joined_users.append(interaction.user)
            await interaction.response.send_message(f"{interaction.user.display_name} が預言者として登録されました。", ephemeral=True)
        else:
            await interaction.response.send_message("既に登録されています。", ephemeral=True)

class ActionSelect(discord.ui.Select):
    """手札から行動を選択するセレクトメニュー"""
    def __init__(self, player, game_state, channel):
        self.player = player
        self.game_state = game_state
        self.channel = channel
        
        # 魔法カードの場合、MP不足なら選択肢に入れない等の制御が可能
        options = []
        for i, card in enumerate(player["hand"]):
            label = f"{card.name} ({card.category})"
            desc = f"威力:{card.value} " + (f"消費MP:{card.mp_cost}" if card.mp_cost > 0 else "")
            options.append(discord.SelectOption(label=label, value=str(i), description=desc))
        
        # 攻撃カードがない場合の「祈る」の代わり（今回はシンプルに常に表示も可）
        if not options:
            options.append(discord.SelectOption(label="祈る", value="pray", description="何も持たずに天に祈ります"))

        super().__init__(placeholder="行動を選んでください", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        if self.values[0] == "pray":
            await interaction.response.send_message("天に祈りました。（何も起きなかった...）", ephemeral=True)
            return await self.game_state["cog"].process_turn_end(self.channel)

        card_idx = int(self.values[0])
        card = self.player["hand"][card_idx]

        if card.category in ["ATTACK", "MAGIC"]:
            if self.player["mp"] < card.mp_cost:
                return await interaction.response.send_message("MPが足りません！", ephemeral=True)
            
            # ターゲット選択へ
            view = TargetSelectView(self.player, card, self.game_state, self.channel)
            await interaction.response.send_message(f"【{card.name}】の対象を選んでください：", view=view, ephemeral=True)
        else:
            await interaction.response.send_message("このフェーズでは攻撃または魔法カードのみ選択可能です。", ephemeral=True)

class TargetSelectView(discord.ui.View):
    """攻撃対象を選択するビュー"""
    def __init__(self, attacker, card, game_state, channel):
        super().__init__(timeout=60)
        self.attacker = attacker
        self.card = card
        self.game_state = game_state
        self.channel = channel

        for p_id, p_data in game_state["players"].items():
            if p_id != attacker["id"] and p_data["hp"] > 0:
                btn = discord.ui.Button(label=f"{p_data['name']} を狙う", style=discord.ButtonStyle.danger)
                btn.callback = self.make_callback(p_id)
                self.add_item(btn)

    def make_callback(self, target_id):
        async def callback(interaction: discord.Interaction):
            await interaction.response.send_message(f"{self.game_state['players'][target_id]['name']} への攻撃を確定しました。", ephemeral=True)
            await self.game_state["cog"].trigger_defense_phase(self.channel, self.attacker, target_id, self.card)
        return callback

class DefenseView(discord.ui.View):
    """ターゲットに表示される防御開始ボタン"""
    def __init__(self, attacker, target_id, card, game_state, channel):
        super().__init__(timeout=20)
        self.attacker = attacker
        self.target_id = target_id
        self.card = card
        self.game_state = game_state
        self.channel = channel

    @discord.ui.button(label="防御行動をとる！", style=discord.ButtonStyle.primary)
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
                def_card = player["hand"][int(select.values[0])]
                player["hand"].pop(int(select.values[0])) # 消費
            
            await inter.response.send_message("防御行動を決定しました。", ephemeral=True)
            await self.game_state["cog"].resolve_damage(self.channel, self.attacker, player, self.card, def_card)

        select.callback = select_callback
        view.add_item(select)
        await interaction.response.send_message("手札から防御カードを選んでください：", view=view, ephemeral=True)

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
        embed = discord.Embed(title="🙏 ゴッドフィールド：預言者集結", description=f"ボタンを押して参加してください。\n開始まで残り {wait_time} 秒...", color=0xffd700)
        msg = await ctx.send(embed=embed, view=view)

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

        await ctx.send("⚡ 戦いの火蓋が切って落とされた！")
        await self.send_turn_panel(ctx.channel)

    async def send_turn_panel(self, channel):
        game = self.games[channel.id]
        p_id = game["turn_order"][game["current_index"]]
        player = game["players"][p_id]

        embed = discord.Embed(title=f"🔯 {player['name']} のターン", color=0x3498db)
        status_text = ""
        for pid, pdata in game["players"].items():
            status_text += f"👤 **{pdata['name']}**: HP {pdata['hp']} / MP {pdata['p_mp' if 'p_mp' in pdata else 'mp']} / 💰 {pdata['money']}\n"
        
        embed.add_field(name="生存者ステータス", value=status_text)
        
        view = discord.ui.View(timeout=None)
        btn = discord.ui.button(label="自分の行動を選択", style=discord.ButtonStyle.primary)
        
        async def btn_callback(interaction: discord.Interaction):
            if interaction.user.id != p_id:
                return await interaction.response.send_message("あなたのターンではありません。", ephemeral=True)
            
            action_view = discord.ui.View()
            action_view.add_item(ActionSelect(player, game, channel))
            await interaction.response.send_message("天啓を受けよ。手札を表示します：", view=action_view, ephemeral=True)

        btn.callback = btn_callback
        view.add_item(btn)
        await channel.send(embed=embed, view=view)

    async def trigger_defense_phase(self, channel, attacker, target_id, attack_card):
        game = self.games[channel.id]
        target_name = game["players"][target_id]["name"]
        
        await channel.send(f"⚠️ **{target_name}** に攻撃が迫っている！ ({attacker['name']} の {attack_card.name})")
        
        # ターゲットに防御用パネルを送信
        view = DefenseView(attacker, target_id, attack_card, game, channel)
        await channel.send(f"<@{target_id}> 防御してください！", view=view)

    async def resolve_damage(self, channel, attacker, target, atk_card, def_card):
        # MP消費
        attacker["mp"] -= atk_card.mp_cost
        
        # ダメージ計算
        damage = atk_card.value
        if def_card:
            # 属性が一致するか、物理防御の場合ダメージ軽減
            if def_card.attr == atk_card.attr or def_card.attr == "PHYSICAL":
                damage = max(0, damage - def_card.value)
        
        target["hp"] -= damage
        
        # 手札から使用した攻撃カードを削除
        if atk_card in attacker["hand"]:
            attacker["hand"].remove(atk_card)
            attacker["hand"].append(random.choice(TEST_CARDS)) # 補充

        res_embed = discord.Embed(title="💥 決着", color=0xe74c3c)
        res_text = f"{attacker['name']} の攻撃！\n{target['name']} は {damage} のダメージを受けた！"
        if target["hp"] <= 0:
            res_text += f"\n💀 **{target['name']} は昇天した...**"
        
        res_embed.description = res_text
        await channel.send(embed=res_embed)
        
        await self.process_turn_end(channel)

    async def process_turn_end(self, channel):
        game = self.games[channel.id]
        
        # 生存チェック
        alive_players = [pid for pid, pdata in game["players"].items() if pdata["hp"] > 0]
        if len(alive_players) <= 1:
            winner_name = game["players"][alive_players[0]]["name"] if alive_players else "なし"
            await channel.send(f"🏆 試合終了！勝者: **{winner_name}**")
            del self.games[channel.id]
            return

        # ターンを進める
        game["current_index"] = (game["current_index"] + 1) % len(game["turn_order"])
        # 次の生存者まで飛ばす
        while game["players"][game["turn_order"][game["current_index"]]]["hp"] <= 0:
            game["current_index"] = (game["current_index"] + 1) % len(game["turn_order"])
        
        await self.send_turn_panel(channel)

async def setup(bot):
    await bot.add_cog(GodField(bot))

