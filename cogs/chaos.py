import discord
from discord.ext import commands
from discord import app_commands
import json
import random
import asyncpg
from config import DATABASE_URL

def generate_modules(floor):
    p_f = 10 * (50 ** ((floor - 1) / 29))
    num_modules = random.randint(1, 5)
    modules = []
    event_types = ["plus", "minus", "buff", "debuff"]
    
    for _ in range(num_modules):
        prob = random.randint(1, 99)
        routes = {}
        for r in ["A", "B"]:
            etype = random.choice(event_types)
            if etype == "plus":
                val = round(random.uniform(1, p_f), 1)
                routes[r] = {"type": "plus", "val": val}
            elif etype == "minus":
                val = round(random.uniform(1, p_f), 1)
                routes[r] = {"type": "minus", "val": val}
            elif etype == "buff":
                btype = random.choice(["resurrection", "chaos_reverse", "chronos", "regen"])
                if btype == "resurrection":
                    routes[r] = {"type": "buff", "id": "resurrection", "turns": random.randint(3, 5)}
                elif btype == "chaos_reverse":
                    routes[r] = {"type": "buff", "id": "chaos_reverse", "turns": random.randint(1, 3)}
                elif btype == "chronos":
                    routes[r] = {"type": "buff", "id": "chronos"}
                elif btype == "regen":
                    routes[r] = {"type": "buff", "id": "regen", "turns": random.randint(2, 5), "val": random.randint(5, 20)}
            elif etype == "debuff":
                routes[r] = {"type": "debuff", "id": "slip", "turns": random.randint(2, 5), "val": random.randint(5, 20)}
        modules.append({"prob": prob, "A": routes["A"], "B": routes["B"]})
    return modules

