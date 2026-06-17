import discord
from discord.ext import commands
from discord import app_commands
import json
import random
import asyncio
import config

def generate_modules(floor):
    p_f = 10 * (50 ** ((floor - 1) / 19))
    num_modules = random.randint(1, 3)
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

class ChaosDiveNextView(discord.ui.View):
    def __init__(self, cog, user_id):
        super().__init__(timeout=None)
        self.cog = cog
        self.user_id = user_id
        
        next_btn = discord.ui.Button(
            label="次の運命を開く",
            style=discord.ButtonStyle.success,
            custom_id=f"chaos_next_{user_id}"
        )
        next_btn.callback = self.next_callback
        self.add_item(next_btn)

    async def next_callback(self, interaction: discord.Interaction):
        if str(interaction.user.id) != self.user_id:
            await interaction.response.send_message("他のプレイヤーのゲームです。", ephemeral=True)
            return
            
        await interaction.response.defer()
        
        try:
            await interaction.message.delete()
        except discord.HTTPException:
            pass
            
        res = await asyncio.to_thread(config.supabase.table("chaos_dive_saves").select("*").eq("user_id", self.user_id).execute)
        save = res.data[0] if res.data else None
        if not save:
            await interaction.followup.send("セーブデータが見つかりません。", ephemeral=True)
            return
            
        await self.cog.show_game_screen(interaction, save)

