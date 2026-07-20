import asyncio
import discord
from discord import app_commands
from discord.ext import commands
import yfinance as yf


class StockAnalysis7AxisCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    def _fetch_and_analyze(self, ticker_symbol: str):
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

        return {
            "name": info.get("shortName", ticker_symbol),
            "symbol": ticker_symbol.upper(),
            "currency": info.get("currency", "USD"),
            "price": info.get("currentPrice") or info.get("regularMarketPrice"),
            "growth_score": growth_score,
            "prof_score": prof_score,
            "val_score": val_score,
            "health_score": health_score,
            "cf_score": cf_score,
            "return_score": return_score,
            "mom_score": mom_score,
            "total_score": total_score,
            "rank": rank,
            "pe": pe,
            "pbr": pbr,
            "roe": roe,
            "de": de,
            "div_yield": div_yield,
            "beta": beta,
        }

    def _build_bar(
        self, score: float, max_score: float = 5.0, length: int = 10
    ) -> str:
        filled = int(round((score / max_score) * length))
        return "█" * filled + "░" * (length - filled)

    @app_commands.command(
        name="stock",
        description="指定したティッカーの7軸総合評価レポートを表示します",
    )
    @app_commands.describe(
        ticker="分析対象のティッカーシンボル (例: 7203.T, AAPL)"
    )
    async def stock_eval7(self, interaction: discord.Interaction, ticker: str):
        await interaction.response.defer()

        data = await asyncio.to_thread(self._fetch_and_analyze, ticker)

        if not data:
            embed = discord.Embed(
                title="ERROR: INVALID TICKER",
                description=f"ティッカー `{ticker}` のデータを取得できませんでした。",
                color=0xFF2A2A,
            )
            await interaction.followup.send(embed=embed)
            return

        embed = discord.Embed(
            title=f"7-AXIS EVALUATION REPORT // {data['symbol']}",
            description=f"```\nNAME  : {data['name']}\nPRICE : {data['price']} {data['currency']}\n```",
            color=00000000,
        )

        overall_bar = self._build_bar(data["total_score"])
        embed.add_field(
            name="━━━ OVERALL RATING ━━━",
            value=f"```\nRANK  : [ {data['rank']} ]\nSCORE : {data['total_score']} / 5.0\n[{overall_bar}]\n```",
            inline=False,
        )

        gb = self._build_bar(data["growth_score"])
        pb = self._build_bar(data["prof_score"])
        vb = self._build_bar(data["val_score"])
        hb = self._build_bar(data["health_score"])
        cb = self._build_bar(data["cf_score"])
        rb = self._build_bar(data["return_score"])
        mb = self._build_bar(data["mom_score"])

        score_details = (
            f"GROWTH     : {data['growth_score']}/5 [{gb}]\n"
            f"PROFIT     : {data['prof_score']}/5 [{pb}]\n"
            f"VALUE      : {data['val_score']}/5 [{vb}]\n"
            f"HEALTH     : {data['health_score']}/5 [{hb}]\n"
            f"CASH FLOW  : {data['cf_score']}/5 [{cb}]\n"
            f"RETURN     : {data['return_score']}/5 [{rb}]\n"
            f"MOMENTUM   : {data['mom_score']}/5 [{mb}]"
        )
        embed.add_field(
            name="━━━ 7-AXIS EVALUATION ━━━",
            value=f"```\n{score_details}\n```",
            inline=False,
        )

        pe_str = f"{data['pe']:.2f}" if data["pe"] is not None else "N/A"
        pbr_str = f"{data['pbr']:.2f}" if data["pbr"] is not None else "N/A"
        roe_str = (
            f"{data['roe']*100:.2f}%" if data["roe"] is not None else "N/A"
        )
        de_str = f"{data['de']:.2f}" if data["de"] is not None else "N/A"
        dy_str = (
            f"{data['div_yield']*100:.2f}%"
            if data["div_yield"] is not None
            else "N/A"
        )
        beta_str = f"{data['beta']:.2f}" if data["beta"] is not None else "N/A"

        notes = (
            f"・PER : {pe_str}\n"
            f"・PBR : {pbr_str}\n"
            f"・ROE : {roe_str}\n"
            f"・D/E : {de_str}\n"
            f"・YIELD: {dy_str}\n"
            f"・BETA : {beta_str}"
        )
        embed.add_field(
            name="━━━ METRICS ━━━",
            value=f"```\n{notes}\n```",
            inline=False,
        )

        embed.set_footer(text="POWERED BY YFINANCE ARCHITECTURE")

        await interaction.followup.send(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(StockAnalysis7AxisCog(bot))
