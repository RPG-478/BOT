import asyncio
import json
import os
import random
import subprocess
import sys
from datetime import datetime
from typing import List, Optional, Dict, Any

import discord
from discord.ext import commands
import numpy as np
import pandas as pd

# インポートエラーの検知
try:
    import yfinance as yf
    import lightgbm as lgb
    HAS_REQUIRED_LIBS = True
except ImportError as e:
    print(f"[ModelEta Critical Error] ライブラリのインポートに失敗しました: {e}", file=sys.stderr)
    HAS_REQUIRED_LIBS = False


class ModelEtaLgbCog(commands.Cog):
    """
    投資機械学習モデル η (Eta) - 高精度・バッチ一括同期完全版 (LightGBM)
    ・学習終了時に一括まとめて Git 同期（モデル・サマリー更新）
    ・バッチ進捗表示 [11/50 完了] 対応
    """

    MODEL_VERSION = "v2_precision"

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.symbols_file = "tse_gps_symbols.json"
        self.csv_source_file = "Assets/Issues_20260725170724.csv"
        self.log_file = "logs/eta_lgb_predictions.csv"
        self.models_dir = "models"
        self.summary_file = os.path.join(self.models_dir, "evaluation_summary.json")
        self.symbols_data: List[Dict[str, str]] = []
        self.eval_summary: Dict[str, Dict[str, Any]] = {}
        
        # ディレクトリ準備
        os.makedirs("logs", exist_ok=True)
        os.makedirs("Assets", exist_ok=True)
        os.makedirs(self.models_dir, exist_ok=True)
        
        # データおよび要約キャッシュのロード
        try:
            self.load_symbols()
            self.load_eval_summary()
        except Exception as e:
            print(f"[ModelEta Warning] 初期ロード中に例外が発生しました: {e}", file=sys.stderr)
            self.symbols_data = [{"code": "7203", "name": "トヨタ自動車", "market": "Prime"}]

    def load_symbols(self):
        """JSONマスターファイルの読み込み、存在しない場合はCSVから生成"""
        if os.path.exists(self.symbols_file):
            try:
                with open(self.symbols_file, "r", encoding="utf-8") as f:
                    self.symbols_data = json.load(f)
            except Exception as e:
                print(f"[ModelEta Error] JSON読み込み失敗: {e}", file=sys.stderr)

        if not self.symbols_data and os.path.exists(self.csv_source_file):
            print("[ModelEta] JSONマスターが見つかりません。CSVから自動生成します...")
            self.convert_csv_to_json()

        if not self.symbols_data:
            self.symbols_data = [{"code": "7203", "name": "トヨタ自動車", "market": "Prime"}]
        else:
            print(f"[ModelEta] {len(self.symbols_data)} 銘柄のロードに成功しました。")

    def load_eval_summary(self):
        """学習済みサマリー（評価結果）のロードと互換性判定"""
        if os.path.exists(self.summary_file):
            try:
                with open(self.summary_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    
                valid_entries = {}
                for code, entry in data.items():
                    if isinstance(entry, dict):
                        valid_entries[code] = entry
                
                self.eval_summary = valid_entries
                print(f"[ModelEta] {len(self.eval_summary)} 銘柄の評価サマリーをロードしました。")
            except Exception as e:
                print(f"[ModelEta Error] サマリーロード失敗: {e}", file=sys.stderr)

    def save_eval_summary(self):
        """評価サマリーのディスク保存"""
        try:
            with open(self.summary_file, "w", encoding="utf-8") as f:
                json.dump(self.eval_summary, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[ModelEta Error] サマリー保存失敗: {e}", file=sys.stderr)

    def convert_csv_to_json(self) -> int:
        """Assets配下のCSVを解析し、JSONマスターとして保存"""
        if not os.path.exists(self.csv_source_file):
            raise FileNotFoundError(f"ファイルが見つかりません: {self.csv_source_file}")

        encodings = ["utf-8-sig", "utf-8", "cp932", "shift_jis"]
        df = None

        for enc in encodings:
            try:
                df = pd.read_csv(self.csv_source_file, encoding=enc)
                print(f"[ModelEta] CSV読み込み成功 (文字コード: {enc})")
                break
            except UnicodeDecodeError:
                continue

        if df is None:
            df = pd.read_csv(self.csv_source_file, encoding="cp932", encoding_errors="replace")
        
        target_markets = ["プライム", "スタンダード", "グロース"]
        
        market_col = "市場区分" if "市場区分" in df.columns else ("市場・商品区分" if "市場・商品区分" in df.columns else None)
        code_col = "銘柄コード" if "銘柄コード" in df.columns else ("コード" if "コード" in df.columns else None)
        name_col = "銘柄名称" if "銘柄名称" in df.columns else ("銘柄名" if "銘柄名" in df.columns else None)

        if not (market_col and code_col and name_col):
            raise KeyError(f"CSVに必要なカラムが見つかりません。検出されたカラム: {list(df.columns)}")

        filtered = df[df[market_col].notna() & df[market_col].astype(str).str.contains("|".join(target_markets))]

        symbols_list = []
        for _, row in filtered.iterrows():
            code_raw = str(row[code_col]).strip()
            code = code_raw[:4]
            
            if len(code) == 4 and code.isdigit():
                market_raw = str(row[market_col])
                market_name = "Prime" if "プライム" in market_raw else ("Standard" if "スタンダード" in market_raw else "Growth")
                
                symbols_list.append({
                    "code": code,
                    "name": str(row[name_col]).strip(),
                    "market": market_name
                })

        with open(self.symbols_file, "w", encoding="utf-8") as f:
            json.dump(symbols_list, f, ensure_ascii=False, indent=2)

        self.symbols_data = symbols_list
        return len(symbols_list)

    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """8つのテクニカル指標を計算"""
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
        tr = pd.concat([high - low, (high - close.shift()).abs(), (low - close.shift()).abs()], axis=1).max(axis=1)
        atr = tr.rolling(14).mean()
        plus_di = 100 * pd.Series(plus_dm, index=df.index).rolling(14).mean() / (atr + 1e-8)
        minus_di = 100 * pd.Series(minus_dm, index=df.index).rolling(14).mean() / (atr + 1e-8)
        dx = (plus_di - minus_di).abs() / (plus_di + minus_di + 1e-8) * 100
        df["feat_plus_di"] = plus_di
        df["feat_minus_di"] = minus_di
        df["feat_adx"] = dx.rolling(14).mean()

        # 5. ストキャスティクス (9日, 3日)
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

    async def train_and_evaluate_model(
        self, symbol_code: str, df: pd.DataFrame, status_msg: Optional[discord.Message] = None, current_progress_str: str = ""
    ) -> Optional[Dict[str, Any]]:
        """高精度モデルの構築と安全なモデルファイルローカル保存"""
        df = self.calculate_indicators(df)
        feature_cols = [c for c in df.columns if c.startswith("feat_")]
        clean_df = df.dropna(subset=feature_cols + ["target"])

        if len(clean_df) < 250:
            return None

        probs = []
        actuals = []
        losses = []

        lgb_params = {
            "objective": "binary",
            "metric": "binary_logloss",
            "boosting_type": "gbdt",
            "num_leaves": 31,
            "learning_rate": 0.03,
            "feature_fraction": 0.8,
            "bagging_fraction": 0.8,
            "bagging_freq": 1,
            "verbose": -1,
            "seed": 42,
            "num_threads": 4
        }

        train_window = 200
        rolling_steps = 60

        last_model = None
        for i in range(rolling_steps):
            idx_end = len(clean_df) - rolling_steps + i
            sub_df = clean_df.iloc[idx_end - train_window : idx_end]

            if len(sub_df) < 100:
                continue

            X_train = sub_df[feature_cols].iloc[:-1]
            y_train = sub_df["target"].iloc[:-1]
            X_latest = sub_df[feature_cols].iloc[[-1]]

            if len(np.unique(y_train)) < 2:
                continue

            train_data = lgb.Dataset(X_train, label=y_train)
            last_model = lgb.train(lgb_params, train_data, num_boost_round=150)

            prob = last_model.predict(X_latest)[0]
            actual = sub_df["target"].iloc[-1]

            probs.append(prob)
            actuals.append(actual)

            p_clipped = np.clip(prob, 1e-15, 1 - 1e-15)
            single_loss = -(actual * np.log(p_clipped) + (1 - actual) * np.log(1 - p_clipped))
            losses.append(single_loss)

            if status_msg and ((i + 1) % 15 == 0 or i == rolling_steps - 1):
                current_loss_avg = float(np.mean(losses)) if losses else 0.693
                try:
                    prefix = f"{current_progress_str}\n" if current_progress_str else ""
                    await status_msg.edit(
                        content=f"{prefix}【モデル学習中】検証 [{i+1}/{rolling_steps} 完了 | 直近Loss: {current_loss_avg:.3f}]"
                    )
                except Exception:
                    pass
                await asyncio.sleep(0.05)

        if not probs or last_model is None:
            return None

        # 最新250日での最終モデル構築
        final_X = clean_df[feature_cols].iloc[-250:]
        final_y = clean_df["target"].iloc[-250:]
        final_train_data = lgb.Dataset(final_X, label=final_y)
        final_model = lgb.train(lgb_params, final_train_data, num_boost_round=150)

        # モデルのローカル保存 (完全置き換え)
        model_path = os.path.join(self.models_dir, f"{symbol_code}_lgb.txt")
        if os.path.exists(model_path):
            try:
                os.remove(model_path)
            except Exception as e:
                print(f"[ModelEta Warning] 既存モデル削除スキップ: {e}")

        final_model.save_model(model_path)

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

        summary_entry = {
            "version": self.MODEL_VERSION,
            "last_trained": datetime.now().isoformat(),
            "avg_loss": avg_loss,
            "accuracy": accuracy,
            "buy_threshold": buy_threshold,
            "sell_threshold": sell_threshold,
            "model_path": model_path
        }
        self.eval_summary[symbol_code] = summary_entry
        self.save_eval_summary()

        return summary_entry

    def sync_to_github(self, commit_msg: str):
        """全学習終了後にまとめて一括で models/ および ログを Git Commit & Push"""
        def git_sync():
            try:
                subprocess.run(
                    ["git", "add", self.log_file, self.models_dir, self.symbols_file],
                    check=True,
                    capture_output=True
                )
                subprocess.run(
                    ["git", "commit", "-m", f"{commit_msg} [skip ci]"],
                    check=True,
                    capture_output=True,
                )
                subprocess.run(["git", "push"], check=True, capture_output=True)
                print(f"[ModelEta Git Sync] まとめて一括Git Push成功: {commit_msg}")
            except Exception as e:
                print(f"[ModelEta Git Sync] Push スキップまたは失敗: {e}")

        asyncio.create_task(asyncio.to_thread(git_sync))

    def find_symbol_info(self, query: str) -> Optional[Dict[str, str]]:
        """入力クエリから銘柄情報を検索"""
        query = query.replace(".T", "").replace(".t", "").strip()
        for s in self.symbols_data:
            if s["code"] == query:
                return s
        for s in self.symbols_data:
            if query in s["name"]:
                return s
        return None

    # --- Commands ---

    @commands.command(name="import_symbols")
    @commands.has_permissions(administrator=True)
    async def import_symbols(self, ctx: commands.Context):
        """Assets内のCSVファイルから銘柄マスターを再構築する管理者用コマンド"""
        msg = await ctx.send(f"Assets 内のCSV (`{self.csv_source_file}`) から銘柄マスターをインポート中...")
        try:
            count = await asyncio.to_thread(self.convert_csv_to_json)
            await msg.edit(content=f"銘柄マスターのインポートが完了しました。対象銘柄数: {count}")
            self.sync_to_github("chore: import symbols from CSV")
        except FileNotFoundError:
            await msg.edit(content=f"エラー: 指定されたCSVファイル (`{self.csv_source_file}`) が見つかりません。")
        except Exception as e:
            await msg.edit(content=f"エラーが発生しました: {e}")

    @commands.command(name="train_eta")
    async def train_eta(self, ctx: commands.Context, target_input: str = "random", auto_sync: bool = True):
        """
        【高精度単一学習コマンド】単一銘柄のモデルを学習・構築
        """
        status_msg = await ctx.send("学習対象の銘柄マスター照合中...")

        symbol_info = None
        if target_input.lower() == "random":
            symbol_info = random.choice(self.symbols_data)
        else:
            symbol_info = self.find_symbol_info(target_input)

        if not symbol_info:
            await status_msg.edit(content=f"エラー: 銘柄 `{target_input}` が見つかりませんでした。")
            return

        target_symbol = f"{symbol_info['code']}.T"
        await status_msg.edit(content=f"高精度学習用データ取得中 (2年分)... ({symbol_info['name']} / {target_symbol})")

        try:
            df = await asyncio.to_thread(yf.download, target_symbol, period="2y", progress=False)
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
        except Exception as e:
            await status_msg.edit(content=f"エラー: データ取得失敗 (`{e}`)")
            return

        if df.empty or len(df) < 250:
            await status_msg.edit(content=f"エラー: {symbol_info['name']} のデータ件数が不足しています(250日以上必要)。")
            return

        res = await self.train_and_evaluate_model(symbol_info["code"], df, status_msg)

        if not res:
            await status_msg.edit(content="エラー: 高精度モデル学習処理に失敗しました。")
            return

        embed = discord.Embed(
            title=f"モデル η (LightGBM {self.MODEL_VERSION}) 学習完了: {symbol_info['name']} ({target_symbol})",
            description=f"モデルファイル: `{res['model_path']}`",
            color=0x9b59b6,
        )
        embed.add_field(name="学習完了日時", value=res["last_trained"][:19], inline=False)
        embed.add_field(name="60日平均 Log Loss", value=f"**{res['avg_loss']:.4f}**", inline=True)
        embed.add_field(name="60日検証勝率", value=f"**{res['accuracy']:.1f}%**", inline=True)
        embed.add_field(name="算出適正閾値", value=f"BUY: `{res['buy_threshold']*100:.1f}%` | SELL: `{res['sell_threshold']*100:.1f}%`", inline=False)

        await status_msg.edit(content="高精度モデルのローカル学習・保存が完了しました。", embed=embed)
        
        # 単一実行時のみ即座に同期、バッチ処理時はバッチ完了時に一括同期
        if auto_sync:
            self.sync_to_github(f"feat: train precision model [{symbol_info['code']}]")

    @commands.command(name="train_eta_batch")
    @commands.has_permissions(administrator=True)
    async def train_eta_batch(self, ctx: commands.Context, count: int = 5):
        """【一括学習バッチ】指定件数を連続学習し、終了時にまとめて Git 同期更新"""
        count = max(1, count)
        batch_msg = await ctx.send(f"一括学習バッチ準備中 (全 {count} 銘柄)...")

        success_count = 0
        for i in range(count):
            matched = random.choice(self.symbols_data)
            progress_header = f"**[ 一括学習バッチ進行中: {i+1}/{count} 完了 ({((i+1)/count)*100:.1f}%) ]**\n現在ターゲット: **{matched['name']} ({matched['code']}.T)**"
            await batch_msg.edit(content=f"{progress_header}\nデータ取得中...")

            target_symbol = f"{matched['code']}.T"
            try:
                df = await asyncio.to_thread(yf.download, target_symbol, period="2y", progress=False)
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.get_level_values(0)
                
                if not df.empty and len(df) >= 250:
                    res = await self.train_and_evaluate_model(
                        matched["code"], df, batch_msg, current_progress_str=progress_header
                    )
                    if res:
                        success_count += 1
            except Exception as e:
                print(f"[ModelEta Batch Error] {matched['code']} スキップ: {e}")

            await asyncio.sleep(0.5)

        # 全銘柄の学習終了後に「まとめて一括で」GitHubへPush
        await batch_msg.edit(content=f"全 {count} 銘柄中 {success_count} 銘柄の学習が完了しました。一括モデル同期(GitHub Push)を開始します...")
        self.sync_to_github(f"feat: batch train complete [{success_count}/{count} models updated]")
        await ctx.send(f"全 {count} 銘柄のモデル学習および一括更新（GitHub同期）が完了しました！")

    @commands.command(name="eta")
    async def predict_eta(self, ctx: commands.Context, target_input: str = "random"):
        """【高速推論コマンド】保存済みモデルから即座に推論回答"""
        status_msg = await ctx.send("銘柄照合中...")

        symbol_info = None
        if target_input.lower() == "random":
            symbol_info = random.choice(self.symbols_data)
        else:
            symbol_info = self.find_symbol_info(target_input)

        if not symbol_info:
            await status_msg.edit(content=f"エラー: 銘柄 `{target_input}` が見つかりませんでした。")
            return

        code = symbol_info["code"]
        target_symbol = f"{code}.T"
        
        cached_eval = self.eval_summary.get(code)
        model_path = os.path.join(self.models_dir, f"{code}_lgb.txt")
        
        is_v2_model = (
            cached_eval is not None 
            and isinstance(cached_eval, dict) 
            and cached_eval.get("version") == self.MODEL_VERSION
        )
        has_cached_model = os.path.exists(model_path) and is_v2_model

        await status_msg.edit(content=f"データ取得中... ({symbol_info['name']} / {target_symbol})")

        try:
            df = await asyncio.to_thread(yf.download, target_symbol, period="1y", progress=False)
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
        except Exception as e:
            await status_msg.edit(content=f"エラー: データ取得失敗 (`{e}`)")
            return

        if df.empty or len(df) < 30:
            await status_msg.edit(content=f"エラー: データ件数が不足しています。")
            return

        df = self.calculate_indicators(df)
        feature_cols = [c for c in df.columns if c.startswith("feat_")]
        clean_df = df.dropna(subset=feature_cols)

        if clean_df.empty:
            await status_msg.edit(content=f"エラー: 有効な特徴量が生成できませんでした。")
            return

        latest_features = clean_df[feature_cols].iloc[[-1]]
        latest_row = clean_df.iloc[-1]

        if has_cached_model:
            model = lgb.Booster(model_file=model_path)
            mode_text = f"高精度モデル ({self.MODEL_VERSION})"
            avg_loss = cached_eval["avg_loss"]
            accuracy = cached_eval["accuracy"]
            buy_t = cached_eval["buy_threshold"]
            sell_t = cached_eval["sell_threshold"]
        else:
            mode_text = "オンデマンド即時推論 (未保存)"
            X_train = clean_df[feature_cols].iloc[-150:-1]
            y_train = clean_df["target"].iloc[-150:-1]
            
            if len(np.unique(y_train)) < 2:
                await status_msg.edit(content="エラー: 学習データのクラスが偏っているため推論できません。")
                return

            train_data = lgb.Dataset(X_train, label=y_train)
            lgb_params = {
                "objective": "binary",
                "metric": "binary_logloss",
                "boosting_type": "gbdt",
                "num_leaves": 31,
                "learning_rate": 0.03,
                "verbose": -1,
                "seed": 42
            }
            model = lgb.train(lgb_params, train_data, num_boost_round=100)
            avg_loss = 0.693
            accuracy = 50.0
            buy_t = 0.55
            sell_t = 0.45

        p_latest = float(model.predict(latest_features)[0])

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
            title=f"モデル η (LightGBM) 推論レポート: {symbol_info['name']} ({target_symbol})",
            description=f"推論モード: `{mode_text}` | 市場: 東証{symbol_info['market']}",
            color=color,
        )
        embed.add_field(name="判定シグナル", value=f"**{signal}**", inline=False)
        embed.add_field(name="翌日上昇確率", value=f"**{p_latest * 100:.2f}%**", inline=True)
        embed.add_field(name="検証 Loss", value=f"**{avg_loss:.4f}**", inline=True)
        embed.add_field(name="検証勝率", value=f"{accuracy:.1f}%", inline=True)
        embed.add_field(name="適用閾値", value=f"BUY 閾値: `{buy_t*100:.1f}%` | SELL 閾値: `{sell_t*100:.1f}%`", inline=False)
        embed.add_field(name="主要テクニカル指標", value=f"RSI: `{latest_row['feat_rsi']:.1f}` | RCI: `{latest_row['feat_rci']:.1f}` | 25日乖離: `{latest_row['feat_ma_bias']:.2f}%`", inline=False)
        embed.set_footer(text="Model Eta Precision Inference | Raspberry Pi Fully Engine")

        await status_msg.edit(content="", embed=embed)

        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "symbol": target_symbol,
            "name": symbol_info["name"],
            "market": symbol_info["market"],
            "latest_prob": round(p_latest, 4),
            "avg_loss": round(avg_loss, 4),
            "accuracy": round(accuracy, 2),
            "buy_threshold": round(buy_t, 2),
            "sell_threshold": round(sell_t, 2),
            "signal": signal,
        }
        
        file_exists = os.path.exists(self.log_file)
        df_log = pd.DataFrame([log_entry])
        df_log.to_csv(self.log_file, mode="a", header=not file_exists, index=False)
        self.sync_to_github(f"chore: log inference prediction [{target_symbol}]")


async def setup(bot: commands.Bot):
    if not HAS_REQUIRED_LIBS:
        print("[ModelEta Error] 依存ライブラリ不足のため ModelEtaCog のロードを中止します。", file=sys.stderr)
        return
    await bot.add_cog(ModelEtaLgbCog(bot))
    print("[ModelEta] ModelEtaLgbCog (一括Git同期・バッチ進捗対応版) が正常にロードされました。")

