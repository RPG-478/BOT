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
from collections import deque
from supabase import create_client, Client
import json
import hashlib

SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

NOTIFY_CHANNEL_ID = 1513038883787505764
DEBUG_CHANNEL_ID = 1407389497016193177
HASH_FILE = "command_hash.json"

class LogBuffer(logging.Handler):
    def __init__(self, maxlen=100):
        logging.Handler.__init__(self)
        self.logs = deque(maxlen=maxlen)
 
    def emit(self, record):
        log_entry = self.format(record)
        self.logs.append(log_entry)

class MyBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.all() 
        super().__init__(command_prefix=config.PREFIX, intents=intents)
        self.updated_notified = False

    def _get_commands_hash(self):
        cmds = self.tree.get_commands()
        cmd_data = sorted([f"{c.name}:{c.description}" for c in cmds])
        return hashlib.sha256("".join(cmd_data).encode("utf-8")).hexdigest()

    async def setup_hook(self):
        print(df.format_log("--- COGS LOADING PROCESS START ---"))
        
        if os.path.exists('./cogs'):
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
                        err_detail = traceback.format_exc()
                        print(df.format_log(f"FAILED: {filename}\n{err_detail}"))
        else:
            print(df.format_log("ERROR: './cogs' directory not found."))
        
        current_hash = self._get_commands_hash()
        previous_hash = ""
        if os.path.exists(HASH_FILE):
            try:
                with open(HASH_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    previous_hash = data.get("hash", "")
            except Exception:
                pass

        if current_hash != previous_hash:
            print(df.format_log("Command changes detected. Syncing slash commands..."))
            try:
                await self.tree.sync()
                print(df.format_log("Slash commands synced successfully."))
                with open(HASH_FILE, "w", encoding="utf-8") as f:
                    json.dump({"hash": current_hash}, f)
            except Exception:
                print(df.format_log(f"Sync Error: {traceback.format_exc()}"))
        else:
            print(df.format_log("No command changes detected. Skipped tree.sync()."))

    async def on_ready(self):
        print(df.format_log(f"Logged in as {self.user} (ID: {self.user.id})"))
        
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
bot.supabase = supabase

@bot.command()
@commands.is_owner()
async def sync(ctx):
    try:
        synced = await bot.tree.sync()
        current_hash = bot._get_commands_hash()
        with open(HASH_FILE, "w", encoding="utf-8") as f:
            json.dump({"hash": current_hash}, f)
        await ctx.send(f"{len(synced)} 個のスラッシュコマンドを手動同期しました。")
    except Exception as e:
        await ctx.send(f"同期失敗: {e}")

log_buffer = LogBuffer(maxlen=100)
log_buffer.setFormatter(logging.Formatter(
    "[%(levelname)s] %(asctime)s | %(message)s",
    "%H:%M:%S"
))
logger = logging.getLogger()
logger.setLevel(logging.WARNING)
logger.addHandler(log_buffer)
bot.log_buffer = log_buffer

if __name__ == "__main__":
    keep_alive()
    print("DEBUG: Keep-alive server initiated.")
    try:
        bot.run(config.TOKEN)
    except Exception:
        print(df.format_log(f"Bot runtime crash:\n{traceback.format_exc()}"))
