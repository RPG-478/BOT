# -*- coding: utf-8 -*-
import discord
from discord.ext import commands
import defining as df

class System(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @discord.app_commands.command(name="ping_game", description="ボットのPing値を予想しよう！")
    @discord.app_commands.describe(guess="予想するPing値（ミリ秒）を入力してください")
    async def ping_game(self, interaction: discord.Interaction, guess: int):
        # 実際のレイテンシを取得（ミリ秒）
        latency = round(self.bot.latency * 1000)
        # 誤差の絶対値を計算
        diff = abs(guess - latency)

        # 判定ロジックと色の設定
        if diff == 0:
            result_title = "🎯 ジャストミート！完全一致です！"
            result_color = discord.Color.gold()
            description = f"神がかってますね！ピッタリ **{latency}ms** でした！"
        elif diff <= 3:
            result_title = "✨ 惜しい！あと一歩！"
            result_color = discord.Color.green()
            description = f"非常に近いです！誤差はわずか **{diff}ms** でした。"
        else:
            result_title = "❌ 残念..."
            result_color = discord.Color.red()
            description = f"もっと修行が必要です。誤差は **{diff}ms** でした。"

        # Embedの作成
        embed = discord.Embed(
            title=result_title,
            description=description,
            color=result_color
        )
        embed.add_field(name="あなたの予想", value=f"{guess} ms", inline=True)
        embed.add_field(name="実際のPing", value=f"{latency} ms", inline=True)
        embed.set_footer(text=f"Executed by {interaction.user.display_name}")

        # ログ出力（defining.pyを利用）
        print(df.format_log(f"Ping Game: {interaction.user} guessed {guess} (Actual: {latency})"))

        await interaction.response.send_message(embed=embed)

async def setup(bot):
    await bot.add_cog(System(bot))

