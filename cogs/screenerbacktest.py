import asyncio
import sqlite3
import json
import os
import sys
import math
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any, Union, Tuple
from concurrent.futures import ThreadPoolExecutor
from enum import Enum

import discord
from discord import app_commands
from discord.ext import commands
import numpy as np
import pandas as pd

try:
    import yfinance as yf
    import config
    HAS_REQUIRED_LIBS = True
except ImportError as e:
    print(f"[StockScreener Critical Error] ライブラリのインポートに失敗しました: {e}", file=sys.stderr)
    HAS_REQUIRED_LIBS = False


JAPAN_STOCK_SYMBOLS = [
    ("9984", "ソフトバンクG"),
    ("6758", "Sony"),
    ("7203", "トヨタ"),
    ("9437", "NTT DoCoMo"),
    ("8306", "三菱UFJ"),
    ("8411", "みずほFG"),
    ("8001", "伊藤忠"),
    ("9020", "JR東日本"),
    ("6902", "デンソー"),
    ("9983", "ファーストリテイリング"),
]

JAPAN_STOCK_TICKERS = [f"{code}.T" for code, _ in JAPAN_STOCK_SYMBOLS]


class ScreeningCategory(Enum):
    TECHNICAL = "テクニカル指標"
    FUNDAMENTAL = "ファンダメンタルズ"
    FINANCIAL_SAFETY = "財務・安全性"
    PRICE_VOLUME = "株価・出来高"


TECHNICAL_INDICATORS = {
    "バイアス25": ("bias_25", "25日線からの乖離率"),
    "バイアス75": ("bias_75", "75日線からの乖離率"),
    "バイアス200": ("bias_200", "200日線からの乖離率"),
    "MACD": ("macd", "トレンド追従"),
    "RSI": ("rsi", "オシレーター"),
    "RCI": ("rci_9", "価格の買われすぎ/売られすぎ"),
    "DMI": ("plus_di", "トレンド強度"),
    "VWAP乖離": ("vwap_bias", "VWAP乖離率"),
    "騰落率1週間": ("roc_1w", "1週間の騰落率"),
    "騰落率1ヶ月": ("roc_1m", "1ヶ月の騰落率"),
}

FUNDAMENTAL_INDICATORS = {
    "PER (予想)": ("forward_per", "予想PER"),
    "PER (実績)": ("per", "実績PER"),
    "PBR": ("pbr", "株価純資産倍率"),
    "PSR": ("psr", "株価売上高倍率"),
    "ROE": ("roe", "自己資本利益率"),
    "配当利回り": ("dividend_yield", "配当利回り"),
}

FINANCIAL_SAFETY_INDICATORS = {
    "営業利益率": ("operating_margin", "営業利益率"),
    "売上高成長率": ("revenue_growth", "売上成長率"),
    "EPS成長率": ("earnings_growth", "利益成長率"),
    "配当性向": ("payout_ratio", "配当性向"),
    "時価総額": ("market_cap_oku", "時価総額（億円）"),
}

PRICE_VOLUME_INDICATORS = {
    "52週高値からの下落": ("high_52w_drop", "52週高値比"),
    "52週安値からの上昇": ("low_52w_rise", "52週安値比"),
    "出来高変化率": ("volume_change", "出来高変化"),
}


@dataclass
class TradePosition:
    symbol: str
    side: str
    entry_date: datetime
    entry_price: float
    shares: int
    stop_loss_price: Optional[float] = None
    take_profit_price: Optional[float] = None
    is_hedged: bool = False
    current_price: float = 0.0
    unrealized_pnl: float = 0.0
    highest_price: float = 0.0


@dataclass
class BacktestConfig:
    initial_capital: float = 10000000.0
    commission_rate: float = 0.001
    slippage_rate: float = 0.001
    tax_rate: float = 0.20315
    short_fee_daily: float = 0.0115 / 365.0
    max_position_percent: float = 0.10
    max_positions: int = 10
    allow_short: bool = False
    allow_pyramiding: bool = False
    pyramiding_step: float = 0.05
    pyramiding_trigger_down: float = 0.05
    allow_hedge: bool = False
    hedge_trigger_drawdown: float = 0.10
    stop_loss_percent: Optional[float] = None
    take_profit_percent: Optional[float] = None
    trailing_stop_percent: Optional[float] = None
    partial_exit_profit: Optional[float] = None
    partial_exit_loss: Optional[float] = None


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
            if n < 2:
                return 0
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
            "pcfr": info.get("priceToOperatingCashFlow"),
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
        }


