import asyncio
import json
import os
import random
import subprocess
import urllib.request
from datetime import datetime
from typing import List, Optional, Dict, Any

import discord
from discord.ext import commands
import numpy as np
import pandas as pd
import yfinance as yf
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import log_loss
from sklearn.preprocessing import StandardScaler


class ModelEtaCog(commands.Cog):
    """
    投資機械学習モデル η (Eta) - Discord Cog
    東証GPS約3,500銘柄に対する8テクニカル指標計算、100日学習×30日ローリング推論。
    進捗表示および動的閾値制御に Log Loss を活用。
    """

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.symbols_file = "tse_gps_symbols.json"
        self.log_file = "logs/eta_predictions.csv"
        self.symbols_data: List[Dict[str, str]] = []
        self.reload_symbols()
        os.makedirs("logs", exist_ok=True)

    def reload_symbols(self):
        """銘柄マスターJSONの再読み込み"""
        if os.path.exists(self.symbols_file):
            try:
                with open(self.symbols_file, "r", encoding="utf-8") as f:
                    self.symbols_data = json.load(f)
                    print(f"[ModelEta] 銘柄マスター読み込み完了: {len(self.symbols_data)} 銘柄")
            except Exception as e:
                print(f"[ModelEta] 銘柄ファイルのロードに失敗しました: {e}")
        
        if not self.symbols_data:
            self.symbols_data = [{"code": "7203", "name": "トヨタ自動車", "market": "Prime"}]

    # --- 8つのテクニカル指標算出 (標準偏差を除く) ---
    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        close = df["Close"]
        high = df["High"]
        low = df["Low"]

        # 1. MACD
        ema12 = close.ewm(span=12, adjust=False).mean()
        ema26 = close.ewm(span=26, adjust=False).mean()
        df["feat_macd"] = ema12 - ema26
        df["feat_macd_signal"] = df["feat_macd"].ewm(span=9, adjust=False).mean()
        df["feat_macd_hist"] = df["feat_macd"] - df["feat_macd_signal"]

        # 2. RSI (14日)
        delta = close.diff()
        gain = (delta.where(delta > 0, 0)).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rs = gain / (loss + 1e-8)
        df["feat_rsi"] = 100 - (100 / (1 + rs))

        # 3. RCI (9日)
        def calc_rci(series):
            n = len(series)
            ranks = np.arange(n, 0, -1)
            price_ranks = series.rank(ascending=False).values
            d_sq = np.sum((ranks - price_ranks) ** 2)
            return (1 - (6 * d_sq) / (n * (n**2 - 1))) * 100

        df["feat_rci"] = close.rolling(9).apply(calc_rci, raw=False)

        # 4. DMI (14日)
        up_move = high.diff()
        down_move = -low.diff()
        plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0)
        minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0)
        tr = pd.concat(
            [
                high - low,
                (high - close.shift()).abs(),
                (low - close.shift()).abs(),
            ],
            axis=1,
        ).max(axis=1)
        atr = tr.rolling(14).mean()
        plus_di = 100 * pd.Series(plus_dm, index=df.index).rolling(14).mean() / (atr + 1e-8)
        minus_di = 100 * pd.Series(minus_dm, index=df.index).rolling(14).mean() / (atr + 1e-8)
        dx = (plus_di - minus_di).abs() / (plus_di + minus_di + 1e-8) * 100
        df["feat_plus_di"] = plus_di
        df["feat_minus_di"] = minus_di
        df["feat_adx"] = dx.rolling(14).mean()

        # 5. ストキャスティクス (9日)
        low9 = low.rolling(9).min()
        high9 = high.rolling(9).max()
        df["feat_stoch_k"] = 100 * (close - low9) / (high9 - low9 + 1e-8)
        df["feat_stoch_d"] = df["feat_stoch_k"].rolling(3).mean()

        # 6. 移動平均乖離率 (25日)
        ma25 = close.rolling(25).mean()
        df["feat_ma_bias"] = (close - ma25) / ma25 * 100

        # 7. サイコロジカルライン (12日)
        is_up = (delta > 0).astype(int)
        df["feat_psychological"] = is_up.rolling(12).sum() / 12 * 100

        # 8. モメンタム (10日)
        df["feat_momentum"] = close - close.shift(10)

        # ターゲット (翌日上昇なら 1、それ以外は 0)
        df["target"] = (close.shift(-1) > close).astype(int)

        return df

    # --- モデル η ローリング学習＆予測コア ---
    async def run_eta_rolling_pipeline(
        self, df: pd.DataFrame, status_msg: discord.Message, symbol_name: str
    ) -> Optional[Dict[str, Any]]:
        df = self.calculate_indicators(df)
        feature_cols = [c for c in df.columns if c.startswith("feat_")]
        clean_df = df.dropna(subset=feature_cols + ["target"])

        if len(clean_df) < 130:
            return None

        probs = []
        actuals = []
        losses = []

        for i in range(30):
            idx_end = len(clean_df) - 30 + i
            sub_df = clean_df.iloc[idx_end - 100 : idx_end]

            if len(sub_df) < 80:
                continue

            X_train = sub_df[feature_cols].iloc[:-1]
            y_train = sub_df["target"].iloc[:-1]
            X_latest = sub_df[feature_cols].iloc[[-1]]

            if len(np.unique(y_train)) < 2:
                continue

            scaler = StandardScaler()
            X_train_scaled = scaler.fit_transform(X_train)
            X_latest_scaled = scaler.transform(X_latest)

            model = LogisticRegression(C=1.0, max_iter=200, solver="lbfgs")
            model.fit(X_train_scaled, y_train)

            prob = model.predict_proba(X_latest_scaled)[0][1]
            actual = sub_df["target"].iloc[-1]

            probs.append(prob)
            actuals.append(actual)

            p_clipped = np.clip(prob, 1e-15, 1 - 1e-15)
            single_loss = -(actual * np.log(p_clipped) + (1 - actual) * np.log(1 - p_clipped))
            losses.append(single_loss)

            if (i + 1) % 5 == 0 or i == 29:
                current_loss_avg = float(np.mean(losses)) if losses else 0.693
                try:
                    await status_msg.edit(
                        content=f"特徴量計算およびローリング学習中... [{i+1}/30 完了 | 直近Loss: {current_loss_avg:.3f}]"
                    )
                except Exception:
                    pass
                await asyncio.sleep(0.1)

        if not probs:
            return None

        latest_prob = probs[-1]
        avg_prob = float(np.mean(probs))
        avg_loss = float(np.mean(losses)) if losses else 0.693

        predictions = [1 if p >= 0.5 else 0 for p in probs]
        matches = sum(1 for p, a in zip(predictions, actuals) if p == a)
        accuracy = (matches / len(probs)) * 100 if probs else 0.0

        buy_threshold = 0.55
        sell_threshold = 0.45

        if avg_loss >= 0.693:
            buy_threshold += 0.05
            sell_threshold -= 0.05
        elif avg_loss < 0.650:
            buy_threshold -= 0.02
            sell_threshold += 0.02

        latest_row = clean_df.iloc[-1]

        return {
            "latest_prob": latest_prob,
            "avg_prob": avg_prob,
            "avg_loss": avg_loss,
            "accuracy": accuracy,
            "buy_threshold": buy_threshold,
            "sell_threshold": sell_threshold,
            "rsi": latest_row["feat_rsi"],
            "rci": latest_row["feat_rci"],
            "bias": latest_row["feat_ma_bias"],
        }

    # --- ログ書き込み & Git Push ---
    def log_and_push(self, record: Dict[str, Any]):
        file_exists = os.path.exists(self.log_file)
        df_log = pd.DataFrame([record])
        df_log.to_csv(self.log_file, mode="a", header=not file_exists, index=False)

        def git_sync():
            try:
                subprocess.run(["git", "add", self.log_file], check=True, capture_output=True)
                subprocess.run(
                    ["git", "commit", "-m", f"chore: log model eta [{record['symbol']}] [skip ci]"],
                    check=True,
                    capture_output=True,
                )
                subprocess.run(["git", "push"], check=True, capture_output=True)
            except Exception as e:
                print(f"[ModelEta] Git Push スキップ (ローカル保存完了): {e}")

        asyncio.create_task(asyncio.to_thread(git_sync))

    # --- 銘柄検索ユーティリティ ---
    def find_symbol_info(self, query: str) -> Optional[Dict[str, str]]:
        query = query.replace(".T", "").replace(".t", "").strip()
        for s in self.symbols_data:
            if s["code"] == query:
                return s
        for s in self.symbols_data:
            if query in s["name"]:
                return s
        return None

    # --- Discord コマンド: 単一銘柄予測 ---
    @commands.command(name="eta")
    async def predict_eta(self, ctx: commands.Context, target_input: str = "random"):
        """
        モデル η 予測実行コマンド
        使用例:
          !eta 7203      (トヨタ自動車)
          !eta ソニー    (銘柄名検索)
          !eta random    (全3500銘柄からランダム選定)
        """
        status_msg = await ctx.send("銘柄マスター照合中...")

        symbol_info = None
        if target_input.lower() == "random":
            symbol_info = random.choice(self.symbols_data)
        else:
            symbol_info = self.find_symbol_info(target_input)

        if not symbol_info:
            await status_msg.edit(content=f"エラー: 銘柄 `{target_input}` が東証GPSマスター内に見つかりませんでした。")
            return

        target_symbol = f"{symbol_info['code']}.T"
        await status_msg.edit(content=f"株価データダウンロード中... (160日分: {symbol_info['name']} / {target_symbol})")

        try:
            df = await asyncio.to_thread(
                yf.download, target_symbol, period="1y", progress=False
            )
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
        except Exception as e:
            await status_msg.edit(content=f"エラー: データ取得失敗 (`{e}`)")
            return

        if df.empty or len(df) < 130:
            await status_msg.edit(content=f"エラー: {symbol_info['name']} の日足データ件数が不足しています。")
            return

        result = await self.run_eta_rolling_pipeline(df, status_msg, symbol_info["name"])

        if not result:
            await status_msg.edit(content="エラー: 分析中に例外が発生しました。")
            return

        p_latest = result["latest_prob"]
        buy_t = result["buy_threshold"]
        sell_t = result["sell_threshold"]

        if p_latest >= buy_t:
            signal = "BUY (買いシグナル)"
            color = 0x2ecc71
        elif p_latest <= sell_t:
            signal = "SELL (売りシグナル)"
            color = 0xe74c3c
        else:
            signal = "HOLD (静観)"
            color = 0xf1c40f

        embed = discord.Embed(
            title=f"モデル η 分析レポート: {symbol_info['name']} ({target_symbol})",
            description=f"市場区分: 東証{symbol_info['market']} | 対象マスター数: {len(self.symbols_data)}",
            color=color,
        )
        embed.add_field(name="判定シグナル", value=f"**{signal}**", inline=False)
        embed.add_field(name="翌日上昇確率", value=f"**{p_latest * 100:.2f}%**", inline=True)
        embed.add_field(name="30日平均 Loss", value=f"**{result['avg_loss']:.4f}**", inline=True)
        embed.add_field(name="ローリング勝率", value=f"{result['accuracy']:.1f}%", inline=True)

        embed.add_field(
            name="動的適用閾値",
            value=f"BUY 閾値: `{buy_t*100:.1f}%` | SELL 閾値: `{sell_t*100:.1f}%`",
            inline=False,
        )
        embed.add_field(
            name="主要テクニカル指標",
            value=f"RSI (14): `{result['rsi']:.1f}` | RCI (9): `{result['rci']:.1f}` | 25日乖離率: `{result['bias']:.2f}%`",
            inline=False,
        )
        embed.set_footer(text="Model Eta | Raspberry Pi 2GB Restricted | Auto Logged")

        await status_msg.edit(content="", embed=embed)

        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "symbol": target_symbol,
            "name": symbol_info["name"],
            "market": symbol_info["market"],
            "latest_prob": p_latest,
            "avg_loss": result["avg_loss"],
            "avg_prob": result["avg_prob"],
            "accuracy": result["accuracy"],
            "buy_threshold": buy_t,
            "sell_threshold": sell_t,
            "signal": signal,
        }
        self.log_and_push(log_entry)

    # --- Discord コマンド: 複数ランダム銘柄バッチ学習 ---
    @commands.command(name="eta_rand")
    async def predict_eta_random_batch(self, ctx: commands.Context, count: int = 3):
        """
        複数銘柄をランダム選定してモデル η で連続分析
        使用例: !eta_rand 3
        """
        count = min(max(1, count), 5)
        batch_msg = await ctx.send(f"バッチ処理開始 (全 {count} 銘柄)")

        for i in range(count):
            matched = random.choice(self.symbols_data)
            await batch_msg.edit(content=f"[{i+1}/{count}] 銘柄分析中: {matched['name']} ({matched['code']}.T)")
            await self.predict_eta(ctx, target_input=matched["code"])
            await asyncio.sleep(1)

        await ctx.send(f"全 {count} 銘柄の分析処理が完了しました。")

    # --- 銘柄マスター自動更新コマンド (HTTP 404 回避修正) ---
    @commands.command(name="update_symbols")
    @commands.has_permissions(administrator=True)
    async def update_symbols_cmd(self, ctx: commands.Context):
        """JPX公式CSVから3,500銘柄マスターデータを最新化する管理者コマンド"""
        msg = await ctx.send("JPX公式サイトより全東証銘柄データ(CSV)を取得中...")

        def fetch_jpx():
            # ヘッダー付与による 403 / 404 回避処理
            url = "https://www.jpx.co.jp/markets/statistics-equities/misc/tvdivq0000001vg2-att/data_j.csv"
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
            )
            
            with urllib.request.urlopen(req) as response:
                df = pd.read_csv(response, encoding="shift_jis")

            target_markets = ["プライム（内国株式）", "スタンダード（内国株式）", "グロース（内国株式）"]
            filtered = df[df["市場・商品区分"].isin(target_markets)]

            symbols_list = []
            for _, row in filtered.iterrows():
                code = str(row["コード"]).strip()
                if len(code) == 4 and code.isdigit():
                    market_raw = str(row["市場・商品区分"])
                    market_name = "Prime" if "プライム" in market_raw else ("Standard" if "スタンダード" in market_raw else "Growth")
                    symbols_list.append({
                        "code": code,
                        "name": str(row["銘柄名"]).strip(),
                        "market": market_name
                    })

            with open(self.symbols_file, "w", encoding="utf-8") as f:
                json.dump(symbols_list, f, ensure_ascii=False, indent=2)

            return len(symbols_list)

        try:
            count = await asyncio.to_thread(fetch_jpx)
            self.reload_symbols()
            await msg.edit(content=f"銘柄マスターの全更新が完了しました。対象: {count} 銘柄")
        except Exception as e:
            await msg.edit(content=f"エラー: 銘柄マスター更新失敗 (`{e}`)")


async def setup(bot: commands.Bot):
    await bot.add_cog(ModelEtaCog(bot))

