# -*- coding: utf-8 -*-
import discord
from discord.ext import commands
import os
import asyncio

#読み取り config→定義　defining→関数
import config
import defining as df
from keep_alive import keep_alive

#botコマンド定義
class MyBot(commands.Bot):
    def __init__(self):
        # config.py から PREFIX を取得
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix=config.PREFIX, intents=intents)

    async def setup_hook(self):
        """
        cogsフォルダ内のファイルを自動ロード
        bot.run() の内部で実行される初期化処理
        """
        for filename in os.listdir('./cogs'):
            if filename.endswith('.py'):
                try:
                    await self.load_extension(f'cogs.{filename[:-3]}')
                    print(df.format_log(f"Extension loaded: {filename}"))
                except Exception as e:
                    print(df.format_log(f"Error loading {filename}: {e}"))

    async def on_ready(self):
        print(df.format_log(f"Logged in as {self.user}"))
        print(f"Supabase URL: {config.SUPABASE_URL}")

# --- インスタンス化 ---
bot = MyBot()

# --- 実行セクション ---
if __name__ == "__main__":
    from threading import Thread

    # 1. Flaskサーバーを別スレッド（バックグラウンド）で動かす
    def run_flask():
        # keep_alive.py 内で app.run() が呼ばれている想定
        keep_alive()

    flask_thread = Thread(target=run_flask)
    flask_thread.daemon = True  # メインが終了したら一緒に終了するように
    flask_thread.start()
    print("DEBUG: Flask server started in background thread.")

    # 2. メインスレッドで Bot を起動
    try:
        # config.py から TOKEN を取得
        bot.run(config.TOKEN)
    except Exception as e:
        print(f"Bot runtime error: {e}")