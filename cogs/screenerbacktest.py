import asyncio
import ast
import json
import os
import sys
import math
from datetime import datetime, date
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any, Union
from concurrent.futures import ThreadPoolExecutor

import discord
from discord import app_commands
from discord.ext import commands
import numpy as np
import pandas as pd

try:
    import yfinance as yf
    HAS_REQUIRED_LIBS = True
except ImportError as e:
    print(f"[StockScreener Critical Error] ライブラリのインポートに失敗しました: {e}", file=sys.stderr)
    HAS_REQUIRED_LIBS = False


# ==========================================
# 1. データモデル (Dataclasses)
# ==========================================
@dataclass
class TradePosition:
    symbol: str
    side: str  # "LONG" または "SHORT"
    entry_date: datetime
    entry_price: float
    shares: int
    stop_loss_price: Optional[float] = None
    take_profit_price: Optional[float] = None
    is_hedged: bool = False
    current_price: float = 0.0
    unrealized_pnl: float = 0.0
    highest_price: float = 0.0  # 追記: トレーリングストップ用
@dataclass
class BacktestConfig:
    initial_capital: float = 10000000.0
    tax_rate: float = 0.20315
    commission_rate: float = 0.001
    slippage_rate: float = 0.001
    short_fee_daily: float = 0.0115 / 365.0
    max_position_percent: float = 0.10
    max_positions: int = 10
    allow_short: bool = False
    allow_pyramiding: bool = False
    pyramiding_step: float = 0.05
    allow_hedge: bool = False
    hedge_trigger_drawdown: float = 0.10
    partial_exit_profit: Optional[float] = None
    partial_exit_loss: Optional[float] = None
    trailing_stop_percent: Optional[float] = None


@dataclass
class TradeResult:
    initial_capital: float
    final_capital: float
    total_profit_loss: float
    tax_amount: float
    net_profit: float
    total_trades: int
    win_trades: int
    lose_trades: int
    win_rate: float
    profit_factor: float
    max_drawdown_percent: float
    max_drawdown_amount: float
    sharpe_ratio: float
    trade_logs: List[Dict[str, Any]] = field(default_factory=list)
# ==========================================
# 2. 指標計算モジュール (IndicatorEngine)
# ==========================================