class ChaosDiveView(discord.ui.View):
    def __init__(self, cog, user_id, rerolls_used):
        super().__init__(timeout=None)
        self.cog = cog
        self.user_id = user_id
        
        reroll_btn = discord.ui.Button(
            label="振り直す",
            style=discord.ButtonStyle.secondary,
            custom_id=f"chaos_reroll_{user_id}",
            disabled=(rerolls_used >= 3)
        )
        reroll_btn.callback = self.reroll_callback
        self.add_item(reroll_btn)
        
        match_btn = discord.ui.Button(
            label="この条件で勝負する（取る）",
            style=discord.ButtonStyle.primary,
            custom_id=f"chaos_match_{user_id}"
        )
        match_btn.callback = self.match_callback
        self.add_item(match_btn)

    async def reroll_callback(self, interaction: discord.Interaction):
        if str(interaction.user.id) != self.user_id:
            await interaction.response.send_message("他のプレイヤーのゲームです。", ephemeral=True)
            return
            
        await interaction.response.defer()
        
        res = await asyncio.to_thread(config.supabase.table("chaos_dive_saves").select("*").eq("user_id", self.user_id).execute)
        save = res.data[0] if res.data else None
        if not save:
            await interaction.followup.send("セーブデータが見つかりません。", ephemeral=True)
            return
            
        rerolls = save["rerolls_used"] + 1
        modules = generate_modules(save["current_floor"])
        
        await asyncio.to_thread(
            config.supabase.table("chaos_dive_saves")
            .update({"rerolls_used": rerolls, "pending_modules": modules})
            .eq("user_id", self.user_id)
            .execute
        )
        
        try:
            await interaction.message.delete()
        except discord.HTTPException:
            pass
            
        res_new = await asyncio.to_thread(config.supabase.table("chaos_dive_saves").select("*").eq("user_id", self.user_id).execute)
        await self.cog.show_game_screen(interaction, res_new.data[0])

    async def match_callback(self, interaction: discord.Interaction):
        if str(interaction.user.id) != self.user_id:
            await interaction.response.send_message("他のプレイヤーのゲームです。", ephemeral=True)
            return
            
        await interaction.response.defer()
        
        res = await asyncio.to_thread(config.supabase.table("chaos_dive_saves").select("*").eq("user_id", self.user_id).execute)
        save = res.data[0] if res.data else None
        if not save:
            await interaction.followup.send("セーブデータが見つかりません。", ephemeral=True)
            return
            
        floor = save["current_floor"]
        bet = save["current_bet"]
        fund = save["current_fund"]
        
        active_buffs = save["active_buffs"]
        if isinstance(active_buffs, str):
            active_buffs = json.loads(active_buffs)
            
        pending_modules = save["pending_modules"]
        if isinstance(pending_modules, str):
            pending_modules = json.loads(pending_modules)
        
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
            
            if route_data["type"] == "plus":
                val = route_data["val"]
                if has_reverse:
                    total_pct -= val
                    log_messages.append(f"運命 {i}: 命値 -{val}% (ルート{selected_route} / 堕天反転)")
                else:
                    total_pct += val
                    log_messages.append(f"運命 {i}: 命値 +{val}% (ルート{selected_route})")
            elif route_data["type"] == "minus":
                val = route_data["val"]
                if has_reverse:
                    total_pct += val
                    log_messages.append(f"運命 {i}: 命値 +{val}% (ルート{selected_route} / 堕天反転)")
                else:
                    total_pct -= val
                    log_messages.append(f"運命 {i}: 命値 -{val}% (ルート{selected_route})")
            elif route_data["type"] == "buff":
                if route_data["id"] == "chronos":
                    chronos_triggered += random.randint(1, 3)
                    log_messages.append(f"運命 {i}: アクション [継続ターンプラス] を獲得 (ルート{selected_route})")
                else:
                    b_names = {"resurrection": "命乞い", "chaos_reverse": "堕天", "regen": "天啓"}
                    new_buffs.append({
                        "id": route_data["id"],
                        "name": b_names[route_data["id"]],
                        "remaining_turns": route_data.get("turns", 1),
                        "val": route_data.get("val", 0)
                    })
                    log_messages.append(f"運命 {i}: アクション [{b_names[route_data['id']]}] を獲得 (ルート{selected_route})")
            elif route_data["type"] == "debuff":
                new_buffs.append({
                    "id": route_data["id"],
                    "name": "罰",
                    "remaining_turns": route_data.get("turns", 1),
                    "val": route_data.get("val", 0)
                })
                log_messages.append(f"運命 {i}: アクション [罰] を獲得 (ルート{selected_route})")
        
        fund_change = int(fund * (total_pct / 100))
        fund += fund_change
        log_messages.append(f"運命抽選結果による変動: {fund_change:+,} コイン (累計: {total_pct:+.1f}%)")
        
        for b in buffs_list:
            if b["id"] == "regen":
                regen_val = int(fund * (b["val"] / 100))
                fund += regen_val
                log_messages.append(f"天啓による変動: +{regen_val} コイン (+{b['val']}%)")
            elif b["id"] == "slip":
                slip_val = int(fund * (b["val"] / 100))
                fund -= slip_val
                log_messages.append(f"罰による変動: -{slip_val} コイン (-{b['val']}%)")
        
        if chronos_triggered > 0:
            for b in buffs_list:
                b["remaining_turns"] += chronos_triggered
            log_messages.append(f"クロノス・ブースト発動: 既存バフの持続ターンが +{chronos_triggered} されました。")
        
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
                log_messages.append("命乞いが発動しました。命値1で耐えます。")
        
        try:
            await interaction.message.delete()
        except discord.HTTPException:
            pass
            
        if fund <= 0:
            await asyncio.to_thread(config.supabase.table("chaos_dive_saves").delete().eq("user_id", self.user_id).execute)
            net_change = -bet
            embed_result = discord.Embed(title="ゲームオーバー（破産）", color=0xffffff)
            embed_result.description = "\n".join(log_messages) + f"\n\n命値が0以下になりました。賭け金 {bet:,} コインは没収されました。\n最終損益: {net_change:,} コイン"
            await interaction.channel.send(embed=embed_result)
            return
            
        if floor == 20:
            await asyncio.to_thread(config.supabase.table("chaos_dive_saves").delete().eq("user_id", self.user_id).execute)
            res_user = await asyncio.to_thread(config.supabase.table("users").select("balance").eq("user_id", self.user_id).execute)
            current_balance = res_user.data[0]["balance"] if res_user.data else 0
            
            clear_bonus = 1000
            total_payout = fund + clear_bonus
            net_change = total_payout - bet
            
            await asyncio.to_thread(config.supabase.table("users").upsert({"user_id": self.user_id, "balance": current_balance + total_payout}).execute)
            await asyncio.to_thread(config.supabase.table("transaction_history").insert({
                "sender_id": "SYSTEM",
                "receiver_id": self.user_id,
                "amount": total_payout,
                "reason": "カオス・ダイブ生還報酬"
            }).execute)
            
            embed_result = discord.Embed(title="最下層クリア！生還成功", color=0xffffff)
            embed_result.description = "\n".join(log_messages) + f"\n\n地下20階をクリアしました。現在の命値 {fund:,} コインにクリア報酬 {clear_bonus:,} コインを加えた、計 {total_payout:,} コインが払い戻されます。\n最終損益: {net_change:+,} コイン"
            await interaction.channel.send(embed=embed_result)
            return
            
        next_floor = floor + 1
        for b in list(buffs_list):
            b["remaining_turns"] -= 1
            if b["remaining_turns"] <= 0:
                buffs_list.remove(b)
        
        next_modules = generate_modules(next_floor)
        active_buffs["buffs"] = buffs_list
        
        await asyncio.to_thread(
            config.supabase.table("chaos_dive_saves")
            .update({
                "current_floor": next_floor,
                "current_fund": fund,
                "active_buffs": active_buffs,
                "rerolls_used": 0,
                "pending_modules": next_modules
            })
            .eq("user_id", self.user_id)
            .execute
        )
        
        embed_log = discord.Embed(title=f"B{floor}F 結果", color=0xffffff)
        embed_log.description = "\n".join(log_messages) + f"\n\n次の階層 B{next_floor}F へ進む準備ができました。"
        
        next_view = ChaosDiveNextView(self.cog, self.user_id)
        await interaction.channel.send(embed=embed_log, view=next_view)