class DatabaseManager:
    def __init__(self, db_path: str = "screener_data.db"):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute('''
            CREATE TABLE IF NOT EXISTS stocks (
                code TEXT PRIMARY KEY,
                name TEXT,
                market TEXT,
                last_update TIMESTAMP,
                bias_25 REAL,
                bias_75 REAL,
                bias_200 REAL,
                macd REAL,
                rsi REAL,
                rci_9 REAL,
                plus_di REAL,
                vwap_bias REAL,
                roc_1w REAL,
                roc_1m REAL,
                roc_3m REAL,
                roc_1y REAL,
                per REAL,
                forward_per REAL,
                pbr REAL,
                psr REAL,
                roe REAL,
                dividend_yield REAL,
                operating_margin REAL,
                revenue_growth REAL,
                earnings_growth REAL,
                payout_ratio REAL,
                market_cap_oku REAL,
                high_52w_drop REAL,
                low_52w_rise REAL,
                volume_change REAL
            )
        ''')
        c.execute('CREATE INDEX IF NOT EXISTS idx_code ON stocks(code)')
        conn.commit()
        conn.close()

    def save_stock_data(self, code: str, name: str, market: str, tech_data: dict, fund_data: dict):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        
        all_data = {**tech_data, **fund_data}
        columns = ['code', 'name', 'market', 'last_update'] + list(all_data.keys())
        values = [code, name, market, datetime.now().isoformat()] + list(all_data.values())
        
        placeholders = ','.join(['?' for _ in columns])
        cols_str = ','.join(columns)
        
        c.execute(f'''
            INSERT OR REPLACE INTO stocks ({cols_str})
            VALUES ({placeholders})
        ''', values)
        conn.commit()
        conn.close()

    def get_all_stocks(self) -> List[Dict[str, Any]]:
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute('SELECT * FROM stocks')
        results = c.fetchall()
        conn.close()

        if not results:
            return []

        columns = [desc[0] for desc in c.description]
        stocks = []
        for row in results:
            stocks.append(dict(zip(columns, row)))

        return stocks

    def screening_filter(self, conditions: List[Dict[str, Any]], universe: Optional[str] = None) -> List[Dict[str, Any]]:
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()

        query = 'SELECT * FROM stocks WHERE 1=1'
        params = []

        for condition in conditions:
            field_name = condition.get("field")
            operator = condition.get("operator")
            threshold = condition.get("threshold")

            if not field_name or not operator or threshold is None:
                continue

            if operator == ">":
                query += f' AND {field_name} > ?'
                params.append(threshold)
            elif operator == ">=":
                query += f' AND {field_name} >= ?'
                params.append(threshold)
            elif operator == "<":
                query += f' AND {field_name} < ?'
                params.append(threshold)
            elif operator == "<=":
                query += f' AND {field_name} <= ?'
                params.append(threshold)
            elif operator == "==":
                query += f' AND {field_name} = ?'
                params.append(threshold)
            elif operator == "between":
                query += f' AND {field_name} BETWEEN ? AND ?'
                params.extend([threshold[0], threshold[1]])

        try:
            c.execute(query, params)
            results = c.fetchall()
            columns = [desc[0] for desc in c.description]
            conn.close()

            stocks = [dict(zip(columns, row)) for row in results]
            return stocks
        except Exception as e:
            print(f"[DB Error] {e}", file=sys.stderr)
            conn.close()
            return []


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
        for pos in self.positions[:]:
            should_exit = False

            if self.config.stop_loss_percent and pos.unrealized_pnl < 0:
                loss_pct = (abs(pos.unrealized_pnl) / (pos.entry_price * pos.shares)) * 100
                if loss_pct >= self.config.stop_loss_percent:
                    should_exit = True

            if self.config.take_profit_percent and pos.unrealized_pnl > 0:
                profit_pct = (pos.unrealized_pnl / (pos.entry_price * pos.shares)) * 100
                if profit_pct >= self.config.take_profit_percent:
                    should_exit = True

            if should_exit:
                exit_price = pos.current_price * (1 - self.config.slippage_rate)
                if pos.side == "SHORT":
                    exit_price = pos.current_price * (1 + self.config.slippage_rate)

                commission = (exit_price * pos.shares) * self.config.commission_rate
                net_pnl = pos.unrealized_pnl - commission
                tax = max(0, net_pnl * self.config.tax_rate) if net_pnl > 0 else 0

                self.cash += exit_price * pos.shares - commission
                self.total_tax_paid += tax
                self.trade_logs.append({
                    "symbol": pos.symbol,
                    "side": pos.side,
                    "entry_date": pos.entry_date,
                    "exit_date": current_date,
                    "entry_price": pos.entry_price,
                    "exit_price": exit_price,
                    "shares": pos.shares,
                    "gross_pnl": pos.unrealized_pnl,
                    "net_pnl": net_pnl
                })
                self.positions.remove(pos)

    def _process_entries(self, current_date: pd.Timestamp, screening_signals: Dict[str, pd.Series]):
        for symbol, signals in screening_signals.items():
            if current_date not in signals.index or not signals.loc[current_date]:
                continue

            df = self.data_map.get(symbol)
            if df is None or current_date not in df.index:
                continue

            entry_price = float(df.loc[current_date, "Close"])

            existing_long = len([p for p in self.positions if p.side == "LONG"])
            existing_short = len([p for p in self.positions if p.side == "SHORT"])

            should_enter_long = existing_long < self.config.max_positions
            should_enter_short = self.config.allow_short and existing_short < self.config.max_positions

            if not should_enter_long and not should_enter_short:
                continue

            side = "LONG" if should_enter_long else "SHORT"
            entry_price_with_slippage = entry_price * (1 + self.config.slippage_rate) if side == "LONG" else entry_price * (1 - self.config.slippage_rate)

            allocation = self.cash * self.config.max_position_percent
            shares = int(allocation / entry_price_with_slippage)

            if shares > 0:
                commission = (entry_price_with_slippage * shares) * self.config.commission_rate
                total_cost = (entry_price_with_slippage * shares) + commission

                if self.cash >= total_cost or side == "SHORT":
                    if side == "LONG":
                        self.cash -= total_cost
                    pos = TradePosition(
                        symbol=symbol,
                        side=side,
                        entry_date=current_date,
                        entry_price=entry_price_with_slippage,
                        shares=shares
                    )
                    self.positions.append(pos)

    def _empty_result(self) -> TradeResult:
        return TradeResult(
            initial_capital=self.config.initial_capital,
            final_capital=self.config.initial_capital,
            total_profit_loss=0,
            tax_amount=0,
            net_profit=0,
            total_trades=0,
            win_trades=0,
            lose_trades=0,
            win_rate=0.0,
            profit_factor=0.0,
            max_drawdown_percent=0.0,
            max_drawdown_amount=0.0,
            sharpe_ratio=0.0
        )


