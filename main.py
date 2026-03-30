# -*- coding: utf-8 -*-
import discord
from discord.ext import commands
import os
import asyncio
import config
import defining as df    
from keep_alive import keep_alive

class MyBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.all() 
        super().__init__(command_prefix=config.PREFIX, intents=intents)

    async def setup_hook(self):
        if os.path.exists('./cogs'):
            for filename in os.listdir('./cogs'):
                if filename.endswith('.py') and os.path.isfile(os.path.join('./cogs', filename)):
                    try:
                        await self.load_extension(f'cogs.{filename[:-3]}')
                        print(df.format_log(f"Extension loaded: {filename}"))
                    except Exception as e:
                        print(df.format_log(f"Error loading {filename}: {e}"))
        else:
            print(df.format_log("Warning: 'cogs' directory not found."))
        
        await self.tree.sync()
        print(df.format_log("Slash commands synced successfully."))

    async def on_ready(self):
        print(df.format_log(f"Logged in as {self.user} (ID: {self.user.id})"))
        # config.supabaseが存在しない場合のエラーを避けるため、getattrを使用
        sb_exists = getattr(config, 'supabase', None)
        print(f"Supabase Status: {'Connected' if sb_exists else 'Disconnected'}")

bot = MyBot()

if __name__ == "__main__":
    keep_alive()
    print("DEBUG: Keep-alive server initiated.")
    try:
        bot.run(config.TOKEN)
    except Exception as e:
        # df.format_log が万が一エラーになっても表示できるよう標準出力も併用
        error_msg = f"Bot runtime error: {e}"
        try:
            print(df.format_log(error_msg))
        except:
            print(error_msg)
