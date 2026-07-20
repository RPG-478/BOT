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
        pbr = info.get("priceToBook")
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

        total_score = round(sum(scores) / len(scores), 1)
        if total_score >= 4.5:
            rank = "S"
        elif total_score >= 3.8:
            rank = "A"
        elif total_score >= 2.8:
            rank = "B"
        elif total_score >= 1.8:
            rank = "C"
        else:
            rank = "D"

        name = info.get("shortName", ticker_symbol)
        price = info.get("currentPrice") or info.get("regularMarketPrice")
        currency = info.get("currency", "USD")

        fig = plt.figure(figsize=(12, 6), facecolor="#090d16")
        fig.suptitle(
            f"SYSTEM DASHBOARD // {ticker_symbol.upper()} - {name}",
            color="#00e5ff",
            fontsize=15,
            fontweight="bold",
            x=0.5,
            y=0.95,
        )

        ax1 = fig.add_subplot(121, facecolor="#090d16")
        ax1.axis("off")

        pe_str = f"{pe:.2f}" if pe is not None else "N/A"
        pbr_str = f"{pbr:.2f}" if pbr is not None else "N/A"
        roe_str = f"{roe*100:.2f}%" if roe is not None else "N/A"
        de_str = f"{de:.2f}" if de is not None else "N/A"

        status_text = (
            f"━ COMPANY DATA ━\n"
            f"NAME   : {name}\n"
            f"PRICE  : {price} {currency}\n\n"
            f"━ RATING ━\n"
            f"RANK   : [ {rank} ]\n"
            f"SCORE  : {total_score} / 5.0\n\n"
            f"━ 7-AXIS SCORES ━\n"
            f"Growth   : {growth_score}/5   Profit   : {prof_score}/5\n"
            f"Value    : {val_score}/5   Health   : {health_score}/5\n"
            f"CashFlow : {cf_score}/5   Return   : {return_score}/5\n"
            f"Momentum : {mom_score}/5\n\n"
            f"━ METRICS ━\n"
            f"PER: {pe_str} | PBR: {pbr_str}\nROE: {roe_str} | D/E: {de_str}"
        )

        ax1.text(
            0.02,
            0.95,
            status_text,
            color="#ffffff",
            fontsize=11,
            family="monospace",
            verticalalignment="top",
            linespacing=1.35,
        )

        angles = np.linspace(0, 2 * np.pi, len(labels), endpoint=False).tolist()
        scores_closed = scores + [scores[0]]
        angles_closed = angles + [angles[0]]

        ax2 = fig.add_subplot(122, polar=True, facecolor="#101726")
        ax2.plot(
            angles_closed,
            scores_closed,
            color="#00e5ff",
            linewidth=2,
            marker="o",
            markersize=5,
            markerfacecolor="#00e5ff",
        )
        ax2.fill(angles_closed, scores_closed, color="#00e5ff", alpha=0.25)
        ax2.set_xticks(angles)
        ax2.set_xticklabels(labels, color="#ffffff", fontsize=11)
        ax2.set_yticks([1, 2, 3, 4, 5])
        ax2.set_yticklabels(
            ["1", "2", "3", "4", "5"], color="#556677", fontsize=9
        )
        ax2.set_ylim(0, 5.5)
        ax2.grid(color="#1a2638", linestyle="--", linewidth=0.8)

        for angle, score in zip(angles, scores):
            ax2.text(
                angle,
                score + 0.35,
                str(score),
                color="#00e5ff",
                fontsize=11,
                fontweight="bold",
                ha="center",
                va="center",
            )

        plt.subplots_adjust(
            left=0.03, right=0.97, bottom=0.05, top=0.85, wspace=0.1
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
        name="stock", description="指定したティッカーの分析ダッシュボードを表示します"
    )
    @app_commands.describe(
        ticker="分析対象のティッカー (例: 7203.T, AAPL)"
    )
    async def stock(self, interaction: discord.Interaction, ticker: str):
        await interaction.response.defer()

        buffer = await asyncio.to_thread(self._fetch_and_draw, ticker)

        if not buffer:
            await interaction.followup.send(
                f"ティッカー `{ticker}` のデータを取得できませんでした。"
            )
            return

        file = discord.File(buffer, filename="dashboard.png")
        embed = discord.Embed(color=0x000000)
        embed.set_image(url="attachment://dashboard.png")
        await interaction.followup.send(file=file, embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(StockDashboardCog(bot))
