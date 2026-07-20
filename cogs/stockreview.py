import asyncio
import io
import discord
from discord import app_commands
from discord.ext import commands
import matplotlib.style as mplstyle
import matplotlib.pyplot as plt
import numpy as np
import yfinance as yf

mplstyle.use("dark_background")


class StockDashboardCog(commands.Cog):

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    def _fetch_and_draw(self, ticker_symbol: str) -> io.BytesIO | None:
        ticker = yf.Ticker(ticker_symbol)
        info = ticker.info

        if not info or "shortName" not in info:
            return None

        rev_growth = info.get("revenueGrowth")
        earn_growth = info.get("earningsGrowth")
        roe = info.get("returnOnEquity")
        op_margin = info.get("operatingMargins")
        pe = info.get("trailingPE")
        de = info.get("debtToEquity")
        cur_ratio = info.get("currentRatio")
        fcf = info.get("freeCashflow")
        ocf = info.get("operatingCashflow")
        div_yield = info.get("dividendYield")
        beta = info.get("beta")

        growth_score = 3
        if rev_growth is not None and earn_growth is not None:
            if rev_growth > 0.15 and earn_growth > 0.15:
                growth_score = 5
            elif rev_growth > 0.08 and earn_growth > 0.08:
                growth_score = 4
            elif rev_growth > 0 and earn_growth > 0:
                growth_score = 3
            elif rev_growth > -0.1:
                growth_score = 2
            else:
                growth_score = 1

        prof_score = 3
        if roe is not None and op_margin is not None:
            if roe > 0.15 and op_margin > 0.15:
                prof_score = 5
            elif roe > 0.10 and op_margin > 0.10:
                prof_score = 4
            elif roe > 0.05 and op_margin > 0.05:
                prof_score = 3
            elif roe > 0:
                prof_score = 2
            else:
                prof_score = 1

        val_score = 3
        if pe is not None:
            if 0 < pe < 10:
                val_score = 5
            elif 10 <= pe < 15:
                val_score = 4
            elif 15 <= pe < 25:
                val_score = 3
            elif 25 <= pe < 40:
                val_score = 2
            else:
                val_score = 1

        health_score = 3
        if de is not None and cur_ratio is not None:
            if de < 50 and cur_ratio > 1.5:
                health_score = 5
            elif de < 100 and cur_ratio > 1.2:
                health_score = 4
            elif de < 150 and cur_ratio > 1.0:
                health_score = 3
            elif de < 200:
                health_score = 2
            else:
                health_score = 1

        cf_score = 3
        if fcf is not None and ocf is not None:
            if fcf > 0 and ocf > 0:
                cf_score = 5 if fcf > ocf * 0.5 else 4
            elif ocf > 0:
                cf_score = 3
            elif ocf < 0 and fcf < 0:
                cf_score = 1
            else:
                cf_score = 2

        return_score = 3
        if div_yield is not None:
            if div_yield > 0.04:
                return_score = 5
            elif div_yield > 0.025:
                return_score = 4
            elif div_yield > 0.01:
                return_score = 3
            elif div_yield > 0:
                return_score = 2
            else:
                return_score = 1

        mom_score = 3
        if beta is not None:
            if 0.8 <= beta <= 1.2:
                mom_score = 5
            elif 0.5 <= beta < 0.8 or 1.2 < beta <= 1.5:
                mom_score = 4
            elif 0.3 <= beta < 0.5 or 1.5 < beta <= 2.0:
                mom_score = 3
            else:
                mom_score = 2

        scores = [
            growth_score,
            prof_score,
            val_score,
            health_score,
            cf_score,
            return_score,
            mom_score,
        ]
        labels = [
            "Growth",
            "Profit",
            "Value",
            "Health",
            "CashFlow",
            "Return",
            "Momentum",
        ]

        hist = ticker.history(period="6m")

        fig = plt.figure(figsize=(12, 5.5), facecolor="#090d16")
        fig.suptitle(
            f"SYSTEM DASHBOARD // {ticker_symbol.upper()} - {info.get('shortName', '')}",
            color="#00e5ff",
            fontsize=14,
            fontweight="bold",
            x=0.5,
            y=0.95,
        )

        angles = np.linspace(0, 2 * np.pi, len(labels), endpoint=False).tolist()
        scores_closed = scores + [scores[0]]
        angles_closed = angles + [angles[0]]

        ax1 = fig.add_subplot(121, polar=True, facecolor="#101726")
        ax1.plot(angles_closed, scores_closed, color="#00e5ff", linewidth=2)
        ax1.fill(angles_closed, scores_closed, color="#00e5ff", alpha=0.25)
        ax1.set_xticks(angles)
        ax1.set_xticklabels(labels, color="#ffffff", fontsize=9)
        ax1.set_yticks([1, 2, 3, 4, 5])
        ax1.set_yticklabels(
            ["1", "2", "3", "4", "5"], color="#556677", fontsize=8
        )
        ax1.set_ylim(0, 5)
        ax1.grid(color="#1a2638", linestyle="--", linewidth=0.8)

        ax2 = fig.add_subplot(122, facecolor="#101726")
        if not hist.empty:
            ax2.plot(
                hist.index,
                hist["Close"],
                color="#ff007f",
                linewidth=2,
                label="Close Price",
            )
            ax2.fill_between(
                hist.index, hist["Close"], color="#ff007f", alpha=0.15
            )

        ax2.set_title(
            "PRICE TREND (6-MONTHS)", color="#ffffff", fontsize=11, pad=10
        )
        ax2.tick_params(colors="#8899a1", labelsize=8)
        ax2.grid(color="#1a2638", linestyle="--", linewidth=0.8)

        for spine in ax2.spines.values():
            spine.set_color("#1a2638")

        plt.subplots_adjust(
            left=0.05, right=0.95, bottom=0.1, top=0.85, wspace=0.25
        )

        buffer = io.BytesIO()
        plt.savefig(
            buffer,
            format="png",
            dpi=150,
            facecolor=fig.get_facecolor(),
            edgecolor="none",
        )
        buffer.seek(0)
        plt.close(fig)

        return buffer

    @app_commands.command(
        name="dash", description="分析ダッシュボード画像を生成します"
    )
    @app_commands.describe(
        ticker="分析対象のティッカー (例: 7203.T, AAPL)"
    )
    async def stock_dash(self, interaction: discord.Interaction, ticker: str):
        await interaction.response.defer()

        buffer = await asyncio.to_thread(self._fetch_and_draw, ticker)

        if not buffer:
            await interaction.followup.send(
                f"ティッカー `{ticker}` のデータを取得できませんでした。"
            )
            return

        file = discord.File(buffer, filename="dashboard.png")
        embed = discord.Embed(color=0x00E5FF)
        embed.set_image(url="attachment://dashboard.png")
        await interaction.followup.send(file=file, embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(StockDashboardCog(bot))
