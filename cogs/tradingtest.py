import discord
from discord.ext import commands
import math
import yfinance as yf
import numpy as np
import pandas as pd
import torch
import torch.nn as nn
import asyncio

class PositionalEncoding(nn.Module):
    def __init__(self, d_model, max_len=500):
        super().__init__()
        pe = torch.zeros(max_len, d_model)
        position = torch.arange(0, max_len, dtype=torch.float).unsqueeze(1)
        div_term = torch.exp(torch.arange(0, d_model, 2).float() * (-math.log(10000.0) / d_model))
        pe[:, 0::2] = torch.sin(position * div_term)
        pe[:, 1::2] = torch.cos(position * div_term)
        self.register_buffer('pe', pe.unsqueeze(0))

    def forward(self, x):
        return x + self.pe[:, :x.size(1)]

class StockTransformerMultiTask(nn.Module):
    def __init__(self, input_size, d_model=64, nhead=4, num_layers=3, dim_feedforward=128):
        super().__init__()
        self.input_projection = nn.Linear(input_size, d_model)
        self.pos_encoder = PositionalEncoding(d_model)
        encoder_layer = nn.TransformerEncoderLayer(
            d_model=d_model, nhead=nhead, dim_feedforward=dim_feedforward, batch_first=True
        )
        self.transformer_encoder = nn.TransformerEncoder(encoder_layer, num_layers=num_layers)
        
        self.fc_prob = nn.Linear(d_model, 1)
        self.fc_up = nn.Linear(d_model, 1)
        self.fc_down = nn.Linear(d_model, 1)

    def forward(self, x):
        x = self.input_projection(x)
        x = self.pos_encoder(x)
        out = self.transformer_encoder(x)
        out = out[:, -1, :]
        
        prob = torch.sigmoid(self.fc_prob(out))
        max_up = self.fc_up(out)
        max_down = self.fc_down(out)
        return prob, max_up, max_down

class StockPredictorCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.model_path = 'Assets/stock_transformer_model.pth'
        self.window_size = 100
        self.model = StockTransformerMultiTask(input_size=7)
        self.model.load_state_dict(torch.load(self.model_path, map_location=torch.device('cpu')))
        self.model.eval()

    @commands.command(name="predict")
    async def predict(self, ctx, ticker_code: str):
        await ctx.send(f"{ticker_code} の予測データを取得中...")
        
        try:
            ticker = yf.Ticker(ticker_code)
            df = await asyncio.to_thread(ticker.history, period="6mo")
            
            if len(df) < self.window_size + 20:
                await ctx.send("予測に必要なデータ期間が不足しています。")
                return
                
            df['MA20'] = df['Close'].rolling(window=20).mean()
            df['MA_Diff'] = (df['Close'] - df['MA20']) / df['MA20']
            delta = df['Close'].diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
            rs = gain / (loss + 1e-8)
            df['RSI'] = 100 - (100 / (1 + rs))
            df = df.dropna()
            
            feature_cols = ['Open', 'High', 'Low', 'Close', 'Volume', 'MA_Diff', 'RSI']
            features = df[feature_cols].tail(self.window_size).values
            current_close = df['Close'].iloc[-1]
            
            features_scaled = (features - features.mean(axis=0)) / (features.std(axis=0) + 1e-8)
            input_tensor = torch.tensor(features_scaled, dtype=torch.float32).unsqueeze(0)
            
            with torch.no_grad():
                prob, max_up_ratio, max_down_ratio = self.model(input_tensor)
                
            p = prob.item()
            u_ratio = max_up_ratio.item()
            d_ratio = max_down_ratio.item()
            
            pred_high = current_close * (1 + u_ratio)
            pred_low = current_close * (1 + d_ratio)
            
            score_prob = p * 60
            score_up = min(20, (u_ratio / 0.05) * 20) if u_ratio > 0 else 0
            score_down_base = 20
            penalty_down = min(20, (abs(d_ratio) / 0.05) * 20) if d_ratio < 0 else 0
            score_down = score_down_base - penalty_down
            
            score = int(score_prob + score_up + score_down)
            score = max(0, min(100, score))
            
            embed = discord.Embed(title=f"株価予測結果: {ticker_code}", color=0x00ff00)
            embed.add_field(name="現在値", value=f"{current_close:.1f}円", inline=False)
            embed.add_field(name="明日の上昇確率", value=f"{p * 100:.2f}%", inline=True)
            embed.add_field(name="総合評価スコア", value=f"{score} / 100", inline=True)
            embed.add_field(name="予測最大高値", value=f"{pred_high:.1f}円", inline=False)
            embed.add_field(name="予測最大安値", value=f"{pred_low:.1f}円", inline=False)
            
            await ctx.send(embed=embed)
            
        except Exception as e:
            await ctx.send(f"予測処理中にエラーが発生しました: {str(e)}")

async def setup(bot):
    await bot.add_cog(StockPredictorCog(bot))
