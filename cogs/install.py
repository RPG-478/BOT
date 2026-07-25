import asyncio
import os
import subprocess
import sys
import discord
from discord.ext import commands

class TempInstallerCog(commands.Cog):
    """
    一時的なライブラリインストーラー Cog
    Bot起動時に未インストールのパッケージを自動的に pip install します。
    インストール確認完了後、このファイルを削除してください。
    """
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # 自動実行タスクを登録
        self.bot.loop.create_task(self.auto_install_requirements())

    async def auto_install_requirements(self):
        await self.bot.wait_until_ready()
        
        req_file = "requirements.txt"
        if not os.path.exists(req_file):
            print(f"[TempInstaller] ⚠️ {req_file} が見つかりません。")
            return

        print(f"[TempInstaller] 📦 {req_file} から不足ライブラリのインストールを開始します...")

        # 別スレッドで pip install を実行（Botのイベントループをブロックしない）
        def run_pip():
            return subprocess.run(
                [sys.executable, "-m", "pip", "install", "-r", req_file],
                capture_output=True,
                text=True
            )

        try:
            result = await asyncio.to_thread(run_pip)
            
            if result.returncode == 0:
                msg = f"✅ [TempInstaller] 依存ライブラリ ({req_file}) のインストールが正常に完了しました！"
                print(msg)
                
                # 最初に見つかるテキストチャンネルに結果を報告（任意）
                for guild in self.bot.guilds:
                    for channel in guild.text_channels:
                        if channel.permissions_for(guild.me).send_messages:
                            await channel.send(f"```\n{msg}\n```")
                            break
                    break
            else:
                error_msg = f"❌ [TempInstaller] インストールエラー:\n{result.stderr}"
                print(error_msg)

        except Exception as e:
            print(f"❌ [TempInstaller] 実行中に例外が発生しました: {e}")

    @commands.command(name="check_sklearn")
    async def check_sklearn(self, ctx: commands.Context):
        """scikit-learn が利用可能か確認する手動コマンド"""
        try:
            import sklearn
            await ctx.send(f"✅ `scikit-learn` (v{sklearn.__version__}) は正常に読み込めます。このCogを削除しても問題ありません。")
        except ImportError:
            await ctx.send("❌ `scikit-learn` はまだ読み込めません。インストール処理中です。")

async def setup(bot: commands.Bot):
    await bot.add_cog(TempInstallerCog(bot))