class IndicatorEngine:
    @staticmethod
    def calculate_technical_indicators(df: pd.DataFrame) -> pd.DataFrame:
        if df.empty or len(df) < 2:
            return df

        df = df.copy()
        
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        close = df["Close"]
        high = df["High"]
        low = df["Low"]
        volume = df["Volume"]

        df["sma_25"] = close.rolling(25).mean()
        df["sma_75"] = close.rolling(75).mean()
        df["sma_200"] = close.rolling(200).mean()

        df["bias_25"] = (close - df["sma_25"]) / df["sma_25"] * 100
        df["bias_75"] = (close - df["sma_75"]) / df["sma_75"] * 100
        df["bias_200"] = (close - df["sma_200"]) / df["sma_200"] * 100

        df["golden_cross"] = (df["sma_25"] > df["sma_75"]) & (df["sma_25"].shift(1) <= df["sma_75"].shift(1))
        df["dead_cross"] = (df["sma_25"] < df["sma_75"]) & (df["sma_25"].shift(1) >= df["sma_75"].shift(1))

        ema12 = close.ewm(span=12, adjust=False).mean()
        ema26 = close.ewm(span=26, adjust=False).mean()
        df["macd"] = ema12 - ema26
        df["macd_signal"] = df["macd"].ewm(span=9, adjust=False).mean()
        df["macd_hist"] = df["macd"] - df["macd_signal"]

        delta = close.diff()
        gain = (delta.where(delta > 0, 0)).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rs = gain / (loss + 1e-8)
        df["rsi"] = 100 - (100 / (1 + rs))

        def calc_rci(series):
            n = len(series)
            ranks = np.arange(n, 0, -1)
            price_ranks = series.rank(ascending=False).values
            d_sq = np.sum((ranks - price_ranks) ** 2)
            return (1 - (6 * d_sq) / (n * (n**2 - 1))) * 100

        df["rci_9"] = close.rolling(9).apply(calc_rci, raw=False)

        up_move = high.diff()
        down_move = -low.diff()
        plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0)
        minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0)
        tr = pd.concat([high - low, (high - close.shift()).abs(), (low - close.shift()).abs()], axis=1).max(axis=1)
        atr = tr.rolling(14).mean()
        plus_di = 100 * pd.Series(plus_dm, index=df.index).rolling(14).mean() / (atr + 1e-8)
        minus_di = 100 * pd.Series(minus_dm, index=df.index).rolling(14).mean() / (atr + 1e-8)
        dx = (plus_di - minus_di).abs() / (plus_di + minus_di + 1e-8) * 100
        df["plus_di"] = plus_di
        df["minus_di"] = minus_di
        df["adx"] = dx.rolling(14).mean()

        low9 = low.rolling(9).min()
        high9 = high.rolling(9).max()
        df["stoch_k"] = 100 * (close - low9) / (high9 - low9 + 1e-8)
        df["stoch_d"] = df["stoch_k"].rolling(3).mean()

        is_up = (delta > 0).astype(int)
        df["psychological"] = is_up.rolling(12).sum() / 12 * 100

        df["momentum_10"] = close - close.shift(10)

        std_20 = close.rolling(20).std()
        sma_20 = close.rolling(20).mean()
        df["bollinger_upper_2s"] = sma_20 + (std_20 * 2)
        df["bollinger_lower_2s"] = sma_20 - (std_20 * 2)

        typical_price = (high + low + close) / 3
        pv = typical_price * volume
        df["vwap"] = pv.cumsum() / (volume.cumsum() + 1e-8)
        df["vwap_bias"] = (close - df["vwap"]) / df["vwap"] * 100

        df["roc_1w"] = close.pct_change(5) * 100
        df["roc_1m"] = close.pct_change(20) * 100
        df["roc_3m"] = close.pct_change(60) * 100
        df["roc_1y"] = close.pct_change(250) * 100

        high_52w = high.rolling(250, min_periods=1).max()
        low_52w = low.rolling(250, min_periods=1).min()
        df["high_52w_drop"] = (close - high_52w) / high_52w * 100
        df["low_52w_rise"] = (close - low_52w) / low_52w * 100

        df["volume_change"] = volume.pct_change() * 100
        vol_ma20 = volume.rolling(20).mean()
        df["volume_ratio_ma20"] = volume / (vol_ma20 + 1e-8)
        df["trading_value"] = close * volume

        return df

    @staticmethod
    def process_fundamental_metrics(info: dict) -> dict:
        mcap = info.get("marketCap")
        rev = info.get("totalRevenue")
        psr = (mcap / rev) if (mcap and rev and rev > 0) else info.get("priceToSalesTrailing12Months")

        return {
            "per": info.get("trailingPE"),
            "forward_per": info.get("forwardPE"),
            "pbr": info.get("priceToBook"),
            "psr": psr,
            "pcfr": info.get("priceToToOperatingCashFlow"),
            "ev_ebitda": info.get("enterpriseToEBITDA"),
            "roe": info.get("returnOnEquity") * 100 if info.get("returnOnEquity") is not None else None,
            "roa": info.get("returnOnAssets") * 100 if info.get("returnOnAssets") is not None else None,
            "operating_margin": info.get("operatingMargins") * 100 if info.get("operatingMargins") is not None else None,
            "dividend_yield": info.get("dividendYield") * 100 if info.get("dividendYield") is not None else None,
            "payout_ratio": info.get("payoutRatio") * 100 if info.get("payoutRatio") is not None else None,
            "market_cap": mcap,
            "market_cap_oku": mcap / 100000000 if mcap else None,
            "revenue_growth": info.get("revenueGrowth") * 100 if info.get("revenueGrowth") is not None else None,
            "earnings_growth": info.get("earningsGrowth") * 100 if info.get("earningsGrowth") is not None else None,
            "free_cashflow": info.get("freeCashflow"),
            "operating_cashflow": info.get("operatingCashflow"),
            "target_mean_price": info.get("targetMeanPrice"),
            "analyst_rating": info.get("recommendationMean")
        }
# ==========================================
# 3. クエリ構文解析・評価モジュール (QueryParserEngine)
# ==========================================

