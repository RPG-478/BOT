import io
import random
import os
import math
import asyncio
import discord
from discord import app_commands
from discord.ext import commands
import pandas as pd
import yfinance as yf
import matplotlib
matplotlib.use('Agg')
import mplfinance as mpf

import config

def truncate_num(val):
    if isinstance(val, (int, float)) and not math.isnan(val):
        return int(val)
    return None

class PredictionView(discord.ui.View):
    def __init__(self, correct_answer, chart_data_full, future_idx_end, ticker, name, sector, info, reward_amount=500):
        super().__init__(timeout=120)
        self.correct_answer = correct_answer
        self.chart_data_full = chart_data_full
        self.future_idx_end = future_idx_end
        self.ticker = ticker
        self.name = name
        self.sector = sector
        self.info = info
        self.reward_amount = reward_amount

    @discord.ui.button(label="上がる", style=discord.ButtonStyle.green)
    async def up_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_answer(interaction, "上がる")

    @discord.ui.button(label="下がる", style=discord.ButtonStyle.red)
    async def down_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_answer(interaction, "下がる")

    @discord.ui.button(label="横ばい", style=discord.ButtonStyle.gray)
    async def flat_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_answer(interaction, "横ばい")

    async def handle_answer(self, interaction: discord.Interaction, choice: str):
        user_id = str(interaction.user.id)
        is_correct = choice == self.correct_answer
        result_text = "正解" if is_correct else "不正解"
        earned_coins = self.reward_amount if is_correct else 0
        
        if is_correct:
            res_user = await asyncio.to_thread(
                config.supabase.table("users").select("balance").eq("user_id", user_id).execute
            )
            current_balance = res_user.data[0]["balance"] if (res_user.data and len(res_user.data) > 0) else 0
            new_balance = current_balance + earned_coins

            await asyncio.to_thread(
                config.supabase.table("users").upsert({"user_id": user_id, "balance": new_balance}).execute
            )
            await asyncio.to_thread(
                config.supabase.table("transaction_history").insert({
                    "sender_id": "SYSTEM",
                    "receiver_id": user_id,
                    "amount": earned_coins,
                    "reason": "株価予測クイズ正解報酬"
                }).execute
            )

        res_stats = await asyncio.to_thread(
            config.supabase.table("stock_quiz_stats").select("*").eq("user_id", user_id).execute
        )
        stats_data = res_stats.data[0] if (res_stats.data and len(res_stats.data) > 0) else None

        if stats_data:
            total_games = stats_data.get("total_games", 0) + 1
            correct_games = stats_data.get("correct_games", 0) + (1 if is_correct else 0)
            total_earned = stats_data.get("total_earned", 0) + earned_coins
        else:
            total_games = 1
            correct_games = 1 if is_correct else 0
            total_earned = earned_coins

        await asyncio.to_thread(
            config.supabase.table("stock_quiz_stats").upsert({
                "user_id": user_id,
                "total_games": total_games,
                "correct_games": correct_games,
                "total_earned": total_earned
            }).execute
        )

        start_price = float(self.chart_data_full['Close'].iloc[124])
        future_price = float(self.chart_data_full['Close'].iloc[self.future_idx_end])
        change_rate = ((future_price - start_price) / start_price) * 100
        price_diff = future_price - start_price

        future_period_data = self.chart_data_full.iloc[124:self.future_idx_end+1]
        high_price = float(future_period_data['High'].max())
        low_price = float(future_period_data['Low'].min())

        vlines_date = self.chart_data_full.index[124]
        
        buf = io.BytesIO()
        mpf.plot(
            self.chart_data_full.iloc[:self.future_idx_end+1],
            type='candle',
            style='yahoo',
            mav=(25, 75),
            vlines=dict(vlines=vlines_date, linewidths=1.5, linestyle='--'),
            title=f"\n{self.name} ({self.ticker}) - 事後チャート",
            ylabel='Price (JPY)',
            figsize=(14, 6),
            savefig=dict(fname=buf, dpi=100, bbox_inches='tight')
        )
        buf.seek(0)
        file = discord.File(buf, filename="after_candle.png")

        ma25 = self.chart_data_full['Close'].iloc[:125].rolling(25).mean().iloc[-1]
        ma75 = self.chart_data_full['Close'].iloc[:125].rolling(75).mean().iloc[-1]
        
        if ma25 > ma75:
            ma_analysis = "25日線が75日線の上に位置する短期上昇傾向（ゴールデンクロス後）"
        else:
            ma_analysis = "25日線が75日線の下に位置する短期下落傾向（デッドクロス後）"

        if change_rate > 5:
            trend_summary = "強い上昇トレンド"
        elif change_rate > 1:
            trend_summary = "ゆるやかな上昇"
        elif change_rate < -5:
            trend_summary = "大幅な下落"
        elif change_rate < -1:
            trend_summary = "ゆるやかな下落"
        else:
            trend_summary = "レンジ内での横ばい推移"

        raw_market_cap = self.info.get('marketCap', None)
        market_cap_val = truncate_num(raw_market_cap / 100000000) if raw_market_cap else None
        market_cap_str = f"{market_cap_val:,}億円" if market_cap_val is not None else "N/A"

        per_val = truncate_num(self.info.get('trailingPE', None))
        per_str = f"{per_val}倍" if per_val is not None else "N/A"

        pbr_val = truncate_num(self.info.get('priceToBook', None))
        pbr_str = f"{pbr_val}倍" if pbr_val is not None else "N/A"

        div_raw = self.info.get('dividendYield', None)
        div_str = f"{div_raw * 100:.2f}%" if isinstance(div_raw, (int, float)) else "N/A"

        reward_msg = f"\n獲得報酬: **+{earned_coins:,} ago coin**" if is_correct else ""

        embed = discord.Embed(
            title=f"結果発表: {result_text} (正解: {self.correct_answer})",
            description=f"回答者: {interaction.user.mention}\n選択予測: **{choice}**{reward_msg}",
            color=discord.Color.green() if is_correct else discord.Color.red()
        )
        
        embed.add_field(
            name="銘柄情報",
            value=f"**企業名**: {self.name}\n**コード**: {self.ticker}\n**業種**: {self.sector}",
            inline=True
        )

        embed.add_field(
            name="財務指標",
            value=f"**時価総額**: {market_cap_str}\n**PER**: {per_str}\n**PBR**: {pbr_str}\n**配当利回り**: {div_str}",
            inline=True
        )

        embed.add_field(
            name="1ヶ月後の価格変化",
            value=(
                f"**基準日価格**: {start_price:,.1f}円\n"
                f"**1ヶ月後価格**: {future_price:,.1f}円\n"
                f"**変動幅**: {price_diff:+,.1f}円 ({change_rate:+.2f}%)\n"
                f"**期間最高値**: {high_price:,.1f}円\n"
                f"**期間最安値**: {low_price:,.1f}円\n"
                f"**展開**: {trend_summary}"
            ),
            inline=False
        )

        embed.add_field(
            name="テクニカル分析",
            value=f"**移動平均線**: {ma_analysis}",
            inline=False
        )

        embed.set_image(url="attachment://after_candle.png")

        for child in self.children:
            child.disabled = True

        await interaction.response.edit_message(embed=embed, attachments=[file], view=self)
        self.stop()