class ChaosDive(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="chaos_dive", description="カオス・ダイブを開始または再開します")
    @app_commands.describe(bet="初期賭け金（新規開始時のみ必要）")
    async def chaos_dive(self, interaction: discord.Interaction, bet: int = None):
        user_id = str(interaction.user.id)
        
        res_save = await asyncio.to_thread(config.supabase.table("chaos_dive_saves").select("*").eq("user_id", user_id).execute)
        save = res_save.data[0] if res_save.data else None
        if save:
            await interaction.response.send_message("ゲームを再開します。", ephemeral=True)
            await self.show_game_screen(interaction, save)
            return
        
        if bet is None or bet < 1000:
            await interaction.response.send_message("新しくゲームを開始するには、1000以上の賭け金を指定してください。", ephemeral=True)
            return
            
        res_user = await asyncio.to_thread(config.supabase.table("users").select("balance").eq("user_id", user_id).execute)
        balance = res_user.data[0]["balance"] if res_user.data else 0
        
        if balance < bet:
            await interaction.response.send_message(f"コインが不足しています。現在の残高: {balance}", ephemeral=True)
            return
            
        await asyncio.to_thread(config.supabase.table("users").update({"balance": balance - bet}).eq("user_id", user_id).execute)
        await asyncio.to_thread(config.supabase.table("transaction_history").insert({
            "sender_id": user_id,
            "receiver_id": "SYSTEM",
            "amount": bet,
            "reason": "カオス・ダイブ賭け金"
        }).execute)
        
        modules = generate_modules(1)
        await asyncio.to_thread(
            config.supabase.table("chaos_dive_saves")
            .insert({
                "user_id": user_id,
                "current_floor": 1,
                "current_bet": bet,
                "current_fund": bet,
                "active_buffs": {"buffs": []},
                "rerolls_used": 0,
                "pending_modules": modules
            })
            .execute
        )
        
        await interaction.response.send_message("ゲームを開始します。", ephemeral=True)
        res_new = await asyncio.to_thread(config.supabase.table("chaos_dive_saves").select("*").eq("user_id", user_id).execute)
        await self.show_game_screen(interaction, res_new.data[0])

    async def show_game_screen(self, interaction: discord.Interaction, save):
        user_id = save["user_id"]
        floor = save["current_floor"]
        bet = save["current_bet"]
        fund = save["current_fund"]
        
        active_buffs = save["active_buffs"]
        if isinstance(active_buffs, str):
            active_buffs = json.loads(active_buffs)
            
        rerolls_used = save["rerolls_used"]
        
        pending_modules = save["pending_modules"]
        if isinstance(pending_modules, str):
            pending_modules = json.loads(pending_modules)
        
        buffs_list = active_buffs.get("buffs", [])
        has_reverse = any(b["id"] == "chaos_reverse" for b in buffs_list)
        
        embed = discord.Embed(title=f"B{floor}F - カオス・ダイブ", color=0xffffff)
        
        bar_cells = 20
        bar_str = "■" * floor + "□" * (bar_cells - floor)
        
        desc = f"現在の命値: {fund:,} コイン (初期賭け金: {bet:,})\n"
        desc += f"進行状況: [{bar_str}] ({floor}/20)\n\n"
        desc += "【あなたのステータス】\n"
        
        if not buffs_list:
            desc += "・なし\n"
        for b in buffs_list:
            if b["id"] == "chaos_reverse":
                desc += f"・堕天 (残り {b['remaining_turns']} 階層)\n"
            elif b["id"] == "resurrection":
                desc += f"・命乞い (残り {b['remaining_turns']} 階層)\n"
            elif b["id"] == "regen":
                desc += f"・天啓 (残り {b['remaining_turns']} 階層: 毎階層 +{b['val']}%)\n"
            elif b["id"] == "slip":
                desc += f"・罰 (残り {b['remaining_turns']} 階層: 毎階層 -{b['val']}%)\n"
                
        desc += f"\n--------------------------------------------\n【現在の提示条件】(振り直し回数: {rerolls_used} / 3)\n"
        if has_reverse:
            desc += "※堕天適用中！プラスとマイナスが逆転します。\n"
            
        for i, mod in enumerate(pending_modules, 1):
            desc += f"[運命 {i}]\n"
            for r in ["A", "B"]:
                route = mod[r]
                prob = mod["prob"] if r == "A" else (100 - mod["prob"])
                prefix = f"├─ ルートA ({prob}%)" if r == "A" else f"└─ ルートB ({prob}%)"
                
                details = []
                if route["type"] == "plus":
                    orig = f"+{route['val']}%"
                    rev = f"-{route['val']}%" if has_reverse else None
                    details.append(f"命値 {orig}" + (f" (逆転: {rev})" if rev else ""))
                elif route["type"] == "minus":
                    orig = f"-{route['val']}%"
                    rev = f"+{route['val']}%" if has_reverse else None
                    details.append(f"命値 {orig}" + (f" (逆転: {rev})" if rev else ""))
                elif route["type"] == "buff":
                    b_name = {"resurrection": "命乞い", "chaos_reverse": "堕天", "chronos": "継続ターンプラス", "regen": "天啓"}[route["id"]]
                    details.append(f"[{b_name}]獲得")
                elif route["type"] == "debuff":
                    details.append("[罰]獲得")
                    
                desc += f"{prefix}: " + " + ".join(details) + "\n"
                
        embed.description = desc
        view = ChaosDiveView(self, user_id, rerolls_used)
        
        await interaction.channel.send(embed=embed, view=view)

async def setup(bot):
    await bot.add_cog(ChaosDive(bot))
