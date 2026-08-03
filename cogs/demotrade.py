import os
import random
import asyncio
import yfinance as yf
import discord
from discord import app_commands
from discord.ext import commands, tasks
from supabase import create_client, Client

# ---------------------------------------------------------
# 定数設定
# ---------------------------------------------------------
FEE_RATE = 0.001          # 取引手数料 (0.1%)
SLIPPAGE_RATE = 0.0005     # スリッページ幅 (最大0.05%の変動)

# Supabase 接続情報の取得（環境変数から取得することを推奨）
SUPABASE_URL = os.getenv("SUPABASE_URL", "YOUR_SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "YOUR_SUPABASE_SERVICE_ROLE_KEY") # サービスロールキー推奨

# ---------------------------------------------------------
# 価格取得ユーティリティ関数
# ---------------------------------------------------------
def _fetch_price_sync(symbol: str) -> float | None:
    """yfinanceを用いてリアルタイム価格を同期取得する（スレッド用）"""
    try:
        ticker = yf.Ticker(symbol)
        fast_info = ticker.fast_info
        price = getattr(fast_info, 'last_price', None)
        if price is None or str(price) == 'nan' or price <= 0:
            hist = ticker.history(period="1d", interval="1m")
            if not hist.empty:
                price = float(hist['Close'].iloc[-1])
            else:
                price = None
        return price
    except Exception:
        return None

async def get_price(symbol: str) -> float | None:
    """非同期で価格を取得"""
    return await asyncio.to_thread(_fetch_price_sync, symbol)

def apply_slippage(price: float, side: str) -> float:
    """成行注文時にスリッページを適用"""
    slippage = price * random.uniform(0, SLIPPAGE_RATE)
    return price + slippage if side == "buy" else price - slippage

def get_asset_class(symbol: str) -> str:
    """ティッカー名から資産クラスを判定"""
    if "-USD" in symbol or "-JPY" in symbol or symbol in ["BTC", "ETH"]:
        return "CRYPTO"
    return "STOCK"

# ---------------------------------------------------------
# AgoTrade Cog
# ---------------------------------------------------------
class AgoTrade(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
        self.check_limit_orders.start()

    def cog_unload(self):
        self.check_limit_orders.cancel()

    # --- Helper: ユーザー残高取得 or 自動初期化 ---
    async def _get_or_create_user(self, user_id: str) -> dict:
        """ユーザー情報を取得。未登録の場合は残高0で作成（ON CONFLICT対応）"""
        def _db_op():
            # upsert で初期化・既存取得
            res = self.supabase.table("users").upsert(
                {"user_id": user_id},
                on_conflict="user_id",
                ignore_duplicates=True
            ).execute()
            
            # 再度取得
            user_res = self.supabase.table("users").select("*").eq("user_id", user_id).single().execute()
            return user_res.data

        return await asyncio.to_thread(_db_op)

    # --- 1. 価格確認コマンド ---
    @app_commands.command(name="price", description="株・暗号資産・ETFなどの現在価格を確認します")
    @app_commands.describe(symbol="ティッカーシンボル (例: BTC-USD, AAPL, 7203.T)")
    async def price_cmd(self, interaction: discord.Interaction, symbol: str):
        symbol = symbol.upper()
        await interaction.response.defer()

        price = await get_price(symbol)
        if price is None:
            await interaction.followup.send(f"❌ `{symbol}` の価格データが見つかりませんでした。正しいティッカーを指定してください。")
            return

        embed = discord.Embed(
            title=f"📈 価格情報: {symbol}",
            color=discord.Color.green()
        )
        embed.add_field(name="現在価格", value=f"**${price:,.4f}**" if "USD" in symbol or not symbol.endswith(".T") else f"**¥{price:,.2f}**", inline=False)
        embed.set_footer(text="データソース: Yahoo! Finance")
        
        await interaction.followup.send(embed=embed)

    # --- 2. 成行注文コマンド ---
    @app_commands.command(name="market_order", description="成行で銘柄を売買します")
    @app_commands.describe(side="buy (購入) または sell (売却)", symbol="ティッカーシンボル", amount="数量")
    @app_commands.choices(side=[
        app_commands.Choice(name="Buy (買い)", value="buy"),
        app_commands.Choice(name="Sell (売り)", value="sell")
    ])
    async def market_order(self, interaction: discord.Interaction, side: str, symbol: str, amount: float):
        if amount <= 0:
            await interaction.response.send_message("数量は0より大きい値を指定してください。", ephemeral=True)
            return

        symbol = symbol.upper()
        user_id = str(interaction.user.id)
        asset_class = get_asset_class(symbol)
        await interaction.response.defer()

        current_price = await get_price(symbol)
        if current_price is None:
            await interaction.followup.send(f"❌ `{symbol}` の価格データを取得できませんでした。")
            return

        exec_price = apply_slippage(current_price, side)
        total_value = exec_price * amount
        fee = total_value * FEE_RATE

        user_data = await self._get_or_create_user(user_id)
        current_balance = user_data.get("balance", 0)

        # ---------------- 買い処理 ----------------
        if side == "buy":
            total_cost = int(total_value + fee)
            if current_balance < total_cost:
                await interaction.followup.send(f"❌ 残高が不足しています。\n必要金額: **{total_cost:,}** ago coin (保有残高: {current_balance:,})")
                return

            def _execute_buy():
                # 1. 残高減算
                new_balance = current_balance - total_cost
                self.supabase.table("users").update({"balance": new_balance}).eq("user_id", user_id).execute()

                # 2. ポジション情報取得・更新
                pos_res = self.supabase.table("positions").select("*").eq("user_id", user_id).eq("symbol", symbol).eq("position_type", "LONG").execute()
                
                if pos_res.data:
                    current_pos = pos_res.data[0]
                    old_amount = float(current_pos["amount"])
                    old_avg = float(current_pos["avg_price"])
                    new_amount = old_amount + amount
                    new_avg = ((old_amount * old_avg) + (amount * exec_price)) / new_amount
                    
                    self.supabase.table("positions").update({
                        "amount": new_amount,
                        "avg_price": new_avg
                    }).eq("id", current_pos["id"]).execute()
                else:
                    self.supabase.table("positions").insert({
                        "user_id": user_id,
                        "symbol": symbol,
                        "asset_class": asset_class,
                        "position_type": "LONG",
                        "amount": amount,
                        "avg_price": exec_price
                    }).execute()

                # 3. 注文・ログ記録
                order_res = self.supabase.table("orders").insert({
                    "user_id": user_id,
                    "symbol": symbol,
                    "asset_class": asset_class,
                    "side": "buy",
                    "position_type": "LONG",
                    "order_type": "market",
                    "amount": amount,
                    "executed_price": exec_price,
                    "fee_amount": fee,
                    "status": "executed"
                }).execute()

                order_id = order_res.data[0]["id"] if order_res.data else None
                self.supabase.table("trade_logs").insert({
                    "order_id": order_id,
                    "user_id": user_id,
                    "symbol": symbol,
                    "side": "buy",
                    "amount": amount,
                    "price": exec_price,
                    "fee": fee
                }).execute()

                # 取引履歴ログ
                self.supabase.table("transaction_history").insert({
                    "sender_id": user_id,
                    "amount": total_cost,
                    "reason": f"デモトレード購入: {symbol} x {amount}"
                }).execute()

            await asyncio.to_thread(_execute_buy)

            await interaction.followup.send(
                f"✅ **{symbol}** を **{amount}** 購入しました！\n"
                f"約定価格: **${exec_price:,.4f}** | 手数料: **{int(fee):,}** ago coin\n"
                f"支払合計: **{total_cost:,}** ago coin"
            )

        # ---------------- 売り処理 ----------------
        elif side == "sell":
            def _check_pos():
                pos_res = self.supabase.table("positions").select("*").eq("user_id", user_id).eq("symbol", symbol).eq("position_type", "LONG").execute()
                return pos_res.data[0] if pos_res.data else None

            pos = await asyncio.to_thread(_check_pos)
            if not pos or float(pos["amount"]) < amount:
                current_holding = float(pos["amount"]) if pos else 0
                await interaction.followup.send(f"❌ 保有数量が不足しています。\n現在の保有量: **{current_holding}** {symbol}")
                return

            def _execute_sell():
                old_amount = float(pos["amount"])
                avg_price = float(pos["avg_price"])
                net_revenue = int(total_value - fee)
                realized_pnl = (exec_price - avg_price) * amount

                # 1. ポジション更新・削除
                new_amount = old_amount - amount
                if new_amount <= 0.00000001:
                    self.supabase.table("positions").delete().eq("id", pos["id"]).execute()
                else:
                    self.supabase.table("positions").update({"amount": new_amount}).eq("id", pos["id"]).execute()

                # 2. 残高加算
                new_balance = current_balance + net_revenue
                self.supabase.table("users").update({"balance": new_balance}).eq("user_id", user_id).execute()

                # 3. 注文・約定ログ保存
                order_res = self.supabase.table("orders").insert({
                    "user_id": user_id,
                    "symbol": symbol,
                    "asset_class": asset_class,
                    "side": "sell",
                    "position_type": "LONG",
                    "order_type": "market",
                    "amount": amount,
                    "executed_price": exec_price,
                    "fee_amount": fee,
                    "status": "executed"
                }).execute()

                order_id = order_res.data[0]["id"] if order_res.data else None
                self.supabase.table("trade_logs").insert({
                    "order_id": order_id,
                    "user_id": user_id,
                    "symbol": symbol,
                    "side": "sell",
                    "amount": amount,
                    "price": exec_price,
                    "fee": fee,
                    "realized_pnl": realized_pnl
                }).execute()

                # 取引履歴ログ
                self.supabase.table("transaction_history").insert({
                    "receiver_id": user_id,
                    "amount": net_revenue,
                    "reason": f"デモトレード売却: {symbol} x {amount}"
                }).execute()

                return realized_pnl, net_revenue

            pnl, revenue = await asyncio.to_thread(_execute_sell)

            pnl_sign = "+" if pnl >= 0 else ""
            await interaction.followup.send(
                f"✅ **{symbol}** を **{amount}** 売却しました！\n"
                f"約定価格: **${exec_price:,.4f}** | 手数料: **{int(fee):,}** ago coin\n"
                f"受取金額: **{revenue:,}** ago coin (実現損益: **{pnl_sign}${pnl:,.2f}**)"
            )

    # --- 3. 指値注文コマンド ---
    @app_commands.command(name="limit_order", description="指値注文を発注します")
    @app_commands.describe(side="buy または sell", symbol="ティッカーシンボル", amount="数量", target_price="指定目標価格 (USD/JPY)")
    @app_commands.choices(side=[
        app_commands.Choice(name="Buy (買い指値)", value="buy"),
        app_commands.Choice(name="Sell (売り指値)", value="sell")
    ])
    async def limit_order(self, interaction: discord.Interaction, side: str, symbol: str, amount: float, target_price: float):
        if amount <= 0 or target_price <= 0:
            await interaction.response.send_message("数量および価格は0より大きい値を指定してください。", ephemeral=True)
            return

        symbol = symbol.upper()
        user_id = str(interaction.user.id)
        asset_class = get_asset_class(symbol)
        await interaction.response.defer(ephemeral=True)

        user_data = await self._get_or_create_user(user_id)

        if side == "buy":
            total_cost = int(target_price * amount * (1 + FEE_RATE))
            current_balance = user_data.get("balance", 0)

            if current_balance < total_cost:
                await interaction.followup.send(f"❌ 買い指値に必要な残高が不足しています (必要: **{total_cost:,}** ago coin)")
                return

            def _place_buy_limit():
                # 資金を拘束 (balanceから引き引いて frozen_balance に追加)
                self.supabase.table("users").update({
                    "balance": current_balance - total_cost,
                    "frozen_balance": user_data.get("frozen_balance", 0) + total_cost
                }).eq("user_id", user_id).execute()

                # 指値注文テーブルに挿入
                self.supabase.table("orders").insert({
                    "user_id": user_id,
                    "symbol": symbol,
                    "asset_class": asset_class,
                    "side": "buy",
                    "order_type": "limit",
                    "amount": amount,
                    "target_price": target_price,
                    "status": "pending"
                }).execute()

            await asyncio.to_thread(_place_buy_limit)

        elif side == "sell":
            def _check_pos():
                pos_res = self.supabase.table("positions").select("*").eq("user_id", user_id).eq("symbol", symbol).execute()
                return pos_res.data[0] if pos_res.data else None

            pos = await asyncio.to_thread(_check_pos)
            if not pos or float(pos["amount"]) < amount:
                current_holding = float(pos["amount"]) if pos else 0
                await interaction.followup.send(f"❌ 保有数量が不足しています (保有量: **{current_holding}** {symbol})")
                return

            def _place_sell_limit():
                # 指値注文テーブルに挿入 (注文管理用)
                self.supabase.table("orders").insert({
                    "user_id": user_id,
                    "symbol": symbol,
                    "asset_class": asset_class,
                    "side": "sell",
                    "order_type": "limit",
                    "amount": amount,
                    "target_price": target_price,
                    "status": "pending"
                }).execute()

            await asyncio.to_thread(_place_sell_limit)

        await interaction.followup.send(
            f"📌 **{symbol}** の {side.upper()} 指値注文を受け付けました！\n"
            f"目標価格: **${target_price:,.4f}** | 数量: **{amount}**"
        )

    # --- 4. ポートフォリオ（保有資産一覧）確認コマンド ---
    @app_commands.command(name="portfolio", description="現在の保有資産と資産評価額、含み損益を表示します")
    async def portfolio(self, interaction: discord.Interaction):
        user_id = str(interaction.user.id)
        await interaction.response.defer()

        user_data = await self._get_or_create_user(user_id)
        balance = user_data.get("balance", 0)
        frozen = user_data.get("frozen_balance", 0)

        def _get_positions():
            res = self.supabase.table("positions").select("*").eq("user_id", user_id).execute()
            return res.data or []

        positions = await asyncio.to_thread(_get_positions)

        embed = discord.Embed(title=f"📊 {interaction.user.display_name} さんのポートフォリオ", color=discord.Color.blue())
        embed.add_field(
            name="💰 口座残高",
            value=f"利用可能: **{balance:,}** ago coin\n注文拘束中: **{frozen:,}** ago coin",
            inline=False
        )

        if not positions:
            embed.add_field(name="📈 保有ポジション", value="現在保有している資産はありません。", inline=False)
        else:
            pos_text = ""
            total_eval = 0.0

            for pos in positions:
                symbol = pos["symbol"]
                amount = float(pos["amount"])
                avg_price = float(pos["avg_price"])

                cur_price = await get_price(symbol) or avg_price
                eval_val = cur_price * amount
                total_eval += eval_val

                pnl = (cur_price - avg_price) * amount
                pnl_pct = ((cur_price - avg_price) / avg_price) * 100 if avg_price > 0 else 0
                pnl_sign = "+" if pnl >= 0 else ""

                pos_text += f"**{symbol}**: {amount} 単位\n"
                pos_text += f"├ 取得単価: `${avg_price:,.4f}` | 現在値: `${cur_price:,.4f}`\n"
                pos_text += f"└ 含み損益: **{pnl_sign}${pnl:,.2f}** ({pnl_sign}{pnl_pct:.2f}%)\n\n"

            embed.add_field(name="📈 保有ポジション", value=pos_text, inline=False)
            embed.add_field(name="💵 ポジション評価額合計", value=f"**${total_eval:,.2f}**", inline=False)

        await interaction.followup.send(embed=embed)

    # --- 5. バックグラウンドタスク: 指値注文監視 (30秒毎) ---
    @tasks.loop(seconds=30)
    async def check_limit_orders(self):
        def _get_pending():
            res = self.supabase.table("orders").select("*").eq("status", "pending").execute()
            return res.data or []

        pending_orders = await asyncio.to_thread(_get_pending)
        if not pending_orders:
            return

        for order in pending_orders:
            order_id = order["id"]
            user_id = order["user_id"]
            symbol = order["symbol"]
            side = order["side"]
            amount = float(order["amount"])
            target_price = float(order["target_price"])

            cur_price = await get_price(symbol)
            if cur_price is None:
                continue

            should_execute = False
            if side == "buy" and cur_price <= target_price:
                should_execute = True
            elif side == "sell" and cur_price >= target_price:
                should_execute = True

            if should_execute:
                exec_price = apply_slippage(cur_price, side)
                total_value = exec_price * amount
                fee = total_value * FEE_RATE

                def _process_execution():
                    # 約定ステータスに更新
                    self.supabase.table("orders").update({
                        "status": "executed",
                        "executed_price": exec_price,
                        "fee_amount": fee
                    }).eq("id", order_id).execute()

                    if side == "buy":
                        # ポジション加算
                        pos_res = self.supabase.table("positions").select("*").eq("user_id", user_id).eq("symbol", symbol).execute()
                        if pos_res.data:
                            pos = pos_res.data[0]
                            old_amount = float(pos["amount"])
                            old_avg = float(pos["avg_price"])
                            new_amount = old_amount + amount
                            new_avg = ((old_amount * old_avg) + (amount * exec_price)) / new_amount
                            self.supabase.table("positions").update({"amount": new_amount, "avg_price": new_avg}).eq("id", pos["id"]).execute()
                        else:
                            self.supabase.table("positions").insert({
                                "user_id": user_id,
                                "symbol": symbol,
                                "asset_class": order["asset_class"],
                                "amount": amount,
                                "avg_price": exec_price
                            }).execute()

                        # 拘束解除
                        user_res = self.supabase.table("users").select("frozen_balance").eq("user_id", user_id).single().execute()
                        frozen = user_res.data.get("frozen_balance", 0)
                        cost = int(target_price * amount * (1 + FEE_RATE))
                        self.supabase.table("users").update({"frozen_balance": max(0, frozen - cost)}).eq("user_id", user_id).execute()

                    elif side == "sell":
                        # 残高加算
                        net_revenue = int(total_value - fee)
                        user_res = self.supabase.table("users").select("balance").eq("user_id", user_id).single().execute()
                        bal = user_res.data.get("balance", 0)
                        self.supabase.table("users").update({"balance": bal + net_revenue}).eq("user_id", user_id).execute()

                        # ポジション減算
                        pos_res = self.supabase.table("positions").select("*").eq("user_id", user_id).eq("symbol", symbol).execute()
                        if pos_res.data:
                            pos = pos_res.data[0]
                            new_amount = float(pos["amount"]) - amount
                            if new_amount <= 0.00000001:
                                self.supabase.table("positions").delete().eq("id", pos["id"]).execute()
                            else:
                                self.supabase.table("positions").update({"amount": new_amount}).eq("id", pos["id"]).execute()

                    # 約定ログ
                    self.supabase.table("trade_logs").insert({
                        "order_id": order_id,
                        "user_id": user_id,
                        "symbol": symbol,
                        "side": side,
                        "amount": amount,
                        "price": exec_price,
                        "fee": fee
                    }).execute()

                await asyncio.to_thread(_process_execution)


async def setup(bot: commands.Bot):
    await bot.add_cog(AgoTrade(bot))
