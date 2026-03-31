# -*- coding: utf-8 -*-
import discord
from discord.ext import commands
import os
import asyncio
import config
import defining as df    
from keep_alive import keep_alive

# 他の設定...
GROQ_API_KEY = os.getenv("GROQ_API_KEY")


NOTIFY_CHANNEL_ID = 1476170098673717414

class MyBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.all() 
        super().__init__(command_prefix=config.PREFIX, intents=intents)
        self.updated_notified = False

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
        sb_exists = getattr(config, 'supabase', None)
        print(f"Supabase Status: {'Connected' if sb_exists else 'Disconnected'}")

        if not self.updated_notified:
            channel = self.get_channel(NOTIFY_CHANNEL_ID)
            if channel:
                try:
                    await channel.send("システムを更新しました。")
                    print(df.format_log(f"Update notification sent to {channel.name}"))
                except Exception as e:
                    print(df.format_log(f"Failed to send update message: {e}"))
            else:
                print(df.format_log("Warning: Notification channel not found."))
            
            self.updated_notified = True 

bot = MyBot()

if __name__ == "__main__":
    keep_alive()
    print("DEBUG: Keep-alive server initiated.")
    try:
        bot.run(config.TOKEN)
    except Exception as e:
        error_msg = f"Bot runtime error: {e}"
        try:
            print(df.format_log(error_msg))
        except:
            print(error_msg)
