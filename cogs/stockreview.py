import asyncio
import discord
from discord import app_commands
from discord.ext import commands
import yfinance as yf


class StockAnalysisCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    def _fetch_and_analyze(self, ticker_symbol: str):
        ticker = yf.Ticker(ticker_symbol)
        info = ticker.info

        if not info or "shortName" not in info:
            return None

        roe = info.get("returnOnEquity")
        rev_growth = info.get("revenueGrowth")
        pe = info.get("trailingPE")
        pbr = info.get("priceToBook")
        de = info.get("debtToEquity")

        growth_score = 3
        if roe is not None and rev_growth is not None:
            if roe > 0.15 and rev_growth > 0.10:
                growth_score = 5
            elif roe > 0.10 and rev_growth > 0.05:
                growth_score = 4
            elif roe > 0.05:
                growth_score = 3
            elif roe > 0:
                growth_score = 2
            else:
                growth_score = 1

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

        safety_score = 3
        if de is not None:
            if de < 50:
                safety_score = 5
            elif de < 100:
                safety_score = 4
            elif de < 150:
                safety_score = 3
            elif de < 200:
                safety_score = 2
            else:
                safety_score = 1

        total_score = round((growth_score + val_score + safety_score) / 3.0, 1)

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
            "val_score": val_score,
            "safety_score": safety_score,
            "total_score": total_score,
            "rank": rank,
            "pe": pe,
            "pbr": pbr,
            "roe": roe,
            "de": de,
        }

    def _build_bar(
        self, score: float, max_score: float = 5.0, length: int = 10
    ) -> str:
        filled = int(round((score / max_score) * length))
        return "█" * filled + "░" * (length - filled)

    @app_commands.command(
        name="stock",
        description="指定したティッカーの総合評価レポートを表示します",
    )
    @app_commands.describe(
        ticker="分析対象のティッカーシンボル (例: 7203.T, AAPL)"
    )
    async def stock_eval(self, interaction: discord.Interaction, ticker: str):
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
            title=f"SYSTEM EVALUATION REPORT // {data['symbol']}",
            description=f"```\nNAME  : {data['name']}\nPRICE : {data['price']} {data['currency']}\n```",
            color=0x00E5FF,
        )

        overall_bar = self._build_bar(data["total_score"])
        embed.add_field(
            name="━━━ OVERALL RATING ━━━",
            value=f"```\nRANK  : [ {data['rank']} ]\nSCORE : {data['total_score']} / 5.0\n[{overall_bar}]\n```",
            inline=False,
        )

        growth_bar = self._build_bar(data["growth_score"])
        val_bar = self._build_bar(data["val_score"])
        safety_bar = self._build_bar(data["safety_score"])

        score_details = (
            f"GROWTH  : {data['growth_score']}/5 [{growth_bar}]\n"
            f"VALUE   : {data['val_score']}/5 [{val_bar}]\n"
            f"SAFETY  : {data['safety_score']}/5 [{safety_bar}]"
        )
        embed.add_field(
            name="━━━ 3-AXIS EVALUATION ━━━",
            value=f"```\n{score_details}\n```",
            inline=False,
        )

        pe_str = f"{data['pe']:.2f}" if data["pe"] is not None else "N/A"
        pbr_str = f"{data['pbr']:.2f}" if data["pbr"] is not None else "N/A"
        roe_str = (
            f"{data['roe']*100:.2f}%" if data["roe"] is not None else "N/A"
        )
        de_str = f"{data['de']:.2f}" if data["de"] is not None else "N/A"

        notes = (
            f"・PER : {pe_str}\n"
            f"・PBR : {pbr_str}\n"
            f"・ROE : {roe_str}\n"
            f"・D/E : {de_str}"
        )
        embed.add_field(
            name="━━━ NOTES & METRICS ━━━",
            value=f"```\n{notes}\n```",
            inline=False,
        )

        embed.set_footer(text="POWERED BY YFINANCE ARCHITECTURE")

        await interaction.followup.send(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(StockAnalysisCog(bot))