class StockGame(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        try:
            csv_path = os.path.join('Assets', 'Issues_20260725170724.csv')
            df_csv = pd.read_csv(csv_path, encoding='shift-jis')
            self.stock_df = df_csv[df_csv['商品分類'] == '株式'].copy()
            self.stock_df['Ticker'] = self.stock_df['銘柄コード'].astype(str).str.zfill(5).str[:4] + '.T'
        except Exception:
            self.stock_df = pd.DataFrame()

    @app_commands.command(name="quiz_stock", description="株価1ヶ月予測クイズを開始します")
    async def quiz_stock(self, interaction: discord.Interaction):
        if self.stock_df.empty:
            await interaction.response.send_message("銘柄データがありません。", ephemeral=True)
            return

        await interaction.response.defer()

        for _ in range(10):
            row = self.stock_df.sample(1).iloc[0]
            ticker = row['Ticker']
            name = row['銘柄名称']
            sector = row['業種']
            if pd.isna(sector):
                sector = "その他"

            try:
                stock = yf.Ticker(ticker)
                df = stock.history(period="3y")
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.get_level_values(0)
                
                if len(df) > 150:
                    info = stock.info
                    break
            except Exception:
                continue
        else:
            await interaction.followup.send("データ取得に失敗しました。")
            return

        max_start_idx = len(df) - 125 - 20
        if max_start_idx <= 0:
            await interaction.followup.send("データ期間が不足しています。")
            return

        start_idx = random.randint(0, max_start_idx)
        end_idx = start_idx + 125
        future_idx = end_idx + 20

        chart_data_full = df.iloc[start_idx:future_idx+1].copy()
        chart_data_initial = chart_data_full.iloc[:125].copy()
        
        price_start = chart_data_initial['Close'].iloc[-1]
        price_future = chart_data_full['Close'].iloc[-1]
        
        change_rate = (price_future - price_start) / price_start
        if change_rate > 0.01:
            correct = "上がる"
        elif change_rate < -0.01:
            correct = "下がる"
        else:
            correct = "横ばい"

        buf = io.BytesIO()
        mpf.plot(
            chart_data_initial,
            type='candle',
            style='yahoo',
            mav=(25, 75),
            title=f"\nSector: {sector} (銘柄非公開)",
            ylabel='Price (JPY)',
            figsize=(14, 6),
            savefig=dict(fname=buf, dpi=100, bbox_inches='tight')
        )
        buf.seek(0)
        
        file = discord.File(buf, filename="candle.png")
        view = PredictionView(correct, chart_data_full, len(chart_data_full)-1, ticker, name, sector, info, reward_amount=500)

        period_str = f"{chart_data_initial.index[0].strftime('%Y-%m-%d')} 〜 {chart_data_initial.index[-1].strftime('%Y-%m-%d')}"
        
        raw_market_cap = info.get('marketCap', None)
        market_cap_val = truncate_num(raw_market_cap / 100000000) if raw_market_cap else None
        market_cap_str = f"{market_cap_val:,}億円" if market_cap_val is not None else "N/A"

        per_val = truncate_num(info.get('trailingPE', None))
        per_str = f"{per_val}倍" if per_val is not None else "N/A"

        pbr_val = truncate_num(info.get('priceToBook', None))
        pbr_str = f"{pbr_val}倍" if pbr_val is not None else "N/A"

        embed = discord.Embed(
            title="株価1ヶ月予測チャートクイズ",
            description=(
                f"**対象期間**: {period_str} (日足6ヶ月)\n"
                f"右端（基準日）から **1ヶ月後（約20営業日後）** の値動きを予測してください。\n"
                f"正解報酬: **500 ago coin**"
            ),
            color=discord.Color.blue()
        )
        embed.add_field(
            name="ヒント & 企業財務データ", 
            value=f"**業種**: {sector}\n**時価総額**: {market_cap_str}\n**PER**: {per_str}\n**PBR**: {pbr_str}", 
            inline=False
        )
        embed.set_image(url="attachment://candle.png")

        await interaction.followup.send(embed=embed, file=file, view=view)

    @app_commands.command(name="states_stock", description="株価予測クイズの戦績と相場観の分析を表示します")
    async def states_stock(self, interaction: discord.Interaction):
        user_id = str(interaction.user.id)
        
        res_stats = await asyncio.to_thread(
            config.supabase.table("stock_quiz_stats").select("*").eq("user_id", user_id).execute
        )
        stats_data = res_stats.data[0] if (res_stats.data and len(res_stats.data) > 0) else None

        if not stats_data or stats_data.get("total_games", 0) == 0:
            await interaction.response.send_message("まだプレイ記録がありません。/quiz_stock で挑戦してみましょう。", ephemeral=True)
            return

        total = stats_data.get("total_games", 0)
        correct = stats_data.get("correct_games", 0)
        win_rate = (correct / total) * 100 if total > 0 else 0.0
        earned = stats_data.get("total_earned", 0)

        if win_rate >= 70:
            analysis = "移動平均線や財務指標を的確に分析できています。"
        elif win_rate >= 50:
            analysis = "25日・75日移動平均線のクロス状態やPER/PBRの組み合わせに注目して精度を上げましょう。"
        else:
            analysis = "トレンドの転換点を見極める練習が必要です。事後チャートのフィードバックを参考にしてみましょう。"

        embed = discord.Embed(
            title=f"{interaction.user.display_name} さんの株価予測戦績",
            color=discord.Color.gold()
        )
        embed.add_field(name="総挑戦数", value=f"{total} 回", inline=True)
        embed.add_field(name="正解数", value=f"{correct} 回", inline=True)
        embed.add_field(name="勝率", value=f"{win_rate:.1f} %", inline=True)
        embed.add_field(name="累計獲得 ago coin", value=f"{earned:,} コイン", inline=False)
        embed.add_field(name="相場観分析", value=analysis, inline=False)

        await interaction.response.send_message(embed=embed)

async def setup(bot):
    await bot.add_cog(StockGame(bot))
