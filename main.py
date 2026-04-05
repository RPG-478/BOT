# -*- coding: utf-8 -*-
import discord
from discord.ext import commands
import os
import asyncio
import traceback
import config
import defining as df    
from keep_alive import keep_alive

# 通知用・デバッグ用チャンネルID
NOTIFY_CHANNEL_ID = 1476170098673717414
DEBUG_CHANNEL_ID = 1476946191362166894

class MyBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.all() 
        super().__init__(command_prefix=config.PREFIX, intents=intents)
        self.updated_notified = False

    async def send_debug_log(self, message: str):
        """Discordのデバッグチャンネルに詳細ログを送信する"""
        channel = self.get_channel(DEBUG_CHANNEL_ID)
        if channel:
            # 長すぎるログ対策で分割送信も考慮（簡易版）
            msg = f"```py\n[SYSTEM DEBUG]\n{message}\n```"
            await channel.send(msg[:2000])

    async def setup_hook(self):
        # 起動時にまずデバッグ出力を試みる
        print(df.format_log("Starting extension loading process..."))
        
        if os.path.exists('./cogs'):
            for filename in os.listdir('./cogs'):
                if filename.endswith('.py') and not filename.startswith('__'):
                    try:
                        await self.load_extension(f'cogs.{filename[:-3]}')
                        print(df.format_log(f"Extension loaded: {filename}"))
                    except Exception:
                        # ここが最強ポイント：エラーの全内容（トレースバック）を文字列にする
                        err = traceback.format_exc()
                        print(df.format_log(f"CRITICAL ERROR loading {filename}:\n{err}"))
                        # 起動直後でまだReadyでない場合があるため、あとで送信するためのフラグなどを立てるのもアリですが
                        # ここではコンソール出力を最優先します
        else:
            print(df.format_log("Warning: 'cogs' directory not found."))
        
        await self.tree.sync()
        print(df.format_log("Slash commands synced successfully."))

    async def on_ready(self):
        print(df.format_log(f"Logged in as {self.user} (ID: {self.user.id})"))
        
        # 起動時にエラーがあった場合、ここでDiscordに一括報告させる仕組み
        channel = self.get_channel(NOTIFY_CHANNEL_ID)
        if channel and not self.updated_notified:
            try:
                await channel.send("<a:AGOMUNIMUNI:1490255555632037909>システムを更新しました。")
                
                # もし起動時に読み込めなかったCogがあれば、デバッグチャンネルに詳細を飛ばす
                # (setup_hookでのエラーを保存しておいてここで送るのも有効)
                
                self.updated_notified = True
            except Exception as e:
                print(df.format_log(f"Notification error: {e}"))

bot = MyBot()

if __name__ == "__main__":
    keep_alive()
    print("DEBUG: Keep-alive server initiated.")
    try:
        bot.run(config.TOKEN)
    except Exception:
        # 実行時エラーも丸ごとキャッチ
        err = traceback.format_exc()
        print(df.format_log(f"Bot runtime crash:\n{err}"))