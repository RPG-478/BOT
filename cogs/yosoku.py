import io
import random
import os
import discord
from discord.ext import commands
import pandas as pd
import yfinance as yf
import matplotlib
matplotlib.use('Agg')
import mplfinance as mpf

class PredictionView(discord.ui.View):
    def __init__(self, correct_answer, chart_data_full, future_idx_end, name, sector, info):
        super().__init__(timeout=60)
        self.correct_answer = correct_answer
        self.chart_data_full = chart_data_full
        self.future_idx_end = future_idx_end
        self.name = name
        self.sector = sector
        self.info = info

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
        result = "正解" if choice == self.correct_answer else "不正解"
        
        price_start = self.chart_data_full['Close'].iloc[124]
        price_future = self.chart_data_full['Close'].iloc[self.future_idx_end]
        change_rate = ((price_future - price_start) / price_start) * 100

        buf = io.BytesIO()
        mpf.plot(
            self.chart_data_full.iloc[:self.future_idx_end+1],
            type='candle',
            style='yahoo',
            mav=(25, 75),
            title=f"\n{self.name} ({self.sector}) - 事後チャート",
            ylabel='Price (JPY)',
            figsize=(12, 6),
            savefig=dict(fname=buf, dpi=100, bbox_inches='tight')
        )
        buf.seek(0)
        file = discord.File(buf, filename="after_candle.png")

        market_cap = self.info.get('marketCap', 'N/A')
        per = self.info.get('trailingPE', 'N/A')
        pbr = self.info.get('priceToBook', 'N/A')

        embed = discord.Embed(
            title="株価1ヶ月予測ゲーム結果",
            description=f"回答者: {interaction.user.display_name}\n選択: {choice} / 結果: **{result}** (正解: {self.correct_answer})\n1ヶ月後の変動率: {change_rate:.2f}%",
            color=discord.Color.green() if choice == self.correct_answer else discord.Color.red()
        )
        embed.add_field(name="財務情報", value=f"時価総額: {market_cap}\nPER: {per}\nPBR: {pbr}", inline=False)
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

    @commands.command(name="start")
    async def start_game(self, ctx):
        if self.stock_df.empty:
            await ctx.send("銘柄データがありません。")
            return

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
            await ctx.send("データ取得に失敗しました。")
            return

        max_start_idx = len(df) - 125 - 20
        if max_start_idx <= 0:
            await ctx.send("データ期間が不足しています。")
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
            title=f"\n{name} ({sector})",
            ylabel='Price (JPY)',
            figsize=(12, 6),
            savefig=dict(fname=buf, dpi=100, bbox_inches='tight')
        )
        buf.seek(0)
        
        file = discord.File(buf, filename="candle.png")
        view = PredictionView(correct, chart_data_full, len(chart_data_full)-1, name, sector, info)

        period_str = f"{chart_data_initial.index[0].strftime('%Y-%m-%d')} 〜 {chart_data_initial.index[-1].strftime('%Y-%m-%d')}"
        
        market_cap = info.get('marketCap', 'N/A')
        per = info.get('trailingPE', 'N/A')
        pbr = info.get('priceToBook', 'N/A')

        embed = discord.Embed(
            title="株価1ヶ月予測ゲーム",
            description=f"表示期間: {period_str} (6ヶ月)\n1ヶ月後の値動きを予測してください。",
            color=discord.Color.blue()
        )
        embed.add_field(name="企業情報", value=f"銘柄名: {name}\n業種: {sector}\n時価総額: {market_cap}\nPER: {per}\nPBR: {pbr}", inline=False)
        embed.set_image(url="attachment://candle.png")

        await ctx.send(embed=embed, file=file, view=view)

async def setup(bot):
    await bot.add_cog(StockGame(bot))