class ChaosDiveView(discord.ui.View):
    def __init__(self, cog, user_id, rerolls_used):
        super().__init__(timeout=None)
        self.cog = cog
        self.user_id = user_id
        
        reroll_btn = discord.ui.Button(
            label="🎲 振り直す",
            style=discord.ButtonStyle.secondary,
            custom_id=f"chaos_reroll_{user_id}",
            disabled=(rerolls_used >= 3)
        )
        reroll_btn.callback = self.reroll_callback
        self.add_item(reroll_btn)
        
        match_btn = discord.ui.Button(
            label="💥 この条件で勝負する（取る）",
            style=discord.ButtonStyle.primary,
            custom_id=f"chaos_match_{user_id}"
        )
        match_btn.callback = self.match_callback
        self.add_item(match_btn)

    async def reroll_callback(self, interaction: discord.Interaction):
        if str(interaction.user.id) != self.user_id:
            await interaction.response.send_message("他のプレイヤーのゲームです。", ephemeral=True)
            return
            
        async with self.cog.pool.acquire() as conn:
            save = await conn.fetchrow("SELECT * FROM chaos_dive_saves WHERE user_id = $1", self.user_id)
            if not save:
                await interaction.response.send_message("セーブデータが見つかりません。", ephemeral=True)
                return
                
            rerolls = save["rerolls_used"] + 1
            modules = generate_modules(save["current_floor"])
            
            await conn.execute(
                "UPDATE chaos_dive_saves SET rerolls_used = $1, pending_modules = $2 WHERE user_id = $3",
                rerolls, json.dumps(modules), self.user_id
            )
            
            new_save = await conn.fetchrow("SELECT * FROM chaos_dive_saves WHERE user_id = $1", self.user_id)
            await self.cog.show_game_screen(interaction, new_save)

    async def match_callback(self, interaction: discord.Interaction):
        if str(interaction.user.id) != self.user_id:
            await interaction.response.send_message("他のプレイヤーのゲームです。", ephemeral=True)
            return
            
        await interaction.response.defer()
        
        async with self.cog.pool.acquire() as conn:
            save = await conn.fetchrow("SELECT * FROM chaos_dive_saves WHERE user_id = $1", self.user_id)
            if not save:
                await interaction.followup.send("セーブデータが見つかりません。", ephemeral=True)
                return
                
            floor = save["current_floor"]
            bet = save["current_bet"]
            fund = save["current_fund"]
            active_buffs = json.loads(save["active_buffs"])
            pending_modules = json.loads(save["pending_modules"])
            
            buffs_list = active_buffs.get("buffs", [])
            has_reverse = any(b["id"] == "chaos_reverse" for b in buffs_list)
            
            total_pct = 0.0
            new_buffs = []
            chronos_triggered = 0
            log_messages = []
            
            for i, mod in enumerate(pending_modules, 1):
                prob = mod["prob"]
                roll = random.randint(1, 100)
                selected_route = "A" if roll <= prob else "B"
                route_data = mod[selected_route]
                
                log_messages.append(f"モジュール {i}: ルート{selected_route}が選択されました。")
                
                if route_data["type"] == "plus":
                    val = route_data["val"]
                    if has_reverse:
                        total_pct -= val
                        log_messages.append(f"  軍資金 +{val}% -> 反転により -{val}%")
                    else:
                        total_pct += val
                        log_messages.append(f"  軍資金 +{val}%")
                elif route_data["type"] == "minus":
                    val = route_data["val"]
                    if has_reverse:
                        total_pct += val
                        log_messages.append(f"  軍資金 -{val}% -> 反転により +{val}%")
                    else:
                        total_pct -= val
                        log_messages.append(f"  軍資金 -{val}%")
                elif route_data["type"] == "buff":
                    if route_data["id"] == "chronos":
                        chronos_triggered += random.randint(1, 3)
                        log_messages.append("  ⏳ 継続ターンプラスを獲得")
                    else:
                        b_names = {"resurrection": "確定回避", "chaos_reverse": "損得の反転", "regen": "定期報酬"}
                        new_buffs.append({
                            "id": route_data["id"],
                            "name": b_names[route_data["id"]],
                            "remaining_turns": route_data.get("turns", 1),
                            "val": route_data.get("val", 0)
                        })
                        b_emojis = {"resurrection": "🛡️ 確定回避", "chaos_reverse": "🌀 損得の反転", "regen": "💰 定期報酬"}
                        log_messages.append(f"  {b_emojis[route_data['id']]} を獲得")
                elif route_data["type"] == "debuff":
                    new_buffs.append({
                        "id": route_data["id"],
                        "name": "定期マイナス",
                        "remaining_turns": route_data.get("turns", 1),
                        "val": route_data.get("val", 0)
                    })
                    log_messages.append("  💀 定期マイナス を獲得")
            
            fund_change = int(fund * (total_pct / 100))
            fund += fund_change
            log_messages.append(f"モジュール抽選結果による変動: {fund_change:+,} コイン (累計: {total_pct:+.1f}%)")
            
            for b in buffs_list:
                if b["id"] == "regen":
                    regen_val = int(fund * (b["val"] / 100))
                    fund += regen_val
                    log_messages.append(f"💰 定期報酬による変動: +{regen_val} コイン (+{b['val']}%)")
                elif b["id"] == "slip":
                    slip_val = int(fund * (b["val"] / 100))
                    fund -= slip_val
                    log_messages.append(f"💀 定期マイナスによる変動: -{slip_val} コイン (-{b['val']}%)")
            
            if chronos_triggered > 0:
                for b in buffs_list:
                    b["remaining_turns"] += chronos_triggered
                log_messages.append(f"⏳ クロノス・ブースト発動: 既存バフの持続ターンが +{chronos_triggered} されました。")
            
            for nb in new_buffs:
                match_found = False
                for ob in buffs_list:
                    if ob["id"] == nb["id"] and ob.get("val", 0) == nb.get("val", 0):
                        ob["remaining_turns"] += nb["remaining_turns"]
                        match_found = True
                        break
                if not match_found:
                    buffs_list.append(nb)
            
            if fund <= 0:
                res_buff = next((b for b in buffs_list if b["id"] == "resurrection"), None)
                if res_buff:
                    fund = 1
                    res_buff["remaining_turns"] -= 1
                    if res_buff["remaining_turns"] <= 0:
                        buffs_list.remove(res_buff)
                    log_messages.append("🛡️ 確定回避（リザレクション）が発動しました。軍資金1で耐えます。")
            
            if fund <= 0:
                await conn.execute("DELETE FROM chaos_dive_saves WHERE user_id = $1", self.user_id)
                embed_result = discord.Embed(title="ゲームオーバー（破産）", color=discord.Color.red())
                embed_result.description = "\n".join(log_messages) + f"\n\n軍資金が0以下になりました。賭け金 {bet:,} コインは没収されました。"
                await interaction.followup.send(embed=embed_result)
                return
                
            if floor == 30:
                async with conn.transaction():
                    await conn.execute("DELETE FROM chaos_dive_saves WHERE user_id = $1", self.user_id)
                    await conn.execute(
                        "INSERT INTO users (user_id, balance) VALUES ($1, $2) ON CONFLICT (user_id) DO UPDATE SET balance = users.balance + $2",
                        self.user_id, fund
                    )
                    await conn.execute(
                        "INSERT INTO transaction_history (sender_id, receiver_id, amount, reason) VALUES ($1, $2, $3, $4)",
                        "SYSTEM", self.user_id, fund, "カオス・ダイブ生還報酬"
                    )
                embed_result = discord.Embed(title="最下層クリア！生還成功", color=discord.Color.gold())
                embed_result.description = "\n".join(log_messages) + f"\n\n地下30階をクリアしました。現在の軍資金 {fund:,} コインが払い戻されます。"
                await interaction.followup.send(embed=embed_result)
                return
                
            next_floor = floor + 1
            for b in list(buffs_list):
                b["remaining_turns"] -= 1
                if b["remaining_turns"] <= 0:
                    buffs_list.remove(b)
            
            next_modules = generate_modules(next_floor)
            active_buffs["buffs"] = buffs_list
            
            await conn.execute(
                """
                UPDATE chaos_dive_saves 
                SET current_floor = $1, current_fund = $2, active_buffs = $3, rerolls_used = 0, pending_modules = $4 
                WHERE user_id = $5
                """,
                next_floor, fund, json.dumps(active_buffs), json.dumps(next_modules), self.user_id
            )
            
            embed_log = discord.Embed(title=f"B{floor}F 結果", color=discord.Color.green())
            embed_log.description = "\n".join(log_messages) + f"\n\n次の階層 B{next_floor}F へ進みます。"
            await interaction.followup.send(embed=embed_log)
            
            next_save = await conn.fetchrow("SELECT * FROM chaos_dive_saves WHERE user_id = $1", self.user_id)
            await self.cog.show_game_screen(interaction, next_save)

