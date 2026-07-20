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

    def _draw_radar_chart(self, labels: list[str], scores: list[int]) -> io.BytesIO:
        fig = plt.figure(figsize=(6, 6), facecolor="#090d16")
        angles = np.linspace(0, 2 * np.pi, len(labels), endpoint=False).tolist()
        scores_closed = scores + [scores[0]]
        angles_closed = angles + [angles[0]]

        ax = fig.add_subplot(111, polar=True, facecolor="#090d16")
        ax.plot(
            angles_closed,
            scores_closed,
            color="#00e5ff",
            linewidth=3,
            marker="o",
            markersize=8,
            markerfacecolor="#00e5ff",
        )
        ax.fill(angles_closed, scores_closed, color="#00e5ff", alpha=0.25)

        formatted_labels = [f"{lbl}\n({sc}/5)" for lbl, sc in zip(labels, scores)]
        ax.set_xticks(angles)
        ax.set_xticklabels(formatted_labels, color="#ffffff", fontsize=12, fontweight="bold")
        ax.tick_params(axis="x", pad=15)

        ax.set_yticks([1, 2, 3, 4, 5])
        ax.set_yticklabels([])
        ax.set_ylim(0, 5.5)
        ax.grid(color="#2a384c", linestyle="--", linewidth=1.0)

        plt.subplots_adjust(left=0.15, right=0.85, top=0.85, bottom=0.15)

        buffer = io.BytesIO()
        plt.savefig(
            buffer,
            format="png",
            dpi=120,
            facecolor=fig.get_facecolor(),
            edgecolor="none",
        )
        buffer.seek(0)
        plt.close(fig)
        return buffer

    def _fetch_data(self, ticker_symbol: str):
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
            "GROWTH",
            "PROFIT",
            "VALUE",
            "HEALTH",
            "CASH FLOW",
            "RETURN",
            "MOMENTUM",
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

        buffer = self._draw_radar_chart(labels, scores)

        pe_str = f"{pe:.2f}" if pe is not None else "N/A"
        pbr_str = f"{pbr:.2f}" if pbr is not None else "N/A"
        roe_str = f"{roe*100:.2f}%" if roe is not None else "N/A"
        de_str = f"{de:.2f}" if de is not None else "N/A"
        yield_str = f"{div_yield*100:.2f}%" if div_yield is not None else "N/A"
        beta_str = f"{beta:.2f}" if beta is not None else "N/A"

        return {
            "name": name,
            "price": price,
            "currency": currency,
            "rank": rank,
            "total_score": total_score,
            "scores": scores,
            "labels": labels,
            "pe": pe_str,
            "pbr": pbr_str,
            "roe": roe_str,
            "de": de_str,
            "yield": yield_str,
            "beta": beta_str,
            "buffer": buffer,
        }

    @app_commands.command(
        name="stock", description="指定したティッカーの分析ダッシュボードを表示します"
    )
    @app_commands.describe(
        ticker="分析対象のティッカー (例: 7203.T, AAPL)"
    )
    async def stock(self, interaction: discord.Interaction, ticker: str):
        await interaction.response.defer()

        data = await asyncio.to_thread(self._fetch_data, ticker)

        if not data:
            await interaction.followup.send(
                f"ティッカー `{ticker}` のデータを取得できませんでした。"
            )
            return

        desc = (
            f"```\n"
            f"NAME   : {data['name']}\n"
            f"PRICE  : {data['price']} {data['currency']}\n\n"
            f"━━━ OVERALL RATING ━━━\n\n"
            f"RANK   : [ {data['rank']} ]\n"
            f"SCORE  : {data['total_score']} / 5.0\n\n"
            f"━━━ 7-AXIS EVALUATION ━━━\n\n"
            f"GROWTH    : {data['scores'][0]}/5\n"
            f"PROFIT    : {data['scores'][1]}/5\n"
            f"VALUE     : {data['scores'][2]}/5\n"
            f"HEALTH    : {data['scores'][3]}/5\n"
            f"CASH FLOW : {data['scores'][4]}/5\n"
            f"RETURN    : {data['scores'][5]}/5\n"
            f"MOMENTUM  : {data['scores'][6]}/5\n\n"
            f"━━━ METRICS ━━━\n\n"
            f"・ PER   : {data['pe']}\n"
            f"・ PBR   : {data['pbr']}\n"
            f"・ ROE   : {data['roe']}\n"
            f"・ D/E   : {data['de']}\n"
            f"・ YIELD : {data['yield']}\n"
            f"・ BETA  : {data['beta']}\n"
            f"```"
        )

        embed = discord.Embed(
            title=f"7-AXIS EVALUATION REPORT // {ticker.upper()}",
            description=desc,
            color=0x2f3136,
        )

        file = discord.File(data["buffer"], filename="chart.png")
        embed.set_image(url="attachment://chart.png")
        embed.set_footer(text="POWERED BY YFINANCE ARCHITECTURE")

        await interaction.followup.send(file=file, embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(StockDashboardCog(bot))