class ScreeningDashboardView(discord.ui.View):
    def __init__(self, cog: 'StockScreenerBacktestCog', timeout: float = 600):
        super().__init__(timeout=timeout)
        self.cog = cog
        self.selected_universe = "ALL"
        self.screening_conditions: List[Dict[str, Any]] = []
        self.screening_results: List[Dict[str, Any]] = []
        self.parent_message: Optional[discord.Message] = None

    async def update_dashboard(self, parent_interaction: discord.Interaction):
        results = self.cog.db_manager.screening_filter(self.screening_conditions, self.selected_universe)
        self.screening_results = results

        embed = discord.Embed(
            title="SCREENING DASHBOARD",
            color=0x00D9FF,
            description=f"Universe: {self.selected_universe} | Matches: {len(results)}"
        )
        embed.add_field(name="Active Conditions", value=f"{len(self.screening_conditions)}", inline=True)
        embed.add_field(name="Results", value=f"{len(results)} stocks", inline=True)

        await parent_interaction.edit_original_response(embed=embed, view=self)

    @discord.ui.button(label="Universe Select", style=discord.ButtonStyle.primary)
    async def button_universe(self, interaction: discord.Interaction, button: discord.ui.Button):
        select = discord.ui.Select(
            placeholder="Choose universe",
            options=[
                discord.SelectOption(label="ALL", value="all"),
                discord.SelectOption(label="Nikkei 225", value="nikkei"),
                discord.SelectOption(label="TOPIX 100", value="topix"),
                discord.SelectOption(label="Prime", value="prime"),
                discord.SelectOption(label="Standard", value="standard"),
                discord.SelectOption(label="Growth", value="growth"),
            ]
        )

        async def select_callback(select_interaction: discord.Interaction):
            self.selected_universe = select.values[0].upper()
            await self.update_dashboard(interaction)
            await select_interaction.response.defer()

        select.callback = select_callback
        view = discord.ui.View()
        view.add_item(select)
        await interaction.response.send_message("Select universe:", view=view, ephemeral=True)

    @discord.ui.button(label="Add Condition", style=discord.ButtonStyle.success)
    async def button_add_condition(self, interaction: discord.Interaction, button: discord.ui.Button):
        categories = [
            discord.SelectOption(label=cat.value, value=cat.name) for cat in ScreeningCategory
        ]
        select = discord.ui.Select(placeholder="Select category", options=categories)

        async def select_callback(select_interaction: discord.Interaction):
            category = select.values[0]
            
            if category == "TECHNICAL":
                options = [discord.SelectOption(label=k, value=v[0]) for k, v in TECHNICAL_INDICATORS.items()]
            elif category == "FUNDAMENTAL":
                options = [discord.SelectOption(label=k, value=v[0]) for k, v in FUNDAMENTAL_INDICATORS.items()]
            elif category == "FINANCIAL_SAFETY":
                options = [discord.SelectOption(label=k, value=v[0]) for k, v in FINANCIAL_SAFETY_INDICATORS.items()]
            else:
                options = [discord.SelectOption(label=k, value=v[0]) for k, v in PRICE_VOLUME_INDICATORS.items()]

            indicator_select = discord.ui.Select(placeholder="Select indicator", options=options[:25])

            async def indicator_callback(ind_interaction: discord.Interaction):
                field_name = indicator_select.values[0]
                await self._show_condition_modal(ind_interaction, field_name, interaction)

            indicator_select.callback = indicator_callback
            view = discord.ui.View()
            view.add_item(indicator_select)
            await select_interaction.response.send_message("Select indicator:", view=view, ephemeral=True)

        select.callback = select_callback
        view = discord.ui.View()
        view.add_item(select)
        await interaction.response.send_message("Select category:", view=view, ephemeral=True)

    async def _show_condition_modal(self, interaction: discord.Interaction, field_name: str, parent_interaction: discord.Interaction):
        class ConditionModal(discord.ui.Modal, title="Set Condition"):
            operator_input = discord.ui.TextInput(label="Operator (>, >=, <, <=, ==, between)", required=True)
            threshold_input = discord.ui.TextInput(label="Threshold Value", required=True)

            async def on_submit(self, modal_interaction: discord.Interaction):
                try:
                    op = operator_input.value.strip()
                    val = float(threshold_input.value.strip())
                    if op == "between":
                        val = [val, val]

                    self.parent_view.screening_conditions.append({
                        "field": field_name,
                        "operator": op,
                        "threshold": val
                    })
                    await self.parent_view.update_dashboard(parent_interaction)
                    await modal_interaction.response.defer()
                except ValueError:
                    await modal_interaction.response.send_message("Invalid threshold value", ephemeral=True)

        modal = ConditionModal()
        modal.parent_view = self
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Execute Screening", style=discord.ButtonStyle.green)
    async def button_execute(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.screening_results:
            await interaction.response.send_message("No results found", ephemeral=True)
            return

        await interaction.response.defer()
        embed = discord.Embed(title="SCREENING RESULTS", color=0x00FFA3)

        for stock in self.screening_results[:20]:
            name = stock.get("name", "N/A")
            code = stock.get("code", "N/A")
            per = f"{stock.get('per', 0):.1f}" if stock.get("per") else "N/A"
            pbr = f"{stock.get('pbr', 0):.2f}" if stock.get("pbr") else "N/A"
            roe = f"{stock.get('roe', 0):.1f}%" if stock.get("roe") else "N/A"

            embed.add_field(
                name=f"{name} ({code})",
                value=f"PER: {per} | PBR: {pbr} | ROE: {roe}",
                inline=False
            )

        await interaction.followup.send(embed=embed)

    @discord.ui.button(label="Go to Backtest", style=discord.ButtonStyle.blurple)
    async def button_backtest(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.cog.current_screening_conditions = self.screening_conditions
        self.cog.current_screening_results = self.screening_results
        
        await interaction.response.defer()
        view = BacktestDashboardView(self.cog)
        embed = discord.Embed(title="BACKTEST DASHBOARD", color=0xFF6B6B)
        embed.add_field(name="Screening Conditions", value=f"{len(self.screening_conditions)} active", inline=True)
        
        await interaction.edit_original_response(embed=embed, view=view)


class BacktestDashboardView(discord.ui.View):
    def __init__(self, cog: 'StockScreenerBacktestCog', timeout: float = 600):
        super().__init__(timeout=timeout)
        self.cog = cog
        self.config = BacktestConfig()

    @discord.ui.button(label="Capital & Cost", style=discord.ButtonStyle.primary)
    async def button_capital(self, interaction: discord.Interaction, button: discord.ui.Button):
        class CapitalModal(discord.ui.Modal, title="Capital & Cost Settings"):
            initial_capital = discord.ui.TextInput(label="Initial Capital (JPY)", required=True)
            commission = discord.ui.TextInput(label="Commission Rate (%)", required=True)
            slippage = discord.ui.TextInput(label="Slippage Rate (%)", required=True)

            async def on_submit(self, modal_self, modal_interaction: discord.Interaction):
                try:
                    self.parent_config.initial_capital = float(initial_capital.value)
                    self.parent_config.commission_rate = float(commission.value) / 100.0
                    self.parent_config.slippage_rate = float(slippage.value) / 100.0
                    await modal_interaction.response.send_message("Settings saved", ephemeral=True)
                except ValueError:
                    await modal_interaction.response.send_message("Invalid input", ephemeral=True)

        modal = CapitalModal()
        modal.parent_config = self.config
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Trade Direction", style=discord.ButtonStyle.primary)
    async def button_direction(self, interaction: discord.Interaction, button: discord.ui.Button):
        select = discord.ui.Select(
            placeholder="Select trade direction",
            options=[
                discord.SelectOption(label="LONG Only", value="long"),
                discord.SelectOption(label="SHORT Allowed", value="short"),
                discord.SelectOption(label="Both (Hedge)", value="both"),
            ]
        )

        async def select_callback(select_interaction: discord.Interaction):
            if select.values[0] == "long":
                self.config.allow_short = False
            elif select.values[0] == "short":
                self.config.allow_short = True
            else:
                self.config.allow_short = True
                self.config.allow_hedge = True

            await select_interaction.response.send_message("Trade direction set", ephemeral=True)

        select.callback = select_callback
        view = discord.ui.View()
        view.add_item(select)
        await interaction.response.send_message("Select trade direction:", view=view, ephemeral=True)

    @discord.ui.button(label="Risk Management", style=discord.ButtonStyle.primary)
    async def button_risk(self, interaction: discord.Interaction, button: discord.ui.Button):
        class RiskModal(discord.ui.Modal, title="Risk Management"):
            stop_loss = discord.ui.TextInput(label="Stop Loss (%)", required=False)
            take_profit = discord.ui.TextInput(label="Take Profit (%)", required=False)
            trailing_stop = discord.ui.TextInput(label="Trailing Stop (%)", required=False)

            async def on_submit(self, modal_self, modal_interaction: discord.Interaction):
                try:
                    if stop_loss.value:
                        self.parent_config.stop_loss_percent = float(stop_loss.value)
                    if take_profit.value:
                        self.parent_config.take_profit_percent = float(take_profit.value)
                    if trailing_stop.value:
                        self.parent_config.trailing_stop_percent = float(trailing_stop.value)
                    await modal_interaction.response.send_message("Risk settings saved", ephemeral=True)
                except ValueError:
                    await modal_interaction.response.send_message("Invalid input", ephemeral=True)

        modal = RiskModal()
        modal.parent_config = self.config
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Execute Backtest", style=discord.ButtonStyle.green)
    async def button_execute(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()

        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            self.cog.executor,
            self.cog._execute_backtest_pipeline,
            self.config,
            self.cog.current_screening_conditions,
            self.cog.current_screening_results
        )

        if not result:
            await interaction.followup.send("Backtest failed")
            return

        embed = discord.Embed(
            title="BACKTEST RESULTS",
            color=0x00FFA3 if result.net_profit > 0 else 0xFF0055
        )

        embed.add_field(
            name="Capital & PnL",
            value=f"Initial: ¥{result.initial_capital:,.0f}\nFinal: ¥{result.final_capital:,.0f}\nNet Profit: ¥{result.net_profit:,.0f}",
            inline=False
        )

        embed.add_field(
            name="Performance",
            value=f"Win Rate: {result.win_rate:.1f}%\nTotal Trades: {result.total_trades}\nProfit Factor: {result.profit_factor:.2f}\nSharpe Ratio: {result.sharpe_ratio:.2f}",
            inline=False
        )

        await interaction.followup.send(embed=embed)


class StockScreenerBacktestCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.executor = ThreadPoolExecutor(max_workers=4)
        self.db_manager = DatabaseManager("screener_data.db")
        self.current_screening_conditions: List[Dict[str, Any]] = []
        self.current_screening_results: List[Dict[str, Any]] = []

    @app_commands.command(name="screening", description="Interactive stock screening dashboard")
    async def screening(self, interaction: discord.Interaction):
        view = ScreeningDashboardView(self)
        embed = discord.Embed(title="SCREENING DASHBOARD", color=0x00D9FF)
        embed.add_field(name="Status", value="Ready to screen", inline=True)
        await interaction.response.send_message(embed=embed, view=view)

    @app_commands.command(name="backtest", description="Execute backtest with custom settings")
    async def backtest(self, interaction: discord.Interaction):
        view = BacktestDashboardView(self)
        embed = discord.Embed(title="BACKTEST DASHBOARD", color=0xFF6B6B)
        embed.add_field(name="Status", value="Configure backtest parameters", inline=True)
        await interaction.response.send_message(embed=embed, view=view)

    @app_commands.command(name="update_screener_cache", description="Update screener database from yfinance")
    async def update_screener_cache(self, interaction: discord.Interaction):
        await interaction.response.send_message("Cache update started...")
        progress_msg = await interaction.original_response()

        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            self.executor,
            self._update_cache_task,
            interaction,
            progress_msg
        )

    def _update_cache_task(self, interaction: discord.Interaction, progress_msg: discord.Message):
        try:
            total = len(JAPAN_STOCK_TICKERS)

            for idx, sym in enumerate(JAPAN_STOCK_TICKERS):
                try:
                    data = yf.download(sym, period="2y", progress=False)
                    info = yf.Ticker(sym).info

                    tech_data = {}
                    fund_data = {}

                    if not data.empty:
                        df = IndicatorEngine.calculate_technical_indicators(data)
                        tech_data = {
                            "bias_25": float(df["bias_25"].iloc[-1]) if pd.notna(df["bias_25"].iloc[-1]) else None,
                            "bias_75": float(df["bias_75"].iloc[-1]) if pd.notna(df["bias_75"].iloc[-1]) else None,
                            "bias_200": float(df["bias_200"].iloc[-1]) if pd.notna(df["bias_200"].iloc[-1]) else None,
                            "macd": float(df["macd"].iloc[-1]) if pd.notna(df["macd"].iloc[-1]) else None,
                            "rsi": float(df["rsi"].iloc[-1]) if pd.notna(df["rsi"].iloc[-1]) else None,
                            "rci_9": float(df["rci_9"].iloc[-1]) if pd.notna(df["rci_9"].iloc[-1]) else None,
                            "plus_di": float(df["plus_di"].iloc[-1]) if pd.notna(df["plus_di"].iloc[-1]) else None,
                            "vwap_bias": float(df["vwap_bias"].iloc[-1]) if pd.notna(df["vwap_bias"].iloc[-1]) else None,
                            "roc_1w": float(df["roc_1w"].iloc[-1]) if pd.notna(df["roc_1w"].iloc[-1]) else None,
                            "roc_1m": float(df["roc_1m"].iloc[-1]) if pd.notna(df["roc_1m"].iloc[-1]) else None,
                            "roc_3m": float(df["roc_3m"].iloc[-1]) if pd.notna(df["roc_3m"].iloc[-1]) else None,
                            "roc_1y": float(df["roc_1y"].iloc[-1]) if pd.notna(df["roc_1y"].iloc[-1]) else None,
                            "high_52w_drop": float(df["high_52w_drop"].iloc[-1]) if pd.notna(df["high_52w_drop"].iloc[-1]) else None,
                            "low_52w_rise": float(df["low_52w_rise"].iloc[-1]) if pd.notna(df["low_52w_rise"].iloc[-1]) else None,
                            "volume_change": float(df["volume_change"].iloc[-1]) if pd.notna(df["volume_change"].iloc[-1]) else None,
                        }

                    fund_data = IndicatorEngine.process_fundamental_metrics(info)
                    fund_data = {k: (float(v) if isinstance(v, (int, np.integer)) else v) for k, v in fund_data.items()}

                    code = sym.replace(".T", "")
                    name = info.get("longName", code)
                    market = info.get("market", "Unknown")

                    self.db_manager.save_stock_data(code, name, market, tech_data, fund_data)

                except Exception as e:
                    print(f"Error processing {sym}: {e}", file=sys.stderr)

                pct = ((idx + 1) / total) * 100
                print(f"[Cache Update] {pct:.0f}% ({idx + 1}/{total})")

        except Exception as e:
            print(f"[Cache Update Error] {e}", file=sys.stderr)

    def _execute_backtest_pipeline(
        self,
        config: BacktestConfig,
        screening_conditions: List[Dict[str, Any]],
        screening_results: List[Dict[str, Any]]
    ) -> Optional[TradeResult]:
        try:
            if not screening_results:
                return None

            target_symbols = [f"{s['code']}.T" for s in screening_results[:20]]
            historical_map = {}
            screening_signals = {}

            for sym in target_symbols:
                try:
                    data = yf.download(sym, period="2y", progress=False)
                    if data.empty or len(data) < 50:
                        continue

                    df_calc = IndicatorEngine.calculate_technical_indicators(data)
                    historical_map[sym] = df_calc

                    signals = pd.Series(False, index=df_calc.index)
                    for idx in range(len(df_calc)):
                        row_dict = df_calc.iloc[idx].to_dict()
                        row_dict['code'] = sym.replace('.T', '')
                        
                        match = True
                        for condition in screening_conditions:
                            field = condition.get('field')
                            op = condition.get('operator')
                            threshold = condition.get('threshold')
                            
                            val = row_dict.get(field)
                            if val is None:
                                match = False
                                break
                            
                            if op == '>' and not (val > threshold):
                                match = False
                                break
                            elif op == '>=' and not (val >= threshold):
                                match = False
                                break
                            elif op == '<' and not (val < threshold):
                                match = False
                                break
                            elif op == '<=' and not (val <= threshold):
                                match = False
                                break
                            elif op == '==' and not (val == threshold):
                                match = False
                                break
                            elif op == 'between' and not (threshold[0] <= val <= threshold[1]):
                                match = False
                                break
                        
                        if match:
                            signals.iloc[idx] = True

                    screening_signals[sym] = signals

                except Exception as e:
                    print(f"Error processing {sym}: {e}", file=sys.stderr)
                    continue

            if not historical_map:
                return None

            engine = RealisticBacktestEngine(config, historical_map)
            return engine.run(screening_signals)

        except Exception as e:
            print(f"[Backtest Error] {e}", file=sys.stderr)
            return None


async def setup(bot: commands.Bot):
    if not HAS_REQUIRED_LIBS:
        print("[StockScreener Error] Missing required libraries", file=sys.stderr)
        return
    await bot.add_cog(StockScreenerBacktestCog(bot))
    print("[StockScreener] StockScreenerBacktestCog loaded successfully")