class QueryParserEngine:
    ALLOWED_OPERATORS = {
        ast.Gt: lambda a, b: a > b,
        ast.GtE: lambda a, b: a >= b,
        ast.Lt: lambda a, b: a < b,
        ast.LtE: lambda a, b: a <= b,
        ast.Eq: lambda a, b: a == b,
        ast.NotEq: lambda a, b: a != b,
        ast.And: lambda a, b: a and b,
        ast.Or: lambda a, b: a or b,
        ast.Add: lambda a, b: a + b,
        ast.Sub: lambda a, b: a - b,
        ast.Mult: lambda a, b: a * b,
        ast.Div: lambda a, b: a / b if b != 0 else 0,
    }

    @classmethod
    def eval_condition(cls, expr: str, context_data: Dict[str, Any]) -> bool:
        if not expr or not expr.strip():
            return True

        try:
            tree = ast.parse(expr, mode="eval")
            return bool(cls._eval_node(tree.body, context_data))
        except Exception:
            return False

    @classmethod
    def _eval_node(cls, node: ast.AST, context: Dict[str, Any]) -> Any:
        if isinstance(node, ast.Constant):
            return node.value
        elif isinstance(node, ast.Name):
            val = context.get(node.id)
            if val is None:
                raise ValueError(f"Variable '{node.id}' not found in context")
            return val
        elif isinstance(node, ast.UnaryOp):
            if isinstance(node.op, ast.USub):
                return -cls._eval_node(node.operand, context)
            elif isinstance(node.op, ast.Not):
                return not cls._eval_node(node.operand, context)
            raise ValueError(f"Unsupported unary operator: {type(node.op)}")
        elif isinstance(node, ast.BinOp):
            op_type = type(node.op)
            if op_type in cls.ALLOWED_OPERATORS:
                left = cls._eval_node(node.left, context)
                right = cls._eval_node(node.right, context)
                if left is None or right is None:
                    return False
                return cls.ALLOWED_OPERATORS[op_type](left, right)
            raise ValueError(f"Unsupported binary operator: {op_type}")
        elif isinstance(node, ast.Compare):
            left = cls._eval_node(node.left, context)
            if left is None:
                return False
            for op, comparator in zip(node.ops, node.comparators):
                op_type = type(op)
                right = cls._eval_node(comparator, context)
                if right is None:
                    return False
                if op_type not in cls.ALLOWED_OPERATORS:
                    raise ValueError(f"Unsupported comparison operator: {op_type}")
                if not cls.ALLOWED_OPERATORS[op_type](left, right):
                    return False
                left = right
            return True
        elif isinstance(node, ast.BoolOp):
            op_type = type(node.op)
            if op_type == ast.And:
                for value in node.values:
                    res = cls._eval_node(value, context)
                    if not res:
                        return False
                return True
            elif op_type == ast.Or:
                for value in node.values:
                    res = cls._eval_node(value, context)
                    if res:
                        return True
                return False
            raise ValueError(f"Unsupported boolean operator: {op_type}")
        else:
            raise ValueError(f"Unsupported AST node type: {type(node)}")
# ==========================================
# 4. 高精度バックテスト処理モジュール (RealisticBacktestEngine)
# ==========================================

