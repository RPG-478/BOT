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
        print(f"Supabase Status: {'Connected' if config.supabase else 'Disconnected'}")

bot = MyBot()

if __name__ == "__main__":
    keep_alive()
    print("DEBUG: Keep-alive server initiated.")
    try:
        bot.run(config.TOKEN)
    except Exception as e:
        print(df.format_log(f"Bot runtime error: {e}"))