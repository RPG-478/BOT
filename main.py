# -*- coding: utf-8 -*-
import discord
from discord.ext import commands
import os
import asyncio
# 自作モジュールのインポート
import config           # 設定・環境変数・Supabase接続
import defining as df    # 共通関数 (format_logなど)
from keep_alive import keep_alive
# Botクラス定義
class MyBot(commands.Bot):
    def __init__(self):
        # config.py から PREFIX を取得
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix=config.PREFIX, intents=intents)
    async def setup_hook(self): #時間がかかる場合setup_hookそれ以外はon_readyに入れること
        if os.path.exists('./cogs'):
            for filename in os.listdir('./cogs'):
                # .pyファイルかつファイルである場合のみロード
                if filename.endswith('.py') and os.path.isfile(os.path.join('./cogs', filename)):
                    try:
                        await self.load_extension(f'cogs.{filename[:-3]}')
                        print(df.format_log(f"Extension loaded: {filename}"))
                    except Exception as e:
                        print(df.format_log(f"Error loading {filename}: {e}"))
        else:
            print(df.format_log("Warning: 'cogs' directory not found."))
    async def on_ready(self):
        await self.tree.sync()
        print(df.format_log(f"Logged in as {self.user} (ID: {self.user.id})"))
        print(f"Supabase Status: {'Connected' if config.supabase else 'Disconnected'}")
# --- インスタンス化 ---
bot = MyBot()
# --- 実行セクション ---
if __name__ == "__main__":
    # 1. Flaskサーバーを別スレッドで起動
    # keep_alive.py 側で Thread が定義されているため、関数を呼ぶだけでOK
    keep_alive()
    print("DEBUG: Keep-alive server initiated.")
    # 2. メインスレッドで Bot を起動
    try:
        # config.py から TOKEN を取得
        bot.run(config.TOKEN)
    except Exception as e:
        print(df.format_log(f"Bot runtime error: {e}"))
