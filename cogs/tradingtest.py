import discord
from discord.ext import commands
import yfinance as yf
import asyncio

class StockCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="stock")
    async def stock(self, ctx, ticker: str):
        def fetch_data():
            t = yf.Ticker(ticker)
            hist = t.history(period="1d")
            try:
                info = t.info
            except Exception:
                info = {}
            return hist, info

        try:
            hist, info = await asyncio.to_thread(fetch_data)
            
            if hist.empty:
                await ctx.send("指定されたティッカーコードのデータが見つかりませんでした。")
                return

            current_price = hist["Close"].iloc[-1]
            currency = info.get("currency", "USD")
            name = info.get("longName", ticker.upper())

            embed = discord.Embed(
                title=f"{name} ({ticker.upper()})", 
                color=discord.Color.green()
            )
            embed.add_field(name="現在値", value=f"{current_price:.2f} {currency}", inline=False)
            embed.add_field(name="始値", value=f"{hist['Open'].iloc[-1]:.2f} {currency}", inline=True)
            embed.add_field(name="高値", value=f"{hist['High'].iloc[-1]:.2f} {currency}", inline=True)
            embed.add_field(name="安値", value=f"{hist['Low'].iloc[-1]:.2f} {currency}", inline=True)
            
            await ctx.send(embed=embed)
            
        except Exception as e:
            await ctx.send(f"エラーが発生しました: {str(e)}")

async def setup(bot):
    await bot.add_cog(StockCog(bot))
