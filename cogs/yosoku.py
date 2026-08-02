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
    def __init__(self, correct_answer):
        super().__init__(timeout=60)
        self.correct_answer = correct_answer

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
        await interaction.response.send_message(f"{result}. 正解は {self.correct_answer} でした。", ephemeral=True)
        for child in self.children:
            child.disabled = True
        await interaction.message.edit(view=self)
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
                df = yf.download(ticker, period="3y", progress=False)
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.get_level_values(0)
                
                if len(df) > 150:
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

        chart_data = df.iloc[start_idx:end_idx].copy()
        
        price_start = chart_data['Close'].iloc[-1]
        price_future = df['Close'].iloc[future_idx]
        
        change_rate = (price_future - price_start) / price_start
        if change_rate > 0.01:
            correct = "上がる"
        elif change_rate < -0.01:
            correct = "下がる"
        else:
            correct = "横ばい"

        buf = io.BytesIO()
        mpf.plot(
            chart_data,
            type='candle',
            style='yahoo',
            title=f"\n{name} ({sector})",
            ylabel='Price (JPY)',
            savefig=dict(fname=buf, dpi=100, bbox_inches='tight')
        )
        buf.seek(0)
        
        file = discord.File(buf, filename="candle.png")
        view = PredictionView(correct)

        period_str = f"{chart_data.index[0].strftime('%Y-%m-%d')} 〜 {chart_data.index[-1].strftime('%Y-%m-%d')}"
        embed = discord.Embed(
            title="株価1ヶ月予測ゲーム",
            description=f"表示期間: {period_str} (6ヶ月)\n1ヶ月後の値動きを予測してください。",
            color=discord.Color.blue()
        )
        embed.set_image(url="attachment://candle.png")

        await ctx.send(embed=embed, file=file, view=view)

async def setup(bot):
    await bot.add_cog(StockGame(bot))