class ChaosDive(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.pool = None

    async def cog_load(self):
        self.pool = await asyncpg.create_pool(DATABASE_URL)

    async def cog_unload(self):
        if self.pool:
            await self.pool.close()

    @app_commands.command(name="chaos_dive", description="カオス・ダイブを開始または再開します")
    @app_commands.describe(bet="初期賭け金（新規開始時のみ必要）")
    async def chaos_dive(self, interaction: discord.Interaction, bet: int = None):
        user_id = str(interaction.user.id)
        
        async with self.pool.acquire() as conn:
            save = await conn.fetchrow("SELECT * FROM chaos_dive_saves WHERE user_id = $1", user_id)
            if save:
                await self.show_game_screen(interaction, save)
                return
            
            if bet is None or bet <= 0:
                await interaction.response.send_message("新しくゲームを開始するには、1以上の賭け金を指定してください。", ephemeral=True)
                return
                
            user = await conn.fetchrow("SELECT balance FROM users WHERE user_id = $1", user_id)
            balance = user["balance"] if user else 0
            
            if balance < bet:
                await interaction.response.send_message(f"コインが不足しています。現在の残高: {balance}", ephemeral=True)
                return
                
            async with conn.transaction():
                await conn.execute("UPDATE users SET balance = balance - $1 WHERE user_id = $2", bet, user_id)
                await conn.execute(
                    "INSERT INTO transaction_history (sender_id, receiver_id, amount, reason) VALUES ($1, $2, $3, $4)",
                    user_id, "SYSTEM", bet, "カオス・ダイブ賭け金"
                )
                modules = generate_modules(1)
                await conn.execute(
                    """
                    INSERT INTO chaos_dive_saves (user_id, current_floor, current_bet, current_fund, active_buffs, rerolls_used, pending_modules)
                    VALUES ($1, 1, $2, $3, $4, 0, $5)
                    """,
                    user_id, bet, bet, json.dumps({"buffs": []}), json.dumps(modules)
                )
            
            new_save = await conn.fetchrow("SELECT * FROM chaos_dive_saves WHERE user_id = $1", user_id)
            await self.show_game_screen(interaction, new_save)

    async def show_game_screen(self, interaction: discord.Interaction, save):
        user_id = save["user_id"]
        floor = save["current_floor"]
        bet = save["current_bet"]
        fund = save["current_fund"]
        active_buffs = json.loads(save["active_buffs"])
        rerolls_used = save["rerolls_used"]
        pending_modules = json.loads(save["pending_modules"])
        
        buffs_list = active_buffs.get("buffs", [])
        has_reverse = any(b["id"] == "chaos_reverse" for b in buffs_list)
        
        embed = discord.Embed(title=f"B{floor}F - カオス・ダイブ", color=discord.Color.purple())
        
        bar_cells = 30
        bar_str = "■" * floor + "□" * (bar_cells - floor)
        
        desc = f"現在の軍資金: {fund:,} コイン (初期賭け金: {bet:,})\n"
        desc += f"進行状況: [{bar_str}] ({floor}/30)\n\n"
        desc += "【あなたのステータス】\n"
        
        if not buffs_list:
            desc += "・なし\n"
        for b in buffs_list:
            if b["id"] == "chaos_reverse":
                desc += f"・🌀 損得の反転 (残り {b['remaining_turns']} 階層)\n"
            elif b["id"] == "resurrection":
                desc += f"・🛡️ 確定回避 (残り {b['remaining_turns']} 階層)\n"
            elif b["id"] == "regen":
                desc += f"・💰 定期報酬 (残り {b['remaining_turns']} 階層: 毎階層 +{b['val']}%)\n"
            elif b["id"] == "slip":
                desc += f"・💀 定期マイナス (残り {b['remaining_turns']} 階層: 毎階層 -{b['val']}%)\n"
                
        desc += f"\n--------------------------------------------\n【現在の提示条件】(振り直し回数: {rerolls_used} / 3)\n"
        if has_reverse:
            desc += "※損得反転適用中！プラスとマイナスが逆転します。\n"
            
        for i, mod in enumerate(pending_modules, 1):
            desc += f"[モジュール {i}]\n"
            for r in ["A", "B"]:
                route = mod[r]
                prob = mod["prob"] if r == "A" else (100 - mod["prob"])
                prefix = f"├─ 🔴 ルートA ({prob}%)" if r == "A" else f"└─ 🔵 ルートB ({prob}%)"
                
                details = []
                if route["type"] == "plus":
                    orig = f"+{route['val']}%"
                    rev = f"-{route['val']}%" if has_reverse else None
                    details.append(f"軍資金 {orig}" + (f" (逆転: {rev})" if rev else ""))
                elif route["type"] == "minus":
                    orig = f"-{route['val']}%"
                    rev = f"+{route['val']}%" if has_reverse else None
                    details.append(f"軍資金 {orig}" + (f" (逆転: {rev})" if rev else ""))
                elif route["type"] == "buff":
                    b_name = {"resurrection": "🛡️ 確定回避", "chaos_reverse": "🌀 損得の反転", "chronos": "⏳ 継続ターンプラス", "regen": "💰 定期報酬"}[route["id"]]
                    details.append(f"[{b_name}]獲得")
                elif route["type"] == "debuff":
                    details.append("[💀 定期マイナス]獲得")
                    
                desc += f"{prefix}: " + " + ".join(details) + "\n"
                
        embed.description = desc
        view = ChaosDiveView(self, user_id, rerolls_used)
        
        if interaction.response.is_done():
            await interaction.edit_original_response(embed=embed, view=view)
        else:
            await interaction.response.send_message(embed=embed, view=view)

async def setup(bot):
    await bot.add_cog(ChaosDive(bot))
