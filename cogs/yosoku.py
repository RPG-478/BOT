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

        start_price = float(self.chart_data_full['Close'].iloc[61])
        future_price = float(self.chart_data_full['Close'].iloc[self.future_idx_end])
        change_rate = ((future_price - start_price) / start_price) * 100

        vlines_date = self.chart_data_full.index[61]
        
        buf = io.BytesIO()
        mpf.plot(
            self.chart_data_full.iloc[:self.future_idx_end+1],
            type='candle',
            style='yahoo',
            mav=(5, 25),
            vlines=dict(vlines=vlines_date, linewidths=1.5, linestyle='--'),
            title=f"\n{self.name} ({self.ticker})",
            ylabel='Price (JPY)',
            figsize=(14, 6),
            savefig=dict(fname=buf, dpi=100, bbox_inches='tight')
        )
        buf.seek(0)
        file = discord.File(buf, filename="after_candle.png")

        raw_market_cap = self.info.get('marketCap', None)
        market_cap_val = truncate_num(raw_market_cap / 100000000) if raw_market_cap else None
        market_cap_str = f"{market_cap_val:,}億円" if market_cap_val is not None else "N/A"

        per_val = truncate_num(self.info.get('trailingPE', None))
        per_str = f"{per_val}倍" if per_val is not None else "N/A"

        pbr_val = truncate_num(self.info.get('priceToBook', None))
        pbr_str = f"{pbr_val}倍" if pbr_val is not None else "N/A"

        div_raw = self.info.get('dividendYield', None)
        if isinstance(div_raw, (int, float)) and not math.isnan(div_raw):
            div_val = truncate_num(div_raw if div_raw > 1 else div_raw * 100)
            div_str = f"{div_val}%" if div_val is not None else "N/A"
        else:
            div_str = "N/A"

        embed = discord.Embed(
            title=f"結果: {result_text} (正解: {self.correct_answer})",
            description=f"回答: **{choice}**",
            color=discord.Color.green() if is_correct else discord.Color.red()
        )
        
        embed.add_field(
            name="銘柄情報",
            value=f"**{self.name}** ({self.ticker})\n業種: {self.sector}",
            inline=True
        )

        embed.add_field(
            name="指標",
            value=f"時価総額: {market_cap_str}\nPER: {per_str} | PBR: {pbr_str}\n配当利回り: {div_str}",
            inline=True
        )

        embed.add_field(
            name="10営業日後の変化",
            value=f"{start_price:,.1f}円 → {future_price:,.1f}円 ({change_rate:+.2f}%)",
            inline=False
        )

        embed.set_image(url="attachment://after_candle.png")

        for child in self.children:
            child.disabled = True

        await interaction.response.edit_message(embed=embed, attachments=[file], view=self)
        self.stop()

