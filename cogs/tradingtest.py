import discord
from discord.ext import commands
import onnxruntime as ort
import numpy as np

class StockPredictorCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # Colab側で出力した新しいファイル名に合わせる
        self.model_path = 'Assets/stock_transformer_multitask_v2.onnx'
        self.window_size = 100
        self.session = ort.InferenceSession(self.model_path)

    @commands.command(name="predict")
    async def predict(self, ctx, ticker_code: str):
        try:
            # 以前のデータ取得および特徴量抽出ロジックをここに配置
            
            input_data = np.expand_dims(features, axis=0).astype(np.float32)
            
            input_name = self.session.get_inputs()[0].name
            outputs = self.session.run(None, {input_name: input_data})
            
            prob = outputs[0][0]
            max_up = outputs[1][0]
            max_down = outputs[2][0]
            
            response = (
                f"=== {ticker_code} 予測結果 ===\n"
                f"上昇確率: {prob * 100:.2f}%\n"
                f"最大上昇率予測: {max_up * 100:.2f}%\n"
                f"最大下落率予測: {max_down * 100:.2f}%"
            )
            await ctx.send(response)
            
        except Exception as e:
            await ctx.send(f"Error: {str(e)}")

async def setup(bot):
    await bot.add_cog(StockPredictorCog(bot))
