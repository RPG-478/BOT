# -*- coding: utf-8 -*-
import discord
from discord.ext import commands
import os
import asyncio
import traceback
import config
import defining as df    
from keep_alive import keep_alive
import logging


NOTIFY_CHANNEL_ID = 1476170098673717414
DEBUG_CHANNEL_ID = 1476946191362166894

class MyBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.all() 
        super().__init__(command_prefix=config.PREFIX, intents=intents)
        self.updated_notified = False

    async def setup_hook(self):
        print(df.format_log("--- COGS LOADING PROCESS START ---"))
        
        if os.path.exists('./cogs'):
            # フォルダ内の全ファイルを表示（認識チェック）
            files = os.listdir('./cogs')
            print(df.format_log(f"Files found in ./cogs: {files}"))
            
            for filename in files:
                if filename.endswith('.py') and not filename.startswith('__'):
                    ext_name = f'cogs.{filename[:-3]}'
                    print(df.format_log(f"Attempting to load: {ext_name}"))
                    try:
                        await self.load_extension(ext_name)
                        print(df.format_log(f"SUCCESS: {filename} loaded."))
                    except Exception:
                        # ここでエラーの全詳細を出力
                        err_detail = traceback.format_exc()
                        print(df.format_log(f"FAILED: {filename}\n{err_detail}"))
        else:
            print(df.format_log("ERROR: './cogs' directory not found."))
        
        try:
            await self.tree.sync()
            print(df.format_log("Slash commands synced successfully."))
        except Exception:
            print(df.format_log(f"Sync Error: {traceback.format_exc()}"))

    async def on_ready(self):
        print(df.format_log(f"Logged in as {self.user} (ID: {self.user.id})"))
        
        # ロード済みのCogを一覧表示
        print(df.format_log(f"Active Cogs: {list(self.cogs.keys())}"))

        if not self.updated_notified:
            channel = self.get_channel(NOTIFY_CHANNEL_ID)
            if channel:
                try:
                    await channel.send("<a:AGOMUNIMUNI:1490255555632037909>システムを更新しました。")
                except Exception as e:
                    print(df.format_log(f"Notification error: {e}"))
            self.updated_notified = True 

bot = MyBot()

# ===== ログ設定 =====
log_buffer = LogBuffer(maxlen=100)

log_buffer.setFormatter(logging.Formatter(
    "[%(levelname)s] %(asctime)s | %(message)s",
    "%H:%M:%S"
))

logger = logging.getLogger()
logger.setLevel(logging.INFO)
logger.addHandler(log_buffer)

bot.log_buffer = log_buffer


class LogBuffer(logging.Handler):
    def __init__(bot, maxlen=100):
        commands.Cog.__init__(self)
        logging.Handler.__init__(self)

        self.logs = deque(maxlen=maxlen)

    def emit(record):
        log_entry = bot.format(record)
        bot.logs.append(log_entry)





if __name__ == "__main__":
    keep_alive()
    print("DEBUG: Keep-alive server initiated.")
    try:
        bot.run(config.TOKEN)
    except Exception:
        print(df.format_log(f"Bot runtime crash:\n{traceback.format_exc()}"))