class CompanyQuizView(discord.ui.View):
    def __init__(self, correct_name, correct_ticker, options, sector, info, reward_amount=500):
        super().__init__(timeout=120)
        self.correct_name = correct_name
        self.correct_ticker = correct_ticker
        self.sector = sector
        self.info = info
        self.reward_amount = reward_amount

        for option in options:
            button = discord.ui.Button(label=option, style=discord.ButtonStyle.primary)
            button.callback = self.make_callback(option)
            self.add_item(button)

    def make_callback(self, choice):
        async def callback(interaction: discord.Interaction):
            await self.handle_answer(interaction, choice)
        return callback

    async def handle_answer(self, interaction: discord.Interaction, choice: str):
        user_id = str(interaction.user.id)
        is_correct = choice == self.correct_name
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
                    "reason": "企業名当てクイズ正解報酬"
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

        raw_market_cap = self.info.get('marketCap', None)
        market_cap_val = truncate_num(raw_market_cap / 100000000) if raw_market_cap else None
        market_cap_str = f"{market_cap_val:,}億円" if market_cap_val is not None else "N/A"

        per_val = truncate_num(self.info.get('trailingPE', None))
        per_str = f"{per_val}倍" if per_val is not None else "N/A"

        pbr_val = truncate_num(self.info.get('priceToBook', None))
        pbr_str = f"{pbr_val}倍" if pbr_val is not None else "N/A"

        div_raw = self.info.get('dividendYield', None)
        if isinstance(div_raw, (int, float)) and not math.isnan(div_raw):
            div_val = truncate_num(div_raw if div_raw > 1 else div_raw * 100)
            div_str = f"{div_val}%" if div_val is not None else "N/A"
        else:
            div_str = "N/A"

        embed = discord.Embed(
            title=f"結果: {result_text}",
            description=f"正解: **{self.correct_name}** ({self.correct_ticker})\nあなたの回答: **{choice}**",
            color=discord.Color.green() if is_correct else discord.Color.red()
        )
        embed.add_field(
            name="企業詳細",
            value=f"業種: {self.sector}\n時価総額: {market_cap_str}\nPER: {per_str} | PBR: {pbr_str}\n配当利回り: {div_str}",
            inline=False
        )

        for child in self.children:
            child.disabled = True

        await interaction.response.edit_message(embed=embed, view=self)
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

    @app_commands.command(name="quiz_stock", description="株価10営業日予測クイズを開始します")
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
                
                if len(df) > 100:
                    info = stock.info
                    break
            except Exception:
                continue
        else:
            await interaction.followup.send("データ取得に失敗しました。")
            return

        max_start_idx = len(df) - 72
        if max_start_idx <= 0:
            await interaction.followup.send("データ期間が不足しています。")
            return

        start_idx = random.randint(0, max_start_idx)
        chart_data_full = df.iloc[start_idx : start_idx + 72].copy()
        chart_data_initial = chart_data_full.iloc[:62].copy()
        
        price_start = chart_data_initial['Close'].iloc[-1]
        price_future = chart_data_full['Close'].iloc[-1]
        
        if price_future >= price_start:
            correct = "上がる"
        else:
            correct = "下がる"

        buf = io.BytesIO()
        mpf.plot(
            chart_data_initial,
            type='candle',
            style='yahoo',
            mav=(5, 25),
            title=f"\nSector: {sector} (銘柄非公開)",
            ylabel='Price (JPY)',
            figsize=(14, 6),
            savefig=dict(fname=buf, dpi=100, bbox_inches='tight')
        )
        buf.seek(0)
        
        file = discord.File(buf, filename="candle.png")
        view = PredictionView(correct, chart_data_full, len(chart_data_full)-1, ticker, name, sector, info, reward_amount=500)

        raw_market_cap = info.get('marketCap', None)
        market_cap_val = truncate_num(raw_market_cap / 100000000) if raw_market_cap else None
        market_cap_str = f"{market_cap_val:,}億円" if market_cap_val is not None else "N/A"

        per_val = truncate_num(info.get('trailingPE', None))
        per_str = f"{per_val}倍" if per_val is not None else "N/A"

        pbr_val = truncate_num(info.get('priceToBook', None))
        pbr_str = f"{pbr_val}倍" if pbr_val is not None else "N/A"

        embed = discord.Embed(
            title="株価10営業日予測クイズ",
            description="右端から10営業日後の値動きを予測してください。",
            color=discord.Color.blue()
        )
        embed.add_field(
            name="企業情報", 
            value=f"業種: {sector} | 時価総額: {market_cap_str}\nPER: {per_str} | PBR: {pbr_str}", 
            inline=False
        )
        embed.set_image(url="attachment://candle.png")

        await interaction.followup.send(embed=embed, file=file, view=view)

    @app_commands.command(name="quiz_company", description="企業情報から企業名を当てるクイズを開始します")
    async def quiz_company(self, interaction: discord.Interaction):
        if self.stock_df.empty or len(self.stock_df) < 4:
            await interaction.response.send_message("銘柄データが不足しています。", ephemeral=True)
            return

        await interaction.response.defer()

        for _ in range(10):
            sample_df = self.stock_df.sample(4)
            correct_row = sample_df.iloc[0]
            ticker = correct_row['Ticker']
            correct_name = correct_row['銘柄名称']
            sector = correct_row['業種']
            if pd.isna(sector):
                sector = "その他"

            options = sample_df['銘柄名称'].tolist()
            random.shuffle(options)

            try:
                stock = yf.Ticker(ticker)
                df = stock.history(period="1y")
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.get_level_values(0)

                if len(df) > 60:
                    info = stock.info
                    break
            except Exception:
                continue
        else:
            await interaction.followup.send("データ取得に失敗しました。")
            return

        chart_data = df.iloc[-60:].copy()

        buf = io.BytesIO()
        mpf.plot(
            chart_data,
            type='candle',
            style='yahoo',
            mav=(5, 25),
            title=f"\nSector: {sector} (銘柄非公開)",
            ylabel='Price (JPY)',
            figsize=(14, 6),
            savefig=dict(fname=buf, dpi=100, bbox_inches='tight')
        )
        buf.seek(0)
        file = discord.File(buf, filename="company_candle.png")

        raw_market_cap = info.get('marketCap', None)
        market_cap_val = truncate_num(raw_market_cap / 100000000) if raw_market_cap else None
        market_cap_str = f"{market_cap_val:,}億円" if market_cap_val is not None else "N/A"

        per_val = truncate_num(info.get('trailingPE', None))
        per_str = f"{per_val}倍" if per_val is not None else "N/A"

        pbr_val = truncate_num(info.get('priceToBook', None))
        pbr_str = f"{pbr_val}倍" if pbr_val is not None else "N/A"

        div_raw = info.get('dividendYield', None)
        if isinstance(div_raw, (int, float)) and not math.isnan(div_raw):
            div_val = truncate_num(div_raw if div_raw > 1 else div_raw * 100)
            div_str = f"{div_val}%" if div_val is not None else "N/A"
        else:
            div_str = "N/A"

        embed = discord.Embed(
            title="企業名当てクイズ",
            description="提示されたチャートや指標から企業名を当ててください。",
            color=discord.Color.purple()
        )
        embed.add_field(
            name="企業情報",
            value=f"業種: {sector}\n時価総額: {market_cap_str}\nPER: {per_str} | PBR: {pbr_str}\n配当利回り: {div_str}",
            inline=False
        )
        embed.set_image(url="attachment://company_candle.png")

        view = CompanyQuizView(correct_name, ticker, options, sector, info, reward_amount=500)
        await interaction.followup.send(embed=embed, file=file, view=view)

    @app_commands.command(name="states_stock", description="株価予測クイズの戦績を表示します")
    async def states_stock(self, interaction: discord.Interaction):
        user_id = str(interaction.user.id)
        
        res_stats = await asyncio.to_thread(
            config.supabase.table("stock_quiz_stats").select("*").eq("user_id", user_id).execute
        )
        stats_data = res_stats.data[0] if (res_stats.data and len(res_stats.data) > 0) else None

        if not stats_data or stats_data.get("total_games", 0) == 0:
            await interaction.response.send_message("プレイ記録がありません。", ephemeral=True)
            return

        total = stats_data.get("total_games", 0)
        correct = stats_data.get("correct_games", 0)
        win_rate = (correct / total) * 100 if total > 0 else 0.0

        embed = discord.Embed(
            title=f"{interaction.user.display_name} さんの戦績",
            color=discord.Color.gold()
        )
        embed.add_field(name="挑戦数", value=f"{total}回", inline=True)
        embed.add_field(name="正解数", value=f"{correct}回", inline=True)
        embed.add_field(name="勝率", value=f"{win_rate:.1f}%", inline=True)

        await interaction.response.send_message(embed=embed)

async def setup(bot):
    await bot.add_cog(StockGame(bot))