class RealisticBacktestEngine:
    def __init__(self, config: BacktestConfig, historical_data_map: Dict[str, pd.DataFrame]):
        self.config = config
        self.data_map = historical_data_map
        self.positions: List[TradePosition] = []
        self.cash = config.initial_capital
        self.realized_gross_pnl = 0.0
        self.total_tax_paid = 0.0
        self.trade_logs: List[Dict[str, Any]] = []

    def run(self, screening_signals: Dict[str, pd.Series]) -> TradeResult:
        if not self.data_map:
            return self._empty_result()

        all_dates = sorted(list(set().union(*[df.index for df in self.data_map.values()])))
        if not all_dates:
            return self._empty_result()

        portfolio_history = []

        for current_date in all_dates:
            self._update_existing_positions(current_date)
            self._process_exits_and_adjustments(current_date)
            self._process_entries(current_date, screening_signals)

            current_portfolio_value = self.cash + sum(p.shares * p.current_price for p in self.positions if p.side == "LONG") \
                                      - sum(p.shares * p.current_price for p in self.positions if p.side == "SHORT")
            portfolio_history.append(current_portfolio_value)

        net_profit = (self.cash - self.config.initial_capital)
        total_pnl = net_profit + self.total_tax_paid

        trades_count = len(self.trade_logs)
        wins = [t for t in self.trade_logs if t["net_pnl"] > 0]
        losses = [t for t in self.trade_logs if t["net_pnl"] <= 0]
        win_count = len(wins)
        lose_count = len(losses)
        win_rate = (win_count / trades_count * 100) if trades_count > 0 else 0.0

        gross_profit = sum(t["net_pnl"] for t in wins)
        gross_loss = abs(sum(t["net_pnl"] for t in losses))
        profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else (gross_profit if gross_profit > 0 else 0.0)

        peak = portfolio_history[0] if portfolio_history else self.config.initial_capital
        max_dd_amount = 0.0
        max_dd_percent = 0.0

        for val in portfolio_history:
            if val > peak:
                peak = val
            dd_amt = peak - val
            dd_pct = (dd_amt / peak * 100) if peak > 0 else 0.0
            if dd_amt > max_dd_amount:
                max_dd_amount = dd_amt
            if dd_pct > max_dd_percent:
                max_dd_percent = dd_pct

        returns = pd.Series(portfolio_history).pct_change().dropna()
        sharpe = 0.0
        if len(returns) > 1 and returns.std() > 0:
            sharpe = float((returns.mean() / returns.std()) * np.sqrt(250))

        return TradeResult(
            initial_capital=self.config.initial_capital,
            final_capital=self.cash,
            total_profit_loss=total_pnl,
            tax_amount=self.total_tax_paid,
            net_profit=net_profit,
            total_trades=trades_count,
            win_trades=win_count,
            lose_trades=lose_count,
            win_rate=win_rate,
            profit_factor=profit_factor,
            max_drawdown_percent=max_dd_percent,
            max_drawdown_amount=max_dd_amount,
            sharpe_ratio=sharpe,
            trade_logs=self.trade_logs
        )

    def _update_existing_positions(self, current_date: pd.Timestamp):
        for pos in self.positions:
            df = self.data_map.get(pos.symbol)
            if df is not None and current_date in df.index:
                val = df.loc[current_date, "Close"]
                price = float(val.iloc[0] if isinstance(val, pd.Series) else val)
                pos.current_price = price
                if pos.side == "LONG":
                    pos.unrealized_pnl = (price - pos.entry_price) * pos.shares
                else:
                    pos.unrealized_pnl = (pos.entry_price - price) * pos.shares
                    daily_short_fee = (pos.entry_price * pos.shares) * self.config.short_fee_daily
                    self.cash -= daily_short_fee

    def _process_exits_and_adjustments(self, current_date: pd.Timestamp):
        positions_to_remove = []

        total_portfolio_val = self.cash + sum(p.unrealized_pnl for p in self.positions)
        total_unrealized_loss = sum(p.unrealized_pnl for p in self.positions if p.unrealized_pnl < 0)

        hedge_targets = []
        if self.config.allow_hedge and total_portfolio_val > 0 and (abs(total_unrealized_loss) / total_portfolio_val) >= self.config.hedge_trigger_drawdown:
            for p in self.positions:
                if p.side == "LONG" and not p.is_hedged:
                    p.is_hedged = True
                    hedge_targets.append(p)

        for p in hedge_targets:
            self._execute_open(p.symbol, current_date, p.current_price, "SHORT", "HEDGE_SHORT")

        for pos in self.positions:
            df = self.data_map.get(pos.symbol)
            if df is None or current_date not in df.index:
                continue

            current_price = pos.current_price
            if current_price > pos.highest_price:
                pos.highest_price = current_price

            exit_needed = False
            exit_reason = ""

            # LONG / SHORT 両対応のストップロス・テイクプロフィット判定
            if pos.side == "LONG":
                if pos.stop_loss_price and current_price <= pos.stop_loss_price:
                    exit_needed = True
                    exit_reason = "STOP_LOSS"
                elif pos.take_profit_price and current_price >= pos.take_profit_price:
                    exit_needed = True
                    exit_reason = "TAKE_PROFIT"
            elif pos.side == "SHORT":
                if pos.stop_loss_price and current_price >= pos.stop_loss_price:
                    exit_needed = True
                    exit_reason = "STOP_LOSS"
                elif pos.take_profit_price and current_price <= pos.take_profit_price:
                    exit_needed = True
                    exit_reason = "TAKE_PROFIT"

            if not exit_needed and self.config.trailing_stop_percent and pos.side == "LONG":
                drop_ratio = (pos.highest_price - current_price) / pos.highest_price
                if drop_ratio >= self.config.trailing_stop_percent:
                    exit_needed = True
                    exit_reason = "TRAILING_STOP"

            if not exit_needed and self.config.partial_exit_profit and pos.side == "LONG":
                pnl_ratio = (current_price - pos.entry_price) / pos.entry_price
                if pnl_ratio >= self.config.partial_exit_profit and pos.shares > 100:
                    exit_shares = pos.shares // 2
                    self._execute_close(pos, current_date, current_price, exit_shares, "PARTIAL_TAKE_PROFIT")

            if exit_needed:
                self._execute_close(pos, current_date, current_price, pos.shares, exit_reason)
                positions_to_remove.append(pos)

        for p in positions_to_remove:
            if p in self.positions:
                self.positions.remove(p)

    def _process_entries(self, current_date: pd.Timestamp, screening_signals: Dict[str, pd.Series]):
        if len(self.positions) >= self.config.max_positions:
            return

        for symbol, signal_series in screening_signals.items():
            if len(self.positions) >= self.config.max_positions:
                break

            if current_date not in signal_series.index or not bool(signal_series.loc[current_date]):
                continue

            df = self.data_map.get(symbol)
            if df is None or current_date not in df.index:
                continue

            val = df.loc[current_date, "Close"]
            raw_price = float(val.iloc[0] if isinstance(val, pd.Series) else val)
            existing_pos = next((p for p in self.positions if p.symbol == symbol), None)

            if existing_pos:
                if self.config.allow_pyramiding:
                    pnl_pct = (raw_price - existing_pos.entry_price) / existing_pos.entry_price
                    if abs(pnl_pct) >= self.config.pyramiding_step:
                        self._execute_open(symbol, current_date, raw_price, existing_pos.side, "PYRAMIDING")
            else:
                entry_side = "SHORT" if self.config.allow_short else "LONG"
                entry_reason = "SCREENING_SHORT_ENTRY" if self.config.allow_short else "SCREENING_ENTRY"
                self._execute_open(symbol, current_date, raw_price, entry_side, entry_reason)

    def _execute_open(self, symbol: str, current_date: pd.Timestamp, price: float, side: str, reason: str):
        exec_price = price * (1 + self.config.slippage_rate) if side == "LONG" else price * (1 - self.config.slippage_rate)
        max_alloc = self.cash * self.config.max_position_percent
        shares = int(max_alloc // (exec_price * 100)) * 100

        if shares <= 0:
            return

        cost = shares * exec_price
        commission = cost * self.config.commission_rate

        if self.cash < (cost + commission):
            return

        self.cash -= (cost + commission)

        if side == "LONG":
            sl = exec_price * (1 - self.config.partial_exit_loss) if self.config.partial_exit_loss else None
            tp = exec_price * (1 + self.config.partial_exit_profit) if self.config.partial_exit_profit else None
        else:
            sl = exec_price * (1 + self.config.partial_exit_loss) if self.config.partial_exit_loss else None
            tp = exec_price * (1 - self.config.partial_exit_profit) if self.config.partial_exit_profit else None

        pos = TradePosition(
            symbol=symbol,
            side=side,
            entry_date=current_date,
            entry_price=exec_price,
            shares=shares,
            stop_loss_price=sl,
            take_profit_price=tp,
            current_price=exec_price,
            highest_price=exec_price,
            unrealized_pnl=0.0
        )
        self.positions.append(pos)

    def _execute_close(self, pos: TradePosition, current_date: pd.Timestamp, price: float, shares: int, reason: str):
        exec_price = price * (1 - self.config.slippage_rate) if pos.side == "LONG" else price * (1 + self.config.slippage_rate)
        revenue = shares * exec_price
        commission = revenue * self.config.commission_rate
        gross_pnl = (exec_price - pos.entry_price) * shares if pos.side == "LONG" else (pos.entry_price - exec_price) * shares

        tax = 0.0
        if gross_pnl > 0:
            tax = gross_pnl * self.config.tax_rate

        net_pnl = gross_pnl - commission - tax
        self.cash += (revenue - commission - tax)
        self.total_tax_paid += tax
        pos.shares -= shares

        self.trade_logs.append({
            "symbol": pos.symbol,
            "side": pos.side,
            "entry_date": pos.entry_date.strftime("%Y-%m-%d"),
            "exit_date": current_date.strftime("%Y-%m-%d"),
            "entry_price": pos.entry_price,
            "exit_price": exec_price,
            "shares": shares,
            "gross_pnl": gross_pnl,
            "tax": tax,
            "commission": commission,
            "net_pnl": net_pnl,
            "reason": reason
        })

    def _empty_result(self) -> TradeResult:
        return TradeResult(
            initial_capital=self.config.initial_capital,
            final_capital=self.config.initial_capital,
            total_profit_loss=0.0,
            tax_amount=0.0,
            net_profit=0.0,
            total_trades=0,
            win_trades=0,
            lose_trades=0,
            win_rate=0.0,
            profit_factor=0.0,
            max_drawdown_percent=0.0,
            max_drawdown_amount=0.0,
            sharpe_ratio=0.0,
            trade_logs=[]
        )
# ==========================================
# 5. Discord Cog本体 (StockScreenerBacktestCog)
# ==========================================

class StockScreenerBacktestCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.symbols_file = "tse_gps_symbols.json"
        self.cache_file = "financial_cache.json"
        self.symbols_data: List[Dict[str, str]] = []
        self.financial_cache: Dict[str, Dict[str, Any]] = {}
        self.is_updating = False
        self.executor = ThreadPoolExecutor(max_workers=4)

        self.load_symbols()
        self.load_cache()

    def load_symbols(self):
        if os.path.exists(self.symbols_file):
            try:
                with open(self.symbols_file, "r", encoding="utf-8") as f:
                    self.symbols_data = json.load(f)
            except Exception as e:
                print(f"[StockScreener Error] Symbols load failed: {e}", file=sys.stderr)

    def load_cache(self):
        if os.path.exists(self.cache_file):
            try:
                with open(self.cache_file, "r", encoding="utf-8") as f:
                    self.financial_cache = json.load(f)
            except Exception as e:
                print(f"[StockScreener Error] Cache load failed: {e}", file=sys.stderr)

    def save_cache(self):
        try:
            with open(self.cache_file, "w", encoding="utf-8") as f:
                json.dump(self.financial_cache, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[StockScreener Error] Cache save failed: {e}", file=sys.stderr)

    def sync_fetch_all_cache(self):
        if not self.symbols_data:
            return

        for item in self.symbols_data:
            code = item.get("code")
            if not code:
                continue
            symbol = f"{code}.T"
            try:
                ticker = yf.Ticker(symbol)
                info = ticker.info
                fund_metrics = IndicatorEngine.process_fundamental_metrics(info)

                hist = ticker.history(period="1y")
                tech_metrics = {}
                if not hist.empty and len(hist) > 30:
                    hist_calc = IndicatorEngine.calculate_technical_indicators(hist)
                    latest = hist_calc.iloc[-1]
                    tech_metrics = {
                        "close": float(latest.get("Close", 0.0)),
                        "sma_25": float(latest.get("sma_25", 0.0)),
                        "sma_75": float(latest.get("sma_75", 0.0)),
                        "sma_200": float(latest.get("sma_200", 0.0)),
                        "bias_25": float(latest.get("bias_25", 0.0)),
                        "macd": float(latest.get("macd", 0.0)),
                        "macd_hist": float(latest.get("macd_hist", 0.0)),
                        "rsi": float(latest.get("rsi", 0.0)),
                        "rci_9": float(latest.get("rci_9", 0.0)),
                        "adx": float(latest.get("adx", 0.0)),
                        "vwap": float(latest.get("vwap", 0.0)),
                        "vwap_bias": float(latest.get("vwap_bias", 0.0)),
                        "roc_1m": float(latest.get("roc_1m", 0.0)),
                        "volume_ratio_ma20": float(latest.get("volume_ratio_ma20", 0.0))
                    }

                cache_entry = {
                    "code": code,
                    "name": item.get("name", ""),
                    "market": item.get("market", "")
                }
                cache_entry.update(fund_metrics)
                cache_entry.update(tech_metrics)

                self.financial_cache[code] = cache_entry
            except Exception:
                continue

        self.save_cache()

    @app_commands.command(name="update_screener_cache", description="財務およびテクニカルキャッシュデータを全件更新します")
    async def update_screener_cache(self, interaction: discord.Interaction):
        if self.is_updating:
            await interaction.response.send_message("キャッシュ更新処理が既に実行中です。", ephemeral=True)
            return

        self.is_updating = True
        await interaction.response.send_message("全銘柄のキャッシュデータ同期を開始しました。完了まで時間がかかります。")

        loop = asyncio.get_running_loop()
        await loop.run_in_executor(self.executor, self.sync_fetch_all_cache)

        self.is_updating = False
        await interaction.followup.send("財務およびテクニカルキャッシュデータの更新が完了しました。")

    @app_commands.command(name="screening", description="高機能条件指定およびカスタムクエリで銘柄をスクリーニングします")
    @app_commands.describe(
        min_per="PER 最小値",
        max_per="PER 最大値",
        min_pbr="PBR 最小値",
        max_pbr="PBR 最大値",
        min_roe="ROE 最小値 (%)",
        min_psr="PSR 最小値",
        min_yield="配当利回り 最小値 (%)",
        market_cap_min_oku="最小時価総額 (億円)",
        universe="対象市場区分 (Prime / Standard / Growth / All)",
        query="カスタム判定クエリ (例: psr < 2.0 and roe > 10 and vwap_bias > 0)"
    )
    async def screening(
        self,
        interaction: discord.Interaction,
        min_per: Optional[float] = None,
        max_per: Optional[float] = None,
        min_pbr: Optional[float] = None,
        max_pbr: Optional[float] = None,
        min_roe: Optional[float] = None,
        min_psr: Optional[float] = None,
        min_yield: Optional[float] = None,
        market_cap_min_oku: Optional[float] = None,
        universe: Optional[str] = "All",
        query: Optional[str] = None
    ):
        await interaction.response.defer()

        if not self.financial_cache:
            await interaction.followup.send("キャッシュデータが存在しません。先に /update_screener_cache を実行してください。")
            return

        loop = asyncio.get_running_loop()
        results = await loop.run_in_executor(
            self.executor,
            self._execute_screening_filter,
            min_per, max_per, min_pbr, max_pbr, min_roe, min_psr, min_yield, market_cap_min_oku, universe, query
        )

        if not results:
            await interaction.followup.send("指定された条件に一致する銘柄は見つかりませんでした。")
            return

        embed = discord.Embed(
            title=f"SCREENING RESULTS // TOTAL: {len(results)} ITEMS",
            color=0x8A2BE2
        )

        for item in results[:20]:
            name = item.get("name", "")
            code = item.get("code", "")
            per_v = f"{item['per']:.1f}" if item.get("per") is not None else "N/A"
            pbr_v = f"{item['pbr']:.2f}" if item.get("pbr") is not None else "N/A"
            psr_v = f"{item['psr']:.2f}" if item.get("psr") is not None else "N/A"
            roe_v = f"{item['roe']:.1f}%" if item.get("roe") is not None else "N/A"
            vwap_b = f"{item['vwap_bias']:.2f}%" if item.get("vwap_bias") is not None else "N/A"

            val_str = f"PER: {per_v} | PBR: {pbr_v} | PSR: {psr_v} | ROE: {roe_v} | VWAP乖離: {vwap_b}"
            embed.add_field(name=f"{name} ({code})", value=val_str, inline=False)

        if len(results) > 20:
            embed.set_footer(text=f"SHOWING TOP 20 OF {len(results)} MATCHES")

        await interaction.followup.send(embed=embed)

    def _execute_screening_filter(
        self,
        min_per: Optional[float],
        max_per: Optional[float],
        min_pbr: Optional[float],
        max_pbr: Optional[float],
        min_roe: Optional[float],
        min_psr: Optional[float],
        min_yield: Optional[float],
        market_cap_min_oku: Optional[float],
        universe: Optional[str],
        query: Optional[str]
    ) -> List[Dict[str, Any]]:
        matched = []

        for code, data in self.financial_cache.items():
            per = data.get("per")
            pbr = data.get("pbr")
            roe = data.get("roe")
            psr = data.get("psr")
            div_yield = data.get("dividend_yield")
            mcap_oku = data.get("market_cap_oku")
            
            if universe and universe.lower() != "all":
                data_market = str(data.get("market", "")).lower()
                if universe.lower() not in data_market:
                    continue

            if min_per is not None and (per is None or per < min_per):
                continue
            if max_per is not None and (per is None or per > max_per):
                continue
            if min_pbr is not None and (pbr is None or pbr < min_pbr):
                continue
            if max_pbr is not None and (pbr is None or pbr > max_pbr):
                continue
            if min_roe is not None and (roe is None or roe < min_roe):
                continue
            if min_psr is not None and (psr is None or psr < min_psr):
                continue
            if min_yield is not None and (div_yield is None or div_yield < min_yield):
                continue
            if market_cap_min_oku is not None and (mcap_oku is None or mcap_oku < market_cap_min_oku):
                continue

            if query and query.strip():
                if not QueryParserEngine.eval_condition(query, data):
                    continue

            matched.append(data)

        return matched

    @app_commands.command(name="backtest", description="スクリーニング対象条件に基づくリアルな過去売買シミュレーションを実行します")
    @app_commands.describe(
        initial_capital="初期資金 (円)",
        universe="対象市場区分 (Prime / Standard / Growth / All)",
        allow_short="空売りを許可する",
        allow_pyramiding="買い増し(ナンピン・ピラミッディング)を許可する",
        allow_hedge="一定ドローダウン到達時に自動ヘッジを発動する",
        query="エントリーシグナル用クエリ条件式"
    )
    async def backtest(
        self,
        interaction: discord.Interaction,
        initial_capital: float = 10000000.0,
        universe: Optional[str] = "All",
        allow_short: bool = False,
        allow_pyramiding: bool = False,
        allow_hedge: bool = False,
        query: Optional[str] = "bias_25 < -5 and rsi < 35"
    ):
        await interaction.response.defer()

        config = BacktestConfig(
            initial_capital=initial_capital,
            allow_short=allow_short,
            allow_pyramiding=allow_pyramiding,
            allow_hedge=allow_hedge,
            tax_rate=0.20315
        )

        loop = asyncio.get_running_loop()
        res = await loop.run_in_executor(
            self.executor,
            self._execute_backtest_pipeline,
            config,
            query,
            universe
        )

        if not res:
            await interaction.followup.send("バックテストの実行に必要なヒストリカルデータの取得に失敗しました。")
            return

        embed = discord.Embed(
            title="QUANTITATIVE BACKTEST REPORT // REALISTIC ENGINE",
            color=0x00FFA3 if res.net_profit >= 0 else 0xFF0055
        )

        embed.add_field(
            name="[ CAPITAL & PnL ]",
            value=f"```text\n"
                  f"INITIAL CAPITAL : ¥{res.initial_capital:,.0f}\n"
                  f"FINAL CAPITAL   : ¥{res.final_capital:,.0f}\n"
                  f"GROSS PROFIT    : ¥{res.total_profit_loss:,.0f}\n"
                  f"TAX DEDUCTED    : ¥{res.tax_amount:,.0f} (20.315%)\n"
                  f"NET PROFIT      : ¥{res.net_profit:,.0f}\n"
                  f"```",
            inline=False
        )

        embed.add_field(
            name="[ PERFORMANCE METRICS ]",
            value=f"```text\n"
                  f"WIN RATE        : {res.win_rate:.1f}% ({res.win_trades}W / {res.lose_trades}L)\n"
                  f"TOTAL TRADES    : {res.total_trades}\n"
                  f"PROFIT FACTOR   : {res.profit_factor:.2f}\n"
                  f"MAX DRAWDOWN    : {res.max_drawdown_percent:.2f}% (¥{res.max_drawdown_amount:,.0f})\n"
                  f"SHARPE RATIO    : {res.sharpe_ratio:.2f}\n"
                  f"```",
            inline=False
        )

        embed.set_footer(text="QUANT SYSTEM ENGINE // BACKTEST COMPLETE")
        await interaction.followup.send(embed=embed)

    def _execute_backtest_pipeline(
        self,
        config: BacktestConfig,
        query: Optional[str],
        universe: Optional[str] = "All",
        max_symbols: int = 100
    ) -> Optional[TradeResult]:
        
        filtered_symbols = self.symbols_data
        if universe and universe.lower() != "all":
            filtered_symbols = [
                s for s in self.symbols_data 
                if universe.lower() in str(s.get("market", "")).lower()
            ]

        target_symbols = [f"{s['code']}.T" for s in filtered_symbols[:max_symbols]]
        
        historical_map = {}
        screening_signals = {}

        try:
            data = yf.download(target_symbols, period="2y", group_by="ticker", progress=False)
            for sym in target_symbols:
                if len(target_symbols) == 1:
                    df = data.copy()
                else:
                    if not isinstance(data.columns, pd.MultiIndex) or sym not in data.columns.levels[0]:
                        continue
                    df = data[sym].dropna()

                if df.empty or len(df) < 50:
                    continue

                df_calc = IndicatorEngine.calculate_technical_indicators(df)
                historical_map[sym] = df_calc

                signals = pd.Series(False, index=df_calc.index)
                for idx in range(len(df_calc)):
                    row_dict = df_calc.iloc[idx].to_dict()
                    if query and QueryParserEngine.eval_condition(query, row_dict):
                        signals.iloc[idx] = True

                screening_signals[sym] = signals

            if not historical_map:
                return None

            engine = RealisticBacktestEngine(config, historical_map)
            return engine.run(screening_signals)

        except Exception as e:
            print(f"[Backtest Pipeline Error] {e}", file=sys.stderr)
            return None

async def setup(bot: commands.Bot):
    if not HAS_REQUIRED_LIBS:
        print("[StockScreener Error] 依存ライブラリ不足のため StockScreenerBacktestCog のロードを中止します。", file=sys.stderr)
        return
    await bot.add_cog(StockScreenerBacktestCog(bot))
    print("[StockScreener] StockScreenerBacktestCog が正常にロードされました。")
