import discord
from discord.ext import commands
import yfinance as yf
import asyncio
import matplotlib
import matplotlib.pyplot as plt
import io

matplotlib.use('Agg')

class StockCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="stock")
    async def stock(self, ctx, ticker: str):
        def fetch_data():
            t = yf.Ticker(ticker)
            hist_1d = t.history(period="1d")
            hist_6m = t.history(period="6m")
            try:
                info = t.info
            except Exception:
                info = {}

            chart_bytes = None
            if not hist_6m.empty:
                plt.figure(figsize=(10, 5))
                plt.plot(hist_6m.index, hist_6m["Close"], color="green")
                plt.title(f"{ticker.upper()} 6-Month Chart")
                plt.xlabel("Date")
                plt.ylabel("Price")
                plt.grid(True)
                
                buf = io.BytesIO()
                plt.savefig(buf, format="png", bbox_inches="tight")
                buf.seek(0)
                chart_bytes = buf.getvalue()
                plt.close()

            return hist_1d, info, chart_bytes

        try:
            hist_1d, info, chart_bytes = await asyncio.to_thread(fetch_data)
            
            if hist_1d.empty:
                await ctx.send("指定されたティッカーコードのデータが見つかりませんでした。")
                return

            current_price = hist_1d["Close"].iloc[-1]
            currency = info.get("currency", "USD")
            name = info.get("longName", ticker.upper())
            
            per = info.get("trailingPE")
            pbr = info.get("priceToBook")
            
            per_val = f"{per:.2f}" if isinstance(per, (int, float)) else "N/A"
            pbr_val = f"{pbr:.2f}" if isinstance(pbr, (int, float)) else "N/A"

            embed = discord.Embed(
                title=f"{name} ({ticker.upper()})", 
                color=discord.Color.green()
            )
            embed.add_field(name="現在値", value=f"{current_price:.2f} {currency}", inline=False)
            embed.add_field(name="始値", value=f"{hist_1d['Open'].iloc[-1]:.2f} {currency}", inline=True)
            embed.add_field(name="高値", value=f"{hist_1d['High'].iloc[-1]:.2f} {currency}", inline=True)
            embed.add_field(name="安値", value=f"{hist_1d['Low'].iloc[-1]:.2f} {currency}", inline=True)
            embed.add_field(name="PER (実績)", value=per_val, inline=True)
            embed.add_field(name="PBR", value=pbr_val, inline=True)
            
            if chart_bytes:
                file = discord.File(io.BytesIO(chart_bytes), filename="chart.png")
                embed.set_image(url="attachment://chart.png")
                await ctx.send(embed=embed, file=file)
            else:
                await ctx.send(embed=embed)
            
        except Exception as e:
            await ctx.send(f"エラーが発生しました: {str(e)}")

async def setup(bot):
    await bot.add_cog(StockCog(bot))
